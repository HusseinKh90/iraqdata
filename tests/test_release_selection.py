"""
tests.test_release_selection
============================
Which data source a load reads.
- A pin (set_release or IRAQDATA_RELEASE) always wins, including over local working data.
- "latest" resolves once to a dated release, changes only through refresh_latest(), and works
  offline.
- A missing repository, release or file each give their own error.

Releases are served by the fake GitHub in conftest; no network, no real user cache.
"""

import hashlib
import io
import json

import pandas as pd
import pytest

import iraqdata
import iraqdata.storage as storage
from conftest import GARDEN_DIR, PINNED_TAG, RELEASE_DIR, build_release, write_marker

TABLE = "money_banking_monthly"
NEXT_TAG = "data-2026-11"


def _modified_table_bytes() -> bytes:
    """The release's money table with its first value changed."""
    df = pd.read_parquet(RELEASE_DIR / f"{TABLE}.parquet")
    df.loc[0, "value"] = df.loc[0, "value"] + 1000.0
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    return buf.getvalue()


@pytest.fixture
def local_dir(tmp_path, monkeypatch):
    """Local working data that differ from the release, set as IRAQDATA_LOCAL_DIR."""
    folder = tmp_path / "local"
    folder.mkdir()
    (folder / f"{TABLE}.parquet").write_bytes(_modified_table_bytes())
    monkeypatch.setenv("IRAQDATA_LOCAL_DIR", str(folder))
    return folder


@pytest.fixture
def next_release(tmp_path, fake_github):
    """Release data-2026-11: data-2026-10 with one money value changed."""
    folder = build_release(tmp_path / NEXT_TAG, files={f"{TABLE}.parquet": _modified_table_bytes()})
    fake_github.add_release(NEXT_TAG, folder)
    return folder


def _release_values() -> pd.Series:
    return pd.read_parquet(RELEASE_DIR / f"{TABLE}.parquet")["value"]


def _first_value() -> float:
    return float(storage.load_table(TABLE)["value"].iloc[0])


def _tree_hashes(folder):
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


# =====================================================================
# A pin is always honoured
# =====================================================================

def test_code_pin_wins_over_local_data(fake_github, local_dir):
    storage.set_release(PINNED_TAG)
    with pytest.warns(UserWarning, match="IRAQDATA_LOCAL_DIR.*ignored"):
        df = storage.load_table(TABLE)
    pd.testing.assert_series_equal(df["value"], _release_values())
    source = iraqdata.get_data_source()
    assert (source.kind, source.release, source.chosen_by) == ("release", PINNED_TAG, "set_release")


def test_environment_pin_wins_over_local_data(fake_github, local_dir, monkeypatch):
    monkeypatch.setenv("IRAQDATA_RELEASE", PINNED_TAG)
    with pytest.warns(UserWarning, match="ignored"):
        df = storage.load_table(TABLE)
        source = iraqdata.get_data_source()
    pd.testing.assert_series_equal(df["value"], _release_values())
    assert source.chosen_by == "IRAQDATA_RELEASE"


def test_code_pin_wins_over_environment_pin(fake_github, monkeypatch):
    monkeypatch.setenv("IRAQDATA_RELEASE", PINNED_TAG)
    storage.set_release("data-2099-01")
    assert storage.get_active_release() == "data-2099-01"
    assert iraqdata.get_data_source(resolve=False).chosen_by == "set_release"


def test_unpinned_local_data_are_used_and_reported(fake_github, local_dir):
    df = storage.load_table(TABLE)
    assert df["value"].iloc[0] == _release_values().iloc[0] + 1000.0
    source = iraqdata.get_data_source()
    assert (source.kind, source.chosen_by, source.location) == ("local", "local", local_dir.resolve())
    assert str(source).startswith("local data at ")
    assert fake_github.urls == []


def test_pinned_release_unreachable_never_falls_back(fake_github, local_dir):
    storage.set_release(PINNED_TAG)
    fake_github.offline = True
    with pytest.warns(UserWarning, match="ignored"), pytest.raises(ConnectionError, match=PINNED_TAG) as exc:
        storage.load_table(TABLE)
    assert TABLE in str(exc.value)


@pytest.mark.parametrize("unpin", [None, "latest"])
def test_set_release_latest_or_none_removes_the_pin(fake_github, unpin):
    storage.set_release(PINNED_TAG)
    storage.set_release(unpin)
    assert storage.get_active_release() == "latest"
    assert iraqdata.get_data_source(resolve=False).chosen_by == "latest"


def test_switching_pins_never_returns_the_other_releases_table(fake_github, next_release):
    storage.set_release(PINNED_TAG)
    first = _first_value()
    storage.set_release(NEXT_TAG)
    assert _first_value() == first + 1000.0
    storage.set_release(PINNED_TAG)
    assert _first_value() == first


def test_checkout_garden_is_used_when_nothing_is_set(monkeypatch):
    monkeypatch.delenv("IRAQDATA_LOCAL_DIR", raising=False)
    monkeypatch.delenv("IRAQDATA_RELEASE", raising=False)
    monkeypatch.setattr(storage, "_code_pin", None)
    assert iraqdata.get_data_source().location == GARDEN_DIR


# =====================================================================
# "latest" resolves once and changes only on refresh
# =====================================================================

def test_latest_resolves_to_newest_data_release(fake_github):
    fake_github.listed[storage.DEFAULT_REPO] = [
        {"tag_name": "v1.0.0", "draft": False, "prerelease": False},
        {"tag_name": PINNED_TAG, "draft": False, "prerelease": False},
        {"tag_name": "data-2026-12", "draft": True, "prerelease": False},
        {"tag_name": NEXT_TAG, "draft": False, "prerelease": True},
    ]
    source = iraqdata.get_data_source()
    assert (source.release, source.requested, source.chosen_by) == (PINNED_TAG, "latest", "latest")
    record = json.loads((storage.get_cache_dir() / storage.LATEST_RECORD).read_text(encoding="utf-8"))
    assert record["tag"] == PINNED_TAG and record["repo"] == storage.DEFAULT_REPO
    assert record["resolved_at"] == source.resolved_at
    assert f"release {PINNED_TAG} (latest, resolved" in str(source)


