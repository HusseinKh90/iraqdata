"""
Deterministic release export.

Every export goes to tmp_path with reference_copy=False, never to release/ or pipeline/data/.
The release gate itself is covered by test_release_gate.py and is stubbed out here.
"""

import datetime
import json
import re
import time

import pytest

import export_release
import iraqdata
import validate
from conftest import GARDEN_DIR, PRODUCTION_TABLES, RELEASE_DIR, REPO_ROOT


@pytest.fixture
def export(tmp_path, monkeypatch):
    monkeypatch.setattr(validate, "run_gatekeeper", lambda *a, **k: 0)
    monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)

    def run(name):
        out = tmp_path / name
        export_release.export_release(tag="data-test", output_dir=out, reference_copy=False)
        return out
    return run


def _tree(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


@pytest.fixture(scope="module")
def two_exports(tmp_path_factory):
    """Two full exports a little over a second apart (history included)."""
    mp = pytest.MonkeyPatch()
    mp.setattr(validate, "run_gatekeeper", lambda *a, **k: 0)
    mp.delenv("SOURCE_DATE_EPOCH", raising=False)
    outs = []
    try:
        for name in ("first", "second"):
            out = tmp_path_factory.mktemp(name)
            export_release.export_release(tag="data-test", output_dir=out, reference_copy=False)
            outs.append(out)
            time.sleep(1.1)
    finally:
        mp.undo()
    return outs


def test_two_exports_are_byte_identical(two_exports):
    first, second = (_tree(o) for o in two_exports)
    assert sorted(first) == sorted(second)
    assert [name for name in first if first[name] != second[name]] == []


def test_csv_lines_end_with_crlf(two_exports):
    csvs = [p for p in two_exports[0].rglob("*.csv")]
    assert csvs
    for path in csvs:
        data = path.read_bytes()
        assert data.endswith(b"\r\n"), path.name
        assert data.count(b"\n") == data.count(b"\r\n"), path.name


def test_metadata_files_are_lf_only(two_exports):
    for name in ("checksums.sha256", "datapackage.json"):
        data = (two_exports[0] / name).read_bytes()
        assert b"\r" not in data, name
        assert data.endswith(b"\n"), name


def test_descriptor_records_the_building_code_version(two_exports):
    meta = json.loads((two_exports[0] / "datapackage.json").read_bytes())
    assert meta["version"] == iraqdata.__version__


def test_descriptor_has_no_created_time_by_default(two_exports):
    meta = json.loads((two_exports[0] / "datapackage.json").read_bytes())
    assert "created" not in meta


def test_source_date_epoch_sets_created(export, monkeypatch):
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1792627200")
    meta = json.loads((export("epoch") / "datapackage.json").read_bytes())
    assert meta["created"] == "2026-10-22T00:00:00Z"
    keys = list(meta)
    assert keys.index("created") == keys.index("release") + 1


def test_wall_clock_does_not_reach_the_output(export, monkeypatch):
    """A different 'now' (as the old code used) changes nothing in the output."""
    first = _tree(export("a"))

    class Later(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.datetime(2031, 1, 1, tzinfo=tz)
    monkeypatch.setattr(export_release.datetime, "datetime", Later)
    assert _tree(export("b")) == first


@pytest.mark.parametrize("table", PRODUCTION_TABLES)
def test_reexport_reproduces_published_csv(two_exports, table):
    """
    Where the garden table is still the one data-2026-10 was built from, re-exporting it
    gives the published CSV bytes. Tables production has since updated
    are not byte copies of the release and are skipped.
    """
    if (GARDEN_DIR / f"{table}.parquet").read_bytes() != (RELEASE_DIR / f"{table}.parquet").read_bytes():
        pytest.skip("garden table has changed since data-2026-10")
    assert (two_exports[0] / f"{table}.csv").read_bytes() == (RELEASE_DIR / f"{table}.csv").read_bytes()


def test_version_matches_pyproject():
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    project = text.split("[project]", 1)[1].split("\n[", 1)[0]
    version = re.search(r'^version\s*=\s*"([^"]+)"', project, re.M).group(1)
    assert version == iraqdata.__version__


def test_descriptor_carries_series_origin(two_exports):
    """Each catalog series in the export states its origin and officialness."""
    import iraqdata.catalog as cat
    meta = json.loads((two_exports[0] / "datapackage.json").read_bytes())
    exported = {s["series_id"]: s for s in meta["seriesCatalog"]["series"]}
    for entry in cat.get_catalog()["series"]:
        item = exported[entry["series_id"]]
        assert [seg["class"] for seg in item["origin"]] == [seg["class"] for seg in entry["origin"]]
        assert item["official"] == cat.is_official(entry["origin"])
    assert exported["parallel_rate_iraq"]["official"] is False


def test_status_flag_description_names_every_code(two_exports):
    meta = json.loads((two_exports[0] / "datapackage.json").read_bytes())
    field = next(f for f in meta["resources"][0]["schema"]["fields"] if f["name"] == "status_flag")
    for code in ("A = normal", "P = provisional", "B = break", "E = estimated", "M = missing", "U = low reliability"):
        assert code in field["description"]


def test_release_assets_list_every_file_once(two_exports):
    first, second = two_exports
    assets_file = first / export_release.RELEASE_ASSETS
    assert assets_file.read_bytes() == (second / export_release.RELEASE_ASSETS).read_bytes()
    assert b"\r" not in assets_file.read_bytes()
    pairs = [line.split("\t") for line in assets_file.read_text(encoding="utf-8").splitlines()]
    listed = [path for path, _ in pairs]
    checksum_paths = [line.split("  ", 1)[1] for line in (first / "checksums.sha256").read_text(encoding="utf-8").splitlines()]
    assert sorted(listed) == listed
    assert set(listed) == set(checksum_paths) | {"checksums.sha256", "datapackage.json"}
    assert len(set(listed)) == len(listed)
    for path, name in pairs:
        assert name == path.replace("/", ".") and "/" not in name
        assert (first / path).is_file()


def test_asset_names_are_flat_and_collisions_rejected():
    assert export_release.asset_name("history/x.parquet") == "history.x.parquet"
    assert export_release.asset_name("x.parquet") == "x.parquet"
    with pytest.raises(ValueError, match="history.x.parquet"):
        export_release.release_assets(["history/x.parquet", "history.x.parquet"])
