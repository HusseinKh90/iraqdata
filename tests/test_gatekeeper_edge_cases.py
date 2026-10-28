"""
tests.test_gatekeeper_edge_cases
================================
Tests for unfinished periods, provisional flags (P/E),
and status-flag count reporting in coverage.
"""

import re
import pytest

import validate
from conftest import (
    run_validate,
    set_value,
    write_tmp_parquet,
)


UNFINISHED_SID = "crude_production_secondary"
UNFINISHED_DATE = "2026-10"  # ends 2026-10-31, after the 2026-10-22 vintage


def _with_unfinished_row(df, flag):
    """oil_monthly plus one row for a month that ends after its vintage."""
    import pandas as pd
    row = df[df["series_id"] == UNFINISHED_SID].sort_values("date").tail(1).copy()
    row["date"], row["status_flag"], row["realtime_start"] = UNFINISHED_DATE, flag, "2026-10-22"
    return pd.concat([df[~((df["series_id"] == UNFINISHED_SID) & (df["date"] == UNFINISHED_DATE))], row],
                     ignore_index=True)


def test_unfinished_period_requires_provisional_flag(garden_tables, tmp_path):
    """An observation ending after realtime_start without a P, E or U flag triggers Unfinished Period Notice."""
    faulty_df = _with_unfinished_row(garden_tables["oil_monthly"], "A")
    tmp_file = write_tmp_parquet(faulty_df, tmp_path, "oil_monthly")

    proc = run_validate(tmp_file)
    assert "Unfinished Period Notice" in proc.stdout
    assert UNFINISHED_SID in proc.stdout
    assert UNFINISHED_DATE in proc.stdout
    assert "2026-10-22" in proc.stdout


@pytest.mark.parametrize("flag", ["P", "E", "U"])
def test_unfinished_period_with_p_e_or_u_passes(garden_tables, tmp_path, flag):
    """An unfinished observation flagged P, E or U (U is low reliability) passes with 0 notices."""
    df = _with_unfinished_row(garden_tables["oil_monthly"], flag)
    proc = run_validate(write_tmp_parquet(df, tmp_path, f"oil_monthly_{flag}"))
    notices = [line for line in proc.stdout.splitlines()
               if "Unfinished Period Notice" in line and UNFINISHED_SID in line]
    assert notices == []


def test_finished_period_with_a_passes(garden_tables, tmp_path):
    """A finished period (period_end <= realtime_start) with status flag A passes."""
    df = garden_tables["oil_monthly"].copy()
    # 2026-09 ends 2026-09-30 <= realtime_start 2026-10-22
    tmp_file = write_tmp_parquet(df, tmp_path, "oil_monthly")
    proc = run_validate(tmp_file)
    assert "Unfinished Period Notice" not in proc.stdout


def test_real_data_has_no_unfinished_warnings(garden_tables, seed_tables):
    """Real data in garden and seed tables produces zero unfinished_period warnings."""
    for name, df in garden_tables.items():
        _, warnings = validate.validate_tier2_details(df, name)
        unf = [w for w in warnings if w.check == "unfinished_period"]
        assert not unf, f"{name} has unfinished_period warnings: {unf}"

    for name, df in seed_tables.items():
        _, warnings = validate.validate_tier2_details(df, name)
        unf = [w for w in warnings if w.check == "unfinished_period"]
        assert not unf, f"{name} has unfinished_period warnings: {unf}"


def test_flags_line_format():
    """Default run outputs [FLAGS] P=..., E=..., B=..., M=..., U=... with 4-space indent for every dataset."""
    proc = run_validate()
    assert proc.returncode == 0
    flag_lines = [l.strip() for l in proc.stdout.splitlines() if l.strip().startswith("[FLAGS]")]
    assert len(flag_lines) == 14

    pattern = re.compile(r"^\[FLAGS\]\s+P=\d+,\s+E=\d+,\s+B=\d+,\s+M=\d+,\s+U=\d+$")
    for line in flag_lines:
        assert pattern.match(line), f"Malformed [FLAGS] line: {line}"
