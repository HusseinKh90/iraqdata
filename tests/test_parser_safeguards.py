"""
Parser safeguards.

A changed source spreadsheet must stop the run with an error that names the file and the sheet,
label, row or period, instead of changing the published data. Each case damages a copy of the
parser's inputs under tmp_path and runs the parser on it, offline. Unchanged copies must give the
same output as today.
"""

import re

import pandas as pd
import pytest

from conftest import block_network
from fixtures import damage
from test_parser_robustness import SPREADSHEET, classify_error, same_content

KFI = "key_financial_indicators.xlsx"
SEED_FX = "cbi_exchange_rate_historical.xlsx"
BULLETIN = "bulletin_latest.xlsx"


def _run(parser, raw_root, seeds_root, tmp_path):
    with block_network():
        return damage.run_parser(parser, raw_root, seeds_root, tmp_path / "out")


def _fails(parser, tmp_path, edit):
    """Damage a copy of the inputs with `edit(raw_root, seeds_root)`; return the parser's ValueError."""
    raw_root, seeds_root = damage.copy_inputs(parser, tmp_path)
    edit(raw_root, seeds_root)
    with pytest.raises(ValueError) as info:
        _run(parser, raw_root, seeds_root, tmp_path)
    return info.value


def _output(parser, tmp_path, edit=None) -> pd.DataFrame:
    raw_root, seeds_root = damage.copy_inputs(parser, tmp_path)
    if edit is not None:
        edit(raw_root, seeds_root)
    out = _run(parser, raw_root, seeds_root, tmp_path)
    import run_parsers
    return pd.read_parquet(out / run_parsers.BY_NAME[parser].outputs[0])


def _has(exc, *words):
    message = str(exc).lower()
    missing = [w for w in words if w.lower() not in message]
    assert not missing, f"{missing} not in: {exc}"


def kfi(raw_root):
    return raw_root / "cbi" / KFI


# ---------------------------------------------------------------- money

def test_money_m2_renamed_stops(tmp_path):
    exc = _fails("cbi_money_banking", tmp_path, lambda r, s: damage.edit_cell(kfi(r), "Sheet1", "B110", "Broad money"))
    _has(exc, KFI, "sheet1", "money.m2", "'m2'")


def test_money_never_takes_the_deposits_component(tmp_path):
    """Old behaviour: a blank M2 label made the scan take row 111, 'Of which: Deposits component of M2'."""
    exc = _fails("cbi_money_banking", tmp_path, lambda r, s: damage.edit_cell(kfi(r), "Sheet1", "B110", None))
    _has(exc, KFI, "money.m2")


def test_money_duplicate_label_stops_and_names_both_rows(tmp_path):
    exc = _fails("cbi_money_banking", tmp_path, lambda r, s: damage.edit_cell(kfi(r), "Sheet1", "B112", "  M1"))
    _has(exc, KFI, "money.m1", "109", "112")


def test_money_missing_source_line_stops(tmp_path):
    exc = _fails("cbi_money_banking", tmp_path, lambda r, s: damage.edit_cell(kfi(r), "Sheet1", "B118", None))
    _has(exc, KFI, "sheet1", "source:")


def test_money_inserted_row_keeps_output(tmp_path):
    base = _output("cbi_money_banking", tmp_path / "a")
    moved = _output("cbi_money_banking", tmp_path / "b", lambda r, s: damage.insert_row(kfi(r), "Sheet1", 50))
    assert same_content(base, moved)


def test_money_formula_without_stored_result_stops(tmp_path):
    exc = _fails("cbi_money_banking", tmp_path, lambda r, s: damage.strip_formula_cache(kfi(r)))
    _has(exc, KFI, "sheet1", "formula")
    assert re.search(r"\b[A-Z]{1,3}\d+\b", str(exc)), exc


# ---------------------------------------------------------------- CPI

@pytest.mark.parametrize("edit, row, expected", [
    (lambda r: damage.insert_row(kfi(r), "Sheet1", 1), "3", ("headline", "1993")),
    (lambda r: damage.swap_rows(kfi(r), "Sheet1", 9, 10), "9", ("headline", "2022")),
    (lambda r: damage.swap_rows(kfi(r), "Sheet1", 5, 7), "5", ("headline", "2007")),
], ids=["row_inserted", "headline_core_swapped", "base_years_swapped"])
def test_cpi_unexpected_row_label_stops(edit, row, expected, tmp_path):
    exc = _fails("cbi_cpi", tmp_path, lambda r, s: edit(r))
    _has(exc, KFI, "sheet1", f"row {row}", *expected)


