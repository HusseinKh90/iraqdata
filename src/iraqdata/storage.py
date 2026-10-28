"""
Storage, Caching, and Data Source Selection for iraqdata.

Every load reads from one data source, chosen in a fixed order:
1. A release pinned in code (`set_release`), then one pinned by the IRAQDATA_RELEASE variable.
   A pin is always honoured: nothing below overrides it.
2. Local working data: a repository checkout's 'pipeline/data/garden/' or IRAQDATA_LOCAL_DIR,
   used only when nothing is pinned.
3. "latest": the newest data-YYYY-MM release, resolved once and recorded in
   '<cache>/latest.json'. It changes only when `refresh_latest()` is called.

Release files are cached under '<cache>/<tag>/' (cache root: IRAQDATA_CACHE_DIR or
'~/.cache/iraqdata/') and verified against the release's checksums.sha256 when downloaded and
before every read from disk, so cached data also work offline. `clear_cache()` removes only files
that iraqdata created. `get_data_source()` reports which source is in use.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import tempfile
import time
import warnings
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import requests

from iraqdata.catalog import list_tables
from iraqdata.errors import (
    ChecksumMismatchError,
    FileNotInReleaseError,
    NoVintageHistoryError,
    ReleaseNotFoundError,
    RepositoryNotFoundError,
    UnverifiableFileError,
)

# Default GitHub release repository
DEFAULT_REPO = "husseinkh90/iraqdata"
DEFAULT_RELEASE = "latest"
GITHUB_API = "https://api.github.com"
HTTP_TIMEOUT = 30

# Files iraqdata writes in the cache
MARKER = ".iraqdata-release.json"
CHECKSUMS = "checksums.sha256"
LATEST_RECORD = "latest.json"
LEGACY_LATEST_DIR = "latest"

_DATED_TAG = re.compile(r"^data-\d{4}-\d{2}$")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")

# Release pinned in code (None: not pinned) and in-memory caches.
# Tables and histories are keyed by (source key, "table" | "history", table name).
_code_pin: str | None = None
_IN_MEMORY_TABLE_CACHE: dict[tuple[str, str, str], pd.DataFrame | None] = {}
_CHECKSUM_CACHE: dict[str, dict[str, str]] = {}


@dataclass(frozen=True)
class DataSource:
    """
    The data source loads read from.

    kind is 'release' or 'local'; release is the dated tag (None for local data, or while
    "latest" is not resolved); requested is what was asked for (a tag, 'latest', or None for
    local data); chosen_by is 'set_release', 'IRAQDATA_RELEASE', 'latest', 'latest-offline' or
    'local'; location is the release cache folder or the local data folder.
    """

    kind: str
    release: str | None
    requested: str | None
    chosen_by: str
    location: Path
    resolved_at: str | None = None
    repo: str | None = None

    def __str__(self) -> str:
        if self.kind == "local":
            return f"local data at {self.location}"
        how = {
            "set_release": "pinned with set_release",
            "IRAQDATA_RELEASE": "pinned by IRAQDATA_RELEASE",
            "latest": "latest",
            "latest-offline": "latest, newest cached copy while offline",
        }[self.chosen_by]
        when = f", resolved {self.resolved_at}" if self.resolved_at else ""
        tag = self.release or "not resolved yet"
        return f"release {tag} ({how}{when}) from {self.repo}"

    @property
    def key(self) -> str:
        """Identity of the data behind this source, for the in-memory cache."""
        return f"local:{self.location}" if self.kind == "local" else f"release:{self.repo}:{self.release}"


def get_cache_dir() -> Path:
    """Return the base user cache directory for iraqdata."""
    env_cache = os.environ.get("IRAQDATA_CACHE_DIR")
    if env_cache:
        path = Path(env_cache)
    else:
        path = Path.home() / ".cache" / "iraqdata"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _repo() -> str:
    return os.environ.get("IRAQDATA_REPO") or DEFAULT_REPO


def _env_pin() -> str | None:
    tag = os.environ.get("IRAQDATA_RELEASE")
    return tag if tag and tag != DEFAULT_RELEASE else None


def _release_dir(tag: str) -> Path:
    return get_cache_dir() / tag


def get_active_release() -> str:
    """
    The release tag asked for: the pin made with set_release(), else IRAQDATA_RELEASE, else
    'latest'. Use get_data_source() for the dated release actually in use.
    """
    return _code_pin or _env_pin() or DEFAULT_RELEASE


def set_release(release_tag: str | None) -> None:
    """
    Pin a specific data release tag for academic reproducibility.

    A pin wins over IRAQDATA_RELEASE and over local working data.

    Parameters
    ----------
    release_tag : str or None
        GitHub release tag (e.g. 'data-2026-10'). 'latest' or None removes the pin.
    """
    global _code_pin
    _code_pin = None if release_tag in (None, DEFAULT_RELEASE) else release_tag


# =====================================================================
# Small file and network helpers
# =====================================================================

def _replace(src: Path, dst: Path) -> None:
    """os.replace, retried once: on Windows the target may be briefly held open by a reader."""
    try:
        os.replace(src, dst)
    except PermissionError:
        time.sleep(0.2)
        os.replace(src, dst)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_bytes(data)
        _replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _write_marker(folder: Path, tag: str) -> None:
    """Record that iraqdata created this release folder (clear_cache relies on it)."""
    from iraqdata import __version__

    record = {"tag": tag, "repo": _repo(), "created_by": f"iraqdata {__version__}"}
    _atomic_write_bytes(folder / MARKER, (json.dumps(record, indent=2) + "\n").encode("utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _http_get(url: str, *, stream: bool = False) -> requests.Response:
    """The client's only network call; callers use the response in a `with` block so it is closed."""
    return requests.get(url, stream=stream, timeout=HTTP_TIMEOUT)


