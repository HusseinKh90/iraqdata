"""
tests.test_gatekeeper_continuity
================================
A monthly, quarterly or annual series with a period missing between its first and last cannot be
told from a source that dropped it, so the gate reports it as a [GAP] review notice. A series that
lacks periods by design (one JODI month; the Basrah anchor months) is listed in
pipeline/metadata/expected_gaps.yaml with the reason.
"""

import pandas as pd
import pytest
import yaml

import validate
from conftest import GARDEN_DIR, SEEDS_DIR


def _frame(rows):
    return pd.DataFrame([{"date": d, "series_id": s, "value": v, "unit": "X", "status_flag": "A",
                          "realtime_start": "2026-10-22", "source_hash": "0" * 16} for s, d, v in rows])


def test_interior_gaps_by_frequency():
    df = _frame([("m", "2020-11", 1.0), ("m", "2021-02", 1.0),                    # monthly, across a year end
                 ("q", "2020-Q3", 1.0), ("q", "2021-Q2", 1.0),                    # quarterly
                 ("a", "2001", 1.0), ("a", "2004", 1.0), ("a", "2003", 1.0),      # annual
                 ("ok", "2020-01", 1.0), ("ok", "2020-02", 1.0),
                 ("d", "2020-01-01", 1.0), ("d", "2020-01-09", 1.0)])             # daily: its own rule
    assert validate.interior_gaps(df) == {
        "m": ["2020-12", "2021-01"], "q": ["2020-Q4", "2021-Q1"], "a": ["2002"]}


def test_a_nan_value_is_no_value():
    df = _frame([("m", "2020-01", 1.0), ("m", "2020-02", float("nan")), ("m", "2020-03", 1.0)])
    assert validate.interior_gaps(df) == {"m": ["2020-02"]}


@pytest.mark.parametrize("missing, text", [
    (["2013-02"], "2013-02"),
    (["2020-12", "2021-01"], "2020-12 to 2021-01 (2 periods)"),
    (["2020-Q4", "2021-Q1", "2021-Q4"], "2020-Q4 to 2021-Q1, 2021-Q4 (3 periods)"),
    (["2002", "2003", "2005"], "2002 to 2003, 2005 (3 periods)"),
])
def test_runs_are_joined(missing, text):
    assert validate._runs(missing) == text


def _gaps(df, name="t"):
    _, warnings = validate.validate_tier2_details(df, dataset_name=name)
    return [w for w in warnings if w.check == "gap" and "no value for" in w.message]


def test_the_real_tables_have_no_unlisted_gap(garden_tables, seed_tables):
    for name, df in {**garden_tables, **seed_tables}.items():
        assert _gaps(df, name) == [], name


def test_a_dropped_quarter_is_a_notice_naming_series_and_period(garden_tables):
    df = garden_tables["gdp_quarterly"]
    cut = df[~((df["series_id"] == "gdp.real") & (df["date"] == "2022-Q3"))]
    (w,) = _gaps(cut, "gdp_quarterly")
    assert (w.series, w.check, w.periods) == ("gdp.real", "gap", ["2022-Q3"])
    assert "[GAP] gdp.real: no value for 2022-Q3 between 2015-Q1 and 2026-Q1" in w.message


def test_the_listed_month_is_expected_but_another_one_is_not(garden_tables):
    df = garden_tables["oil_monthly"]
    other = df[~((df["series_id"] == "crude_production_direct") & (df["date"] == "2014-02"))]
    (w,) = _gaps(other, "oil_monthly")
    assert w.series == "crude_production_direct" and w.periods == ["2013-02", "2014-02"]   # 2013-02 is listed, the set is not


def test_a_sparse_series_is_never_reported(garden_tables):
    df = garden_tables["oil_monthly"]
    assert "oil_price_basrah" in validate.interior_gaps(df)
    assert not [w for w in _gaps(df, "oil_monthly") if w.series == "oil_price_basrah"]


def test_an_acknowledgement_covers_the_notice(garden_tables):
    df = garden_tables["gdp_quarterly"]
    cut = df[~((df["series_id"] == "gdp.real") & (df["date"] == "2022-Q3"))]
    (w,) = _gaps(cut, "gdp_quarterly")
    ack = {"series": "gdp.real", "check": "gap", "periods": ["2022-Q3"], "reason": "test", "reviewer": "t",
           "date": "2026-10-28", "review_by": "2027-10-28"}
    assert validate.match_warning(w, [ack], "gdp_quarterly", "2026-10-28").state == "applies"


def test_the_expectations_file_is_well_formed():
    listed = validate.load_expected_missing()
    assert listed["crude_production_direct"]["periods"] == {"2013-02"} and listed["oil_price_basrah"]["periods"] is None
    assert all(rule["reason"].strip() for rule in listed.values())


@pytest.mark.parametrize("entry, message", [
    ({"series": "x", "reason": "r"}, "either periods"),
    ({"series": "x", "reason": "r", "periods": ["2020-01"], "sparse": True}, "either periods"),
    ({"series": "x", "periods": ["2020-01"]}, "reason"),
])
def test_a_malformed_expectation_is_refused(tmp_path, entry, message):
    path = tmp_path / "gaps.yaml"
    path.write_text(yaml.safe_dump({"expected": [], "missing_periods": [entry]}), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        validate.load_expected_missing(path)


def test_a_series_listed_twice_is_refused(tmp_path):
    path = tmp_path / "gaps.yaml"
    entry = {"series": "x", "periods": ["2020-01"], "reason": "r"}
    path.write_text(yaml.safe_dump({"expected": [], "missing_periods": [entry, entry]}), encoding="utf-8")
    with pytest.raises(ValueError, match="listed twice"):
        validate.load_expected_missing(path)


def test_the_files_checked_are_the_committed_ones():
    assert (GARDEN_DIR / "oil_monthly.parquet").exists() and (SEEDS_DIR / "opec_momr_historical.parquet").exists()
