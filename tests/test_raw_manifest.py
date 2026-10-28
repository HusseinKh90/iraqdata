"""
Raw files are never modified.

The committed manifest records the SHA-256 of every archived raw file and seed input. Any file
that changes, disappears or appears without an entry is reported by path. Checks use content
hashes only, never modification times.
"""

import shutil
import unicodedata

import pytest

import raw_audit
from conftest import REPO_ROOT, diff_trees


def _copy_into(tmp_path, *folders):
    for folder in folders:
        shutil.copytree(REPO_ROOT / folder, tmp_path / folder)


def test_manifest_check_clean():
    problems = raw_audit.check_manifest(raw_audit.load_manifest())
    assert problems == [], "\n".join(f"{d.kind}: {d.path} ({d.detail})" for d in problems)


def test_manifest_lists_every_raw_file():
    """76 immutable files with full hashes (the ones no parser reads included) plus the 4 derived snapshots."""
    manifest = raw_audit.load_manifest()
    assert len(manifest["files"]) == 76
    assert sorted(s["path"] for s in manifest["derived_snapshots"]) == sorted(raw_audit.DERIVED_SNAPSHOTS)


def test_manifest_check_reports_each_kind(tmp_path):
    _copy_into(tmp_path, "pipeline/raw/fred", "pipeline/raw/oecd")
    manifest = raw_audit.build_manifest(root=tmp_path)
    assert raw_audit.check_manifest(manifest, root=tmp_path) == []

    changed = tmp_path / "pipeline/raw/oecd/wb_oda_net.json"
    with open(changed, "ab") as f:
        f.write(b" ")
    (tmp_path / "pipeline/raw/oecd/wb_oda_grants.json").unlink()
    (tmp_path / "pipeline/raw/fred/new_download.csv").write_text("x\n", encoding="utf-8")

    found = {(d.kind, d.path) for d in raw_audit.check_manifest(manifest, root=tmp_path)}
    assert found == {
        ("changed", "pipeline/raw/oecd/wb_oda_net.json"),
        ("missing", "pipeline/raw/oecd/wb_oda_grants.json"),
        ("unlisted", "pipeline/raw/fred/new_download.csv"),
    }


def test_manifest_add_is_append_only(tmp_path):
    manifest_path = tmp_path / "raw_manifest.yaml"
    new_file = tmp_path / "pipeline/raw/fred/brent_2026-11-01.csv"
    new_file.parent.mkdir(parents=True)
    new_file.write_bytes(b"date,value\n2026-11-01,70.1\n")

    assert raw_audit.manifest_add(new_file, manifest_path, root=tmp_path) is True
    assert raw_audit.manifest_add(new_file, manifest_path, root=tmp_path) is False
    entries = raw_audit.load_manifest(manifest_path)["files"]
    assert [e["path"] for e in entries] == ["pipeline/raw/fred/brent_2026-11-01.csv"]
    recorded = entries[0]["sha256"]

    new_file.write_bytes(b"date,value\n2026-11-01,99.9\n")
    with pytest.raises(ValueError, match="never change"):
        raw_audit.manifest_add(new_file, manifest_path, root=tmp_path)
    assert raw_audit.load_manifest(manifest_path)["files"][0]["sha256"] == recorded


def _entry(**fields):
    base = {"path": "pipeline/raw/fred/x.csv", "size": 1, "sha256": "0" * 64, "origin": "o",
            "acquired": "2026-10-01", "source_ref": "fred_brent", "consumers": [], "status": "parsed"}
    base.update(fields)
    return base


