"""
tests.test_bis_break_flags
=========================
The BIS marks the quarters where a series breaks (OBS_STATUS = B, with the pre-break value in
OBS_PRE_BREAK). The parser carries every such quarter into the published table as status flag B,
the net position is flagged B when either of its inputs is, and an unexpected status or a missing
status column stops the run.
"""

import csv

import pandas as pd
import pytest

import run_parsers
from conftest import REPO_ROOT, block_network
from fixtures import damage
from source_io import ParseError

RAW_BIS = REPO_ROOT / "pipeline" / "raw" / "bis"
FILES = {
    "bis.lbs.claims_total": "bis_lbs_claims_total.csv",
    "bis.lbs.liabilities_total": "bis_lbs_liabilities_total.csv",
    "bis.lbs.liabilities_banks": "bis_lbs_liabilities_banks.csv",
    "bis.lbs.liabilities_nonbank": "bis_lbs_liabilities_nonbank.csv",
    "bis.lbs.claims_nonbank": "bis_lbs_claims_nonbank.csv",
}


def _break_quarters(path):
    with open(path, encoding="utf-8", newline="") as f:
        return {r["TIME_PERIOD"] for r in csv.DictReader(f) if r["TIME_PERIOD"] >= "2004-Q1" and r["OBS_STATUS"] == "B"}


def _build(tmp_path, edit=None):
    raw_root, seeds_root = damage.copy_inputs("bis_lbs", tmp_path)
    if edit is not None:
        edit(raw_root / "bis")
    with block_network():
        out = damage.run_parser("bis_lbs", raw_root, seeds_root, tmp_path / "out")
    return pd.read_parquet(out / "bis_lbs_quarterly.parquet")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    return _build(tmp_path_factory.mktemp("bis"))


@pytest.mark.parametrize("series_id", sorted(FILES))
def test_every_bis_break_quarter_is_flagged_b(built, series_id):
    expected = _break_quarters(RAW_BIS / FILES[series_id])
    assert expected, "the archived file has break quarters, so the test is meaningful"
    rows = built[built["series_id"] == series_id]
    assert set(rows.loc[rows["status_flag"] == "B", "date"]) == expected


def test_net_position_is_b_when_either_input_is(built):
    breaks = _break_quarters(RAW_BIS / FILES["bis.lbs.claims_total"]) | _break_quarters(
        RAW_BIS / FILES["bis.lbs.liabilities_total"])
    rows = built[built["series_id"] == "bis.lbs.net_position"]
    assert set(rows.loc[rows["status_flag"] == "B", "date"]) == breaks


def test_unexpected_status_stops_the_run(tmp_path):
    def edit(bis):
        path = bis / FILES["bis.lbs.claims_total"]
        lines = path.read_text(encoding="utf-8").splitlines()
        i = next(n for n, line in enumerate(lines) if ",2010-Q2," in line)
        cells = lines[i].split(",")
        cells[cells.index("B")] = "X"
        lines[i] = ",".join(cells)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ParseError) as info:
        _build(tmp_path, edit)
    assert "OBS_STATUS" in str(info.value) and "2010-Q2" in str(info.value) and "'X'" in str(info.value)


def test_missing_status_column_stops_the_run(tmp_path):
    def edit(bis):
        path = bis / FILES["bis.lbs.claims_total"]
        df = pd.read_csv(path).drop(columns=["OBS_STATUS"])
        df.to_csv(path, index=False)

    with pytest.raises(ParseError) as info:
        _build(tmp_path, edit)
    assert "OBS_STATUS" in str(info.value)
