"""
Hand-checked parser values.

Each value in pipeline/metadata/hand_checks.yaml cites a location in an archived file. This
module reads that location with its own small readers (openpyxl, csv, json, zipfile) and never
calls a parser's extraction code. The read must equal `expected`, and so must the parser's
output in the sandbox run.
"""

import ast
import csv
import json
import math
import re
import warnings
import zipfile
from collections import Counter

import openpyxl
import pandas as pd
import pytest
import yaml

from conftest import GARDEN_DIR, METADATA_DIR, REPO_ROOT

with open(METADATA_DIR / "hand_checks.yaml", encoding="utf-8") as _f:
    VALUES = yaml.safe_load(_f)["values"]

PARSERS = {
    "bis_lbs", "cbi_bop", "cbi_cpi", "cbi_exchange_rates", "fiscal_seed", "cbi_fiscal_bulletin",
    "cbi_money_banking", "cosit_gdp", "oecd_dac", "oil_daily", "oil_monthly",
}
_WORKBOOKS: dict = {}


# =====================================================================
# Independent readers
# =====================================================================

def read_xlsx(path, sheet, cell):
    if path not in _WORKBOOKS:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _WORKBOOKS[path] = openpyxl.load_workbook(path, data_only=True, read_only=True)
    value = _WORKBOOKS[path][sheet][cell].value
    return float(str(value).replace(",", ""))


def read_csv(path, row_match, column):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f) if all(r.get(k) == v for k, v in row_match.items())]
    assert len(rows) == 1, f"{path.name}: {len(rows)} rows match {row_match}"
    return float(rows[0][column])


def read_json(path, pointer):
    node = json.loads(path.read_text(encoding="utf-8"))
    for part in pointer.strip("/").split("/"):
        node = node[int(part)] if isinstance(node, list) else node[part]
    return float(node)


def read_zip(path, member, line_contains, json_path):
    with zipfile.ZipFile(path) as z, z.open(member) as f:
        line = next(line for line in f if line_contains.encode() in line)
    node = json.loads(line.decode("utf-8"))
    for key in json_path:
        node = node[key]
    return float(node)


def independent_read(entry):
    loc, path = entry["locator"], REPO_ROOT / entry["source"]
    if "cell" in loc:
        raw = read_xlsx(path, loc["sheet"], loc["cell"])
    elif "row_match" in loc:
        raw = read_csv(path, loc["row_match"], loc["column"])
    elif "pointer" in loc:
        raw = read_json(path, loc["pointer"])
    elif "member" in loc:
        raw = read_zip(path, loc["member"], loc["line_contains"], loc["json_path"])
    else:
        raise ValueError(f"unknown locator {loc}")
    value = raw * entry.get("scale", 1)
    return round(value, entry["round"]) if "round" in entry else value


def published_value(directory, target):
    df = pd.read_parquet(directory / f"{target['table']}.parquet")
    rows = df[(df["series_id"] == target["series"]) & (df["date"] == target["date"])]["value"]
    assert len(rows) == 1, target
    return float(rows.iloc[0])


def _same(a, b):
    return math.isclose(a, b, rel_tol=1e-12, abs_tol=0.0)


# =====================================================================
# Tests
# =====================================================================

def _id(entry):
    t = entry["target"]
    return f"{entry['parser']}:{t['series']}:{t['date']}"


@pytest.mark.parametrize("entry", VALUES, ids=_id)
def test_hand_check_value(entry, sandbox_runs):
    if entry["locator"].get("published"):
        # No archived source exists: pin the published value.
        assert _same(published_value(GARDEN_DIR, entry["target"]), entry["expected"])
        assert _same(published_value(sandbox_runs.run1, entry["target"]), entry["expected"])
        return
    read = independent_read(entry)
    assert _same(read, entry["expected"]), f"archived file now reads {read}, expected {entry['expected']}"
    parsed = published_value(sandbox_runs.run1, entry["target"])
    assert _same(parsed, entry["expected"]), f"parser produced {parsed}, archived cell holds {entry['expected']}"


def test_every_parser_has_3_to_5_values():
    """3-5 values for each of the 11 parsers (33-55 in total)."""
    counts = Counter(e["parser"] for e in VALUES)
    assert set(counts) == PARSERS
    assert all(3 <= n <= 5 for n in counts.values()), counts
    assert 33 <= len(VALUES) <= 55


def test_status_values_valid():
    for e in VALUES:
        assert e["status"] in {"pending", "confirmed", "unverified-against-source"}, _id(e)
        if e["status"] == "confirmed":
            assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(e["confirmed_on"])), _id(e)
        if e["status"] == "unverified-against-source":
            assert e["parser"] == "cosit_gdp", _id(e)


def test_sources_are_archived_inputs_of_their_parser():
    """Each cited file is in the manifest and listed as parsed by the parser it checks."""
    import raw_audit

    files = {f["path"]: f for f in raw_audit.load_manifest()["files"]}
    for e in VALUES:
        if e["source"] is None:
            continue
        consumers = {(c["parser"], c["use"]) for c in files[e["source"]]["consumers"]}
        assert (e["parser"], "parsed") in consumers, _id(e)


def test_readers_are_independent():
    """This module must not import any parser module."""
    tree = ast.parse(open(__file__, encoding="utf-8").read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not [m for m in imported if m.startswith("parse_") or m == "run_parsers"]
