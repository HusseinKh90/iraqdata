"""
tests.test_gatekeeper_identities
================================
Tests for BOP accounting identities, monetary ordering inequalities,
identity coverage kinds (independent vs definitional, from the catalog), and format.
"""

import re
import pytest

import validate
from conftest import (
    run_validate,
    set_value,
    write_tmp_parquet,
)


def test_real_data_satisfies_all_identities(garden_tables, seed_tables):
    """Real data satisfies all identities with 0 skipped (or expected boundary skips) and 0 errors."""
    for name, df in garden_tables.items():
        cov = validate.identity_coverage(df)
        definitional = {rule for rule, _, n in validate.definitional_coverage(df) if n}
        for rule, checked, skipped in cov:
            # Currency <= M1 has 1 skipped period: the latest month, published for currency (KFI
            # workbook) before M1 (bulletin); an expected ragged edge (expected_gaps.yaml)
            max_allowed_skipped = 1 if rule == "Currency <= M1" else 0
            assert skipped <= max_allowed_skipped, f"{name}/{rule} has skipped periods: {skipped}"
            # A rule that holds by definition has no checked periods
            assert checked > 0 or rule in definitional, f"{name}/{rule} has 0 checked periods"
        errors, _ = validate.validate_tier2_details(df, name)
        assert not errors, f"{name} has identity errors: {errors}"

    for name, df in seed_tables.items():
        cov = validate.identity_coverage(df)
        definitional = {rule for rule, _, n in validate.definitional_coverage(df) if n}
        for rule, checked, skipped in cov:
            max_allowed_skipped = 1 if rule == "Currency <= M1" else 0
            assert skipped <= max_allowed_skipped, f"{name}/{rule} has skipped periods: {skipped}"
            assert checked > 0 or rule in definitional, f"{name}/{rule} has 0 checked periods"
        errors, _ = validate.validate_tier2_details(df, name)
        assert not errors, f"{name} has identity errors: {errors}"


def test_identity_kinds_come_from_the_catalog():
    """No hand-kept label list; the definitional rules follow from the catalog."""
    assert not hasattr(validate, "identity_labels")
    rule_names = [rule for rule, _ in validate.IDENTITY_RULES]
    assert "OECD net ODA" not in rule_names  # residual withdrawn
    assert "OECD gross >= net" not in rule_names  # gross ODA withdrawn
    assert len(rule_names) == 14


def test_bop_trade_balance_failure(garden_tables, tmp_path):
    """Breaking BOP trade balance = exports - imports is detected as fatal error."""
    df = garden_tables["bop_trade_quarterly"].copy()
    target_date = "2020-Q1"
    faulty_df = set_value(df, target_date, "bop.trade_balance", lambda v: v + 50000.0)
    tmp_file = write_tmp_parquet(faulty_df, tmp_path, "bop_trade_quarterly")

    proc = run_validate(tmp_file)
    assert proc.returncode == 1
    assert "Trade Balance" in proc.stdout
    assert target_date in proc.stdout


def test_bop_exports_failure(garden_tables, tmp_path):
    """Breaking BOP exports decomposition is detected as fatal error."""
    df = garden_tables["bop_trade_quarterly"].copy()
    target_date = "2020-Q1"
    faulty_df = set_value(df, target_date, "trade.exports_crude_oil", lambda v: v + 50000.0)
    tmp_file = write_tmp_parquet(faulty_df, tmp_path, "bop_trade_quarterly")

    proc = run_validate(tmp_file)
    assert proc.returncode == 1
    assert "Exports" in proc.stdout
    assert target_date in proc.stdout


def test_bop_imports_failure(garden_tables, tmp_path):
    """Breaking BOP imports decomposition is detected as fatal error."""
    df = garden_tables["bop_trade_quarterly"].copy()
    target_date = "2020-Q1"
    faulty_df = set_value(df, target_date, "trade.imports_government", lambda v: v + 50000.0)
    tmp_file = write_tmp_parquet(faulty_df, tmp_path, "bop_trade_quarterly")

    proc = run_validate(tmp_file)
    assert proc.returncode == 1
    assert "Imports" in proc.stdout
    assert target_date in proc.stdout


def test_bop_current_account_failure(garden_tables, tmp_path):
    """Breaking BOP current account identity is detected as fatal error."""
    df = garden_tables["bop_trade_quarterly"].copy()
    target_date = "2020-Q1"
    faulty_df = set_value(df, target_date, "bop.current_account", lambda v: v + 50000.0)
    tmp_file = write_tmp_parquet(faulty_df, tmp_path, "bop_trade_quarterly")

    proc = run_validate(tmp_file)
    assert proc.returncode == 1
    assert "Current Account" in proc.stdout
    assert target_date in proc.stdout


def test_currency_exceeds_m0(garden_tables, tmp_path):
    """Setting currency_outside_banks > M0 triggers fatal inversion error with values."""
    df = garden_tables["money_banking_monthly"].copy()
    target_date = "2020-01"
    m0_val = float(df[(df["series_id"] == "money.m0") & (df["date"] == target_date)]["value"].iloc[0])
    faulty_val = m0_val + 10000.0
    faulty_df = set_value(df, target_date, "money.currency_outside_banks", faulty_val)
    tmp_file = write_tmp_parquet(faulty_df, tmp_path, "money_banking_monthly")

    proc = run_validate(tmp_file)
    assert proc.returncode == 1
    assert "Currency Outside Banks > M0" in proc.stdout
    assert target_date in proc.stdout
    assert str(faulty_val) in proc.stdout or f"{faulty_val:,.1f}" in proc.stdout or "10000" in proc.stdout


