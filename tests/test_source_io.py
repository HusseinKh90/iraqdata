"""
tests.test_source_io
====================
The shared reading, checking and writing helpers of
pipeline/parsers/source_io.py.
"""

import os
import re
import zipfile

import openpyxl
import pandas as pd
import pytest
import yaml

import source_io
from conftest import make_rows
from source_io import ParseError

MESSAGE = re.compile(r"^.+?(, sheet '[^']*')?(, [^:]+)?(, period [^:]+)?: expected .+, found .+", re.S)


def _raises(fn, *args, match=None, **kwargs) -> ParseError:
    with pytest.raises(ParseError) as info:
        fn(*args, **kwargs)
    assert isinstance(info.value, ValueError)
    assert MESSAGE.match(str(info.value)), str(info.value)
    if match:
        assert re.search(match, str(info.value)), str(info.value)
    return info.value


# --- readers ------------------------------------------------------------------------------------

def test_missing_and_empty_files(tmp_path):
    err = _raises(source_io.require_file, tmp_path / "gone.csv", match="gone.csv.*missing")
    assert isinstance(err, FileNotFoundError)
    (tmp_path / "empty.csv").write_bytes(b"")
    _raises(source_io.require_file, tmp_path / "empty.csv", match="empty.csv.*empty file")


def test_workbooks(tmp_path):
    (tmp_path / "zero.xlsx").write_bytes(b"")
    _raises(source_io.open_workbook, tmp_path / "zero.xlsx", match="zero.xlsx")
    (tmp_path / "junk.xlsx").write_bytes(os.urandom(256))
    _raises(source_io.open_workbook, tmp_path / "junk.xlsx", match="junk.xlsx.*Excel workbook")
    _raises(source_io.read_excel, tmp_path / "junk.xlsx", match="junk.xlsx.*Excel workbook")
    wb = openpyxl.Workbook()
    wb.active.title = "Data"
    wb.save(tmp_path / "ok.xlsx")
    assert source_io.open_workbook(tmp_path / "ok.xlsx", ["Data"])["Data"].title == "Data"
    _raises(source_io.open_workbook, tmp_path / "ok.xlsx", ["Sheet1"], match=r"ok.xlsx, sheet 'Sheet1'.*\['Data'\]")


def test_csv_json_zip(tmp_path):
    (tmp_path / "e.csv").write_text("", encoding="utf-8")
    _raises(source_io.read_csv, tmp_path / "e.csv", match="e.csv")
    (tmp_path / "bad.csv").write_bytes(b"a,b\n\xff\xfe,1\n")
    _raises(source_io.read_csv, tmp_path / "bad.csv", match="bad.csv.*CSV")
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    _raises(source_io.read_json, tmp_path / "bad.json", match="bad.json.*JSON")
    (tmp_path / "bad.zip").write_bytes(b"PK no zip")
    _raises(source_io.open_zip, tmp_path / "bad.zip", "INTL.txt", match="bad.zip.*ZIP")
    with zipfile.ZipFile(tmp_path / "ok.zip", "w") as z:
        z.writestr("other.txt", "x")
    _raises(source_io.open_zip, tmp_path / "ok.zip", "INTL.txt", match="INTL.txt")


# --- values -------------------------------------------------------------------------------------

def test_read_value(tmp_path):
    report = source_io.Report("test", exceptions_path=tmp_path / "none.yaml")
    f = tmp_path / "w.xlsx"
    assert source_io.read_value(1234.5, report, f) == 1234.5
    assert source_io.read_value("1,234.5", report, f) == 1234.5
    assert source_io.read_value("١٢٣", report, f) == 123.0
    assert source_io.read_value(None, report, f) is None
    assert source_io.read_value("-", report, f, markers={"-"}) is None
    assert report.markers[str(f)] == {"blank": 1, "'-'": 1}
    _raises(source_io.read_value, "n.a.", report, f, sheet="S", location="row 3, column B", period="2020-01",
            match=r"sheet 'S', row 3, column B, period 2020-01: expected a number, found 'n.a.'")
    _raises(source_io.read_value, 0, report, f, series_id="fx.official", match="positive value")
    _raises(source_io.read_value, -1, report, f, series_id="fx.official", match="positive value")
    assert source_io.read_value(-1, report, f, series_id="bop.current_account") == -1.0
    for text in ("inf", "-inf", "Infinity", "nan"):  # a cell that parses as float but is not a finite number
        _raises(source_io.read_value, text, report, f, series_id="bop.current_account",
                match=f"expected a number, found '{text}'")