# ---------------------------------------------------------------- BOP

def bop(raw_root, year):
    return raw_root / "cbi" / "bop" / f"bop_{year}.xlsx"


def test_bop_unmatched_label_stops(tmp_path):
    exc = _fails("cbi_bop", tmp_path,
                 lambda r, s: damage.edit_cell(bop(r, 2024), "BOP Q4", "A9", "Current account balance"))
    _has(exc, "bop_2024.xlsx", "bop q4", "bop.current_account")


def test_bop_missing_year_file_stops(tmp_path):
    exc = _fails("cbi_bop", tmp_path, lambda r, s: bop(r, 2024).unlink())
    _has(exc, "bop_2024.xlsx")


def test_bop_missing_quarter_sheet_stops(tmp_path):
    exc = _fails("cbi_bop", tmp_path, lambda r, s: damage.remove_sheet(bop(r, 2023), "Bop Q2"))
    _has(exc, "bop_2023.xlsx", "q2")


def test_bop_partial_latest_year_is_not_a_gap(tmp_path):
    out = _output("cbi_bop", tmp_path)
    assert out["date"].max() == "2026-Q1"
    assert out.groupby("date")["series_id"].nunique().eq(15).all()


# ---------------------------------------------------------------- exchange rates

def test_fx_missing_year_block_stops(tmp_path):
    """Fx.official is read from the CBI workbook (its 2015 header is A410, as in the seed)."""
    import downloads

    def cbi(r):
        return downloads.latest_version(r / "cbi" / "fx" / "cbi_fx_usd.xlsx")

    exc = _fails("cbi_exchange_rates", tmp_path,
                 lambda r, s: damage.edit_cell(cbi(r), "Daily Price basis", "A410", "Year 15 / Date"))
    _has(exc, "cbi_fx_usd_", "daily price basis", "2015")


def test_fx_formula_without_stored_result_stops(tmp_path):
    exc = _fails("cbi_exchange_rates", tmp_path, lambda r, s: damage.strip_formula_cache(s / SEED_FX))
    _has(exc, SEED_FX, "formula")
    assert re.search(r"\b[A-Z]{1,3}\d+\b", str(exc)), exc


# ---------------------------------------------------------------- fiscal bulletin

def test_bulletin_completed_year_without_december_stops(tmp_path):
    exc = _fails("cbi_fiscal_bulletin", tmp_path,
                 lambda r, s: damage.edit_cell(r / "cbi" / BULLETIN, "6-1", "A54", "Year total"))
    _has(exc, BULLETIN, "6-1", "2025")


def test_bulletin_current_year_without_december_is_fine(tmp_path):
    out = _output("cbi_fiscal_bulletin", tmp_path)
    assert {"2024", "2025"} <= set(out["date"])


# ---------------------------------------------------------------- all are clear errors

CLEAR_CASES = {
    "cbi_money_banking": (KFI, lambda r, s: damage.edit_cell(kfi(r), "Sheet1", "B110", "Broad money")),
    "cbi_cpi": (KFI, lambda r, s: damage.swap_rows(kfi(r), "Sheet1", 9, 10)),
    "cbi_bop": ("bop_2024.xlsx", lambda r, s: bop(r, 2024).unlink()),
    "cbi_exchange_rates": (SEED_FX, lambda r, s: damage.strip_formula_cache(s / SEED_FX)),
    "cbi_fiscal_bulletin": (BULLETIN, lambda r, s: damage.edit_cell(r / "cbi" / BULLETIN, "6-1", "A54", "Year total")),
}


@pytest.mark.parametrize("parser", sorted(CLEAR_CASES))
def test_new_errors_are_clear_errors(parser, tmp_path):
    """Raised in the parser file, by a raise statement, naming the file or label."""
    name, edit = CLEAR_CASES[parser]
    exc = _fails(parser, tmp_path, edit)
    assert classify_error(exc, [name] + SPREADSHEET[parser]["label_words"]) == "clear_error", repr(exc)