def test_latest_is_not_checked_again_on_later_loads(fake_github):
    for _ in range(10):
        storage._IN_MEMORY_TABLE_CACHE.clear()
        storage.load_table(TABLE)
    assert len(fake_github.requests_to(r"releases\?per_page")) == 1


def test_refresh_moves_latest_and_keeps_the_old_release(fake_github, tmp_path):
    first = _first_value()
    old_folder = storage.get_cache_dir() / PINNED_TAG
    before = _tree_hashes(old_folder)

    fake_github.add_release(NEXT_TAG, build_release(tmp_path / NEXT_TAG, files={f"{TABLE}.parquet": _modified_table_bytes()}))
    storage._IN_MEMORY_TABLE_CACHE.clear()
    assert _first_value() == first  # no automatic check
    assert iraqdata.refresh_latest() == NEXT_TAG
    assert _first_value() == first + 1000.0
    assert iraqdata.get_data_source().release == NEXT_TAG
    assert _tree_hashes(old_folder) == before


def test_latest_record_of_another_repository_is_ignored(fake_github):
    path = storage.get_cache_dir() / storage.LATEST_RECORD
    path.write_text(json.dumps({"tag": "data-2001-01", "repo": "other/repo", "resolved_at": "x"}), encoding="utf-8")
    assert iraqdata.get_data_source().release == PINNED_TAG


def _cache_release_folder():
    folder = storage.get_cache_dir() / PINNED_TAG
    folder.mkdir(parents=True, exist_ok=True)
    for name in (storage.CHECKSUMS, f"{TABLE}.parquet"):
        (folder / name).write_bytes((RELEASE_DIR / name).read_bytes())
    write_marker(folder, PINNED_TAG)


def test_latest_offline_uses_newest_cached_release(fake_github):
    _cache_release_folder()
    fake_github.offline = True
    with pytest.warns(UserWarning, match="newest cached release"):
        source = iraqdata.get_data_source()
        df = storage.load_table(TABLE)
    assert (source.release, source.chosen_by) == (PINNED_TAG, "latest-offline")
    pd.testing.assert_series_equal(df["value"], _release_values())


def test_latest_offline_without_cache_fails_clearly(fake_github):
    fake_github.offline = True
    with pytest.raises(ConnectionError, match="latest") as exc:
        storage.load_table(TABLE)
    assert storage.DEFAULT_REPO in str(exc.value)


def test_refresh_offline_keeps_the_record(fake_github):
    iraqdata.get_data_source()
    path = storage.get_cache_dir() / storage.LATEST_RECORD
    before = path.read_bytes()
    fake_github.offline = True
    with pytest.raises(ConnectionError):
        iraqdata.refresh_latest()
    assert path.read_bytes() == before


def test_refresh_while_pinned_warns_and_keeps_the_pin(fake_github, next_release):
    storage.set_release(PINNED_TAG)
    with pytest.warns(UserWarning, match="keep reading"):
        assert iraqdata.refresh_latest() == NEXT_TAG
    assert iraqdata.get_data_source().release == PINNED_TAG


def test_source_without_resolving_makes_no_network_call(fake_github):
    source = iraqdata.get_data_source(resolve=False)
    assert source.release is None and source.chosen_by == "latest"
    assert fake_github.urls == []


def test_nothing_is_stored_under_latest(fake_github):
    storage.load_table(TABLE)
    assert not (storage.get_cache_dir() / "latest").exists()
    assert (storage.get_cache_dir() / PINNED_TAG / f"{TABLE}.parquet").is_file()


# =====================================================================
# Missing repository, release or file
# =====================================================================

def test_missing_repository_names_the_setting(fake_github, monkeypatch):
    monkeypatch.setenv("IRAQDATA_REPO", "nobody/nothing")
    storage.set_release(PINNED_TAG)
    with pytest.raises(iraqdata.RepositoryNotFoundError) as exc:
        storage.load_table(TABLE)
    assert isinstance(exc.value, FileNotFoundError)
    for text in ("nobody/nothing", PINNED_TAG, "IRAQDATA_REPO"):
        assert text in str(exc.value)


def test_missing_release_names_the_tag(fake_github):
    storage.set_release("data-2099-01")
    with pytest.raises(iraqdata.ReleaseNotFoundError, match="data-2099-01") as exc:
        storage.load_table(TABLE)
    assert "set_release" in str(exc.value)


def test_missing_file_in_existing_release(fake_github):
    fake_github.missing_assets.add(f"{TABLE}.parquet")
    storage.set_release(PINNED_TAG)
    with pytest.raises(iraqdata.FileNotInReleaseError, match=TABLE):
        storage.load_table(TABLE)


def test_repository_without_data_releases(fake_github):
    fake_github.listed[storage.DEFAULT_REPO] = [{"tag_name": "v1.0.0", "draft": False, "prerelease": False}]
    with pytest.raises(iraqdata.ReleaseNotFoundError, match="no published data release"):
        iraqdata.get_data_source()


def test_every_probe_response_is_closed(fake_github, monkeypatch):
    monkeypatch.setenv("IRAQDATA_REPO", "nobody/nothing")
    storage.set_release(PINNED_TAG)
    with pytest.raises(iraqdata.RepositoryNotFoundError):
        storage.load_table(TABLE)
    assert fake_github.responses and fake_github.unclosed == []
