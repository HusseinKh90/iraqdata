"""
tests.test_fx_auction
=====================
CBI foreign currency sales (pipeline/parsers/parse_cbi_fx_auction.py): the published table adds up,
and a seed whose year no longer matches the bulletin's annual total stops the parser.
"""

import shutil

import openpyxl
import pandas as pd
import pytest

import parse_cbi_fx_auction as p
import source_io
from conftest import GARDEN_DIR, RAW_DIR, SEEDS_DIR

SEED = SEEDS_DIR / "cbi_fx_auction_monthly_seed.xlsx"


def bulletin():
    import parse_cbi_fiscal_bulletin
    return parse_cbi_fiscal_bulletin.resolve_bulletin_input(RAW_DIR / "cbi")


def test_cash_plus_transfers_is_total_every_month():
    df = pd.read_parquet(GARDEN_DIR / f"{p.TABLE}.parquet")
    wide = df.pivot(index="date", columns="series_id", values="value")
    assert wide.index.min() == "2020-01"
    assert len(wide) == len(pd.period_range(wide.index.min(), wide.index.max(), freq="M"))  # no gap
    assert ((wide[p.CASH] + wide[p.TRANSFERS] - wide[p.TOTAL]).abs() <= p.TOLERANCE).all()


def test_seed_year_must_add_up_to_the_bulletin(tmp_path):
    seed = tmp_path / SEED.name
    shutil.copy2(SEED, seed)
    wb = openpyxl.load_workbook(seed)
    ws = wb.active
    ws["B2"].value += 100   # 2020-01 cash
    ws["D2"].value += 100   # and its total, so the month still adds up
    wb.save(seed)
    with pytest.raises(source_io.ParseError, match="2020"):
        p.parse_cbi_fx_auction(seed, bulletin(), tmp_path / "out.parquet")