def test_manifest_check_needs_a_date_and_a_source(tmp_path, monkeypatch):
    """An unknown download date needs held_by; source_ref must exist."""
    monkeypatch.setattr(raw_audit, "iter_raw_files", lambda root: [])
    ids = {"fred_brent"}
    ok = {"files": [_entry(), _entry(path="b", acquired="unknown", held_by="2026-10-25", held_by_basis="commit")]}
    assert [d for d in raw_audit.check_manifest(ok, tmp_path, ids) if d.kind != "missing"] == []
    bad = {"files": [_entry(path="a", acquired="unknown"), _entry(path="b", acquired="unknown", held_by="2026-10-25"),
                     _entry(path="c", source_ref="nope"), _entry(path="d", source_ref=None)]}
    found = {(d.kind, d.path) for d in raw_audit.check_manifest(bad, tmp_path, ids) if d.kind != "missing"}
    assert found == {("undated", "a"), ("undated", "b"), ("terms", "c"), ("terms", "d")}


def test_manifest_add_refuses_a_file_without_a_source_rule(tmp_path):
    new_file = tmp_path / "pipeline/raw/elsewhere/report.pdf"
    new_file.parent.mkdir(parents=True)
    new_file.write_bytes(b"%PDF")
    with pytest.raises(ValueError, match="source_ref"):
        raw_audit.manifest_add(new_file, tmp_path / "m.yaml", root=tmp_path)
    assert not (tmp_path / "m.yaml").exists()


def test_new_entry_without_a_dated_name_is_held_from_today(tmp_path):
    new_file = tmp_path / "pipeline/raw/fred/DCOILBRENTEU.csv"
    new_file.parent.mkdir(parents=True)
    new_file.write_bytes(b"date,value\n")
    raw_audit.manifest_add(new_file, tmp_path / "m.yaml", root=tmp_path)
    entry = raw_audit.load_manifest(tmp_path / "m.yaml")["files"][0]
    assert entry["acquired"] == "unknown" and entry["source_ref"] == "fred_brent"
    import datetime
    assert entry["held_by"] == datetime.datetime.now(datetime.timezone.utc).date().isoformat() and entry["held_by_basis"]


def test_backfill_is_idempotent_and_keeps_fingerprints(monkeypatch):
    manifest = raw_audit.load_manifest()
    for e in manifest["files"]:
        e.pop("held_by", None)
        e.pop("held_by_basis", None)
    monkeypatch.setattr(raw_audit, "_first_commit", lambda path, root=None: ("2026-10-25", "79ac432"))
    keys = [(e["path"], e["sha256"], e["size"]) for e in manifest["files"]]
    n = raw_audit.backfill_held(manifest)
    assert n == sum(e["acquired"] == "unknown" for e in manifest["files"]) > 0
    assert raw_audit.backfill_held(manifest) == 0
    assert [(e["path"], e["sha256"], e["size"]) for e in manifest["files"]] == keys
    assert all(e["held_by"] == "2026-10-25" for e in manifest["files"] if e["acquired"] == "unknown")


def test_real_manifest_has_no_terms_key():
    assert all("terms" not in e for e in raw_audit.load_manifest()["files"])


def test_manifest_paths_are_nfc():
    for entry in raw_audit.load_manifest()["files"]:
        assert entry["path"] == unicodedata.normalize("NFC", entry["path"])
        assert "\\" not in entry["path"]


def test_duplicate_content_listed_twice(tmp_path):
    """Edge case: identical bytes under two names are two entries with one content hash."""
    folder = tmp_path / "pipeline/raw/jodi"
    folder.mkdir(parents=True)
    for name in ("jodi_a.csv", "jodi_b.csv"):
        (folder / name).write_bytes(b"same content\n")
    manifest = raw_audit.build_manifest(root=tmp_path)
    hashes = [e["sha256"] for e in manifest["files"]]
    assert len(hashes) == 2 and hashes[0] == hashes[1]
    assert raw_audit.check_manifest(manifest, root=tmp_path) == []


def test_sandbox_run_leaves_raw_untouched(sandbox_runs):
    """A full run of all parsers changes no raw file or seed input."""
    changed = [p for p in diff_trees(sandbox_runs.before, sandbox_runs.after)
               if p.startswith(("pipeline/raw/", "pipeline/seeds/"))]
    assert changed == []
