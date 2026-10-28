"""
tests.test_verification
=======================
Every release file is checked against the release's checksums.sha256
before it is stored or served, damaged cached files are replaced, interrupted downloads leave
nothing behind, and every connection is closed.
"""

import re

import pandas as pd
import pytest

import iraqdata
import iraqdata.storage as storage
from conftest import PINNED_TAG, PRODUCTION_TABLES, RELEASE_DIR, build_release

TABLE = "money_banking_monthly"
ASSET = f"{TABLE}.parquet"


@pytest.fixture
def pinned(fake_github):
    storage.set_release(PINNED_TAG)
    return fake_github


def _folder():
    return storage.get_cache_dir() / PINNED_TAG


def _leftovers():
    return sorted(p.name for p in _folder().rglob("*") if p.suffix in (".parquet", ".tmp"))


def test_verified_download_is_cached_with_checksums_and_marker(pinned):
    df = storage.load_table(TABLE)
    pd.testing.assert_frame_equal(df, pd.read_parquet(RELEASE_DIR / ASSET))
    names = {p.name for p in _folder().iterdir()}
    assert names == {ASSET, storage.CHECKSUMS, storage.MARKER}
    assert (_folder() / ASSET).read_bytes() == (RELEASE_DIR / ASSET).read_bytes()


def test_altered_download_is_rejected_and_not_kept(pinned):
    pinned.corrupt.add(ASSET)
    with pytest.raises(iraqdata.ChecksumMismatchError) as exc:
        storage.load_table(TABLE)
    message = str(exc.value)
    assert ASSET in message and PINNED_TAG in message
    assert len(set(re.findall(r"\b[0-9a-f]{64}\b", message))) == 2
    assert isinstance(exc.value, ValueError)
    assert _leftovers() == []


def test_release_without_checksums_cannot_be_verified(pinned):
    pinned.missing_assets.add(storage.CHECKSUMS)
    with pytest.raises(iraqdata.UnverifiableFileError, match="cannot be verified"):
        storage.load_table(TABLE)
    assert not (_folder() / ASSET).exists()


def test_file_missing_from_checksums_cannot_be_verified(pinned, tmp_path):
    folder = build_release(tmp_path / "release")
    lines = (folder / storage.CHECKSUMS).read_text(encoding="utf-8").splitlines()
    (folder / storage.CHECKSUMS).write_text("\n".join(l for l in lines if not l.endswith(f"  {ASSET}")) + "\n",
                                            encoding="utf-8")
    pinned.add_release(PINNED_TAG, folder)
    with pytest.raises(iraqdata.UnverifiableFileError, match=f"'{ASSET}' is not listed"):
        storage.load_table(TABLE)


def test_malformed_checksum_line_is_named(pinned, tmp_path):
    folder = build_release(tmp_path / "release")
    (folder / storage.CHECKSUMS).write_text("not-a-digest  money_banking_monthly.parquet\n", encoding="utf-8")
    pinned.add_release(PINNED_TAG, folder)
    with pytest.raises(iraqdata.UnverifiableFileError, match="malformed line 1"):
        storage.load_table(TABLE)
    assert not (_folder() / storage.CHECKSUMS).exists()


def _damage_cached_copy():
    path = _folder() / ASSET
    data = path.read_bytes()
    path.write_bytes(data[:-10] + b"x" * 10)
    storage._IN_MEMORY_TABLE_CACHE.clear()
    return path


def test_damaged_cache_is_downloaded_again_online(pinned):
    storage.load_table(TABLE)
    path = _damage_cached_copy()
    storage.load_table(TABLE)
    assert path.read_bytes() == (RELEASE_DIR / ASSET).read_bytes()


def test_damaged_cache_offline_is_removed_with_clear_error(pinned):
    storage.load_table(TABLE)
    path = _damage_cached_copy()
    pinned.offline = True
    with pytest.raises(ConnectionError, match="corrupt"):
        storage.load_table(TABLE)
    assert not path.exists()


def test_interrupted_download_leaves_nothing_and_closes(pinned):
    pinned.fail_midway.add(ASSET)
    with pytest.raises(ConnectionError, match=TABLE):
        storage.load_table(TABLE)
    assert _leftovers() == []
    assert pinned.responses and pinned.unclosed == []


def test_repeated_loads_leave_no_open_connection(pinned):
    for i in range(20):
        storage.load_table(PRODUCTION_TABLES[i % len(PRODUCTION_TABLES)], use_memory_cache=False)
    assert len(pinned.responses) == 1 + len(PRODUCTION_TABLES)  # checksums once, each table once
    assert pinned.unclosed == []


def test_folder_from_an_earlier_version_is_adopted(pinned):
    _folder().mkdir(parents=True)
    (_folder() / ASSET).write_bytes((RELEASE_DIR / ASSET).read_bytes())
    storage.load_table(TABLE)
    assert pinned.requests_to(ASSET) == []  # served from the cache once verified
    assert (_folder() / storage.MARKER).is_file()


def test_mismatching_file_from_an_earlier_version_is_replaced(pinned):
    _folder().mkdir(parents=True)
    (_folder() / ASSET).write_bytes(b"PAR1 not the release file PAR1")
    storage.load_table(TABLE)
    assert (_folder() / ASSET).read_bytes() == (RELEASE_DIR / ASSET).read_bytes()


@pytest.mark.parametrize("failure", ["corrupt", "fail_midway", "no_checksums", "offline", "missing_file"])
def test_no_library_exception_escapes(pinned, failure):
    if failure == "corrupt":
        pinned.corrupt.add(ASSET)
    elif failure == "fail_midway":
        pinned.fail_midway.add(ASSET)
    elif failure == "no_checksums":
        pinned.missing_assets.add(storage.CHECKSUMS)
    elif failure == "missing_file":
        pinned.missing_assets.add(ASSET)
    else:
        pinned.offline = True
    with pytest.raises(Exception) as exc:
        storage.load_table(TABLE)
    assert isinstance(exc.value, (iraqdata.IraqdataError, ConnectionError))
    assert not isinstance(exc.value, storage.requests.exceptions.RequestException)
    assert pinned.unclosed == []
