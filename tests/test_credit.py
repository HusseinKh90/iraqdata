"""
tests.test_credit
=================
Commercial bank credit (pipeline/parsers/parse_cbi_credit.py): the published table adds up, and a
seed December that no longer matches the bulletin's year-end row stops the parser.
"""

import shutil

import openpyxl
import pandas as pd
import pytest

import parse_cbi_credit as p
import source_io
from conftest import GARDEN_DIR, RAW_DIR, SEEDS_DIR

SEED = SEEDS_DIR / "cbi_credit_monthly_seed.xlsx"


def bulletin():
    import parse_cbi_fiscal_bulletin
    return parse_cbi_fiscal_bulletin.resolve_bulletin_input(RAW_DIR / "cbi")


def test_bank_types_and_sectors_add_up_every_month():
    df = pd.read_parquet(GARDEN_DIR / f"{p.TABLE}.parquet")
    w = df.pivot(index="date", columns="series_id", values="value")
    assert w.index.min() == "2015-01"
    assert len(w) == len(pd.period_range(w.index.min(), w.index.max(), freq="M"))  # no gap
    assert ((w[p.STATE] + w[p.PRIVATE_BANKS] - w[p.PRIVATE]).abs() <= p.TOLERANCE).all()
    assert ((w[p.PRIVATE] + w[p.CENTRAL] + w[p.PUBLIC] - w[p.TOTAL]).abs() <= p.TOLERANCE).all()


def test_seed_december_must_match_the_bulletin(tmp_path):
    seed = tmp_path / SEED.name
    shutil.copy2(SEED, seed)
    wb = openpyxl.load_workbook(seed)
    ws = wb.active
    row = next(r for r in range(2, ws.max_row + 1) if ws.cell(r, 1).value == "2016-12")
    for col in (2, 3, 7):   # private total, state banks and the grand total, so the month still adds up
        ws.cell(row, col).value += 1000
    wb.save(seed)
    with pytest.raises(source_io.ParseError, match="2016-12"):
        p.parse_cbi_credit(seed, bulletin(), tmp_path / "out.parquet")
