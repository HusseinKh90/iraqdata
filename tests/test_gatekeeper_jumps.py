"""
tests.test_gatekeeper_jumps
===========================
Tests for jumps, scale shifts (x1000), break flag handling,
and gap spanning reporting.
"""

import numpy as np
import pandas as pd
import pytest

import validate
from conftest import (
    PRODUCTION_TABLES,
    run_validate,
    set_value,
    write_tmp_parquet,
)


@pytest.mark.parametrize("name", PRODUCTION_TABLES)
def test_times_1000_reported(name, garden_tables, tmp_path):
    """Multiplying a middle observation in a positive series by 1000 triggers Scale Shift."""
    df = garden_tables[name].copy()
    rules = validate.load_rules()["series"]

    # Pick the table's longest strictly positive series
    pos_sids = [
        s for s in df["series_id"].unique()
        if s in rules and rules[s].get("sign") == "positive"
    ]
    counts = df[df["series_id"].isin(pos_sids)]["series_id"].value_counts()
    top_sid = counts.index[0]

    sub = df[df["series_id"] == top_sid]
    mid_idx = sub.index[len(sub) // 2]
    mid_date = str(df.at[mid_idx, "date"])

    faulty_df = set_value(df, mid_date, top_sid, lambda v: v * 1000.0)
    tmp_file = write_tmp_parquet(faulty_df, tmp_path, name)

    proc = run_validate(tmp_file)
    assert "Scale Shift" in proc.stdout
    assert top_sid in proc.stdout
    assert mid_date in proc.stdout


@pytest.mark.parametrize("name", PRODUCTION_TABLES)
def test_divided_by_1000_reported(name, garden_tables, tmp_path):
    """Dividing a middle observation in a positive series by 1000 triggers Scale Shift."""
    df = garden_tables[name].copy()
    rules = validate.load_rules()["series"]

    pos_sids = [
        s for s in df["series_id"].unique()
        if s in rules and rules[s].get("sign") == "positive"
    ]
    counts = df[df["series_id"].isin(pos_sids)]["series_id"].value_counts()
    top_sid = counts.index[0]

    sub = df[df["series_id"] == top_sid]
    mid_idx = sub.index[len(sub) // 2]
    mid_date = str(df.at[mid_idx, "date"])

    faulty_df = set_value(df, mid_date, top_sid, lambda v: v / 1000.0)
    tmp_file = write_tmp_parquet(faulty_df, tmp_path, name)

    proc = run_validate(tmp_file)
    assert "Scale Shift" in proc.stdout
    assert top_sid in proc.stdout
    assert mid_date in proc.stdout


def test_jump_beyond_threshold_reported(garden_tables, tmp_path):
    """A period-on-period move beyond threshold triggers Jump Notice."""
    df = garden_tables["money_banking_monthly"].copy()
    target_date = "2020-01"
    faulty_df = set_value(df, target_date, "money.m2", lambda v: v * 5.0)
    tmp_file = write_tmp_parquet(faulty_df, tmp_path, "money_banking_monthly")

    proc = run_validate(tmp_file)
    assert "Jump Notice" in proc.stdout
    assert "money.m2" in proc.stdout
    assert target_date in proc.stdout


def test_scaled_jump_for_sign_changing_series(garden_tables, tmp_path):
    """Sign-changing series use scaled_change against median absolute value."""
    df = garden_tables["bop_trade_quarterly"].copy()
    rules = validate.load_rules()["series"]
    sid = "bop.current_account"
    rule = rules[sid]
    thresh = float(rule["jump"]["threshold"])

    sub = df[df["series_id"] == sid].dropna(subset=["value"])
    median_abs = float(np.median(np.abs(sub["value"])))

    target_date = "2020-Q1"
    curr_val = float(df[(df["series_id"] == sid) & (df["date"] == target_date)]["value"].iloc[0])
    # Jump with opposite sign and large magnitude
    new_val = -np.sign(curr_val if curr_val != 0 else 1) * median_abs * (thresh + 2.0)

    faulty_df = set_value(df, target_date, sid, new_val)
    tmp_file = write_tmp_parquet(faulty_df, tmp_path, "bop_trade_quarterly")

    proc = run_validate(tmp_file)
    assert "Jump Notice" in proc.stdout
    assert sid in proc.stdout
    assert target_date in proc.stdout


def test_near_zero_crossing_is_not_a_scale_shift(garden_tables, tmp_path):
    """Near-zero values below scale_shift_min_share do not trigger Scale Shift in sign:any series."""
    df = garden_tables["bop_trade_quarterly"].copy()
    sid = "bop.income_net"
    target_date = "2020-Q1"

    # Set value to 0.5 (below 10% of median absolute value of ~500)
    faulty_df = set_value(df, target_date, sid, 0.5)
    tmp_file = write_tmp_parquet(faulty_df, tmp_path, "bop_trade_quarterly")

    proc = run_validate(tmp_file)
    # Must not report Scale Shift for bop.income_net
    scale_shift_lines = [
        l for l in proc.stdout.splitlines() if "Scale Shift" in l and sid in l
    ]
    assert not scale_shift_lines, f"Unexpected scale shift notice: {scale_shift_lines}"


def test_jump_at_break_is_information(garden_tables, tmp_path):
    """A jump at a B-flagged observation is reported as [BREAK], not a review notice."""
    df = garden_tables["money_banking_monthly"].copy()
    target_date = "2020-01"
    faulty_df = set_value(df, target_date, "money.m2", lambda v: v * 1.5)  # inside the envelope
    faulty_df = set_value(faulty_df, target_date, "money.m2", "B", column="status_flag")
    tmp_file = write_tmp_parquet(faulty_df, tmp_path, "money_banking_monthly")

    proc = run_validate(tmp_file)
    assert "[BREAK]" in proc.stdout
    assert "money.m2" in proc.stdout
    assert target_date in proc.stdout
    assert not [line for line in proc.stdout.splitlines() if "[NOTICE]" in line and "Jump Notice" in line]
    assert "0 review notice(s)" in proc.stdout


def test_jump_across_gap_reports_span(garden_tables, tmp_path):
    """A jump across missing periods reports the number of periods spanned."""
    df = garden_tables["money_banking_monthly"].copy()
    # Remove 2020-02 so there is a gap between 2020-01 and 2020-03
    df = df[~((df["series_id"] == "money.m2") & (df["date"] == "2020-02"))]
    faulty_df = set_value(df, "2020-03", "money.m2", lambda v: v * 5.0)
    tmp_file = write_tmp_parquet(faulty_df, tmp_path, "money_banking_monthly")

    proc = run_validate(tmp_file)
    assert "Jump Notice" in proc.stdout
    assert "spanning 2 period(s)" in proc.stdout


def test_first_observation_has_no_jump(garden_tables, tmp_path):
    """The very first observation has no previous period, so no jump is computed."""
    df = garden_tables["money_banking_monthly"].copy()
    sub = df[df["series_id"] == "money.m2"].sort_values("date")
    first_date = str(sub["date"].iloc[0])

    # Increase the first value (still within envelope); a jump, if any, is reported at the
    # second period, never at the first
    faulty_df = set_value(df, first_date, "money.m2", lambda v: v * 1.2)
    _, warnings = validate.validate_tier2_details(faulty_df, "money_banking_monthly")
    assert not [w for w in warnings if w.check == "jump" and first_date in w.periods]


def test_real_data_jump_and_scale_warnings_are_all_acknowledged(garden_tables, seed_tables):
    """Every jump or scale shift on real data is a known, acknowledged event."""
    acks = validate.load_acknowledgements()
    for name, df in {**garden_tables, **seed_tables}.items():
        _, warnings = validate.validate_tier2_details(df, name)
        jump_or_scale = [w for w in warnings if w.check in {"jump", "scale_shift"}]
        _, unacknowledged, _ = validate.match_acknowledgements(jump_or_scale, acks, f"{name}.parquet")
        assert not unacknowledged, f"{name} has unacknowledged jump/scale warnings: {unacknowledged[:3]}"


# =====================================================================
# Jumps across zero and to or from non-positive values
# =====================================================================

def _series(sid, values, unit, flags=None):
    return pd.DataFrame({
        "date": [f"2020-{m:02d}" for m in range(1, len(values) + 1)],
        "series_id": sid, "value": [float(v) for v in values], "unit": unit,
        "status_flag": flags or ["A"] * len(values), "source_hash": "h", "realtime_start": "2026-10-22",
    })


def _jumps(df):
    _, warnings = validate.validate_tier2_details(df, "t")
    return {p for w in warnings if w.check == "jump" for p in w.periods}


def test_scaled_jump_across_zero_is_reported():
    rule = validate.load_rules()["series"]["bop.current_account"]
    scale = rule["jump"]["scale"]
    step = scale * (rule["jump"]["threshold"] + 1)
    df = _series("bop.current_account", [step / 2, -step / 2, -step / 2], "MILLION_USD")
    assert _jumps(df) == {"2020-02"}


def test_log_jump_to_or_from_a_non_positive_value_is_never_skipped():
    df = _series("money.m2", [100000, 0, 100000, -5, 100000], "BILLION_IQD")
    assert _jumps(df) == {"2020-02", "2020-03", "2020-04", "2020-05"}


def test_every_pair_is_measured(garden_tables):
    """No observation pair is skipped because of its sign, on any real series."""
    rules = validate.load_rules()["series"]
    for name, df in garden_tables.items():
        for sid, g in df.dropna(subset=["value"]).groupby("series_id"):
            measure = rules[sid]["jump"]["measure"]
            if (g["value"] <= 0).any():
                assert measure == "scaled", sid


def test_break_flag_still_turns_a_jump_into_information():
    df = _series("money.m2", [100000, 0.1, 100000], "BILLION_IQD", flags=["A", "B", "A"])
    _, warnings = validate.validate_tier2_details(df, "t")
    assert {w.check for w in warnings if w.series == "money.m2"} >= {"break"}
    assert not [w for w in warnings if w.check == "jump"]