def _api_json(url: str):
    """GET a GitHub API URL: the parsed JSON, or None on 404. Network failures raise ConnectionError."""
    try:
        with _http_get(url) as response:
            if response.status_code == 404:
                return None
            if response.status_code == 403 and response.headers.get("X-RateLimit-Remaining") == "0":
                raise ConnectionError(
                    f"The GitHub API rate limit was reached while reading {url}. Try again later, "
                    "or pin a release with id.set_release('data-YYYY-MM')."
                )
            response.raise_for_status()
            return response.json()
    except (requests.exceptions.RequestException, ValueError) as e:
        raise ConnectionError(f"Could not read {url}: {e}") from e


def _asset_name(rel_path: str) -> str:
    """Flat GitHub asset name of a release path: 'history/x.parquet' -> 'history.x.parquet'."""
    return rel_path.replace("/", ".")


def _asset_url(tag: str, rel_path: str) -> str:
    return f"https://github.com/{_repo()}/releases/download/{tag}/{_asset_name(rel_path)}"


def _explain_404(tag: str, rel_path: str) -> None:
    """Raise the error that explains a 404 on a release asset: no repository, no release, or no file."""
    repo = _repo()
    url = _asset_url(tag, rel_path)
    try:
        repo_found = _api_json(f"{GITHUB_API}/repos/{repo}") is not None
        tag_found = repo_found and _api_json(f"{GITHUB_API}/repos/{repo}/releases/tags/{tag}") is not None
    except ConnectionError as e:
        raise FileNotInReleaseError(
            f"'{rel_path}' was not found at {url}, and the repository '{repo}' could not be checked "
            f"({e}). Check the release tag, or set IRAQDATA_REPO to the repository that publishes "
            "iraqdata releases."
        ) from None
    if not repo_found:
        raise RepositoryNotFoundError(
            f"Repository '{repo}' was not found on GitHub (looking for release '{tag}'). "
            "Set IRAQDATA_REPO to the repository that publishes iraqdata releases."
        )
    if not tag_found:
        raise ReleaseNotFoundError(
            f"Release '{tag}' does not exist in '{repo}'. Pin an existing release with "
            "id.set_release('data-YYYY-MM'), or remove the pin to use the latest release."
        )
    if rel_path == CHECKSUMS:
        raise UnverifiableFileError(
            f"Release '{tag}' of '{repo}' publishes no {CHECKSUMS}, so its files cannot be verified."
        )
    raise FileNotInReleaseError(f"Release '{tag}' of '{repo}' does not publish '{rel_path}' (looked for {url}).")


# =====================================================================
# Data source selection and "latest"
# =====================================================================

