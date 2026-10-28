"""
tests.test_client_api
=====================
The client returns correct, unaltered data in every documented
shape.
"""

import numpy as np
import pandas as pd
import pytest

import iraqdata
import iraqdata.catalog as cat
import iraqdata.client as client
from conftest import CANONICAL_COLUMNS, PRODUCTION_TABLES

pytestmark = pytest.mark.usefixtures("fresh_memory_cache")

TIDY_COLUMNS = ["date", "series_id", "value", "unit", "status_flag", "source"]
NAMED_ALIASES = {
    "m2": "money.m2",
    "cpi": "cpi_headline",
    "parallel_rate": "parallel_rate_iraq",
    "gdp": "gdp.nominal",
    "fiscal_balance": "fiscal.balance",
    "oil_production": "crude_production_secondary",
    "reserves": "money.reserves_official",
}


def _stored(garden_tables, series_id: str) -> pd.DataFrame:
    table = cat.SERIES_TO_TABLE[series_id]
    df = garden_tables[table]
    return df[df["series_id"] == series_id].sort_values("date").reset_index(drop=True)


# =====================================================================
# Output shapes and values
# =====================================================================

def test_wide_single_series(garden_tables):
    df = client.get_series("money.m2")
    stored = _stored(garden_tables, "money.m2")
    assert isinstance(df, pd.DataFrame)
    assert df.index.name == "date"
    assert df.index.is_monotonic_increasing
    assert list(df.columns) == ["money.m2"]
    assert list(df.index) == stored["date"].tolist()
    np.testing.assert_array_equal(df["money.m2"].to_numpy(), stored["value"].to_numpy())


def test_wide_same_frequency_alignment(garden_tables):
    df = client.get_series(["money.m1", "money.m2"])
    dates = set(_stored(garden_tables, "money.m1")["date"]) | set(_stored(garden_tables, "money.m2")["date"])
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["money.m1", "money.m2"]
    assert set(df.index) == dates  # a period missing for one series is kept as NaN, never dropped


def test_wide_mixed_frequency_returns_dict_per_frequency():
    out = client.get_series(["money.m2", "fx.official"])
    assert isinstance(out, dict)
    assert list(out.keys()) == ["daily", "monthly"]
    assert list(out["daily"].columns) == ["fx.official"]
    assert list(out["monthly"].columns) == ["money.m2"]
    assert out["daily"].index.str.match(r"^\d{4}-\d{2}-\d{2}$").all()
    assert out["monthly"].index.str.match(r"^\d{4}-\d{2}$").all()


def test_tidy_layout_mixes_frequencies_in_one_table():
    df = client.get_series(["money.m2", "fx.official"], wide=False)
    assert isinstance(df, pd.DataFrame)
    assert set(df["series_id"]) == {"money.m2", "fx.official"}


@pytest.mark.parametrize("alias, canonical", NAMED_ALIASES.items())
def test_named_aliases_match_canonical(alias, canonical):
    assert cat.resolve_series_id(alias) == canonical
    via_alias = client.get_series(alias)
    via_id = client.get_series(canonical)
    assert list(via_alias.index) == list(via_id.index)
    np.testing.assert_array_equal(via_alias.iloc[:, 0].to_numpy(), via_id.iloc[:, 0].to_numpy())


def test_every_alias_resolves_to_a_stored_series():
    unknown = {a: s for a, s in cat.ALIASES.items() if s not in cat.SERIES_TO_TABLE}
    assert unknown == {}


def test_tidy_layout_columns_and_sources():
    df = client.get_series(["money.m2", "cpi", "fx.official"], wide=False)
    assert list(df.columns) == TIDY_COLUMNS
    expected = df["series_id"].map(cat.SERIES_DIRECT_SOURCES)
    assert (df["source"] == expected).all()
    assert (df["source"].str.strip() != "").all()


def test_audit_columns_match_stored_rows(garden_tables):
    df = client.get_series("money.m2", wide=False, audit=True)
    assert list(df.columns) == TIDY_COLUMNS + ["realtime_start", "source_hash"]
    stored = _stored(garden_tables, "money.m2")
    for col in ["date", "realtime_start", "source_hash", "unit", "status_flag"]:
        assert df[col].tolist() == stored[col].tolist(), col


@pytest.mark.parametrize("table", PRODUCTION_TABLES)
def test_client_values_identical_to_stored(garden_tables, table):
    series_id = sorted(garden_tables[table]["series_id"].unique())[0]
    df = client.get_series(series_id, wide=False)
    stored = _stored(garden_tables, series_id)
    np.testing.assert_array_equal(df["value"].to_numpy(), stored["value"].to_numpy())


