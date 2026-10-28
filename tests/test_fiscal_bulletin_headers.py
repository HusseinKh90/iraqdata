"""
tests.test_fiscal_bulletin_headers
==================================
The seven fiscal series are read from fixed columns of sheet 6-1 of the CBI bulletin. The English
header row above the data must carry the label of every column the parser reads; a swapped,
inserted or renamed column stops the run with the cell named instead of publishing one series
under another's name.
"""

import pandas as pd
import pytest

from conftest import block_network
from fixtures import damage
from source_io import ParseError

SHEET = "6-1"
BULLETIN = "bulletin_latest.xlsx"
HEADER_ROW = 8  # 'Actual  Revenues', ' Current Revenues', ... in the archived bulletin


def _run(tmp_path, edits):
    raw, seeds = damage.copy_inputs("cbi_fiscal_bulletin", tmp_path)
    for cell, value in edits.items():
        damage.edit_cell(raw / "cbi" / BULLETIN, SHEET, cell, value)
    with block_network():
        return damage.run_parser("cbi_fiscal_bulletin", raw, seeds, tmp_path / "out")


def test_swapped_current_and_investment_columns_are_named(tmp_path):
    with pytest.raises(ParseError) as info:
        _run(tmp_path, {f"C{HEADER_ROW}": "Investment Revenues", f"D{HEADER_ROW}": "Current Revenues"})
    msg = str(info.value)
    assert f"cell C{HEADER_ROW}" in msg and "current revenues" in msg and "investment revenues" in msg.lower()
    assert f"sheet '{SHEET}'" in msg


def test_renamed_balance_column_is_named(tmp_path):
    with pytest.raises(ParseError) as info:
        _run(tmp_path, {f"H{HEADER_ROW}": "Net borrowing"})
    assert f"cell H{HEADER_ROW}" in str(info.value) and "Net borrowing" in str(info.value)


def test_missing_header_row_is_named(tmp_path):
    edits = {f"B{HEADER_ROW}": None}
    with pytest.raises(ParseError) as info:
        _run(tmp_path, edits)
    assert "Actual Revenues" in str(info.value) and f"sheet '{SHEET}'" in str(info.value)


def test_cosmetic_changes_to_the_header_text_are_accepted(tmp_path):
    out = _run(tmp_path, {f"B{HEADER_ROW}": "  ACTUAL revenues ", f"H{HEADER_ROW}": "Surplus / Deficit"})
    assert (out / "fiscal_annual.parquet").exists()


def test_year_header_typed_as_float_or_arabic_indic_digits_is_still_a_year(tmp_path):
    base = _run(tmp_path / "base", {})
    out = _run(tmp_path / "typed", {"A29": 2024.0, "A42": "٢٠٢٥"})
    left = pd.read_parquet(base / "fiscal_annual.parquet").drop(columns="source_hash")  # the edited file hashes differently
    right = pd.read_parquet(out / "fiscal_annual.parquet").drop(columns="source_hash")
    pd.testing.assert_frame_equal(left, right)
