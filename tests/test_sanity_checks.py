"""
tests.test_sanity_checks
========================
Cross-source sanity checks declared in
pipeline/metadata/sanity_checks.yaml. A breach is a [SANITY] Tier-2 review notice: never fatal,
acknowledgeable (value-tied, with a review-by date), and not part of the identity coverage.
"""

import pandas as pd
import pytest
import yaml

import validate
from conftest import GARDEN_DIR

AS_OF = pd.Timestamp("2026-10-26")


@pytest.fixture
def frames(garden_tables):
    return {name: df.copy() for name, df in garden_tables.items()}


def _set(frames, table, sid, date, value):
    df = frames[table]
    df.loc[(df["series_id"] == sid) & (df["date"] == date), "value"] = value


def _by_period(frames, check_id):
    return {w.periods[0]: w for w in validate.sanity_warnings(frames) if w.series == check_id}


def test_checks_load():
    ids = [c["id"] for c in validate.load_sanity_checks()]
    assert ids == ["fx_parallel_vs_official", "bop_reserves_vs_cbi_stock"]


def test_production_breaches_are_the_measured_ones(frames):
    fx = _by_period(frames, "fx_parallel_vs_official")
    assert len(fx) == 12 and all(p < "2008" for p in fx)  # parallel more than 2% below official
    assert sorted(_by_period(frames, "bop_reserves_vs_cbi_stock")) == [
        "2014-Q1", "2014-Q2", "2015-Q1", "2022-Q3", "2023-Q4", "2024-Q1"]


@pytest.mark.parametrize("ratio,reported", [(0.95, True), (1.35, True), (1.10, False)])
def test_fx_band(frames, ratio, reported):
    df = frames["exchange_rates_daily"]
    day = "2019-03-04"
    official = float(df.loc[(df["series_id"] == "fx.official") & (df["date"] == day), "value"].iloc[0])
    _set(frames, "exchange_rates_daily", "parallel_rate_iraq", day, official * ratio)
    found = _by_period(frames, "fx_parallel_vs_official")
    assert (day in found) == reported
    if reported:
        w = found[day]
        assert f"ratio {ratio:.4g}" in w.message and "parallel_rate_iraq" in w.message and "fx.official" in w.message
        assert set(w.values) == {day, f"{day} fx.official"}


def test_bop_reserves_breach_is_reported_with_both_values(frames):
    q = "2019-Q2"
    assert q not in _by_period(frames, "bop_reserves_vs_cbi_stock")
    _set(frames, "bop_trade_quarterly", "bop.reserve_assets_change", q, 20000.0)
    w = _by_period(frames, "bop_reserves_vs_cbi_stock")[q]
    assert "bop.reserve_assets_change 20000" in w.message and "money.reserves_official change" in w.message
    assert "tolerance" in w.message and q in w.values and f"{q} money.reserves_official change" in w.values


def test_stock_is_converted_at_each_quarter_end_rate(frames):
    """An exchange-rate change alone (IQD stock up, USD stock flat) is not a reserve change."""
    check = [c for c in validate.load_sanity_checks() if c["id"] == "bop_reserves_vs_cbi_stock"]
    tiny = {
        "bop": pd.DataFrame({"date": ["2020-Q4"], "series_id": "a", "value": [0.0]}),
        "money": pd.DataFrame({"date": ["2020-09", "2020-12"], "series_id": "b", "value": [100.0, 200.0]}),
        "fx": pd.DataFrame({"date": ["2020-09-30", "2020-12-31"], "series_id": "f", "value": [1.0, 2.0]}),
    }
    cfg = {**check[0], "a": "a", "b": "b", "convert": {"divide_by": "f", "scale": 1000},
           "tolerance": {"absolute": 1, "relative": 0}}
    assert validate.sanity_warnings(tiny, [cfg]) == []


def _gate(tmp_path, capsys, frames, acks):
    paths = []
    for name in ("exchange_rates_daily", "bop_trade_quarterly", "money_banking_monthly"):
        path = tmp_path / f"{name}.parquet"
        frames[name].to_parquet(path, index=False)
        paths.append(path)
    code = validate.run_gatekeeper(paths, acks, release=True, freshness=False, as_of=AS_OF, all_datasets=False)
    return code, capsys.readouterr().out


def test_breach_is_never_fatal_and_not_identity_coverage(tmp_path, capsys, frames, monkeypatch):
    monkeypatch.setattr(validate, "production_tables", lambda: {"exchange_rates_daily", "bop_trade_quarterly",
                                                               "money_banking_monthly"})
    code, out = _gate(tmp_path, capsys, frames, [])
    assert "ALL CHECKS PASSED" in out  # no fatal error, only review notices
    assert "[NOTICE] [SANITY] bop_reserves_vs_cbi_stock 2014-Q1" in out
    identity_lines = [line for line in out.splitlines() if "[IDENTITY]" in line or "[INFO]" in line]
    assert identity_lines and not [line for line in identity_lines if "SANITY" in line or "sanity" in line]


def test_breach_can_be_acknowledged_and_is_value_tied(tmp_path, capsys, frames, monkeypatch):
    monkeypatch.setattr(validate, "production_tables", lambda: {"exchange_rates_daily", "bop_trade_quarterly",
                                                               "money_banking_monthly"})
    warnings = validate.sanity_warnings(frames)
    drafts = validate.propose_acknowledgements(warnings, [], AS_OF)
    assert all("sanity" in d and d["check"] == "sanity" for d in drafts)
    for d in drafts:
        d.update(reason="test", reviewer="t")
    path = tmp_path / "acks.yaml"
    path.write_text(yaml.safe_dump({"acknowledged": drafts}), encoding="utf-8")
    acks = validate.load_acknowledgements(path)
    _, out = _gate(tmp_path, capsys, frames, acks)
    assert "[NOTICE] [SANITY]" not in out and "[ACKNOWLEDGED] [SANITY]" in out

    # a revision of the other side (the CBI stock) makes the acknowledgement stale-valued
    _set(frames, "money_banking_monthly", "money.reserves_official", "2014-03",
         float(frames["money_banking_monthly"].query("series_id == 'money.reserves_official' and date == '2014-03'")["value"].iloc[0]) + 1)
    _, out = _gate(tmp_path, capsys, frames, acks)
    assert "[CHANGED] sanity bop_reserves_vs_cbi_stock 2014-Q1" in out