# =====================================================================
# Date windows — both argument spellings
# =====================================================================

@pytest.mark.parametrize(
    "series, kwargs, included, excluded",
    [
        ("gdp.nominal", {"start": "2020-01"}, ["2020-Q1"], ["2019-Q4"]),
        ("gdp.nominal", {"end": "2020-06"}, ["2020-Q2"], ["2020-Q3"]),
        ("gdp.nominal", {"start": "2020-02"}, ["2020-Q1"], ["2019-Q4"]),
        ("fiscal.balance", {"end": "2024-12"}, ["2024"], ["2025"]),
        ("money.m2", {"start": "2020-Q2", "end": "2020-Q2"}, ["2020-04", "2020-06"], ["2020-03", "2020-07"]),
    ],
)
def test_window_overlap_semantics(series, kwargs, included, excluded):
    df = client.get_series(series, **kwargs)
    for d in included:
        assert d in df.index, d
    for d in excluded:
        assert d not in df.index, d
    renamed = {f"{k}_date": v for k, v in kwargs.items()}
    pd.testing.assert_frame_equal(df, client.get_series(series, **renamed))


def test_daily_window_two_days():
    df = client.get_series("fx.official", start="2023-01-04", end="2023-01-05")
    assert list(df.index) == ["2023-01-04", "2023-01-05"]
    alt = client.get_series("fx.official", start_date="2023-01-04", end_date="2023-01-05")
    pd.testing.assert_frame_equal(df, alt)


def test_reversed_window_raises():
    with pytest.raises(ValueError):
        client.get_series("money.m2", start="2024", end="2020")


def test_invalid_bound_raises():
    with pytest.raises(ValueError):
        client.get_series("money.m2", start="2024-13")


@pytest.mark.parametrize(
    "kwargs", [{"start": "2020", "start_date": "2020"}, {"end": "2020", "end_date": "2020"}]
)
def test_both_spellings_raise(kwargs):
    with pytest.raises(TypeError):
        client.get_series("money.m2", **kwargs)


def test_window_outside_coverage_returns_empty_with_columns():
    df = client.get_series("money.m2", start="2099")
    assert df.empty
    assert list(df.columns) == ["money.m2"]
    tidy = client.get_series("money.m2", start="2099", wide=False)
    assert tidy.empty
    assert list(tidy.columns) == TIDY_COLUMNS


# =====================================================================
# Column renaming (both forms) and error handling
# =====================================================================

def test_rename_forms_are_equivalent():
    a = client.get_series({"M2": "money.m2"})
    b = client.get_series("money.m2", aliases={"money.m2": "M2"})
    pd.testing.assert_frame_equal(a, b)


def test_partial_aliases_keep_requested_names():
    df = client.get_series(["m2", "m1"], aliases={"m2": "M2"})
    assert list(df.columns) == ["M2", "m1"]


def test_aliases_resolve_keys_like_series_names():
    df = client.get_series(["money.m2"], aliases={"m2": "Broad"})
    assert list(df.columns) == ["Broad"]


def test_duplicate_labels_raise():
    with pytest.raises(ValueError):
        client.get_series(["m1", "m2"], aliases={"m1": "X", "m2": "X"})


def test_aliases_with_mapping_series_raise():
    with pytest.raises(TypeError):
        client.get_series({"M2": "money.m2"}, aliases={"money.m2": "Broad"})


def test_alias_key_not_requested_raises():
    with pytest.raises(ValueError):
        client.get_series(["m2"], aliases={"cpi": "CPI"})


def test_unknown_series_suggests_matches():
    with pytest.raises(KeyError, match="Did you mean"):
        client.get_series("money.m22")


@pytest.mark.parametrize("table", PRODUCTION_TABLES)
def test_get_table_returns_full_stored_table(garden_tables, table):
    df = client.get_table(table, audit=True)[CANONICAL_COLUMNS].reset_index(drop=True)
    stored = garden_tables[table].sort_values(["date", "series_id"]).reset_index(drop=True)
    pd.testing.assert_frame_equal(df, stored)


def test_version_is_1_0_0():
    assert iraqdata.__version__ == "1.0.0"


# =====================================================================
# Origin in the series lookups
# =====================================================================

LOOKUP_COLUMNS = ["series_id", "name_en", "name_ar", "category", "frequency", "unit", "start_date",
                  "table", "source", "origin", "official", "status"]


def test_list_series_and_search_end_with_origin_columns():
    assert list(iraqdata.list_series().columns) == LOOKUP_COLUMNS
    assert list(iraqdata.search("oil").columns) == LOOKUP_COLUMNS
    assert list(iraqdata.search("zzzzqqq").columns) == LOOKUP_COLUMNS


