"""
tests.test_wide_flags
=====================
Wide output can show each value's status flag (flags=True), default
wide output is unchanged, and a FlagWarning says when a wide result hides break (B) or
provisional (P) values. Runs on the checkout's local data.
"""

import warnings

import pandas as pd
import pytest

import iraqdata
import iraqdata.catalog as cat
import iraqdata.client as client
from conftest import REPO_ROOT

pytestmark = pytest.mark.usefixtures("fresh_memory_cache")

BASELINE = REPO_ROOT / "tests" / "fixtures" / "wide_baseline"
BASELINE_REQUESTS = {
    "cpi": (("cpi",), {}),
    "m1_m2": ((["m1", "m2"],), {}),
    "m2_official_rate": ((["m2", "official_rate"],), {}),
    "broad_m2_2015": (({"Broad": "m2"},), {"start": "2015"}),
}


def _quiet(*args, **kwargs):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", iraqdata.FlagWarning)
        return client.get_series(*args, **kwargs)


@pytest.mark.parametrize("name", BASELINE_REQUESTS)
def test_default_wide_output_is_unchanged(name):
    args, kwargs = BASELINE_REQUESTS[name]
    result = _quiet(*args, **kwargs)
    frames = result if isinstance(result, dict) else {None: result}
    for freq, df in frames.items():
        file = BASELINE / (f"{name}.{freq}.csv" if freq else f"{name}.csv")
        assert df.to_csv(lineterminator="\n") == file.read_text(encoding="utf-8"), file.name


def _long_flags(series) -> pd.DataFrame:
    long = client.get_series(series, wide=False)
    return long.set_index(["date", "series_id"])["status_flag"]


def test_flag_columns_follow_values_and_match_long_format():
    df = client.get_series(["cpi", "m2"], flags=True)
    assert list(df.columns) == ["cpi", "cpi_flag", "m2", "m2_flag"]
    long = _long_flags(["cpi", "m2"])
    for label in ("cpi", "m2"):
        sid = cat.resolve_series_id(label)
        has_value = df[label].notna()
        for date in df.index:
            flag = df.at[date, f"{label}_flag"]
            if (date, sid) in long.index:
                assert flag == long[(date, sid)], (label, date)
            else:
                assert flag is None and not has_value[date], (label, date)


@pytest.mark.parametrize("table", ["prices_monthly", "exchange_rates_daily"])
def test_every_break_and_provisional_value_is_visible(table, garden_tables):
    stored = garden_tables[table]
    ids = sorted(stored["series_id"].unique())
    df = client.get_series(ids, flags=True)
    for sid in ids:
        expected = stored.loc[stored["series_id"] == sid, "status_flag"].value_counts()
        shown = df[f"{sid}_flag"].value_counts()
        for flag in ("B", "P"):
            assert shown.get(flag, 0) == expected.get(flag, 0), (sid, flag)
    total = {f: int((stored["status_flag"] == f).sum()) for f in ("B", "P")}
    shown_total = {f: int(sum((df[f"{s}_flag"] == f).sum() for s in ids)) for f in ("B", "P")}
    assert shown_total == total


def test_mixed_frequency_flags_per_frame():
    out = client.get_series(["m2", "official_rate"], flags=True)
    assert list(out["daily"].columns) == ["official_rate", "official_rate_flag"]
    assert list(out["monthly"].columns) == ["m2", "m2_flag"]


def test_hidden_breaks_and_provisional_values_raise_one_warning():
    with pytest.warns(iraqdata.FlagWarning) as record:
        client.get_series("cpi")
    flag_warnings = [w for w in record if issubclass(w.category, iraqdata.FlagWarning)]
    assert len(flag_warnings) == 1
    message = str(flag_warnings[0].message)
    assert "cpi" in message and " B" in message and " P" in message and "flags=True" in message


def test_no_warning_when_nothing_is_hidden():
    with warnings.catch_warnings():
        warnings.simplefilter("error", iraqdata.FlagWarning)
        client.get_series("m1", start="2010", end="2010")
        client.get_series("cpi", flags=True)
        client.get_series("cpi", wide=False)


def test_flag_column_clash_is_rejected():
    with pytest.raises(ValueError, match="x_flag"):
        client.get_series({"x": "m1", "x_flag": "m2"}, flags=True)


def test_deprecated_id_gets_flags_like_its_values(monkeypatch):
    old, new = "money.broad", "money.m2"      # made up: no series has been renamed yet
    monkeypatch.setitem(cat.DEPRECATED_IDS, old, new)
    by_old = client.get_series(old, flags=True)
    by_new = client.get_series(new, flags=True)
    assert list(by_old.columns) == [old, f"{old}_flag"]
    assert by_old[f"{old}_flag"].tolist() == by_new[f"{new}_flag"].tolist()


def test_flags_do_not_change_long_output():
    pd.testing.assert_frame_equal(
        client.get_series("cpi", wide=False, flags=True), client.get_series("cpi", wide=False)
    )
