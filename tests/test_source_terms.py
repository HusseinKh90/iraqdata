"""
tests.test_source_terms
=======================
One dated terms-of-reuse record per
source, referred to from the raw manifest and the catalog, and an accurate licence statement.
"""

import datetime
import re

import yaml

import raw_audit
from conftest import REPO_ROOT

SOURCES = REPO_ROOT / "pipeline" / "metadata" / "sources.yaml"
CATALOG = REPO_ROOT / "src" / "iraqdata" / "series_catalog.yaml"
STATUSES = {"licensed", "no_licence_stated", "confirmed_by_maintainer", "unconfirmed"}
FIELDS = ["id", "publisher", "title", "url", "terms", "licence", "status", "redistribution", "attribution", "checked"]


def _records():
    return yaml.safe_load(SOURCES.read_text(encoding="utf-8"))["sources"]


def test_records_follow_the_schema():
    ids = [r["id"] for r in _records()]
    assert len(ids) == len(set(ids)), "ids must be unique"
    for r in _records():
        assert list(r) == FIELDS, r["id"]
        assert re.fullmatch(r"[a-z][a-z0-9_]*", r["id"]), r["id"]
        assert r["status"] in STATUSES, r["id"]
        # "Must be `null` unless `status: licensed`"
        assert (r["licence"] is None) == (r["status"] != "licensed"), r["id"]
        if r["status"] == "no_licence_stated":
            assert r["terms"] == "No licence stated", r["id"]
        assert datetime.date.fromisoformat(str(r["checked"])), r["id"]
        for field in ("publisher", "title", "url", "terms", "redistribution", "attribution"):
            assert str(r[field]).strip(), (r["id"], field)


def test_no_open_licence_is_claimed_without_one():
    for r in _records():
        if r["status"] != "licensed":
            assert "CC-BY" not in r["terms"] and "Creative Commons" not in r["terms"], r["id"]


def test_manifest_and_catalog_refer_to_existing_records():
    ids = {r["id"] for r in _records()}
    for e in raw_audit.load_manifest()["files"]:
        assert e.get("source_ref") in ids, e["path"]
        assert "terms" not in e, e["path"]
    for entry in yaml.safe_load(CATALOG.read_text(encoding="utf-8"))["series"]:
        for i, seg in enumerate(entry["origin"]):
            if seg["class"] != "derived" or "source_ref" in seg:
                assert seg.get("source_ref") in ids, (entry["series_id"], i)


def test_unconfirmed_sources_are_open_items_in_the_inventory():
    text = (REPO_ROOT / "docs" / "source_inventory.md").read_text(encoding="utf-8")
    block = text.split("<!-- terms:begin -->", 1)[1].split("<!-- terms:end -->", 1)[0]
    assert "## Terms of reuse by source" in block
    items = block.split("**Open items", 1)[1]
    for r in _records():
        assert f"`{r['id']}`" in block, r["id"]
        if r["status"] == "unconfirmed":
            assert f"`{r['id']}`" in items, r["id"]


def test_licence_texts_scope_cc_by_to_the_compilation():
    licence = (REPO_ROOT / "LICENSE-DATA").read_text(encoding="utf-8")
    assert "compiled and derived data only" in licence
    assert "docs/source_inventory.md" in licence and "series metadata" not in licence
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert readme.count("docs/source_inventory.md#terms-of-reuse-by-source") >= 2
    assert "cite both the package and the original publishers" in readme
