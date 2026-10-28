"""
Transcription records.

Hand-typed values live in archived, dated CSV records under pipeline/raw/transcribed/, which the
parsers read; no typed value remains as a constant in parser code.
"""

import re

import pandas as pd
import pytest
import yaml

import transcription
from conftest import GARDEN_DIR, REPO_ROOT

RECORDS_DIR = REPO_ROOT / "pipeline" / "raw" / "transcribed"
PARSERS_DIR = REPO_ROOT / "pipeline" / "parsers"
CATALOG = REPO_ROOT / "src" / "iraqdata" / "series_catalog.yaml"
MANIFEST = REPO_ROOT / "pipeline" / "metadata" / "raw_manifest.yaml"
HEADER = b"series_id,period,value,unit,source_document,page_or_table,transcriber,transcribed_on,notes\n"
EXPECTED_ROWS = {"cosit_gdp_quarterly": 180, "opec_momr_crude_direct": 27, "opec_momr_basrah_anchors": 10}
TABLE_OF = {"cosit_gdp_quarterly": "gdp_quarterly", "opec_momr_crude_direct": "oil_monthly",
            "opec_momr_basrah_anchors": "oil_monthly"}

RECORDS = sorted(RECORDS_DIR.glob("*.csv"))


def _units():
    return {s["series_id"]: s["unit"] for s in yaml.safe_load(CATALOG.read_text(encoding="utf-8"))["series"]}


def _stem(path):
    return re.sub(r"_\d{4}-\d{2}-\d{2}$", "", path.stem)


# a record is never edited: a correction is a newer file, and only the newest of each kind is read
NEWEST = [max(p for p in RECORDS if _stem(p) == stem) for stem in sorted({_stem(p) for p in RECORDS})]


def test_the_three_records_exist():
    assert sorted({_stem(p) for p in RECORDS}) == sorted(EXPECTED_ROWS)


@pytest.mark.parametrize("path", RECORDS, ids=lambda p: p.name)
def test_record_format(path):
    data = path.read_bytes()
    assert data.startswith(HEADER), "header (no BOM, LF)"
    assert b"\r" not in data
    data.decode("utf-8")
    df = transcription.read_transcription(path, _units())
    if path in NEWEST:
        assert len(df) == EXPECTED_ROWS[_stem(path)]
    assert list(df[["series_id", "period"]].itertuples(index=False)) == sorted(df[["series_id", "period"]].itertuples(index=False))
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    assert raw["transcribed_on"].str.fullmatch(r"\d{4}-\d{2}-\d{2}|unknown").all()
    assert (raw["source_document"].str.strip() != "").all() and (raw["transcriber"].str.strip() != "").all()


@pytest.mark.parametrize("path", RECORDS, ids=lambda p: p.name)
def test_record_is_in_the_manifest(path):
    listed = {e["path"] for e in yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["files"]}
    assert path.relative_to(REPO_ROOT).as_posix() in listed


@pytest.mark.parametrize("path", NEWEST, ids=lambda p: p.name)
def test_record_values_equal_the_published_values(path):
    """Moving the values out of the code changed none of them."""
    rec = transcription.read_transcription(path, _units())
    pub = pd.read_parquet(GARDEN_DIR / f"{TABLE_OF[_stem(path)]}.parquet")
    merged = rec.merge(pub, left_on=["series_id", "period"], right_on=["series_id", "date"],
                       suffixes=("_rec", "_pub"), how="left")
    assert merged["value_pub"].notna().all(), "every record row is published"
    assert (merged["value_rec"] == merged["value_pub"]).all()


