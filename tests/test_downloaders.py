"""
CBI downloaders: polite, checked scraping.

Downloads verify TLS, respect robots.txt, pace their requests, identify the project, and save
to a new dated file that is added to the manifest. They never overwrite an existing file. No
test contacts the network: requests.get is replaced by a recording fake.
"""

import importlib.metadata
from datetime import date
from types import SimpleNamespace

import pytest
import requests

from conftest import REPO_ROOT
from fixtures import damage

TODAY = date(2026, 10, 24)
# A real minimal workbook, since downloads are now checked before they are saved
WORKBOOK = damage.workbook_bytes(["6-1", "Sheet1"])  # each downloader checks the sheet its parser reads

DOWNLOADERS = {
    "bulletin": ("parse_cbi_fiscal_bulletin", "download_latest_bulletin", "cbi_bulletin_2026-10-24.xlsx"),
    "indicators": ("parse_cbi_money_banking", "download_latest_indicators",
                   "cbi_key_financial_indicators_2026-10-24.xlsx"),
}


class FakeResponse:
    def __init__(self, status_code=200, text="", content=b""):
        self.status_code, self.text, self.content = status_code, text, content
        self.headers = {}

    def iter_content(self, chunk_size=65536):  # polite_get streams the body
        yield self.content or self.text.encode()

    def close(self):
        pass

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")


class FakeWeb:
    """Serves robots.txt, an HTML page with one .xlsx link, then the workbook bytes."""

    def __init__(self, robots="User-agent: *\nAllow: /\n", ssl_error=False):
        self.robots, self.ssl_error, self.calls = robots, ssl_error, []

    def get(self, url, **kwargs):
        self.calls.append(SimpleNamespace(url=url, kwargs=kwargs))
        if self.ssl_error:
            raise requests.exceptions.SSLError("certificate verify failed")
        if url.endswith("/robots.txt"):
            return FakeResponse(text=self.robots)
        if url.endswith(".xlsx"):
            return FakeResponse(content=WORKBOOK)
        return FakeResponse(text='<a href="/uploads/file-123.xlsx">Download</a>')


@pytest.fixture(params=sorted(DOWNLOADERS))
def downloader(request, monkeypatch, tmp_path):
    import importlib

    import downloads

    module_name, func_name, expected_name = DOWNLOADERS[request.param]
    module = importlib.import_module(module_name)
    web = FakeWeb()
    sleeps = []
    monkeypatch.setattr(requests, "get", web.get)
    monkeypatch.setattr(downloads.time, "sleep", sleeps.append)
    downloads.reset_session()

    raw_cbi = tmp_path / "pipeline" / "raw" / "cbi"
    raw_cbi.mkdir(parents=True)
    manifest_path = tmp_path / "raw_manifest.yaml"

    def run():
        return getattr(module, func_name)(raw_cbi, today=TODAY, manifest_path=manifest_path, manifest_root=tmp_path)

    yield SimpleNamespace(run=run, web=web, sleeps=sleeps, raw_cbi=raw_cbi, manifest_path=manifest_path,
                          target=raw_cbi / expected_name, downloads=downloads)
    downloads.reset_session()


def test_tls_verification_never_disabled(downloader):
    downloader.run()
    assert downloader.web.calls
    assert all(call.kwargs.get("verify", True) is not False for call in downloader.web.calls)


def test_ssl_error_gives_guided_message(downloader):
    downloader.web.ssl_error = True
    with pytest.raises(RuntimeError) as excinfo:
        downloader.run()
    message = str(excinfo.value).lower()
    assert "manually" in message and "archive" in message
    assert list(downloader.raw_cbi.iterdir()) == []


def test_saves_new_dated_file(downloader):
    import raw_audit

    path = downloader.run()
    assert path == downloader.target
    assert path.read_bytes() == WORKBOOK
    assert list(downloader.raw_cbi.iterdir()) == [path]
    entries = raw_audit.load_manifest(downloader.manifest_path)["files"]
    assert [e["path"] for e in entries] == [f"pipeline/raw/cbi/{path.name}"]
    assert entries[0]["sha256"] == raw_audit.sha256_file(path)
    assert entries[0]["acquired"] == TODAY.isoformat()


def test_refuses_existing_target(downloader):
    downloader.target.write_bytes(b"earlier vintage")
    with pytest.raises(FileExistsError):
        downloader.run()
    assert downloader.target.read_bytes() == b"earlier vintage"
    assert downloader.web.calls == []


def test_no_insecure_code_in_parsers():
    for path in sorted((REPO_ROOT / "pipeline" / "parsers").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        assert "verify=False" not in text, path.name
        assert "disable_warnings" not in text, path.name


def test_robots_disallow_stops_download(downloader):
    downloader.web.robots = "User-agent: *\nDisallow: /\n"
    with pytest.raises(PermissionError) as excinfo:
        downloader.run()
    assert "robots.txt" in str(excinfo.value)
    assert [c.url for c in downloader.web.calls] == ["https://cbi.iq/robots.txt"]
    assert list(downloader.raw_cbi.iterdir()) == []


def test_requests_are_paced(downloader):
    downloader.run()
    n_requests = len(downloader.web.calls)
    assert n_requests == 3  # robots.txt, the page, the workbook
    assert len(downloader.sleeps) == n_requests - 1
    assert all(s >= downloader.downloads.REQUEST_DELAY_S >= 2.0 for s in downloader.sleeps)


def test_user_agent_identifies_project(downloader):
    downloader.run()
    try:
        ver = importlib.metadata.version("iraqdata")
    except Exception:
        ver = "unknown"
    expected = f"iraqdata/{ver}"
    assert downloader.downloads.USER_AGENT.startswith(expected)
    for call in downloader.web.calls:
        assert call.kwargs["headers"]["User-Agent"] == downloader.downloads.USER_AGENT
