"""
tests.test_update_rebuild
=========================
Re-running every parser on today's archive in merge mode changes no byte
, and the release export carries vintage histories when they exist
.
"""

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

import export_release
import run_parsers
from conftest import GARDEN_DIR, SEEDS_DIR

pytestmark = pytest.mark.usefixtures("no_network")


def hash_tree(root):
    """SHA-256 of every file under a sandbox folder (conftest.hash_tree is repository-relative)."""
    import hashlib
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(root).rglob("*")) if p.is_file()}


@pytest.fixture(scope="module")
def applied(tmp_path_factory):
    """Today's archive merged into a copy of the production garden."""
    root = tmp_path_factory.mktemp("rebuild")
    shutil.copytree(GARDEN_DIR, root / "garden")
    shutil.copytree(SEEDS_DIR, root / "seeds")
    before = hash_tree(root)
    report = run_parsers.run_all(apply_to=root / "garden")
    return root, before, report


def test_every_table_reports_no_change(applied):
    _, _, report = applied
    assert report["vintage"] == "2026-10-28"  # the newest dated input (the COSIT record of that day)
    assert len(report["tables"]) == 10
    for table, info in report["tables"].items():
        assert (info["changed"], info["added"], info["revised"], info["missing"]) == (False, [], [], []), table


def test_no_file_changes_and_no_history(applied):
    root, before, _ = applied
    assert hash_tree(root) == before
    assert not (root / "history").exists()


def test_output_dir_and_apply_to_are_exclusive(tmp_path):
    with pytest.raises(ValueError, match="mutually exclusive"):
        run_parsers.run_all(out_dir=tmp_path / "a", apply_to=tmp_path / "b")


@pytest.mark.parametrize("only, expected", [
    (["oil_monthly"], ["oil_monthly"]),  # does not read oil_daily
    (["cbi_fiscal_bulletin"], ["fiscal_seed", "cbi_fiscal_bulletin"]),
    (["fiscal_seed"], ["fiscal_seed", "cbi_fiscal_bulletin"]),
    (["cbi_cpi"], ["cbi_cpi"]),
])
def test_only_is_expanded_to_whole_tables(only, expected):
    assert run_parsers.expand_only(only) == expected


# ---------------------------------------------------------------------- release export


def _export(tmp_path, history_dir):
    out = tmp_path / "release"
    export_release.export_release(tag="test", output_dir=out, history_dir=history_dir, reference_copy=False)
    return out


def test_export_without_history_matches_todays_file_list(tmp_path):
    out = _export(tmp_path, tmp_path / "no_history")
    released = [p.name for p in (GARDEN_DIR.parent.parent.parent / "release" / "data-2026-10").iterdir()]
    assert sorted(p.name for p in out.iterdir()) == sorted(released)
    assert export_release.RELEASE_ASSETS in released


def test_export_with_history(tmp_path, garden_tables):
    hist = tmp_path / "history"
    hist.mkdir()
    rows = garden_tables["money_banking_monthly"].head(3).copy()
    rows["realtime_start"] = "2026-10-01"
    rows.to_parquet(hist / "money_banking_monthly.parquet", index=False)
    out = _export(tmp_path, hist)
    assert (out / "history" / "money_banking_monthly.parquet").is_file()
    assert len(pd.read_csv(out / "history" / "money_banking_monthly.csv")) == 3
    checksums = (out / "checksums.sha256").read_text(encoding="utf-8")
    assert "  history/money_banking_monthly.parquet" in checksums
    assert "  history/money_banking_monthly.csv" in checksums
    dp = json.loads((out / "datapackage.json").read_text(encoding="utf-8"))
    res = {r["name"]: r for r in dp["resources"]}
    assert res["money_banking_monthly-history-parquet"]["schema"]["primaryKey"] == ["date", "series_id", "realtime_start"]