@pytest.mark.parametrize("path", NEWEST, ids=lambda p: p.name)
def test_published_rows_carry_the_record_hash(path):
    rec = transcription.read_transcription(path, _units())
    pub = pd.read_parquet(GARDEN_DIR / f"{TABLE_OF[_stem(path)]}.parquet")
    merged = rec.merge(pub, left_on=["series_id", "period"], right_on=["series_id", "date"])
    assert len(merged) == len(rec)
    # A merge keeps the stamp of a row whose value did not change, so a row carries the hash of the newest
    # record that holds its value; rows the newest record added or changed carry its own.
    earlier = [p for p in RECORDS if _stem(p) == _stem(path) and p != path]
    allowed = {transcription.file_hash(path)} | {transcription.file_hash(p) for p in earlier}
    assert merged["source_hash_y"].isin(allowed).all()
    previous = {}
    for p in earlier:
        for row in transcription.read_transcription(p, _units()).itertuples(index=False):
            previous[(row.series_id, row.period)] = row.value
    changed = merged[[previous.get((r.series_id, r.period)) != r.value_x for r in merged.itertuples(index=False)]]
    assert (changed["source_hash_y"] == transcription.file_hash(path)).all()


def test_no_typed_constants_remain_in_parsers():
    """No parser holds typed-in constants any more: they live in transcription records."""
    for p in sorted(PARSERS_DIR.glob("*.py")):
        text = p.read_text(encoding="utf-8")
        for name in ("AUDITED_HISTORICAL_GDP", "OPEC_DIRECT_RECENT", "MOMR_BASRAH_ANCHORS"):
            assert name not in text, (p.name, name)
        literals = re.findall(r'"\d{4}-(?:Q\d|\d{2})"\s*:\s*\(?\s*[\d.]', text)
        assert len(literals) < 6, (p.name, "dict of periods to typed numbers")


@pytest.mark.parametrize("bad, message", [
    ("gdp.real,2015-Q1,1.0,MILLION_IQD,d,p,t,unknown,\ngdp.real,2015-Q1,1.0,MILLION_IQD,d,p,t,unknown,\n", "duplicate"),
    ("gdp.real,2015-Q1,abc,MILLION_IQD,d,p,t,unknown,\n", "not a number"),
    ("gdp.real,2015-Q1,1.0,BILLION_IQD,d,p,t,unknown,\n", "unit"),
])
def test_bad_records_are_rejected_with_file_and_line(tmp_path, bad, message):
    path = tmp_path / "bad_2026-10-25.csv"
    path.write_bytes(HEADER + bad.encode())
    with pytest.raises(ValueError, match=message) as exc:
        transcription.read_transcription(path, _units())
    assert path.name in str(exc.value) and re.search(r":\d+:", str(exc.value))


# ---------------------------------------------------------------------- the record the catalog names


def test_the_catalog_names_the_newest_record_of_each_kind():
    for sid, kind in (("gdp.nominal", "cosit_gdp_quarterly"), ("crude_production_direct", "opec_momr_crude_direct"),
                      ("oil_price_basrah", "opec_momr_basrah_anchors")):
        newest = max(p for p in RECORDS if _stem(p) == kind)
        assert transcription.catalog_record_name(sid) == newest.name


def test_a_missing_named_record_is_not_replaced_by_an_older_one(tmp_path):
    older = tmp_path / "cosit_gdp_quarterly_2026-10-25.csv"
    older.write_bytes(HEADER)
    with pytest.raises(FileNotFoundError) as info:
        transcription.newest(tmp_path, "cosit_gdp_quarterly_*.csv", "gdp.nominal")
    assert "cosit_gdp_quarterly_2026-10-28.csv" in str(info.value) and "2026-10-25" in str(info.value)


def test_a_newer_record_the_catalog_does_not_name_yet_is_refused(tmp_path):
    for day in ("2026-10-28", "2027-01-15"):
        (tmp_path / f"cosit_gdp_quarterly_{day}.csv").write_bytes(HEADER)
    with pytest.raises(FileNotFoundError, match="2027-01-15"):
        transcription.newest(tmp_path, "cosit_gdp_quarterly_*.csv", "gdp.nominal")
    assert transcription.newest(tmp_path, "cosit_gdp_quarterly_*.csv").name == "cosit_gdp_quarterly_2027-01-15.csv"
