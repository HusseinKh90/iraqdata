"""OPEC production through the real parser, vintage merge, provenance, and report flow."""
import hashlib
import json
import shutil
from datetime import date
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

import fetchers
import opec_momr as opec
import raw_audit
import run_parsers
import update_check
from conftest import REPO_ROOT, hash_tree

pytestmark = pytest.mark.usefixtures("no_network")
TODAY = date(2026, 11, 3)
FIXTURES = Path(__file__).parent / "fixtures" / "opec"


def responses():
    routes = json.loads((FIXTURES / "routes.json").read_text())
    return {url: (FIXTURES / record["file"]).read_bytes() for url, record in routes.items()}


def mock_download(monkeypatch, payloads=None):
    pages = responses() if payloads is None else payloads
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        result = pages[url]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(fetchers, "_get", get)
    return pages, calls


@pytest.fixture(scope="module")
def full_flow(tmp_path_factory):
    root = tmp_path_factory.mktemp("opec_complete")
    work, report_dir = root / "work", root / "report"
    before = hash_tree(REPO_ROOT / "pipeline", REPO_ROOT / "release")
    with pytest.MonkeyPatch.context() as mp:
        _, calls = mock_download(mp)
        report = update_check.run_check(work, report_dir, TODAY, only_sources=["opec_momr"])
    return root, before, report, calls


def test_full_check_archives_three_missing_reports_and_requires_review(full_flow):
    root, _, report, calls = full_flow
    source, = report["sources"]
    assert source["outcome"] == "new_release", source["detail"]
    assert len(source["files"]) == 3
    assert len(calls) == 6  # index, two archive pages, three supply chapters
    assert {f["identity"] for f in report["findings"]} >= {"review:opec_momr", "revised:oil_monthly"}
    assert report["needs_review"]
    assert report["gatekeeper"]["errors"] == []
    for entry in source["files"]:
        body = (root / "report" / "downloads" / entry["path"]).read_bytes()
        assert hashlib.sha256(body).hexdigest() == entry["sha256"]
        opec.read_capture(body)
    assert not report["changes"]["oil_monthly"]["missing"]
    assert not report["changes"]["oil_monthly"]["withdrawn"]


def test_published_values_preserved_and_other_oil_series_unchanged(full_flow):
    root, before, report, _ = full_flow
    assert hash_tree(REPO_ROOT / "pipeline", REPO_ROOT / "release") == before
    old = pd.read_parquet(update_check.GARDEN_DIR / "oil_monthly.parquet")
    new = pd.read_parquet(root / "work" / "garden" / "oil_monthly.parquet")
    sid = opec.SERIES
    pd.testing.assert_frame_equal(old[old.series_id != sid].reset_index(drop=True),
                                  new[new.series_id != sid].reset_index(drop=True))
    additions = new[(new.series_id == sid) & (new.date >= "2026-07")].set_index("date")
    assert additions.value.to_dict() == {"2026-07": 2901.0, "2026-08": 3746.0, "2026-09": 4399.0}
    assert set(additions.status_flag) == {"P"}
    assert set(additions.realtime_start) == {TODAY.isoformat()}
    historical = new[(new.series_id == sid) & new.date.isin(["2026-05", "2026-06"])]
    assert set(historical.status_flag) == {"U"}  # conservative pending historical-origin review
    history = pd.read_parquet(root / "work" / "history" / "oil_monthly.parquet")
    revisions = report["changes"]["oil_monthly"]["revised"]
    assert {item["date"] for item in revisions} == {"2026-05", "2026-06"}
    for item in revisions:
        previous = old[(old.series_id == sid) & (old.date == item["date"])].iloc[0]
        superseded = history[(history.series_id == sid) & (history.date == item["date"])].iloc[0]
        assert superseded.value == previous.value
        assert superseded.source_hash == previous.source_hash


def test_repeat_fetch_and_merge_do_not_change_data_or_history(full_flow, monkeypatch):
    root = full_flow[0]
    work = root / "work"
    fingerprint = lambda: {p.relative_to(work).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in work.rglob("*") if p.is_file()}
    before = fingerprint()
    mock_download(monkeypatch)
    assert fetchers.fetch_opec_momr(work / "raw", TODAY, work / "raw_manifest.yaml") is None
    result = run_parsers.run_all(only=["oil_monthly"], raw_root=work / "raw", seeds_root=work / "seeds",
                                apply_to=work / "garden", history_dir=work / "history")
    assert all(not entry["changed"] for entry in result["tables"].values())
    assert fingerprint() == before


