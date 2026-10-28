"""
tests.test_cache_clearing
=========================
Clear_cache() removes only files iraqdata created, and folders only when
they are then empty.
"""

import hashlib

import iraqdata
import iraqdata.storage as storage
from conftest import PINNED_TAG, RELEASE_DIR, build_release

TABLE = "money_banking_monthly"
NEXT_TAG = "data-2026-11"


def _snapshot(*paths):
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def _download_two_releases(fake_github, tmp_path):
    fake_github.add_release(NEXT_TAG, build_release(tmp_path / NEXT_TAG))
    for tag in (PINNED_TAG, NEXT_TAG):
        storage.set_release(tag)
        storage.load_table(TABLE)
        storage.load_table("prices_monthly")
    storage.set_release(None)
    iraqdata.get_data_source()  # writes latest.json


def _user_files(root):
    (root / "notes.txt").write_text("mine", encoding="utf-8")
    (root / "my_project").mkdir()
    (root / "my_project" / "a.csv").write_text("x,y\n", encoding="utf-8")
    (root / PINNED_TAG / "mine.csv").write_text("kept\n", encoding="utf-8")
    return [root / "notes.txt", root / "my_project" / "a.csv", root / PINNED_TAG / "mine.csv"]


def test_clear_all_keeps_everything_iraqdata_did_not_create(fake_github, tmp_path):
    _download_two_releases(fake_github, tmp_path)
    root = storage.get_cache_dir()
    user_files = _user_files(root)
    before = _snapshot(*user_files)

    assert iraqdata.clear_cache() == 4
    assert _snapshot(*user_files) == before
    assert sorted(p.name for p in (root / PINNED_TAG).iterdir()) == ["mine.csv"]
    assert not (root / NEXT_TAG).exists()
    assert not (root / storage.LATEST_RECORD).exists()


def test_clear_one_release_removes_all_its_iraqdata_files(fake_github, tmp_path):
    _download_two_releases(fake_github, tmp_path)
    root = storage.get_cache_dir()
    folder = root / PINNED_TAG
    (folder / "history").mkdir()
    (folder / "history" / "prices_monthly.parquet").write_bytes(b"x")
    (folder / f".{TABLE}.parquet.abc123.tmp").write_bytes(b"partial")
    (folder / f"{TABLE}.parquet.tmp").write_bytes(b"old partial")

    assert iraqdata.clear_cache(PINNED_TAG) == 3
    assert not folder.exists()
    assert (root / NEXT_TAG / f"{TABLE}.parquet").is_file()
    assert storage._read_latest_record()["tag"] == NEXT_TAG  # "latest" points to the other release: kept
    iraqdata.clear_cache(NEXT_TAG)
    assert not (root / storage.LATEST_RECORD).exists()  # cleared with the release it points to


def test_clear_latest_clears_its_release_and_record(fake_github, tmp_path):
    _download_two_releases(fake_github, tmp_path)
    root = storage.get_cache_dir()
    record = storage._read_latest_record()["tag"]
    other = NEXT_TAG if record == PINNED_TAG else PINNED_TAG
    iraqdata.clear_cache("latest")
    assert not (root / record).exists()
    assert not (root / storage.LATEST_RECORD).exists()
    assert (root / other / f"{TABLE}.parquet").is_file()


def test_legacy_latest_folder_is_never_read_and_is_cleared(fake_github):
    root = storage.get_cache_dir()
    legacy = root / "latest"
    legacy.mkdir()
    (legacy / f"{TABLE}.parquet").write_bytes(b"PAR1 stale PAR1")
    df = storage.load_table(TABLE)  # resolves latest to data-2026-10 and downloads it
    assert len(df) > 0
    assert iraqdata.clear_cache() == 2
    assert not legacy.exists()


def test_unrecognised_folders_and_root_files_are_untouched(fake_github):
    root = storage.get_cache_dir()
    mine = root / "my_data"
    mine.mkdir()
    (mine / "prices_monthly.parquet").write_bytes((RELEASE_DIR / "prices_monthly.parquet").read_bytes())
    (root / "prices_monthly.parquet").write_bytes(b"mine")
    before = _snapshot(mine / "prices_monthly.parquet", root / "prices_monthly.parquet")
    assert iraqdata.clear_cache() == 0
    assert _snapshot(mine / "prices_monthly.parquet", root / "prices_monthly.parquet") == before


def test_memory_cache_is_emptied(fake_github):
    storage.set_release(PINNED_TAG)
    storage.load_table(TABLE)
    assert storage._IN_MEMORY_TABLE_CACHE
    iraqdata.clear_cache()
    assert not storage._IN_MEMORY_TABLE_CACHE
