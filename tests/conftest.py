"""
tests.conftest
==============
Shared paths, data loaders and isolation fixtures for the QA verification suite.

All fixtures are read-only with respect to production and release data: any
modified copy of a dataset is written under pytest's ``tmp_path``.
"""

import contextlib
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import unicodedata
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "pipeline" / "parsers"))

import iraqdata.storage as storage  # noqa: E402
from iraqdata.schema import CANONICAL_COLUMNS  # noqa: E402

GARDEN_DIR = REPO_ROOT / "pipeline" / "data" / "garden"
SEEDS_DIR = REPO_ROOT / "pipeline" / "seeds"
RELEASE_DIR = REPO_ROOT / "release" / "data-2026-10"
RAW_DIR = REPO_ROOT / "pipeline" / "raw"
METADATA_DIR = REPO_ROOT / "pipeline" / "metadata"
DATA_DIR = REPO_ROOT / "pipeline" / "data"

PRODUCTION_TABLES = sorted([
    "bis_lbs_quarterly",
    "bop_trade_quarterly",
    "exchange_rates_daily",
    "fiscal_annual",
    "gdp_quarterly",
    "money_banking_monthly",
    "oecd_dac_annual",
    "oil_daily",
    "oil_monthly",
    "prices_monthly",
])
FREQ_OF = {name: name.rsplit("_", 1)[1] for name in PRODUCTION_TABLES}
VALID_FLAGS = {"A", "P", "B", "E", "M", "U"}

# What `validate.py --release` prints for the committed data: every review notice is acknowledged.
GATE_SUMMARY = "ALL CHECKS PASSED: 14 dataset(s) verified (24,496 total observations, 0 review notice(s))."

__all__ = [
    "REPO_ROOT", "GARDEN_DIR", "SEEDS_DIR", "RELEASE_DIR", "RAW_DIR", "METADATA_DIR", "DATA_DIR",
    "PRODUCTION_TABLES", "FREQ_OF", "VALID_FLAGS", "GATE_SUMMARY", "CANONICAL_COLUMNS",
    "write_tmp_parquet", "run_validate", "read_release_csv", "hash_tree", "diff_trees", "block_network",
    "set_value", "make_rows", "write_catalog",
    "PINNED_TAG", "write_marker", "build_release", "FakeGitHub", "FakeResponse",
]


# =====================================================================
# Data loaders
# =====================================================================

@pytest.fixture(scope="session")
def garden_tables() -> dict[str, pd.DataFrame]:
    """The 10 production datasets, keyed by table name. Call .copy() before mutating."""
    return {name: pd.read_parquet(GARDEN_DIR / f"{name}.parquet") for name in PRODUCTION_TABLES}


@pytest.fixture(scope="session")
def seed_tables() -> dict[str, pd.DataFrame]:
    """The seed datasets validated by the gatekeeper, keyed by file stem."""
    return {p.stem: pd.read_parquet(p) for p in sorted(SEEDS_DIR.glob("*.parquet"))}


# =====================================================================
# Helpers
# =====================================================================

def write_tmp_parquet(df: pd.DataFrame, directory: Path, name: str) -> Path:
    """Write ``df`` to ``<directory>/<name>.parquet`` and return the path."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.parquet"
    df.to_parquet(path, index=False)
    return path


def run_validate(*paths) -> subprocess.CompletedProcess:
    """Run the gatekeeper CLI as a subprocess from the repository root."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [sys.executable, "pipeline/validate.py", *map(str, paths)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )


def read_release_csv(path: Path) -> pd.DataFrame:
    """
    Read a release CSV losslessly: text columns as text, `value` with round-trip
    float precision (pandas' default fast parser drifts in the last bits).
    """
    header = pd.read_csv(path, nrows=0, encoding="utf-8").columns.tolist()
    text_cols = {c: str for c in header if c != "value"}
    df = pd.read_csv(
        path,
        dtype=text_cols,
        keep_default_na=False,
        na_values={"value": [""]},
        float_precision="round_trip",
        encoding="utf-8",
    )
    df["value"] = df["value"].astype("float64")
    return df[header]


def set_value(
    df: pd.DataFrame,
    date: str,
    series_id: str,
    fn,
    column: str = "value",
) -> pd.DataFrame:
    """
    Return a copy of ``df`` with ``df.loc[(date, series_id), column]`` replaced by
    ``fn(old_value)`` (or ``fn`` if not callable). Asserts exactly one matching row.
    """
    df = df.copy()
    mask = (df["date"] == date) & (df["series_id"] == series_id)
    n_matches = mask.sum()
    assert n_matches == 1, (
        f"Expected exactly 1 row for date={date!r}, series_id={series_id!r}, found {n_matches}"
    )
    idx = df[mask].index[0]
    old_val = df.at[idx, column]
    new_val = fn(old_val) if callable(fn) else fn
    df.at[idx, column] = new_val
    return df


