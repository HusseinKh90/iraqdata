"""
tests.test_govt_claims
======================
Banking-system claims on government (pipeline/parsers/parse_cbi_govt_claims.py): the published table
adds up, it starts in 2018, and a seed December that no longer matches the bulletin stops the parser.
"""

import shutil

import pandas as pd
import pytest

import parse_cbi_govt_claims as p
import source_io
from conftest import GARDEN_DIR, RAW_DIR, SEEDS_DIR

SEED = SEEDS_DIR / "cbi_govt_claims_monthly_seed.csv"


def bulletin():
    import parse_cbi_fiscal_bulletin
    return parse_cbi_fiscal_bulletin.resolve_bulletin_input(RAW_DIR / "cbi")


def test_claims_deposits_and_nets_add_up_every_month():
    w = pd.read_parquet(GARDEN_DIR / f"{p.TABLE}.parquet").pivot(index="date", columns="series_id", values="value")
    assert w.index.min() == p.FIRST_MONTH
    assert len(w) == len(pd.period_range(w.index.min(), w.index.max(), freq="M"))  # no gap
    close = lambda a, b: ((a - b).abs() <= 1.0).all()
    assert close(w[p.CBI_TBILLS] + w[p.CBI_LOANS], w[p.CBI_CLAIMS])
    assert close(w[p.CBI_CLAIMS] - w[p.CBI_DEPOSITS], w[p.CBI_NET])
    assert close(w[p.BANK_CLAIMS] - w[p.BANK_DEPOSITS], w[p.BANK_NET])
    assert close(w[p.CBI_TBILLS] + w[p.BANK_CLAIMS], w[p.SYSTEM_DEBT])
    assert close(w[p.CBI_DEPOSITS] + w[p.BANK_DEPOSITS], w[p.SYSTEM_DEPOSITS])
    assert close(w[p.CBI_NET] + w[p.BANK_NET], w[p.SYSTEM_NET])


def test_seed_december_must_match_the_bulletin(tmp_path):
    seed = tmp_path / SEED.name
    df = pd.read_csv(SEED, dtype={"Date": str})
    df.loc[df["Date"] == "2019-12", "CBI_Gov_Deposits"] += 100000
    df.to_csv(seed, index=False)
    with pytest.raises(source_io.ParseError, match="2019-12"):
        p.parse_cbi_govt_claims(seed, bulletin(), tmp_path / "out.parquet")
