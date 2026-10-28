"""
tests.test_bop_sheet_checks
===========================
A BOP quarter is dated from the workbook's file name and the sheet's name, and read from the column
under "Items". The sheet's own title ("IRAQI BALANCE OF PAYMENTS (BPM6) Q4 2024"), its units line
("Million Of U.S $") and its value-column header ("(FOB)") must agree with that, otherwise the run
stops with the sheet and row named: a stale copied sheet, a changed unit or an inserted column
would otherwise publish plausible numbers under the wrong period or unit.
"""

import re
import warnings

import openpyxl
import pytest

from conftest import REPO_ROOT, block_network
from fixtures import damage
from source_io import ParseError

SHEET = "BOP Q4"
BOP = "bop_2024.xlsx"


def _find(path, sheet, pattern):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ws = openpyxl.load_workbook(path, data_only=True)[sheet]
    for row in ws.iter_rows(min_row=1, max_row=15):
        for cell in row:
            if isinstance(cell.value, str) and re.search(pattern, cell.value, re.I):
                return cell
    raise AssertionError(f"no cell matching {pattern!r}")


def _run(tmp_path, sheet, pattern, new_text):
    raw, seeds = damage.copy_inputs("cbi_bop", tmp_path)
    path = raw / "cbi" / "bop" / BOP
    cell = _find(path, sheet, pattern)
    damage.edit_cell(path, sheet, cell.coordinate, new_text(cell.value) if callable(new_text) else new_text)
    with block_network():
        damage.run_parser("cbi_bop", raw, seeds, tmp_path / "out")
    return cell.coordinate


def _fails(tmp_path, sheet, pattern, new_text):
    with pytest.raises(ParseError) as info:
        _run(tmp_path, sheet, pattern, new_text)
    return str(info.value)


def test_title_of_another_year_is_named(tmp_path):
    msg = _fails(tmp_path, SHEET, r"BALANCE OF PAYMENTS.*Q4", lambda v: v.replace("2024", "2023"))
    assert "bop_2024.xlsx" in msg and f"sheet '{SHEET}'" in msg and "Q4 2024" in msg and "2023" in msg
    assert "period 2024-Q4" in msg


def test_title_of_another_quarter_is_named(tmp_path):
    msg = _fails(tmp_path, SHEET, r"BALANCE OF PAYMENTS.*Q4", lambda v: v.replace("Q4", "Q3"))
    assert "Q4 2024" in msg and "q3 2024" in msg.lower()


def test_missing_title_is_named(tmp_path):
    msg = _fails(tmp_path, SHEET, r"BALANCE OF PAYMENTS.*Q4", "Balance of payments")
    assert f"sheet '{SHEET}'" in msg and "title" in msg


def test_changed_unit_is_named(tmp_path):
    msg = _fails(tmp_path, SHEET, r"million of", "Thousand Of  U.S $")
    assert "Million" in msg and "Thousand" in msg and f"sheet '{SHEET}'" in msg


def test_changed_value_column_header_is_named(tmp_path):
    msg = _fails(tmp_path, SHEET, r"^\(?\s*FOB\s*\)?$", "(CIF)")
    assert "FOB" in msg and "(CIF)" in msg and f"sheet '{SHEET}'" in msg


def test_untouched_workbook_passes(tmp_path):
    raw, seeds = damage.copy_inputs("cbi_bop", tmp_path)
    with block_network():
        out = damage.run_parser("cbi_bop", raw, seeds, tmp_path / "out")
    assert (out / "bop_trade_quarterly.parquet").exists()