def test_listed_exceptions_and_stale_entries(tmp_path, capsys):
    path = tmp_path / "ex.yaml"
    path.write_text(yaml.safe_dump({"exceptions": [
        {"parser": "test", "file": "w_*.xlsx", "sheet": "S", "cell": "B3", "period": "2011-11-31", "value": "x",
         "reason": "r", "reviewed": "2026-10-27"}]}), encoding="utf-8")
    report = source_io.Report("test", exceptions_path=path)
    assert source_io.read_value("x", report, tmp_path / "w_2026.xlsx", sheet="S", period="2011-11-31") is None
    report.finish()
    assert "[EXCEPTION]" in capsys.readouterr().out
    unused = source_io.Report("test", exceptions_path=path)
    _raises(unused.finish, match="ex.yaml.*no such cell")


# --- tables -------------------------------------------------------------------------------------

def test_collapse_duplicates(tmp_path):
    report = source_io.Report("test", exceptions_path=tmp_path / "none.yaml")
    same = pd.concat([make_rows("money.m2", ["2004-01"]), make_rows("money.m2", ["2004-01", "2004-02"])])
    out = source_io.collapse_duplicates(same, "f.xlsx", report)
    assert out["date"].tolist() == ["2004-01", "2004-02"]
    assert report.lines == ["[DUPLICATE] f.xlsx: money.m2 2004-01 x2"]
    clash = pd.concat([make_rows("money.m2", ["2004-01"], values=[1.0]), make_rows("money.m2", ["2004-01"], values=[2.0])])
    _raises(source_io.collapse_duplicates, clash, "f.xlsx", report, where=["row 3", "row 9"],
            match=r"one value for money.m2 2004-01, found 1.0 \(row 3\) and 2.0 \(row 9\)")


def test_check_schema(tmp_path):
    bad = make_rows("money.m2", ["2004-01"]).assign(status_flag="Z")
    _raises(source_io.check_schema, bad, "f.csv", "money_banking_monthly", match="Tier-1 validation failed")


def _daily(dates):
    return make_rows("fx.official", dates, unit="IQD_PER_USD")


def test_daily_coverage(tmp_path):
    gaps = tmp_path / "gaps.yaml"
    gaps.write_text("gaps: []\n", encoding="utf-8")
    source_io.check_daily_coverage(_daily(["2020-01-01", "2020-01-12"]), "f.xlsx", gaps)  # 10 days missing
    _raises(source_io.check_daily_coverage, _daily(["2020-01-01", "2020-01-13"]), "f.xlsx", gaps,
            match=r"period 2020-01-01..2020-01-13.*11 days")
    gaps.write_text(yaml.safe_dump({"gaps": [{"series": "fx.official", "from": "2020-01-01", "to": "2020-01-13",
                                              "reason": "r", "reviewed": "2026-10-27"}]}), encoding="utf-8")
    source_io._load_list.cache_clear()
    source_io.check_daily_coverage(_daily(["2020-01-01", "2020-01-13"]), "f.xlsx", gaps)
    _raises(source_io.check_daily_coverage, _daily(["2020-01-01", "2020-01-02"]), "f.xlsx", gaps, match="no such gap")
    source_io._load_list.cache_clear()


# --- atomic output ------------------------------------------------------------------------------

def test_write_table_is_atomic(tmp_path, monkeypatch):
    df = make_rows("money.m2", ["2004-01"])
    direct = tmp_path / "direct.parquet"
    df.to_parquet(direct, index=False)
    target = tmp_path / "t.parquet"
    source_io.write_table(df, target)
    assert target.read_bytes() == direct.read_bytes()
    assert not (tmp_path / "t.parquet.part").exists()

    before = target.read_bytes()

    def fail(*a, **k):
        raise OSError("interrupted")

    monkeypatch.setattr(source_io.os, "replace", fail)
    with pytest.raises(OSError):
        source_io.write_table(make_rows("money.m2", ["2004-01", "2004-02"]), target)
    assert target.read_bytes() == before
    assert (tmp_path / "t.parquet.part").exists()
