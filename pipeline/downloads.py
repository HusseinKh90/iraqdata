"""
pipeline.downloads
==================
Polite, safe HTTP for the pipeline's downloaders.

- TLS certificates are always verified; a TLS failure stops with instructions for a manual
  download instead of continuing insecurely.
- robots.txt is checked once per host before the first request (RFC 9309: a 4xx means no
  restrictions; a 5xx or network failure means stop).
- Requests are paced: REQUEST_DELAY_S seconds before every request after the first.
- Every request identifies the project, with a contact address, in its User-Agent.
- Only https URLs without credentials are fetched. Redirects are followed by hand, at most
  MAX_REDIRECTS, and every hop is checked like the first request (https, robots.txt of its host);
  a hop may only go to the same host, or to a host of the source being fetched when the caller
  has declared them with `restrict_hosts` (the weekly check does, from fetchers.HOSTS).
- Timeouts, connection errors and HTTP 429/5xx are retried (3 attempts, RETRY_DELAYS_S or
  Retry-After up to RETRY_AFTER_CAP_S); TLS errors and other 4xx are not.
- Bodies are streamed and a response larger than the caller's max_bytes is refused.
- New files are written to a new path only (temporary .part file, then rename); an existing
  file is never overwritten.
- A spreadsheet download is checked before it is saved (check_workbook): an HTML error
  page served with status 200 never reaches the raw archive or its manifest.
"""

import contextlib
import datetime
import importlib.metadata
import io
import re
import time
import urllib.robotparser
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence
from urllib.parse import urljoin, urlsplit

import requests

try:
    _VERSION = importlib.metadata.version("iraqdata")
except importlib.metadata.PackageNotFoundError:
    _VERSION = "unknown"

PROJECT_URL = "https://github.com/HusseinKh90/iraqdata"
CONTACT_EMAIL = "hk.hussein1990@gmail.com"  # shown to the sites we fetch from, so they can reach the maintainer
USER_AGENT = f"iraqdata/{_VERSION} (academic research; +{PROJECT_URL}; {CONTACT_EMAIL})"
MAX_REDIRECTS = 5
REDIRECT_STATUS = {301, 302, 303, 307, 308}
REQUEST_DELAY_S = 2.0
# Transient failures are retried, 3 attempts in total
RETRY_DELAYS_S = (2, 4)
RETRY_AFTER_CAP_S = 60
RETRY_STATUS = {429, 500, 502, 503, 504}
# Size caps shared by the CBI page and workbook downloads
PAGE_MAX_BYTES = 5_000_000
WORKBOOK_MAX_BYTES = 50_000_000

_robots: Dict[str, urllib.robotparser.RobotFileParser] = {}
_requests_made = 0
_allowed_hosts: Optional[frozenset] = None


def reset_session() -> None:
    """Forget robots.txt rules and the request count (used by tests)."""
    global _requests_made
    _robots.clear()
    _requests_made = 0


@contextlib.contextmanager
def restrict_hosts(urls: Optional[Iterable[str]]) -> Iterator[None]:
    """Inside the block, requests and their redirects may only go to the hosts of `urls` (none given: no restriction)."""
    global _allowed_hosts
    previous = _allowed_hosts
    _allowed_hosts = frozenset(urlsplit(u).hostname for u in urls) if urls else None
    try:
        yield
    finally:
        _allowed_hosts = previous


def _check_url(url: str, origin: str) -> None:
    """https only, no credentials, and a host the caller allowed (or, without a list, the host the chain started at)."""
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError(f"{url}: only https downloads are allowed")
    if parts.username or parts.password:
        raise ValueError(f"{url}: a URL with credentials is not fetched")
    if _allowed_hosts is not None:
        if parts.hostname not in _allowed_hosts:
            raise PermissionError(f"{url}: {parts.hostname} is not one of this source's hosts "
                                  f"({', '.join(sorted(_allowed_hosts))}); check it, then add it to fetchers.HOSTS")
    elif parts.hostname != origin:
        raise PermissionError(f"{url}: a redirect from {origin} to {parts.hostname} is not followed")


def page_link(page_url: str, href: str) -> str:
    """The absolute URL of a link on a page. An http link to the page's own host is fetched over https."""
    url = urljoin(page_url, href.strip())
    parts, page = urlsplit(url), urlsplit(page_url)
    if parts.scheme == "http" and parts.hostname == page.hostname:
        return "https" + url[len("http"):]
    return url


