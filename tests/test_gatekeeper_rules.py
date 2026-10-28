"""
tests.test_gatekeeper_rules
===========================
Tests for plausibility envelopes, sign checks, unit checks,
unruled series detection, and coverage line reporting.
"""

import re
import pandas as pd
import pytest

import validate
from conftest import (
    GATE_SUMMARY,
    PRODUCTION_TABLES,
    run_validate,
    set_value,
    write_tmp_parquet,
)


def test_every_series_has_a_rule(garden_tables, seed_tables):
    """Every series in the 10 production tables and 4 seed tables has a rule entry."""
    rules = validate.load_rules()
    series_rules = rules.get("series", {})
    all_series = set()
    for df in garden_tables.values():
        all_series.update(df["series_id"].unique())
    for df in seed_tables.values():
        all_series.update(df["series_id"].unique())

    assert len(all_series) == 62
    missing = all_series - set(series_rules.keys())
    assert not missing, f"Missing rules for series: {sorted(missing)}"


def test_rules_are_well_formed():
    """Rules schema: statistical or reviewed, log or scaled jumps."""
    rules = validate.load_rules()
    series_rules = rules.get("series", {})

    assert len(series_rules) == 62

    for sid, entry in series_rules.items():
        assert "unit" in entry and entry["unit"], f"{sid} missing unit"
        if "exempt" in entry:
            assert entry["exempt"], f"{sid} has empty exempt reason"
            continue

        for req in ["min", "max", "sign", "jump", "basis", "reviewed"]:
            assert req in entry, f"{sid} missing {req}"

        min_v = float(entry["min"])
        max_v = float(entry["max"])
        assert min_v <= max_v, f"{sid}: min {min_v} > max {max_v}"
        assert entry["sign"] in {"positive", "non_negative", "any"}, f"{sid} invalid sign"

        jump = entry["jump"]
        assert jump["measure"] in {"log", "scaled"}, f"{sid} invalid jump measure"
        assert jump["threshold"] > 0, f"{sid} jump threshold must be positive"
        if jump["measure"] == "scaled":
            assert jump["scale"] > 0, f"{sid}: a scaled jump needs its scale"

        assert entry["basis"] in {"statistical", "reviewed"}, f"{sid} invalid basis"
        if entry["basis"] == "reviewed":
            assert entry.get("rationale"), f"{sid}: reviewed rule without rationale"
        else:
            assert re.match(r"^\d{4}-\d{2}-\d{2}$", str(entry["derived_through"])), f"{sid} invalid derived_through"

        assert re.match(r"^\d{4}-\d{2}-\d{2}$", str(entry["reviewed"])), f"{sid} invalid reviewed date"

        if entry["unit"] == "PERCENT":
            assert 0.0 <= min_v and max_v <= 100.0, f"{sid}: PERCENT envelope outside [0, 100]"


def test_real_data_inside_envelopes(garden_tables):
    """Real data in garden tables all respect their envelopes and signs."""
    rules = validate.load_rules()
    series_rules = rules.get("series", {})

    for name, df in garden_tables.items():
        for sid in df["series_id"].unique():
            rule = series_rules.get(sid)
            if not rule or rule.get("exempt"):
                continue
            sub = df[df["series_id"] == sid].dropna(subset=["value"])
            min_v = float(rule["min"])
            max_v = float(rule["max"])
            out = sub[(sub["value"] < min_v) | (sub["value"] > max_v)]
            assert out.empty, f"{name}/{sid} has {len(out)} values outside [{min_v}, {max_v}]"

            sign = rule.get("sign")
            if sign == "positive":
                bad_sign = sub[sub["value"] <= 0]
                assert bad_sign.empty, f"{name}/{sid} has non-positive values"
            elif sign == "non_negative":
                bad_sign = sub[sub["value"] < 0]
                assert bad_sign.empty, f"{name}/{sid} has negative values"