def make_rows(series_id: str, dates, unit: str = "BILLION_IQD", values=None,
              source_hash: str = "h" * 64) -> pd.DataFrame:
    """Canonical 7-column rows for one series (catalog-check fixtures). A value of None is NaN."""
    values = [1.0] * len(dates) if values is None else values
    return pd.DataFrame({
        "date": list(dates),
        "series_id": series_id,
        "value": [float("nan") if v is None else float(v) for v in values],
        "unit": unit,
        "status_flag": ["M" if v is None else "A" for v in values],
        "realtime_start": "2026-10-01",
        "source_hash": source_hash,
    })[CANONICAL_COLUMNS]


def write_catalog(path: Path, entries: list) -> Path:
    """Write a catalog YAML with `entries` under `series` (catalog fixtures)."""
    import yaml

    path = Path(path)
    path.write_text(yaml.safe_dump({"series": entries}, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


# =====================================================================
# Isolation fixtures
# =====================================================================

@pytest.fixture
def fresh_memory_cache():
    """Clear the client's in-memory table cache before and after the test."""
    storage._IN_MEMORY_TABLE_CACHE.clear()
    yield
    storage._IN_MEMORY_TABLE_CACHE.clear()


PINNED_TAG = "data-2026-10"


def _isolate_client(monkeypatch, tmp_path) -> None:
    """Temporary cache, no local data, no pin or repository override, empty in-memory caches."""
    no_local = tmp_path / "no_local"
    no_local.mkdir(exist_ok=True)
    monkeypatch.setenv("IRAQDATA_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("IRAQDATA_LOCAL_DIR", str(no_local))
    monkeypatch.delenv("IRAQDATA_RELEASE", raising=False)
    monkeypatch.delenv("IRAQDATA_REPO", raising=False)
    monkeypatch.setattr(storage, "_code_pin", None)
    storage._IN_MEMORY_TABLE_CACHE.clear()
    storage._CHECKSUM_CACHE.clear()


def write_marker(folder: Path, tag: str, repo: str = storage.DEFAULT_REPO) -> None:
    """The ownership marker iraqdata writes in a release cache folder."""
    record = {"tag": tag, "repo": repo, "created_by": "iraqdata test"}
    (folder / storage.MARKER).write_text(json.dumps(record), encoding="utf-8")


@pytest.fixture
def offline(monkeypatch, tmp_path):
    """
    Isolate the client from the network and from the user's real cache.

    - IRAQDATA_CACHE_DIR points at a temporary directory; IRAQDATA_LOCAL_DIR at an empty one.
    - Release data-2026-10 is pinned (IRAQDATA_RELEASE). Its cache folder holds the release's
      checksums.sha256 and iraqdata's ownership marker, but no tables.
    - requests.get and socket connections raise and are recorded in ``calls``.
    """
    calls: list = []

    def _blocked_get(*args, **kwargs):
        calls.append(("requests.get", args, kwargs))
        # Same exception type requests raises when the machine is offline
        raise storage.requests.exceptions.ConnectionError("network blocked in test")

    def _blocked_connect(self, *args, **kwargs):
        calls.append(("socket.connect", args, kwargs))
        raise ConnectionError("network blocked in test")

    _isolate_client(monkeypatch, tmp_path)
    monkeypatch.setenv("IRAQDATA_RELEASE", PINNED_TAG)
    monkeypatch.setattr(storage.requests, "get", _blocked_get)
    monkeypatch.setattr(socket.socket, "connect", _blocked_connect)

    cache_dir = storage.get_cache_dir() / PINNED_TAG
    cache_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(RELEASE_DIR / storage.CHECKSUMS, cache_dir / storage.CHECKSUMS)
    write_marker(cache_dir, PINNED_TAG)
    yield SimpleNamespace(cache_dir=cache_dir, calls=calls)
    storage._IN_MEMORY_TABLE_CACHE.clear()
    storage._CHECKSUM_CACHE.clear()


# =====================================================================
# Fake GitHub: release assets and API answers served from local folders
# =====================================================================

def build_release(dst: Path, src: Path = RELEASE_DIR, files: dict | None = None) -> Path:
    """
    A release folder at ``dst``: the files of ``src`` (except its checksums) plus ``files``
    ({release path: bytes or source Path}), with a checksums.sha256 listing them all.
    """
    dst.mkdir(parents=True, exist_ok=True)
    contents = {p.name: p.read_bytes() for p in sorted(src.iterdir()) if p.is_file() and p.name != storage.CHECKSUMS}
    for rel, data in (files or {}).items():
        contents[rel] = data.read_bytes() if isinstance(data, Path) else data
    lines = []
    for rel, data in contents.items():
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        lines.append(f"{hashlib.sha256(data).hexdigest()}  {rel}")
    (dst / storage.CHECKSUMS).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return dst


class FakeResponse:
    """The parts of requests.Response the client uses; records whether it was closed."""

    def __init__(self, url, status_code=200, body=b"", json_data=None, headers=None, fail_midway=False):
        self.url = url
        self.status_code = status_code
        self.body = body
        self.json_data = json_data
        self.headers = headers or {}
        self.fail_midway = fail_midway
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def close(self):
        self.closed = True

    def raise_for_status(self):
        if self.status_code >= 400:
            raise storage.requests.exceptions.HTTPError(f"{self.status_code} for {self.url}")

    def json(self):
        return self.json_data

    def iter_content(self, chunk_size=65536):
        if self.fail_midway:
            yield self.body[: len(self.body) // 2]
            raise storage.requests.exceptions.ConnectionError("stream interrupted in test")
        for i in range(0, len(self.body), chunk_size):
            yield self.body[i:i + chunk_size]


class FakeGitHub:
    """
    Stand-in for requests.get. ``releases`` maps (repo, tag) to a release folder; ``listed``
    overrides a repository's release list; ``corrupt`` and ``fail_midway`` name asset files to
    damage; ``offline`` makes every request fail like a machine without network.
    """

    ASSET = re.compile(r"^https://github\.com/([^/]+/[^/]+)/releases/download/([^/]+)/([^/]+)$")
    LIST = re.compile(r"^https://api\.github\.com/repos/([^/]+/[^/]+)/releases\?per_page=100$")
    REPO = re.compile(r"^https://api\.github\.com/repos/([^/]+/[^/]+)$")
    TAG = re.compile(r"^https://api\.github\.com/repos/([^/]+/[^/]+)/releases/tags/([^/]+)$")

    def __init__(self):
        self.releases: dict[tuple[str, str], Path] = {(storage.DEFAULT_REPO, PINNED_TAG): RELEASE_DIR}
        self.listed: dict[str, list] = {}
        self.missing_assets: set[str] = set()
        self.corrupt: set[str] = set()
        self.fail_midway: set[str] = set()
        self.offline = False
        self.urls: list[str] = []
        self.responses: list[FakeResponse] = []

    def add_release(self, tag: str, folder: Path, repo: str = storage.DEFAULT_REPO) -> None:
        self.releases[(repo, tag)] = folder

    @property
    def repos(self) -> set[str]:
        return {repo for repo, _ in self.releases} | set(self.listed)

    def requests_to(self, pattern: str) -> list[str]:
        return [u for u in self.urls if re.search(pattern, u)]

    @property
    def unclosed(self) -> list[FakeResponse]:
        return [r for r in self.responses if not r.closed]

    def _answer(self, url: str) -> FakeResponse:
        if m := self.ASSET.match(url):
            repo, tag, asset = m.groups()
            folder = self.releases.get((repo, tag))
            rel = asset.replace(".", "/", 1) if asset.startswith("history.") else asset
            if folder is None or asset in self.missing_assets or not (folder / rel).is_file():
                return FakeResponse(url, 404)
            body = (folder / rel).read_bytes()
            if asset in self.corrupt:
                body = bytes([body[0] ^ 0xFF]) + body[1:]
            return FakeResponse(url, body=body, fail_midway=asset in self.fail_midway)
        if m := self.LIST.match(url):
            repo = m.group(1)
            if repo not in self.repos:
                return FakeResponse(url, 404)
            listed = self.listed.get(repo)
            if listed is None:
                listed = [{"tag_name": t, "draft": False, "prerelease": False} for r, t in self.releases if r == repo]
            return FakeResponse(url, json_data=listed)
        if m := self.TAG.match(url):
            return FakeResponse(url, 200 if tuple(m.groups()) in self.releases else 404, json_data={})
        if m := self.REPO.match(url):
            return FakeResponse(url, 200 if m.group(1) in self.repos else 404, json_data={})
        return FakeResponse(url, 404)

    def get(self, url, stream=False, timeout=None, **kwargs):
        self.urls.append(url)
        if self.offline:
            raise storage.requests.exceptions.ConnectionError("network blocked in test")
        response = self._answer(url)
        self.responses.append(response)
        return response


@pytest.fixture
def fake_github(monkeypatch, tmp_path):
    """
    The client isolated as in ``offline`` but unpinned, with requests.get answered by a
    FakeGitHub that serves release data-2026-10 from release/data-2026-10/.
    """
    def _blocked_connect(self, *args, **kwargs):
        raise ConnectionError("network blocked in test")

    _isolate_client(monkeypatch, tmp_path)
    fake = FakeGitHub()
    monkeypatch.setattr(storage.requests, "get", fake.get)
    monkeypatch.setattr(socket.socket, "connect", _blocked_connect)
    yield fake
    storage._IN_MEMORY_TABLE_CACHE.clear()
    storage._CHECKSUM_CACHE.clear()


# =====================================================================
# Raw-layer audit: hashing, network blocking and sandbox parser runs
# =====================================================================

def hash_tree(*roots: Path) -> dict[str, str]:
    """Map every file under ``roots`` (NFC repository-relative path) to its SHA-256."""
    out: dict[str, str] = {}
    for root in roots:
        root = Path(root)
        if not root.exists():
            continue
        for p in sorted(root.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts:
                key = unicodedata.normalize("NFC", p.resolve().relative_to(REPO_ROOT).as_posix())
                out[key] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def diff_trees(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """Paths created, changed or deleted between two ``hash_tree`` snapshots."""
    return sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))


@contextlib.contextmanager
def block_network():
    """
    Block all network access (works at session scope). requests and socket connections
    raise ConnectionError and are recorded in the yielded ``calls`` list.
    """
    import requests

    calls: list = []

    def _blocked_get(*args, **kwargs):
        calls.append(("requests.get", args, kwargs))
        raise requests.exceptions.ConnectionError("network blocked in test")

    def _blocked_request(self, *args, **kwargs):
        calls.append(("requests.Session.request", args, kwargs))
        raise requests.exceptions.ConnectionError("network blocked in test")

    def _blocked_connect(self, *args, **kwargs):
        calls.append(("socket.connect", args, kwargs))
        raise ConnectionError("network blocked in test")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(requests, "get", _blocked_get)
        mp.setattr(requests.Session, "request", _blocked_request)
        mp.setattr(socket.socket, "connect", _blocked_connect)
        yield calls


@pytest.fixture
def no_network():
    """
    Block the network for one test and fail if anything tried to use it.
    Opt-in per module (`pytestmark = pytest.mark.usefixtures("no_network")`). Fakes for
    downloads.polite_get sit above the socket layer, so a bypassed fake is caught too.
    Subprocesses (e.g. run_validate) are not covered.
    """
    with block_network() as calls:
        yield calls
    assert calls == [], f"network access attempted: {calls[:3]}"


@pytest.fixture(scope="session")
def sandbox_runs(tmp_path_factory):
    """
    Run all 11 parsers twice, offline, into two fresh folders.
    Hashes of pipeline/raw, pipeline/seeds and pipeline/data are taken before and after.
    """
    import run_parsers

    before = hash_tree(RAW_DIR, SEEDS_DIR, DATA_DIR)
    run1 = tmp_path_factory.mktemp("run1")
    run2 = tmp_path_factory.mktemp("run2")
    with block_network() as calls:
        run_parsers.run_all(out_dir=run1)
        run_parsers.run_all(out_dir=run2)
    after = hash_tree(RAW_DIR, SEEDS_DIR, DATA_DIR)
    return SimpleNamespace(run1=run1, run2=run2, before=before, after=after, network_calls=calls)


def _raw_inputs_snapshot() -> dict[str, str]:
    import raw_audit

    snap = hash_tree(RAW_DIR, SEEDS_DIR)
    return {k: v for k, v in snap.items() if k not in raw_audit.DERIVED_SNAPSHOTS}


def pytest_sessionstart(session):
    session.config._raw_inputs_before = _raw_inputs_snapshot()


def pytest_sessionfinish(session, exitstatus):
    """No test may create, modify or delete a raw file or seed input."""
    before = getattr(session.config, "_raw_inputs_before", None)
    if before is None:
        return
    changed = diff_trees(before, _raw_inputs_snapshot())
    if changed:
        print("\nRAW FILES CHANGED DURING THE TEST SESSION:")
        for path in changed:
            print(f"  {path}")
        session.exitstatus = 1
