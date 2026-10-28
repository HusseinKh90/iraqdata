"""
Archived files that no parser reads.

The inventory lists every manifest file without a `parsed` consumer, so archived-but-unused
sources (the COSIT early-warning PDFs, the legacy .xls workbooks) are a documented state.
"""

import raw_audit
import run_parsers


def _inventory():
    return raw_audit.inventory(raw_audit.load_manifest())


def test_unparsed_files_listed():
    manifest = raw_audit.load_manifest()
    unparsed = {e["path"] for e in manifest["files"]
                if not any(c["use"] == "parsed" for c in e["consumers"])}
    items = _inventory()
    assert {i["path"] for i in items} == unparsed
    assert all(i["status"] in {"archived-not-parsed", "superseded"} for i in items)
    assert [i["folder"] for i in items] == sorted(i["folder"] for i in items)


def test_cosit_pdfs_archived_not_parsed():
    """The 10 COSIT early-warning PDFs are inventoried; no PDF parser is required."""
    pdfs = [i for i in _inventory() if i["path"].startswith("pipeline/raw/cosit/alarm/")]
    assert len(pdfs) == 10
    assert all(i["path"].endswith(".pdf") and i["status"] == "archived-not-parsed" for i in pdfs)


def test_xls_files_not_parsed():
    """No parser reads legacy .xls workbooks; only the COSIT record check does (pipeline/check_cosit_record.py)."""
    xls = [i for i in _inventory() if i["path"].endswith(".xls")]
    assert len(xls) == 2
    assert all(i["status"] == "archived-not-parsed" for i in xls)


def test_status_matches_consumers():
    """The manifest's status and consumers agree with the parser registry, so they cannot drift."""
    consumers = run_parsers.consumer_map()
    for entry in raw_audit.load_manifest()["files"]:
        expected = [{"parser": p, "use": u} for p, u in consumers.get(entry["path"], [])]
        assert entry["consumers"] == expected, entry["path"]
        parsed = any(c["use"] == "parsed" for c in expected)
        assert (entry["status"] == "parsed") == parsed, entry["path"]