@pytest.mark.parametrize("name", PRODUCTION_TABLES)
def test_out_of_envelope_value_reported(name, garden_tables, tmp_path):
    """Values outside envelope are reported as Plausibility Notice with series and date."""
    df = garden_tables[name].copy()
    counts = df["series_id"].value_counts()
    top_sid = counts.index[0]

    if name == "fiscal_annual":
        top_sid = "fiscal.revenue_total"
    elif name == "gdp_quarterly":
        top_sid = "gdp.real"
    elif name == "oecd_dac_annual":
        top_sid = "oecd.dac.oda_total_net"
    elif name == "money_banking_monthly":
        top_sid = "money.m2"

    rules = validate.load_rules()
    rule = rules["series"][top_sid]
    sub = df[df["series_id"] == top_sid]
    mid_idx = sub.index[len(sub) // 2]
    mid_date = str(df.at[mid_idx, "date"])

    max_v = float(rule["max"])
    old_v = float(df.at[mid_idx, "value"])
    new_v = max_v * 10
    delta = new_v - old_v

    faulty_df = set_value(df, mid_date, top_sid, new_v)

    # Balance accounting identities where all series are bound by strict equalities
    if name == "fiscal_annual":
        faulty_df = set_value(faulty_df, mid_date, "fiscal.revenue_current", lambda v: v + delta)
        faulty_df = set_value(faulty_df, mid_date, "fiscal.balance", lambda v: v + delta)
    elif name == "gdp_quarterly":
        faulty_df = set_value(faulty_df, mid_date, "gdp.real_oil", lambda v: v + delta)
    elif name == "oecd_dac_annual":
        faulty_df = set_value(faulty_df, mid_date, "oecd.dac.grants_excl_tc", lambda v: v + delta)

    tmp_file = write_tmp_parquet(faulty_df, tmp_path, name)

    proc = run_validate(tmp_file)
    assert proc.returncode == 0
    assert "Plausibility Notice" in proc.stdout
    assert top_sid in proc.stdout
    assert mid_date in proc.stdout


def test_negative_level_reported(garden_tables, tmp_path):
    """Negative values in positive series trigger Sign Notice."""
    df = garden_tables["money_banking_monthly"].copy()
    faulty_df = set_value(df, "2020-01", "money.m2", -5.0)
    tmp_file = write_tmp_parquet(faulty_df, tmp_path, "money_banking_monthly")

    proc = run_validate(tmp_file)
    assert "Sign Notice" in proc.stdout
    assert "money.m2" in proc.stdout
    assert "2020-01" in proc.stdout


def test_unit_mismatch_is_fatal(garden_tables, tmp_path):
    """Mismatched unit is a fatal Tier 2 error."""
    df = garden_tables["oil_daily"].copy()
    sub = df[df["series_id"] == "oil_price_brent"]
    test_date = str(sub["date"].iloc[0])

    faulty_df = set_value(df, test_date, "oil_price_brent", "USD_PER_TONNE", column="unit")
    tmp_file = write_tmp_parquet(faulty_df, tmp_path, "oil_daily")

    proc = run_validate(tmp_file)
    assert proc.returncode == 1
    assert "Unit Mismatch" in proc.stdout
    assert "oil_price_brent" in proc.stdout
    assert "USD_PER_TONNE" in proc.stdout
    assert test_date in proc.stdout


def test_unruled_series_reported(garden_tables, tmp_path):
    """An unruled series triggers an Unchecked series notice and shows in coverage."""
    df = garden_tables["money_banking_monthly"].copy()
    new_row = pd.DataFrame([{
        "date": "2024-01",
        "series_id": "money.m3",
        "value": 1000.0,
        "unit": "BILLION_IQD",
        "status_flag": "A",
        "realtime_start": "2024-02-01",
        "source_hash": "testhash",
    }])
    df = pd.concat([df, new_row], ignore_index=True)
    tmp_file = write_tmp_parquet(df, tmp_path, "money_banking_monthly")

    proc = run_validate(tmp_file)
    assert "Unchecked series" in proc.stdout
    assert "money.m3" in proc.stdout
    assert "[COVERAGE]" in proc.stdout
    assert "1 unchecked" in proc.stdout


def test_coverage_line_on_real_data():
    """Default validate run outputs [COVERAGE] lines for each dataset with 0 unchecked."""
    proc = run_validate()
    assert proc.returncode == 0
    coverage_lines = [
        line.strip() for line in proc.stdout.splitlines() if line.strip().startswith("[COVERAGE]")
    ]
    assert len(coverage_lines) == 14
    for line in coverage_lines:
        assert "0 unchecked" in line
        assert "0 exempt" in line

    # Sum of checked series across production tables must equal 64
    checked_counts = [
        int(re.search(r"series:\s*(\d+)\s*checked", l).group(1)) for l in coverage_lines[:10]
    ]
    assert sum(checked_counts) == 62  # gross ODA and the aid residual withdrawn
    assert GATE_SUMMARY in proc.stdout