def _local_data_dir() -> Path | None:
    """Local working data folder: IRAQDATA_LOCAL_DIR, else a checkout's 'pipeline/data/garden/'."""
    env_local = os.environ.get("IRAQDATA_LOCAL_DIR")
    if env_local:
        candidate = Path(env_local)
        has_tables = candidate.is_dir() and any((candidate / f"{t}.parquet").is_file() for t in list_tables())
        return candidate.resolve() if has_tables else None

    repo_garden = Path(__file__).resolve().parents[2] / "pipeline" / "data" / "garden"
    if repo_garden.is_dir() and (repo_garden / "prices_monthly.parquet").is_file():
        return repo_garden
    return None


def _read_latest_record() -> dict | None:
    """The recorded "latest" resolution for the current repository, or None."""
    path = get_cache_dir() / LATEST_RECORD
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (
        not isinstance(record, dict)
        or not _DATED_TAG.match(str(record.get("tag", "")))
        or record.get("repo") != _repo()
        or not isinstance(record.get("resolved_at"), str)
    ):
        return None
    return record


def _record_latest(tag: str) -> dict:
    record = {
        "tag": tag,
        "repo": _repo(),
        "resolved_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    _atomic_write_bytes(get_cache_dir() / LATEST_RECORD, (json.dumps(record, indent=2) + "\n").encode("utf-8"))
    return record


def _resolve_latest_online() -> str:
    """The newest published data-YYYY-MM release of the repository (drafts and prereleases skipped)."""
    repo = _repo()
    releases = _api_json(f"{GITHUB_API}/repos/{repo}/releases?per_page=100")
    if releases is None:
        raise RepositoryNotFoundError(
            f"Repository '{repo}' was not found on GitHub (looking for the latest data release). "
            "Set IRAQDATA_REPO to the repository that publishes iraqdata releases."
        )
    tags = sorted(
        r["tag_name"]
        for r in releases
        if isinstance(r, dict)
        and not r.get("draft")
        and not r.get("prerelease")
        and _DATED_TAG.match(str(r.get("tag_name", "")))
    )
    if not tags:
        raise ReleaseNotFoundError(
            f"Repository '{repo}' has no published data release (data-YYYY-MM). "
            "Set IRAQDATA_REPO to the repository that publishes iraqdata releases."
        )
    return tags[-1]


def _newest_cached_release() -> str | None:
    """Newest cached release folder of the current repository with a marker and checksum list."""
    found = []
    for folder in get_cache_dir().iterdir():
        if not (folder.is_dir() and _DATED_TAG.match(folder.name) and (folder / CHECKSUMS).is_file()):
            continue
        try:
            marker = json.loads((folder / MARKER).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(marker, dict) and marker.get("repo") == _repo():
            found.append(folder.name)
    return max(found) if found else None


def get_data_source(resolve: bool = True) -> DataSource:
    """
    Report the data source that loads read from.

    Order: a release pinned with set_release(), then IRAQDATA_RELEASE, then local working data
    (only when nothing is pinned), then the recorded "latest" release. With no record, "latest"
    is resolved online and recorded (unless resolve=False, which never uses the network); offline,
    the newest cached release is used.

    Returns
    -------
    DataSource
        The source; print it for a one-line description.
    """
    repo = _repo()
    pin, chosen_by = (_code_pin, "set_release") if _code_pin else (_env_pin(), "IRAQDATA_RELEASE")
    if pin:
        if os.environ.get("IRAQDATA_LOCAL_DIR") and _local_data_dir() is not None:
            warnings.warn(
                f"IRAQDATA_LOCAL_DIR ({os.environ['IRAQDATA_LOCAL_DIR']}) is ignored because "
                f"release '{pin}' is pinned.",
                UserWarning,
                stacklevel=2,
            )
        return DataSource("release", pin, pin, chosen_by, _release_dir(pin), None, repo)

    local = _local_data_dir()
    if local is not None:
        return DataSource("local", None, None, "local", local)

    record = _read_latest_record()
    if record is None and resolve:
        try:
            record = _record_latest(_resolve_latest_online())
        except ConnectionError as e:
            cached = _newest_cached_release()
            if cached is None:
                raise ConnectionError(
                    f"Cannot find the latest data release of '{repo}': nothing is cached and GitHub "
                    "could not be reached. Connect to the internet once, or pin a release with "
                    f"id.set_release('data-YYYY-MM'). {e}"
                ) from e
            warnings.warn(
                f"GitHub could not be reached to find the latest data release; using the newest "
                f"cached release '{cached}'.",
                UserWarning,
                stacklevel=2,
            )
            return DataSource("release", cached, DEFAULT_RELEASE, "latest-offline", _release_dir(cached), None, repo)
    if record is None:
        return DataSource("release", None, DEFAULT_RELEASE, "latest", get_cache_dir(), None, repo)
    return DataSource(
        "release", record["tag"], DEFAULT_RELEASE, "latest", _release_dir(record["tag"]), record["resolved_at"], repo
    )


def refresh_latest() -> str:
    """
    Look up the newest published data release online and make "latest" point to it.

    Other cached releases are kept. Without network access this raises ConnectionError and the
    current "latest" stays as it is.

    Returns
    -------
    str
        The dated release tag "latest" now points to.
    """
    previous = _read_latest_record()
    tag = _resolve_latest_online()
    _record_latest(tag)
    if previous and previous["tag"] != tag:
        old_key = f"release:{_repo()}:{previous['tag']}"
        for key in [k for k in _IN_MEMORY_TABLE_CACHE if k[0] == old_key]:
            del _IN_MEMORY_TABLE_CACHE[key]

    source = get_data_source(resolve=False)
    if source.chosen_by != "latest":
        warnings.warn(
            f"'latest' now points to '{tag}', but loads keep reading {source}.",
            UserWarning,
            stacklevel=2,
        )
    return tag


# =====================================================================
# Verified release files
# =====================================================================

def _parse_checksums(text: str, tag: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        digest, sep, path = line.partition("  ")
        if not sep or not _SHA256_HEX.match(digest) or not path.strip():
            raise UnverifiableFileError(
                f"{CHECKSUMS} of release '{tag}' ({_repo()}) has a malformed line {number}: {line!r}, "
                "so its files cannot be verified."
            )
        entries[path.strip()] = digest
    return entries


def _load_checksums(tag: str) -> dict[str, str]:
    """The release's checksum list: read from the cache, or downloaded once and kept there."""
    folder = _release_dir(tag)
    path = folder / CHECKSUMS
    if str(path) in _CHECKSUM_CACHE:
        return _CHECKSUM_CACHE[str(path)]

    if path.is_file():
        data = path.read_bytes()
        downloaded = False
    else:
        url = _asset_url(tag, CHECKSUMS)
        try:
            with _http_get(url, stream=True) as response:
                if response.status_code == 404:
                    _explain_404(tag, CHECKSUMS)
                response.raise_for_status()
                data = b"".join(chunk for chunk in response.iter_content(chunk_size=65536) if chunk)
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Failed to download {CHECKSUMS} of release '{tag}' from {url}. Error: {e}") from e
        downloaded = True

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise UnverifiableFileError(
            f"{CHECKSUMS} of release '{tag}' ({_repo()}) is not text, so its files cannot be verified."
        ) from None
    entries = _parse_checksums(text, tag)
    if downloaded:
        _atomic_write_bytes(path, data)
        _write_marker(folder, tag)
    _CHECKSUM_CACHE[str(path)] = entries
    return entries


def _expected_digest(tag: str, rel_path: str) -> str:
    checksums = _load_checksums(tag)
    if rel_path not in checksums:
        raise UnverifiableFileError(
            f"'{rel_path}' is not listed in {CHECKSUMS} of release '{tag}' ({_repo()}), "
            "so it cannot be verified."
        )
    return checksums[rel_path]


def _download_verified(tag: str, rel_path: str) -> Path:
    """Download a release file into the cache; it is kept only if it matches its checksum."""
    expected = _expected_digest(tag, rel_path)
    folder = _release_dir(tag)
    final = folder / rel_path
    final.parent.mkdir(parents=True, exist_ok=True)
    url = _asset_url(tag, rel_path)

    fd, tmp_name = tempfile.mkstemp(dir=final.parent, prefix=f".{final.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        digest = hashlib.sha256()
        with os.fdopen(fd, "wb") as f:
            try:
                with _http_get(url, stream=True) as response:
                    if response.status_code == 404:
                        _explain_404(tag, rel_path)
                    response.raise_for_status()
                    for chunk in response.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
                            digest.update(chunk)
            except requests.exceptions.RequestException as e:
                raise ConnectionError(
                    f"Failed to download '{rel_path}' of release '{tag}' from {url}. "
                    f"Check your internet connection. Error: {e}"
                ) from e
        actual = digest.hexdigest()
        if actual != expected:
            raise ChecksumMismatchError(
                f"Downloaded '{rel_path}' of release '{tag}' ({url}) does not match the release "
                f"checksum (expected {expected}, got {actual}). The file was not kept."
            )
        _replace(tmp, final)
    finally:
        tmp.unlink(missing_ok=True)

    _write_marker(folder, tag)
    return final


def _verified_release_file(tag: str, rel_path: str) -> Path:
    """
    Path of a verified copy of a release file. A cached copy is checked against the release
    checksum before it is served; a damaged copy is removed and downloaded again.
    """
    folder = _release_dir(tag)
    target = folder / rel_path
    state = "is not cached yet"
    try:
        if target.is_file():
            state = "cannot be verified yet (the release checksums are not cached)"
            expected = _expected_digest(tag, rel_path)
            if _sha256(target) == expected:
                if not (folder / MARKER).is_file():
                    _write_marker(folder, tag)  # adopt a folder left by an earlier version
                return target
            target.unlink(missing_ok=True)
            state = "was corrupt and has been removed"
        elif not (folder / CHECKSUMS).is_file():
            state = "is not cached yet"
        return _download_verified(tag, rel_path)
    except ConnectionError as e:
        raise ConnectionError(
            f"'{rel_path}' of release '{tag}' {state} (cache: {folder}). "
            f"An internet connection is required to download it. {e}"
        ) from e


# =====================================================================
# Tables and vintage histories
# =====================================================================

def _table_file_name(table_name: str) -> str:
    base_name = table_name if table_name.endswith(".parquet") else f"{table_name}.parquet"
    if base_name not in {f"{t}.parquet" for t in list_tables()}:
        raise ValueError(f"Unknown table '{table_name}'. Available tables: {sorted(list_tables())}")
    return base_name


def _table_path(source: DataSource, base_name: str) -> Path:
    if source.kind == "local":
        candidate = source.location / base_name
        if candidate.is_file():
            return candidate
        raise FileNotFoundError(
            f"Table '{base_name[:-8]}' is not in the local data folder {source.location}. "
            "Pin a published release with id.set_release('data-YYYY-MM') to download it."
        )
    return _verified_release_file(source.release, base_name)


def resolve_table_path(table_name: str) -> Path:
    """
    Resolve the physical filesystem path for a parquet table from the current data source
    (see get_data_source). Release files are downloaded if needed and always verified.

    Parameters
    ----------
    table_name : str
        Canonical table name (e.g. 'prices_monthly' or 'prices_monthly.parquet').

    Returns
    -------
    Path
        Absolute Path to the local Parquet file.
    """
    base_name = _table_file_name(table_name)
    return _table_path(get_data_source(), base_name)


def load_table(
    table_name: str,
    columns: list[str] | None = None,
    use_memory_cache: bool = True,
) -> pd.DataFrame:
    """
    Load a production Parquet table into a pandas DataFrame.

    Parameters
    ----------
    table_name : str
        Canonical table name (e.g. 'prices_monthly', 'fiscal_annual').
    columns : list[str], optional
        Subset of columns to read. If None, reads all canonical columns.
    use_memory_cache : bool, default True
        Whether to cache the loaded table in memory for instant subsequent queries.

    Returns
    -------
    pd.DataFrame
        Loaded dataset conforming to the Canonical Observation Schema.
    """
    base_name = _table_file_name(table_name)
    source = get_data_source()
    key = (source.key, "table", base_name[:-8])

    if use_memory_cache and columns is None and key in _IN_MEMORY_TABLE_CACHE:
        return _IN_MEMORY_TABLE_CACHE[key].copy()

    df = pq.read_table(_table_path(source, base_name), columns=columns).to_pandas()

    if use_memory_cache and columns is None:
        _IN_MEMORY_TABLE_CACHE[key] = df.copy()
    return df


def _local_history_file(location: Path, table: str) -> Path | None:
    for folder in (location / "history", location.parent / "history"):
        if folder.is_dir():
            candidate = folder / f"{table}.parquet"
            return candidate if candidate.is_file() else None
    raise NoVintageHistoryError(
        f"The local data folder {location} has no vintage history ('history/' inside or beside it), "
        "so as_of cannot be used with it."
    )


def load_history(table_name: str) -> pd.DataFrame | None:
    """
    Load the vintage history (superseded observations) of a table from the current data source.

    Returns None when the table has had no revisions. Raises NoVintageHistoryError when the
    source carries no vintage history at all.
    """
    base_name = _table_file_name(table_name)
    table = base_name[:-8]
    source = get_data_source()
    key = (source.key, "history", table)
    if key in _IN_MEMORY_TABLE_CACHE:
        cached = _IN_MEMORY_TABLE_CACHE[key]
        return None if cached is None else cached.copy()

    if source.kind == "local":
        path = _local_history_file(source.location, table)
    else:
        checksums = _load_checksums(source.release)
        if not any(p.startswith("history/") for p in checksums):
            raise NoVintageHistoryError(
                f"Release '{source.release}' carries no vintage history, so as_of cannot be used "
                "with it. Use a release published with vintage history."
            )
        rel_path = f"history/{base_name}"
        path = _verified_release_file(source.release, rel_path) if rel_path in checksums else None

    df = pq.read_table(path).to_pandas() if path is not None else None
    _IN_MEMORY_TABLE_CACHE[key] = df
    return None if df is None else df.copy()


# =====================================================================
# Cache clearing
# =====================================================================

def _is_release_folder(folder: Path) -> bool:
    return (folder / MARKER).is_file() or bool(_DATED_TAG.match(folder.name)) or folder.name == LEGACY_LATEST_DIR


def _owned(name: str, bases: set[str]) -> bool:
    """Whether a file name is one iraqdata writes: a base name, or a temporary file of one."""
    if name in bases:
        return True
    return any(
        name == f"{b}.tmp" or (name.startswith(f".{b}.") and name.endswith(".tmp")) for b in bases
    )


def _clear_release_folder(folder: Path) -> int:
    """Delete iraqdata's files in a release folder, then the folder if it is empty. Returns parquet count."""
    data_files = {f"{t}.parquet" for t in list_tables()}
    removed = 0
    for sub, bases in ((folder / "history", data_files), (folder, data_files | {CHECKSUMS, MARKER})):
        if not sub.is_dir():
            continue
        for item in sub.iterdir():
            if item.is_file() and _owned(item.name, bases):
                item.unlink(missing_ok=True)
                removed += item.name.endswith(".parquet")
        try:
            sub.rmdir()  # only succeeds when empty: other files are never touched
        except OSError:
            pass
    return removed


def clear_cache(release_tag: str | None = None) -> int:
    """
    Remove cached data downloaded by iraqdata.

    Only files iraqdata created are removed (tables, histories, checksum lists, its markers and
    temporary download files, and the "latest" record). Other files and folders in the cache
    directory are never touched, and a folder is removed only if it is then empty.

    Parameters
    ----------
    release_tag : str, optional
        Release to clear ('latest' clears the release "latest" points to). If None, clears all.

    Returns
    -------
    int
        Number of parquet files removed.
    """
    _IN_MEMORY_TABLE_CACHE.clear()
    _CHECKSUM_CACHE.clear()

    root = get_cache_dir()
    record = _read_latest_record()
    if release_tag is None:
        folders = [p for p in root.iterdir() if p.is_dir()]
        clear_record = True
    elif release_tag == DEFAULT_RELEASE:
        folders = [root / LEGACY_LATEST_DIR] + ([root / record["tag"]] if record else [])
        clear_record = True
    else:
        folders = [root / release_tag]
        clear_record = bool(record and record["tag"] == release_tag)

    removed = sum(_clear_release_folder(f) for f in folders if f.is_dir() and _is_release_folder(f))
    if clear_record:
        for item in root.iterdir():
            if item.is_file() and _owned(item.name, {LATEST_RECORD}):
                item.unlink(missing_ok=True)
    return removed
