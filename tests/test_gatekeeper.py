"""
tests.test_gatekeeper
=====================
The quality gatekeeper (pipeline/validate.py) verifies every
default dataset, enforces the accounting identities and the broad money
hierarchy, and reports identity coverage.
"""

import sys

import pytest

from conftest import GATE_SUMMARY, REPO_ROOT, run_validate, write_tmp_parquet

sys.path.insert(0, str(REPO_ROOT / "pipeline"))

from validate import identity_coverage, validate_tier2_domain  # noqa: E402

BASELINE = GATE_SUMMARY
INFO_RULES = ["Fiscal balance", "Nominal GDP", "Real GDP", "BIS net position", "Broad money hierarchy"]


def _coverage(df) -> dict[str, tuple[int, int]]:
    return {rule: (checked, skipped) for rule, checked, skipped in identity_coverage(df)}


# =====================================================================
# CLI baseline
# =====================================================================

def test_cli_baseline_passes_with_zero_notices():
    result = run_validate()
    assert result.returncode == 0, result.stdout + result.stderr
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert lines[-1] == BASELINE
    assert "[NOTICE]" not in result.stdout
    info_lines = [ln.strip() for ln in lines if ln.strip().startswith("[INFO]")]
    for rule in INFO_RULES:
        assert any(ln.startswith(f"[INFO] {rule}: checked ") for ln in info_lines), rule
    assert all(ln.endswith("(missing components)") for ln in info_lines)


# =====================================================================
# Identities hold on the real data
# =====================================================================

@pytest.mark.parametrize(
    "name", ["fiscal_annual", "gdp_quarterly", "bis_lbs_quarterly", "money_banking_monthly"]
)
def test_identities_hold_on_garden_data(garden_tables, name):
    errors, _ = validate_tier2_domain(garden_tables[name], name)
    assert errors == []


@pytest.mark.parametrize(
    "name, rule, expected",
    [
        ("fiscal_annual", "Fiscal balance", 22),
        # These three hold by definition (one member is derived from the others), so
        # none of their 44/44/89 complete periods counts as checked
        ("gdp_quarterly", "Nominal GDP", 0),
        ("gdp_quarterly", "Real GDP", 0),
        ("bis_lbs_quarterly", "BIS net position", 0),
        ("bis_lbs_quarterly", "BIS sector liabilities", 89),
        ("money_banking_monthly", "Broad money hierarchy", 272),
    ],
)
def test_identity_coverage_counts(garden_tables, name, rule, expected):
    assert _coverage(garden_tables[name])[rule] == (expected, 0)


# =====================================================================
# Deliberately broken copies are caught and gaps are skipped
# =====================================================================

def _set_value(df, date, series_id, fn):
    mask = (df["date"] == date) & (df["series_id"] == series_id)
    assert mask.sum() == 1, f"expected one row for {series_id} @ {date}"
    df.loc[mask, "value"] = fn(df.loc[mask, "value"])
    return df


def test_broken_fiscal_balance_fails(garden_tables, tmp_path):
    df = _set_value(garden_tables["fiscal_annual"].copy(), "2015", "fiscal.balance", lambda v: v + 1000)
    result = run_validate(write_tmp_parquet(df, tmp_path, "fiscal_annual"))
    assert result.returncode == 1
    assert "VALIDATION FAILED" in result.stdout
    assert "Fiscal" in result.stdout and "2015" in result.stdout


def test_broken_nominal_gdp_fails(garden_tables, tmp_path):
    df = _set_value(garden_tables["gdp_quarterly"].copy(), "2019-Q3", "gdp.nominal_oil", lambda v: v * 1000)
    result = run_validate(write_tmp_parquet(df, tmp_path, "gdp_quarterly"))
    assert result.returncode == 1
    assert "Nominal" in result.stdout and "2019-Q3" in result.stdout


def test_broken_bis_net_position_fails(garden_tables, tmp_path):
    df = _set_value(garden_tables["bis_lbs_quarterly"].copy(), "2015-Q2", "bis.lbs.net_position", lambda v: v + 1.0)
    result = run_validate(write_tmp_parquet(df, tmp_path, "bis_lbs_quarterly"))
    assert result.returncode == 1
    assert "BIS Net Position" in result.stdout and "2015-Q2" in result.stdout


def test_m1_equal_to_m2_is_an_inversion(garden_tables, tmp_path):
    df = garden_tables["money_banking_monthly"].copy()
    m2 = df.loc[(df["date"] == "2020-06") & (df["series_id"] == "money.m2"), "value"].iloc[0]
    df = _set_value(df, "2020-06", "money.m1", lambda v: m2)
    result = run_validate(write_tmp_parquet(df, tmp_path, "money_banking_monthly"))
    assert result.returncode == 1
    assert "M1 >= M2" in result.stdout and "2020-06" in result.stdout


def test_fiscal_balance_within_tolerance_passes(garden_tables, tmp_path):
    df = _set_value(garden_tables["fiscal_annual"].copy(), "2015", "fiscal.balance", lambda v: v + 0.05)
    result = run_validate(write_tmp_parquet(df, tmp_path, "fiscal_annual"))
    assert result.returncode == 0, result.stdout


def test_missing_component_is_skipped_not_failed(garden_tables, tmp_path):
    # An independent identity (definitional ones have no checked periods to lose)
    df = garden_tables["bis_lbs_quarterly"].copy()
    df = df[~((df["date"] == "2020-Q1") & (df["series_id"] == "bis.lbs.liabilities_nonbank"))].reset_index(drop=True)
    assert _coverage(df)["BIS sector liabilities"] == (88, 1)
    result = run_validate(write_tmp_parquet(df, tmp_path, "bis_lbs_quarterly"))
    assert result.returncode == 0, result.stdout
    assert "[INFO] BIS sector liabilities: checked 88 period(s), skipped 1 (missing components)" in result.stdout