def _tls_error(url: str) -> RuntimeError:
    return RuntimeError(
        f"TLS verification failed for {url}. Download the file manually, archive it under "
        "pipeline/raw/ with a dated name and run `python pipeline/raw_audit.py manifest add <path>`."
    )


def _read_capped(resp: requests.Response, url: str, max_bytes: Optional[int]) -> None:
    """Read a streamed body into resp.content, stopping past `max_bytes`."""
    declared = resp.headers.get("Content-Length") if getattr(resp, "headers", None) else None
    if max_bytes is not None and declared and declared.isdigit() and int(declared) > max_bytes:
        resp.close()
        raise ValueError(f"{url}: response exceeds {max_bytes} bytes (Content-Length {declared})")
    chunks, total = [], 0
    for chunk in resp.iter_content(chunk_size=65536):
        total += len(chunk)
        if max_bytes is not None and total > max_bytes:
            resp.close()
            raise ValueError(f"{url}: response exceeds {max_bytes} bytes")
        chunks.append(chunk)
    resp._content = b"".join(chunks)
    resp._content_consumed = True


def _retry_wait(resp: Optional[requests.Response], attempt: int) -> float:
    after = resp.headers.get("Retry-After", "") if resp is not None and getattr(resp, "headers", None) else ""
    return min(int(after), RETRY_AFTER_CAP_S) if after.isdigit() else RETRY_DELAYS_S[attempt]


def _get(url: str, timeout: float, max_bytes: Optional[int] = None) -> requests.Response:
    """
    One polite GET, retried on timeouts, connection errors and HTTP 429/5xx:
    at most len(RETRY_DELAYS_S) + 1 attempts, waiting RETRY_DELAYS_S or Retry-After (capped). TLS
    errors and other 4xx are never retried. The body is streamed and capped at `max_bytes`.
    """
    global _requests_made
    last = len(RETRY_DELAYS_S)
    for attempt in range(last + 1):
        if _requests_made:
            time.sleep(REQUEST_DELAY_S)
        _requests_made += 1
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout, stream=True,
                                allow_redirects=False)
        except requests.exceptions.SSLError as err:
            raise _tls_error(url) from err
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            if attempt == last:
                raise
            time.sleep(RETRY_DELAYS_S[attempt])
            continue
        if resp.status_code in RETRY_STATUS and attempt < last:
            wait = _retry_wait(resp, attempt)
            resp.close()
            time.sleep(wait)
            continue
        if resp.status_code not in REDIRECT_STATUS:
            _read_capped(resp, url, max_bytes)
        return resp


def _fetch(url: str, timeout: float, max_bytes: Optional[int], robots: bool) -> requests.Response:
    """One URL, following up to MAX_REDIRECTS redirects by hand; every hop is checked before it is requested."""
    origin = urlsplit(url).hostname or ""
    for _ in range(MAX_REDIRECTS + 1):
        _check_url(url, origin)
        if robots and not _robots_for(url).can_fetch(USER_AGENT, url):
            raise PermissionError(f"robots.txt of {urlsplit(url).netloc} disallows fetching {url}")
        resp = _get(url, timeout=timeout, max_bytes=max_bytes)
        if resp.status_code not in REDIRECT_STATUS:
            return resp
        location = resp.headers.get("Location")
        resp.close()
        if not location:
            raise ValueError(f"{url}: HTTP {resp.status_code} redirect without a Location header")
        url = urljoin(url, location)
    raise ValueError(f"{origin}: more than {MAX_REDIRECTS} redirects")


def _robots_for(url: str) -> urllib.robotparser.RobotFileParser:
    parts = urlsplit(url)
    host = f"{parts.scheme}://{parts.netloc}"
    if host not in _robots:
        robots_url = f"{host}/robots.txt"
        resp = _fetch(robots_url, timeout=20, max_bytes=PAGE_MAX_BYTES, robots=False)
        parser = urllib.robotparser.RobotFileParser(robots_url)
        if 400 <= resp.status_code < 500:
            parser.parse([])  # no robots.txt: no restrictions
        elif resp.status_code >= 500:
            raise RuntimeError(f"Could not read {robots_url} (HTTP {resp.status_code}); not downloading.")
        else:
            parser.parse(resp.text.splitlines())
        _robots[host] = parser
    return _robots[host]


def polite_get(url: str, *, timeout: float, max_bytes: Optional[int] = None) -> requests.Response:
    """
    GET `url` after checking robots.txt, with pacing, the project User-Agent and TLS on, retrying
    transient failures and refusing a body larger than `max_bytes`. https only;
    redirects are followed and checked hop by hop (see the module docstring).
    """
    return _fetch(url, timeout=timeout, max_bytes=max_bytes, robots=True)


