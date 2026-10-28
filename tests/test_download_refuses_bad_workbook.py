"""
Download check.

A spreadsheet download that is not a workbook, or lacks the sheet its parser reads, is refused
before anything is written to the raw archive or the manifest. downloads.polite_get is replaced by
a fake; nothing contacts the network.
"""

import io
import zipfile
from datetime import date

import pytest

import downloads
import fetchers
import parse_cbi_fiscal_bulletin
import parse_cbi_money_banking
import update_check
from conftest import RAW_DIR
from fixtures import damage

pytestmark = pytest.mark.usefixtures("no_network")

TODAY = date(2026, 10, 24)
URL = "https://cbi.iq/up/file-1.xlsx"
HTML = b"<!DOCTYPE html><html><body>Service temporarily unavailable</body></html>"


def _zip_without_workbook() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("readme.txt", "not a workbook")
    return buf.getvalue()


# ---------------------------------------------------------------- check_workbook

@pytest.mark.parametrize("content, reason", [
    (HTML, "not a spreadsheet"),
    (b"", "not a spreadsheet"),
    (_zip_without_workbook(), "not a readable workbook"),
], ids=["html", "empty", "zip_without_workbook"])
def test_non_workbooks_are_refused(content, reason):
    with pytest.raises(ValueError) as info:
        downloads.check_workbook(content, URL)
    assert URL in str(info.value) and reason in str(info.value)


def test_html_refusal_shows_what_was_received():
    with pytest.raises(ValueError, match="DOCTYPE"):
        downloads.check_workbook(HTML, URL)


def test_missing_required_sheet_is_refused():
    with pytest.raises(ValueError) as info:
        downloads.check_workbook(damage.workbook_bytes(["Sheet1"]), URL, sheets=("6-1",))
    assert URL in str(info.value) and "'6-1'" in str(info.value) and "Sheet1" in str(info.value)


def test_no_sheet_matching_pattern_is_refused():
    with pytest.raises(ValueError) as info:
        downloads.check_workbook(damage.workbook_bytes(["Annual"]), URL, sheet_pattern=r"Q[1-4]")
    assert URL in str(info.value) and "Q[1-4]" in str(info.value)


def test_valid_workbooks_are_accepted():
    assert downloads.check_workbook(damage.workbook_bytes(["6-1"]), URL, sheets=("6-1",)) == ["6-1"]
    bop = (RAW_DIR / "cbi" / "bop" / "bop_2024.xlsx").read_bytes()
    assert "BOP Q4" in downloads.check_workbook(bop, URL, sheet_pattern=r"Q[1-4]")
    kfi = (RAW_DIR / "cbi" / "key_financial_indicators.xlsx").read_bytes()
    assert downloads.check_workbook(kfi, URL)


# ---------------------------------------------------------------- nothing saved

class FakeResponse:
    def __init__(self, content=b"", text=""):
        self.status_code, self.content, self.text = 200, content, text

    def raise_for_status(self):
        pass


def _html_instead_of_workbook(url, *, timeout, max_bytes=None):
    if url.endswith(("/page/145", "/page/122", "/news/view/94")):
        label = "Balance of payments 2026" if url.endswith("/page/145") else "Download"
        return FakeResponse(text=f'<a href="/up/file-1.xlsx">{label}</a>')
    return FakeResponse(content=HTML)


@pytest.fixture
def html_web(monkeypatch):
    monkeypatch.setattr(downloads, "polite_get", _html_instead_of_workbook)


@pytest.mark.parametrize("download", [
    parse_cbi_money_banking.download_latest_indicators,
    parse_cbi_fiscal_bulletin.download_latest_bulletin,
], ids=["indicators", "bulletin"])
def test_cbi_downloaders_save_nothing(download, html_web, tmp_path):
    dest, manifest = tmp_path / "cbi", tmp_path / "raw_manifest.yaml"
    dest.mkdir()
    manifest.write_text("files: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not a spreadsheet"):
        download(dest, today=TODAY, manifest_path=manifest, manifest_root=tmp_path)
    assert list(dest.iterdir()) == []
    assert manifest.read_text(encoding="utf-8") == "files: []\n"


def test_bop_fetcher_saves_nothing(html_web, tmp_path):
    raw = tmp_path / "raw"
    (raw / "cbi" / "bop").mkdir(parents=True)
    with pytest.raises(ValueError, match="not a spreadsheet"):
        fetchers.fetch_cbi_bop(raw, TODAY, tmp_path / "m.yaml")
    assert list((raw / "cbi" / "bop").iterdir()) == []
    assert not (tmp_path / "m.yaml").exists()


def test_update_check_reports_fetch_failed(html_web, tmp_path):
    """The weekly check names the refusal as fetch_failed, not parse_failed."""
    report = update_check.run_check(tmp_path / "work", tmp_path / "report", TODAY, only_sources=["cbi_kfi"])
    (entry,) = report["sources"]
    assert entry["outcome"] == "fetch_failed"
    assert entry["detail"].startswith("ValueError:") and "not a spreadsheet" in entry["detail"]
