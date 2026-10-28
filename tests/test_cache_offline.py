"""
tests.test_cache_offline
========================
Cached releases are served offline with no network attempt,
corrupt cache files are never served, and missing data without a connection
fails with a clear message. Never touches the real user cache.
"""

import shutil
import time
from pathlib import Path

import pytest

import iraqdata.client as client
import iraqdata.storage as storage
from conftest import RELEASE_DIR

TABLE = "money_banking_monthly"


def _seed_cache(offline) -> Path:
    target = offline.cache_dir / f"{TABLE}.parquet"
    shutil.copyfile(RELEASE_DIR / f"{TABLE}.parquet", target)
    return target


def test_cached_table_served_offline_under_one_second(offline):
    _seed_cache(offline)
    storage._IN_MEMORY_TABLE_CACHE.clear()
    t0 = time.perf_counter()
    df = client.get_series("m2")
    elapsed = time.perf_counter() - t0
    assert not df.empty
    assert offline.calls == []
    assert elapsed < 1.0, f"cached load took {elapsed:.3f}s"


@pytest.mark.parametrize("content", [b"", b"garbage"], ids=["zero-byte", "no-magic"])
def test_corrupt_cache_not_served_offline(offline, content):
    target = offline.cache_dir / f"{TABLE}.parquet"
    target.write_bytes(content)
    with pytest.raises(ConnectionError, match=TABLE) as exc:
        client.get_series("m2")
    assert "corrupt" in str(exc.value).lower()
    assert not target.exists()


def test_corrupt_cache_replaced_when_online(offline, monkeypatch):
    target = offline.cache_dir / f"{TABLE}.parquet"
    target.write_bytes(b"garbage")
    payload = (RELEASE_DIR / f"{TABLE}.parquet").read_bytes()

    class _Response:
        status_code = 200
        headers: dict = {}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size=65536):
            for i in range(0, len(payload), chunk_size):
                yield payload[i:i + chunk_size]

    monkeypatch.setattr(storage.requests, "get", lambda *a, **k: _Response())
    df = client.get_series("m2")
    assert not df.empty
    assert target.read_bytes() == payload


def test_empty_cache_without_network_gives_clear_error(offline):
    with pytest.raises(ConnectionError, match=TABLE) as exc:
        client.get_series("m2")
    assert "connection" in str(exc.value).lower()
    assert offline.calls  # one download attempt, blocked


def test_real_user_cache_is_not_used(offline, tmp_path):
    assert storage.get_cache_dir().is_relative_to(tmp_path)