def test_capture_hashes_resolve_to_correct_raw_files(full_flow, tmp_path):
    work = full_flow[0] / "work"
    raw = tmp_path / "pipeline" / "raw"
    shutil.copytree(work / "raw", raw)
    manifest = raw_audit.load_manifest()
    for path in (raw / "opec").glob("*.json"):
        entry = raw_audit.file_entry(path, root=tmp_path)
        assert entry["source_ref"] == "opec_momr"
        assert entry["status"] == "parsed"
        assert entry["acquired"] == TODAY.isoformat()
        manifest["files"].append(entry)
    table = pd.read_parquet(work / "garden" / "oil_monthly.parquet")
    result = raw_audit.resolve_hashes({"oil_monthly": table}, manifest, {"provenance": []}, root=tmp_path)
    assert result.ok, result
    assert result.resolved_rows == len(table)
    # A valid hash from an unrelated chapter/month must not count as correct attribution.
    item = table[(table.series_id == opec.SERIES) & (table.date == "2026-09")].index[0]
    captures = opec.capture_records(raw / "opec")
    table.loc[item, "source_hash"] = captures[0][-1]  # August report cannot explain September data
    wrong = raw_audit.resolve_hashes({"oil_monthly": table}, manifest, {"provenance": []}, root=tmp_path)
    assert len(wrong.unregistered) == 1
    assert wrong.unregistered[0][-1] == "misattributed"


def test_capture_order_does_not_undo_a_newer_report_revision(full_flow, tmp_path):
    source = full_flow[0] / "work" / "raw" / "opec"
    files = sorted(source.glob("*.json"))
    for path in reversed(files):
        shutil.copyfile(path, tmp_path / path.name)
    selected = opec.latest_production(tmp_path)
    assert selected["2026-07"]["report_month"] == "2026-10"
    assert selected["2026-07"]["value"] == "2901"
    latest = next(p for p in files if "2026-10" in p.name)
    metadata = json.loads(latest.read_bytes())
    metadata["retrieved_at"] = "2026-01-01T00:00:00+00:00"
    (tmp_path / "momr_late_copy_2026-11-04.json").write_text(json.dumps(metadata))
    assert opec.latest_production(tmp_path)["2026-07"]["value"] == "2901"


def test_fetch_failure_immediately_reported_and_published_data_untouched(tmp_path, monkeypatch):
    pages = responses()
    pages[opec.INDEX] = TimeoutError("simulated OPEC outage")
    mock_download(monkeypatch, pages)
    report = update_check.run_check(tmp_path / "work", tmp_path / "report", TODAY, ["opec_momr"])
    source, = report["sources"]
    assert source["outcome"] == "fetch_failed"
    assert source["failure_threshold"] == 1
    assert "fetch_failed:opec_momr" in {item["identity"] for item in report["findings"]}
    assert report["changes"] == {}
    assert not (tmp_path / "work" / "raw" / "opec").exists()
    pd.testing.assert_frame_equal(pd.read_parquet(tmp_path / "work" / "garden" / "oil_monthly.parquet"),
                                  pd.read_parquet(update_check.GARDEN_DIR / "oil_monthly.parquet"))


def test_parser_failure_does_not_write_candidate_or_history(tmp_path, monkeypatch):
    mock_download(monkeypatch)

    def broken(*args):
        raise opec.CollectionError("simulated invalid OPEC capture")

    spec = replace(run_parsers.BY_NAME["oil_monthly"], run=broken)
    monkeypatch.setitem(run_parsers.BY_NAME, "oil_monthly", spec)
    monkeypatch.setattr(run_parsers, "REGISTRY", [spec if item.name == "oil_monthly" else item
                                               for item in run_parsers.REGISTRY])
    report = update_check.run_check(tmp_path / "work", tmp_path / "report", TODAY, ["opec_momr"])
    assert report["sources"][0]["outcome"] == "parse_failed"
    assert report["changes"] == {}
    assert not (tmp_path / "work" / "history" / "oil_monthly.parquet").exists()
    pd.testing.assert_frame_equal(pd.read_parquet(tmp_path / "work" / "garden" / "oil_monthly.parquet"),
                                  pd.read_parquet(update_check.GARDEN_DIR / "oil_monthly.parquet"))