_DATED_SUFFIX = re.compile(r"^(?P<stem>.+)_(?P<date>\d{4}-\d{2}-\d{2})$")


def vintage_of(path: Path) -> Optional[str]:
    """The acquisition date in a dated file name (`<stem>_YYYY-MM-DD.<ext>`), else None."""
    m = _DATED_SUFFIX.match(Path(path).stem)
    if not m:
        return None
    try:
        datetime.date.fromisoformat(m.group("date"))
    except ValueError:
        return None
    return m.group("date")


def latest_version(path: Path) -> Path:
    """
    The newest dated re-download of `path` (`<stem>_YYYY-MM-DD<suffix>` in the same folder),
    else `path` itself, whether or not it exists. Raw files are never
    overwritten, so a re-download sits next to the original under a dated name.
    """
    path = Path(path)
    if not path.parent.exists():
        return path
    dated = []
    for p in path.parent.glob(f"{path.stem}_*{path.suffix}"):
        m = _DATED_SUFFIX.match(p.stem)
        if p.suffix == path.suffix and m and m.group("stem") == path.stem and vintage_of(p):
            dated.append((m.group("date"), p))
    return max(dated)[1] if dated else path


def save_new_file(target: Path, content: bytes) -> Path:
    """Write `content` to a path that must not exist yet, via a temporary .part file."""
    target = Path(target)
    if target.exists():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    try:
        part.write_bytes(content)
        part.rename(target)
    finally:
        if part.exists():
            part.unlink()
    return target


MAX_CANDIDATES = 5  # workbook links fetched from one page when choosing a download


def pick_workbook(page_url: str, html: str, sheets: Sequence[str], timeout: int = 60):
    """
    (url, bytes) of the one .xlsx link on `page_url` whose workbook has every sheet in `sheets`
. The links are tried in page order, at most MAX_CANDIDATES; none or
    more than one passing raises a ValueError listing every candidate with "passes" or its reason.
    A link's position on the page never decides.
    """
    links = []
    for href in re.findall(r'href=[\x27\x22]([^\x27\x22]+\.xlsx)[\x27\x22]', html):
        url = page_link(page_url, href)
        if url not in links:
            links.append(url)
    if not links:
        raise ValueError(f"{page_url}: expected an .xlsx link, found none")
    passed, notes = [], []
    for url in links[:MAX_CANDIDATES]:
        response = polite_get(url, timeout=timeout, max_bytes=WORKBOOK_MAX_BYTES)
        response.raise_for_status()
        try:
            check_workbook(response.content, url, sheets=sheets)
        except ValueError as exc:
            notes.append(f"{url} ({exc})")
            continue
        passed.append((url, response.content))
        notes.append(f"{url} (passes)")
    if len(passed) != 1:
        skipped = f"; {len(links) - MAX_CANDIDATES} more not tried" if len(links) > MAX_CANDIDATES else ""
        raise ValueError(f"{page_url}: expected exactly one .xlsx link whose workbook has sheet(s) "
                         f"{', '.join(map(repr, sheets))}, found {len(passed)}: {'; '.join(notes)}{skipped}")
    return passed[0]


def check_workbook(content: bytes, url: str, sheets: Sequence[str] = (),
                   sheet_pattern: Optional[str] = None) -> List[str]:
    """
    The sheet names of `content` when it is an .xlsx workbook that has every sheet in `sheets` and,
    if given, a sheet matching `sheet_pattern` (case-insensitive); otherwise a ValueError naming
    `url` and the reason. Called before a download is saved or added to the manifest.
    """
    import openpyxl

    if content[:4] != b"PK\x03\x04":
        raise ValueError(f"Download from {url} is not a spreadsheet (starts with {content[:40]!r})")
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
        names = list(wb.sheetnames)
        wb.close()
    except Exception as exc:
        raise ValueError(f"Download from {url} is not a readable workbook: {type(exc).__name__}: {exc}") from exc
    missing = [name for name in sheets if name not in names]
    if missing:
        raise ValueError(f"Download from {url} is missing sheet(s) {', '.join(repr(n) for n in missing)} "
                         f"(found: {', '.join(names)})")
    if sheet_pattern is not None and not any(re.search(sheet_pattern, n, re.I) for n in names):
        raise ValueError(f"Download from {url} has no sheet matching {sheet_pattern} (found: {', '.join(names)})")
    return names