def test_currency_exceeds_m1(garden_tables, tmp_path):
    """Setting currency_outside_banks > M1 triggers fatal inversion error with values."""
    df = garden_tables["money_banking_monthly"].copy()
    target_date = "2020-01"
    m1_val = float(df[(df["series_id"] == "money.m1") & (df["date"] == target_date)]["value"].iloc[0])
    faulty_val = m1_val + 5000.0  # strictly exceeds M1
    faulty_df = set_value(df, target_date, "money.currency_outside_banks", faulty_val)
    tmp_file = write_tmp_parquet(faulty_df, tmp_path, "money_banking_monthly")

    proc = run_validate(tmp_file)
    assert proc.returncode == 1
    assert "Currency Outside Banks > M1" in proc.stdout
    assert target_date in proc.stdout


def test_identity_line_format():
    """Default run outputs an [IDENTITY] line per present rule: independent or definitional."""
    proc = run_validate()
    assert proc.returncode == 0
    id_lines = [l.strip() for l in proc.stdout.splitlines() if l.strip().startswith("[IDENTITY]")]
    assert len(id_lines) >= 7

    for line in id_lines:
        if re.match(r"^\[IDENTITY\] .+ \(definitional: \S+\): \d+ period\(s\), not a check$", line):
            continue
        match = re.match(r"^\[IDENTITY\]\s+(.+)\s+\((independent)\):\s+checked\s+(\d+),\s+skipped\s+(\d+)(; .+)?$", line)
        assert match is not None, f"Malformed identity line: {line}"
        if match.group(1) == "Fiscal balance":
            assert match.group(5) == "; 2004-2023 from a seed of unknown origin"


# =====================================================================
# Identity gaps are review notices unless expected
# =====================================================================

def _gaps(df):
    _, warnings = validate.validate_tier2_details(df, "money_banking_monthly.parquet")
    return {(w.series, w.periods[0]) for w in warnings if w.check == "gap"}


def test_ragged_edge_gap_is_expected(garden_tables):
    """Production: currency is published a month before M1; that latest-month gap is expected."""
    assert _gaps(garden_tables["money_banking_monthly"]) == set()


def test_gap_inside_the_data_is_a_notice(garden_tables):
    df = garden_tables["money_banking_monthly"]
    df = df[~((df["series_id"] == "money.m1") & (df["date"] == "2015-06"))]
    # M1 is missing where currency and M2 are published: two identities cannot be checked
    assert _gaps(df) == {("money.m1", "2015-06")}
    _, warnings = validate.validate_tier2_details(df, "money_banking_monthly.parquet")
    messages = [w.message for w in warnings if w.check == "gap"]
    assert any("[GAP] Currency <= M1 2015-06: money.m1 missing" in m for m in messages)
    assert any("[GAP] Broad money hierarchy 2015-06: money.m1 missing" in m for m in messages)


def test_ragged_edge_rule_does_not_hide_a_missing_older_value(garden_tables):
    """`period: latest` covers only periods after the missing series' last value."""
    df = garden_tables["money_banking_monthly"]
    last_m1 = df.loc[df["series_id"] == "money.m1", "date"].max()
    df = df[~((df["series_id"] == "money.m1") & (df["date"] == last_m1))]
    # Currency <= M1 at last_m1 is still after M1's (new) last value, so expected; Broad money
    # hierarchy (M2 published, M1 not) has no expected entry, so its gap is a notice
    assert _gaps(df) == {("money.m1", last_m1)}


def test_gap_can_be_acknowledged(garden_tables, tmp_path, capsys):
    import yaml
    df = garden_tables["money_banking_monthly"]
    df = df[~((df["series_id"] == "money.m1") & (df["date"] == "2015-06"))]
    path = tmp_path / "t.parquet"
    df.to_parquet(path, index=False)
    acks_path = tmp_path / "acks.yaml"
    acks_path.write_text(yaml.safe_dump({"acknowledged": [
        {"series": "money.m1", "check": "gap", "periods": ["2015-06"], "reason": "test gap",
         "reviewer": "t", "date": "2026-10-26", "review_by": "2027-10-26"}]}), encoding="utf-8")
    acks = validate.load_acknowledgements(acks_path)
    import pandas as pd
    validate.run_gatekeeper([path], acks, release=False, freshness=False, as_of=pd.Timestamp("2026-10-26"),
                            all_datasets=False)
    out = capsys.readouterr().out
    assert "[ACKNOWLEDGED]" in out and "[GAP]" in out
    assert not [line for line in out.splitlines() if "[NOTICE]" in line and "[GAP]" in line]


def test_gap_notices_leave_identity_coverage_unchanged(garden_tables):
    cov = dict((r, (c, s)) for r, c, s in validate.identity_coverage(garden_tables["money_banking_monthly"]))
    assert cov["Currency <= M1"][1] == 1
