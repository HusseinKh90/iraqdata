"""
tests.test_fiscal_seed_check
============================
The fiscal seed (2004-2023, publisher not recorded, status flag U) is compared with the annual
budget table of the archived CBI bulletin (sheet 6-1), which prints the same years. Of the 108
values both print, 106 are identical; the other two are the 2012 current and investment revenue
columns, which the bulletin has transposed. The check is evidence for the seed, not a change of
its status.
"""

import csv

import openpyxl
import pytest

import check_fiscal_seed as check
from conftest import REPO_ROOT, SEEDS_DIR
from fixtures import damage


def _run(seed=check.SEED, bulletin=check.BULLETIN):
    return check.compare(check.read_seed(seed), check.read_bulletin(bulletin))


def test_the_seed_agrees_with_the_bulletin_except_for_the_transposed_columns():
    counts, problems = _run()
    assert problems == []
    assert counts == {"identical": 106, "explained": 2, "not-printed": 32, "differs": 0, "stale-exception": 0}


def test_the_bulletin_columns_are_found_by_their_header_text():
    printed = check.read_bulletin()
    assert sorted(printed) == list(range(2004, 2024))
    assert printed[2004]["revenue_actual_total"] == 32982739 and printed[2004]["revenue_current"] is None
    assert printed[2013]["expenditure_current"] == 72225630


def test_the_known_difference_is_a_real_transposition():
    printed, seed = check.read_bulletin()[2012], check.read_seed()[2012]
    assert printed["revenue_current"] == seed["revenue_investment"] == 78495
    assert printed["revenue_investment"] == seed["revenue_current"] == 119387908
    assert seed["revenue_current"] + seed["revenue_investment"] == pytest.approx(seed["revenue_actual_total"], abs=100_000)


def test_the_command_line_reports_ok(capsys):
    assert check.main([]) == 0
    out = capsys.readouterr().out
    assert "106 identical, 2 explained, 0 differ" in out and out.strip().endswith("Fiscal seed check: OK")


def test_a_changed_seed_value_is_named(tmp_path):
    seed = tmp_path / "seed.csv"
    rows = list(csv.DictReader(open(check.SEED, encoding="utf-8", newline="")))
    rows[3]["revenue_actual_total"] = "52046699"  # 2007, one million IQD off
    with open(seed, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    counts, problems = _run(seed=seed)
    assert counts["differs"] == 1 and len(problems) == 1
    assert "revenue_actual_total 2007" in problems[0] and "52,046,699" in problems[0]


def test_columns_are_matched_by_header_not_position(tmp_path):
    """Swapping two header labels swaps what is compared: nothing may agree by accident."""
    bulletin = tmp_path / "bulletin.xlsx"
    bulletin.write_bytes(check.BULLETIN.read_bytes())
    ws = openpyxl.load_workbook(bulletin, data_only=True)["6-1"]
    row = next(r for r in range(1, 13) if ws.cell(r, 2).value and "Actual" in str(ws.cell(r, 2).value))
    damage.edit_cell(bulletin, "6-1", f"E{row}", " Actual  Revenues")
    damage.edit_cell(bulletin, "6-1", f"B{row}", "Actual  Expenditures")
    counts, problems = _run(bulletin=bulletin)
    assert counts["differs"] > 20 and problems


def test_a_corrected_bulletin_makes_the_exception_stale(tmp_path):
    bulletin = tmp_path / "bulletin.xlsx"
    bulletin.write_bytes(check.BULLETIN.read_bytes())
    ws = openpyxl.load_workbook(bulletin, data_only=True)["6-1"]
    row = next(r for r in range(9, 40) if ws.cell(r, 1).value == 2012)
    damage.edit_cell(bulletin, "6-1", f"C{row}", 119387908)
    damage.edit_cell(bulletin, "6-1", f"D{row}", 78495)
    counts, problems = _run(bulletin=bulletin)
    assert counts == {"identical": 106, "explained": 0, "not-printed": 32, "differs": 0, "stale-exception": 2}
    assert len(problems) == 2 and "stale" in problems[0]


def test_a_workbook_without_the_budget_headers_is_refused(tmp_path):
    bulletin = tmp_path / "bulletin.xlsx"
    bulletin.write_bytes(check.BULLETIN.read_bytes())
    damage.edit_cell(bulletin, "6-1", "B8", "Something else")
    with pytest.raises(ValueError, match="seven budget headers"):
        check.read_bulletin(bulletin)


def test_the_seed_in_the_repository_is_the_one_checked():
    assert check.SEED == SEEDS_DIR / "iraq_fiscal_historical.csv"
    assert check.BULLETIN == REPO_ROOT / "pipeline" / "raw" / "cbi" / "bulletin_latest.xlsx"
