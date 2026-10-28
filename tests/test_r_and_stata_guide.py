"""
tests.test_r_and_stata_guide
============================
docs/r_and_stata.md describes the release CSV files, and its R examples run as written (when R is
installed) against the files of the release in this repository. The Stata examples cannot be run
here, so the test checks everything they rely on: the files, the columns, the series and the date
formats.
"""

import re
import shutil
import subprocess

import pandas as pd
import pytest

import iraqdata
from conftest import RELEASE_DIR, REPO_ROOT

GUIDE = REPO_ROOT / "docs" / "r_and_stata.md"
TEXT = GUIDE.read_text(encoding="utf-8")
BLOCK = re.compile(r"(<!-- not run:[^>]*-->\s*\n)?^```(r|stata)\s*\n(.*?)^```", re.DOTALL | re.MULTILINE)
COLUMNS = ["date", "series_id", "value", "unit", "status_flag", "realtime_start", "source_hash"]
DATE_FORMAT = {"monthly": r"\d{4}-\d{2}", "daily": r"\d{4}-\d{2}-\d{2}", "quarterly": r"\d{4}-Q[1-4]", "annual": r"\d{4}"}


def _blocks(language):
    return [code for marker, lang, code in BLOCK.findall(TEXT) if lang == language and not marker]


def test_the_seven_columns_are_the_files_columns():
    section = TEXT[TEXT.index("Every file has the same seven columns"):TEXT.index("## 2. R")]
    named = re.findall(r"^\| `(\w+)` \|", section, re.MULTILINE)
    assert named == COLUMNS
    for table in iraqdata.list_tables():
        header = (RELEASE_DIR / f"{table}.csv").read_text(encoding="utf-8").splitlines()[0]
        assert header.split(",") == COLUMNS, table


def test_the_table_of_files_is_complete_and_its_date_formats_are_right():
    section = TEXT[TEXT.index("| File | Series in it |"):TEXT.index("[series.md]")]
    rows = [[cell.strip() for cell in line.strip("|").split("|")] for line in section.splitlines() if line.startswith("| `")]
    assert sorted(row[0].strip("`").removesuffix(".csv") for row in rows) == sorted(iraqdata.list_tables())
    kinds = {"year-month": "monthly", "day": "daily", "quarter": "quarterly", "year": "annual"}
    for row in rows:
        table = row[0].strip("`").removesuffix(".csv")
        kind, example = re.fullmatch(r"([\w-]+), `([^`]+)`", row[2]).groups()
        assert table.rsplit("_", 1)[1] == kinds[kind], table
        assert re.fullmatch(DATE_FORMAT[kinds[kind]], example), (table, example)
        data = pd.read_csv(RELEASE_DIR / f"{table}.csv", dtype=str)
        assert data["date"].str.fullmatch(DATE_FORMAT[kinds[kind]]).all(), table


def test_every_file_named_in_the_guide_is_a_release_asset():
    assets = {line.split("\t")[0] for line in (RELEASE_DIR / "release-assets.txt").read_text(encoding="utf-8").splitlines()}
    names = set(re.findall(r"\b(\w+_(?:monthly|daily|quarterly|annual)\.(?:csv|parquet))\b", TEXT))
    assert len(names) == 10 + 1                                    # the ten tables, and the parquet example
    assert names <= assets


def test_every_series_in_the_examples_is_in_the_table_it_is_taken_from():
    catalog = iraqdata.list_series().set_index("series_id")
    table_of = lambda series: catalog.loc[series, "table"]
    code = "\n".join(_blocks("r"))                                 # R: by the variable the table was loaded into
    loaded = dict(re.findall(r'(\w+) <- read\.csv\(paste0\(base, "(\w+)\.csv"\)', code))
    used = re.findall(r'subset\((\w+), series_id (?:==|%in% c\()([^)&]*)', code)
    assert len(used) >= 6
    for variable, literals in used:
        for series in re.findall(r'"([^"]+)"', literals):
            assert table_of(series) == loaded[variable], (series, variable)
    for code in _blocks("stata"):                                  # Stata: by the table imported last
        current = None
        for line in code.splitlines():
            found = re.search(r"(\w+)\.csv\"", line)
            if "import delimited" in line and found:
                current = found.group(1)
            for series in re.findall(r'series_id == "([^"]+)"|inlist\(series_id, ([^)]*)\)', line):
                for literal in re.findall(r'"([^"]+)"', " ".join(series)):
                    assert table_of(literal) == current, (literal, current)


def test_stata_variable_names_stay_within_the_limit():
    assert max(len(s.replace(".", "_")) + 1 for s in iraqdata.list_series()["series_id"]) <= 32


@pytest.mark.skipif(shutil.which("Rscript") is None, reason="R is not installed")
def test_the_r_examples_run(tmp_path):
    base = f"file://{RELEASE_DIR.as_posix()}/"
    script = "\n\n".join(_blocks("r"))
    script = re.sub(r'base <- "https://[^"]*"', f'base <- "{base}"', script, count=1)
    assert f'"{base}"' in script
    path = tmp_path / "guide.R"
    path.write_text(script, encoding="utf-8")
    proc = subprocess.run(["Rscript", str(path)], cwd=tmp_path, capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stdout[-1500:] + proc.stderr[-1500:]
    assert (tmp_path / "money_wide.csv").is_file()
    wide = pd.read_csv(tmp_path / "money_wide.csv")
    assert list(wide.columns) == ["date", "money.m1", "money.m2"]