def test_get_origin_returns_segments_in_period_order():
    df = iraqdata.get_origin("crude_production_direct")
    assert list(df.columns) == ["from", "to", "class", "official", "method", "source", "record"]
    assert df[["from", "to", "class"]].values.tolist() == [
        ["2007-01", "2024-03", "observed"], ["2024-04", "open", "transcribed"]]
    assert df["record"].iloc[1].startswith("pipeline/raw/transcribed/")


def test_get_origin_observed_series_and_unknown_id():
    df = iraqdata.get_origin("money.m2")
    assert df["class"].tolist() == ["observed"] and bool(df["official"].iloc[0])
    with pytest.raises(KeyError):
        iraqdata.get_origin("nope.nope")
    assert "get_origin" in iraqdata.__all__


def test_origin_summary_and_official_flag():
    s = iraqdata.list_series().set_index("series_id")
    assert "observed (unofficial) 2023-01-01..open" in s.loc["parallel_rate_iraq", "origin"]
    assert not s.loc["parallel_rate_iraq", "official"]
    assert s.loc["money.m2", "official"]
    # derived from transcribed GDP totals, so not official either
    assert not s.loc["gdp.real_nonoil", "official"]
    assert s.loc["bis.lbs.net_position", "official"]


# =====================================================================
# A renamed series id stays a deprecated alias (no series has been renamed yet, so a rename is made up here)
# =====================================================================

OLD_ID, NEW_ID = "money.broad", "money.m2"


@pytest.fixture
def renamed(monkeypatch):
    monkeypatch.setitem(cat.DEPRECATED_IDS, OLD_ID, NEW_ID)


def _monthly_rows(series_id):
    return pd.DataFrame({
        "date": ["2022-01", "2022-02"], "series_id": [series_id] * 2, "value": [747.207, 744.191],
        "unit": ["BILLION_IQD"] * 2, "status_flag": ["A", "A"], "realtime_start": ["2026-10-22"] * 2,
        "source_hash": ["h"] * 2,
    })


def test_no_series_has_been_renamed_yet():
    assert cat.DEPRECATED_IDS == {}


def test_deprecated_id_resolves_with_a_warning(renamed):
    with pytest.warns(FutureWarning, match=NEW_ID) as record:
        assert iraqdata.resolve_series_id(OLD_ID) == NEW_ID
    assert len(record) == 1


@pytest.mark.parametrize("stored_id", [OLD_ID, NEW_ID])
def test_deprecated_id_reads_old_and_new_releases(monkeypatch, renamed, stored_id):
    """A release older than the rename holds the old id; its rows are returned as stored."""
    monkeypatch.setattr(client, "load_table", lambda table: _monthly_rows(stored_id))
    with pytest.warns(FutureWarning):
        tidy = iraqdata.get_series(OLD_ID, wide=False)
    assert tidy["series_id"].unique().tolist() == [stored_id]
    assert tidy["value"].tolist() == [747.207, 744.191]
    with pytest.warns(FutureWarning):
        wide = iraqdata.get_series(OLD_ID)
    assert wide[OLD_ID].tolist() == [747.207, 744.191]


def test_client_maps_match_catalog():
    """The client's lookup tables cover exactly the catalog's series."""
    from iraqdata import catalog as cat
    ids = {e["series_id"] for e in cat.get_catalog()["series"]}
    assert set(cat.SERIES_TO_TABLE) == ids
    assert set(cat.SERIES_DIRECT_SOURCES) == ids
    assert cat.SERIES_DIRECT_SOURCES["crude_production_secondary"] == "U.S. EIA"


def test_list_series_status_column(monkeypatch):
    """A withdrawn series stays listed, marked as such; none of the published series is withdrawn."""
    assert set(iraqdata.list_series()["status"]) == {"active"}
    real = cat.get_catalog()
    retired = dict(next(e for e in real["series"] if e["series_id"] == "money.m2"),
                   series_id="money.retired", status="withdrawn", withdrawn_in="data-2030-01")
    monkeypatch.setattr(cat, "get_catalog", lambda: {**real, "series": real["series"] + [retired]})
    listed = iraqdata.list_series().set_index("series_id")
    assert listed.loc["money.retired", "status"] == "withdrawn" and listed.loc["money.m2", "status"] == "active"


def test_listings_show_the_corrected_aid_names():
    listed = iraqdata.list_series().set_index("series_id")
    assert "Excluding Technical Cooperation" in listed.loc["oecd.dac.grants_excl_tc", "name_en"]
    assert "oecd.dac.grants_excl_tc" in set(iraqdata.search("grants")["series_id"])
