"""
tests.test_fetchers
===================
One fetcher per automatically fetchable source. downloads.polite_get is replaced by a fake; nothing contacts the network.
"""

import shutil
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

import downloads
import fetchers
from conftest import RAW_DIR
from fixtures import damage

pytestmark = pytest.mark.usefixtures("no_network")

TODAY = date(2026, 10, 24)
# Bytes that differ from every archived file. A real minimal workbook (a quarter sheet and
# the bulletin's 6-1), because CBI spreadsheet downloads are now checked before they are saved
NEW = damage.workbook_bytes(["BOP Q1", "6-1", "Sheet1"])  # Sheet1 is the sheet the KFI parser reads
# The two exchange-rate sources check their content too (a CSV header; the sheet the
# parser reads), so each gets new bytes of its own kind
NEW_FOR = {
    "cbi_fx": damage.workbook_bytes(["Daily Price basis"]),
}


def _grown(source: str) -> bytes:
    """API sources are content-checked and may not shrink, so a new release is the
    archived file plus one later row (or, for World Bank JSON, the same rows newly stamped)."""
    import io
    import json as _json
    import zipfile

    latest = downloads.latest_version
    if source == "fred_brent":
        return latest(RAW_DIR / "fred" / "DCOILBRENTEU.csv").read_bytes().rstrip(b"\n") + b"\n2099-01-01,99.0\n"
    if source == "github_fx":
        text = latest(RAW_DIR / "github" / "daily_fx.csv").read_bytes().rstrip(b"\n")
        last = text.split(b"\n")[-1].split(b",")
        return text + b"\n" + b",".join([b"2099-01-01"] + last[1:]) + b"\n"
    if source == "bis_lbs":
        text = latest(RAW_DIR / "bis" / "bis_lbs_claims_total.csv").read_bytes().rstrip(b"\n")
        return text + b"\n" + text.split(b"\n")[-1] + b"\n"
    if source == "wb_oda":
        payload = _json.loads(latest(RAW_DIR / "oecd" / "wb_oda_net.json").read_text(encoding="utf-8"))
        payload[0]["lastupdated"] = "2099-01-01"
        return _json.dumps(payload).encode()
    if source == "eia_intl":
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            # A fixed timestamp: zip entries store the time, so two builds a second apart would differ
            zf.writestr(zipfile.ZipInfo("INTL.txt", date_time=(2026, 10, 24, 0, 0, 0)), "new release")
        return buf.getvalue()
    return None
# The three workbook links on https://cbi.iq/page/144 as measured on 2026-10-24
PAGE_144 = (
    '<a href="https://cbi.iq/static/uploads/up/file-1.xlsx">اسعار صرف الدينار تجاه الدولار الأمريكي ( يومي - شهري - سنوي )</a>'
    '<a href="https://cbi.iq/static/uploads/up/file-2.xlsx">أسعار صرف الدينار العراقي اليومية تجاه العملات الرئيسية والذهب ( بيع ، شراء )</a>'
    '<a href="https://cbi.iq/static/uploads/up/file-3.xlsx">اسعار العملات العربية والأجنبية تجاه الدولار للفترة من ( 1995 -&nbsp; 2026 )</a>'
)


class Pages:
    """A CBI page with the given .xlsx links, each answered with its own bytes."""

    def __init__(self, files):
        self.files, self.urls = files, []

    def get(self, url, *, timeout, max_bytes=None):
        self.urls.append(url)
        if url.endswith((".xlsx",)):
            name = url.rsplit("/", 1)[-1]
            return FakeResponse(content=self.files[name])
        return FakeResponse(text="".join(f'<a href="/up/{n}">Download</a>' for n in self.files))


@pytest.mark.parametrize("module, func, sheet", [
    ("parse_cbi_money_banking", "download_latest_indicators", "Sheet1"),
    ("parse_cbi_fiscal_bulletin", "download_latest_bulletin", "6-1"),
], ids=["indicators", "bulletin"])
def test_download_is_chosen_by_its_workbook(module, func, sheet, tmp_path, monkeypatch):
    """The link whose workbook has the parser's sheet wins, whatever its position."""
    import importlib
    download = getattr(importlib.import_module(module), func)
    right, wrong = damage.workbook_bytes([sheet]), damage.workbook_bytes(["Other"])

    def run(files, folder):
        web = Pages(files)
        monkeypatch.setattr(downloads, "polite_get", web.get)
        root = tmp_path / folder  # a manifest root with the repository's layout (for the source rules)
        dest = root / "pipeline" / "raw" / "cbi"
        dest.mkdir(parents=True)
        manifest = root / "raw_manifest.yaml"
        manifest.write_text("files: []\n", encoding="utf-8")
        return download(dest, today=TODAY, manifest_path=manifest, manifest_root=root), web

    saved, web = run({"file-1.xlsx": wrong, "file-2.xlsx": right}, "second")
    assert saved.read_bytes() == right
    with pytest.raises(ValueError, match=r"found 2: .*file-1.xlsx \(passes\).*file-2.xlsx \(passes\)"):
        run({"file-1.xlsx": right, "file-2.xlsx": right}, "both")
    with pytest.raises(ValueError, match=r"found 0: .*file-1.xlsx \(.*missing sheet"):
        run({"file-1.xlsx": wrong, "file-2.xlsx": wrong}, "none")
    web = Pages({f"file-{i}.xlsx": (right if i == 7 else wrong) for i in range(1, 8)})
    monkeypatch.setattr(downloads, "polite_get", web.get)
    many = tmp_path / "many" / "pipeline" / "raw" / "cbi"
    many.mkdir(parents=True)
    with pytest.raises(ValueError, match="2 more not tried"):
        download(many, today=TODAY, manifest_path=tmp_path / "m.yaml", manifest_root=tmp_path / "many")
    assert sum(u.endswith(".xlsx") for u in web.urls) == downloads.MAX_CANDIDATES


def new_bytes(source: str, url: str = "") -> bytes:
    grown = _grown(source)
    if source == "bis_lbs":  # one grown file per series key, so each passes its own no-shrink check
        name = next(n for n in fetchers.BIS_FILES if fetchers._bis_key(RAW_DIR / "bis" / n) in url) if url else None
        if name:
            text = (RAW_DIR / "bis" / name).read_bytes().rstrip(b"\n")
            return text + b"\n" + text.split(b"\n")[-1] + b"\n"
    if source == "wb_oda" and url:
        import json as _json
        name = "wb_oda_net.json" if "DT.ODA.ALLD.CD" in url else "wb_oda_grants.json"
        payload = _json.loads(downloads.latest_version(RAW_DIR / "oecd" / name).read_text(encoding="utf-8"))
        payload[0]["lastupdated"] = "2099-01-01"
        return _json.dumps(payload).encode()
    return grown if grown is not None else NEW_FOR.get(source, NEW)


class FakeResponse:
    def __init__(self, content=b"", text=""):
        self.status_code, self.content, self.text = 200, content, text or content.decode("latin-1")

    def raise_for_status(self):
        pass


class FakeWeb:
    """Answers polite_get: HTML pages with labelled .xlsx links, else the bytes from `content_for`."""

    def __init__(self, content_for, error=None, page_144=PAGE_144):
        self.content_for, self.error, self.urls, self.page_144 = content_for, error, [], page_144
        self.caps = []

    def get(self, url, *, timeout, max_bytes=None):
        self.urls.append(url)
        self.caps.append(max_bytes)
        if self.error is not None:
            raise self.error
        if url.endswith("/page/144"):
            return FakeResponse(text=self.page_144)
        if url.endswith(("/page/145", "/page/122", "/news/view/94")):
            links = ('<a href="/up/bop-a.xlsx">Balance of payments 2026</a>'
                     '<a href="/up/bop-b.xlsx">Balance of payments 2025</a>'
                     if url.endswith("/page/145") else '<a href="/up/file-1.xlsx">Download</a>')
            return FakeResponse(text=links)
        content = self.content_for(url)
        if max_bytes is not None and len(content) > max_bytes:  # as downloads.polite_get
            raise ValueError(f"{url}: response exceeds {max_bytes} bytes")
        return FakeResponse(content=content)


@pytest.fixture
def raw(tmp_path):
    root = tmp_path / "raw"
    for folder in ("bis", "cbi", "eia", "fred", "oecd", "github"):
        if (RAW_DIR / folder).exists():
            shutil.copytree(RAW_DIR / folder, root / folder)
    return root


def archived_bytes(raw: Path, source: str, url: str) -> bytes:
    """The bytes of the archived file a request stands for (an identical re-delivery)."""
    if source == "fred_brent":
        return (raw / "fred" / "DCOILBRENTEU.csv").read_bytes()
    if source == "eia_intl":
        return (raw / "eia" / "INTL.zip").read_bytes()
    if source == "wb_oda":
        name = "wb_oda_net.json" if "DT.ODA.ALLD.CD" in url else "wb_oda_grants.json"
        return (raw / "oecd" / name).read_bytes()
    if source == "bis_lbs":
        for name in fetchers.BIS_FILES:
            if fetchers._bis_key(raw / "bis" / name) in url:
                return (raw / "bis" / name).read_bytes()
    if source == "cbi_bop":
        return (raw / "cbi" / "bop" / ("bop_2026.xlsx" if "bop-a" in url else "bop_2025.xlsx")).read_bytes()
    if source == "cbi_kfi":
        return (raw / "cbi" / "key_financial_indicators.xlsx").read_bytes()
    if source == "cbi_bulletin":
        return (raw / "cbi" / "bulletin_latest.xlsx").read_bytes()
    if source == "github_fx":
        return downloads.latest_version(raw / "github" / "daily_fx.csv").read_bytes()
    if source == "cbi_fx":
        return downloads.latest_version(raw / "cbi" / "fx" / "cbi_fx_usd.xlsx").read_bytes()
    raise AssertionError(url)


def run(source, raw, tmp_path, monkeypatch, content_for=None, error=None):
    web = FakeWeb(content_for or (lambda url: new_bytes(source, url)), error)
    monkeypatch.setattr(downloads, "polite_get", web.get)
    result = fetchers.FETCHERS[source](raw, TODAY, tmp_path / "manifest.yaml")
    return result, web


SOURCES = sorted(fetchers.FETCHERS)


@pytest.mark.parametrize("source", SOURCES)
def test_new_content_is_saved_under_a_dated_name(source, raw, tmp_path, monkeypatch):
    saved, web = run(source, raw, tmp_path, monkeypatch)
    assert saved, source
    for path in saved:
        assert path.exists() and path.read_bytes() in {new_bytes(source, u) for u in web.urls}
        assert "2026-10-24" in path.name
        assert path.is_relative_to(raw)
    for url in web.urls:
        assert url.startswith(tuple(fetchers.HOSTS[source])), url


@pytest.mark.parametrize("source", SOURCES)
def test_identical_content_saves_nothing(source, raw, tmp_path, monkeypatch):
    before = sorted(p.relative_to(raw).as_posix() for p in raw.rglob("*") if p.is_file())
    saved, _ = run(source, raw, tmp_path, monkeypatch, content_for=lambda url: archived_bytes(raw, source, url))
    assert saved is None
    after = sorted(p.relative_to(raw).as_posix() for p in raw.rglob("*") if p.is_file())
    assert after == before


@pytest.mark.parametrize("error", [
    requests.exceptions.HTTPError("HTTP 503"),
    RuntimeError("TLS verification failed"),
    PermissionError("robots.txt disallows fetching"),
])
@pytest.mark.parametrize("source", SOURCES)
def test_errors_propagate(source, error, raw, tmp_path, monkeypatch):
    with pytest.raises(type(error)):
        run(source, raw, tmp_path, monkeypatch, error=error)


def test_dated_names_keep_the_cbi_conventions(raw, tmp_path, monkeypatch):
    saved, _ = run("cbi_kfi", raw, tmp_path, monkeypatch)
    assert [p.name for p in saved] == ["cbi_key_financial_indicators_2026-10-24.xlsx"]
    saved, _ = run("cbi_bop", raw, tmp_path, monkeypatch)
    assert sorted(p.name for p in saved) == ["bop_2025_2026-10-24.xlsx", "bop_2026_2026-10-24.xlsx"]


def test_bop_page_without_year_links_fails_clearly(raw, tmp_path, monkeypatch):
    web = SimpleNamespace(get=lambda url, **kw: FakeResponse(text='<a href="/x.xlsx">Download</a>'))
    monkeypatch.setattr(downloads, "polite_get", web.get)
    with pytest.raises(ValueError, match="cbi_bop"):
        fetchers.fetch_cbi_bop(raw, TODAY, tmp_path / "m.yaml")


# ---------------------------------------------------------------------- exchange-rate sources


def test_github_fx_saves_a_dated_csv(raw, tmp_path, monkeypatch):
    saved, web = run("github_fx", raw, tmp_path, monkeypatch)
    assert [p.relative_to(raw).as_posix() for p in saved] == ["github/daily_fx_2026-10-24.csv"]
    assert web.urls == [fetchers.GITHUB_FX_URL]


def test_github_fx_refuses_an_html_page(raw, tmp_path, monkeypatch):
    before = sorted(p.name for p in (raw / "github").glob("*")) if (raw / "github").exists() else []
    with pytest.raises(ValueError, match="DOCTYPE"):
        run("github_fx", raw, tmp_path, monkeypatch, content_for=lambda url: b"<!DOCTYPE html><html>error</html>")
    after = sorted(p.name for p in (raw / "github").glob("*")) if (raw / "github").exists() else []
    assert after == before


def test_cbi_fx_picks_the_dinar_dollar_daily_workbook(raw, tmp_path, monkeypatch):
    saved, web = run("cbi_fx", raw, tmp_path, monkeypatch)
    assert [p.relative_to(raw).as_posix() for p in saved] == ["cbi/fx/cbi_fx_usd_2026-10-24.xlsx"]
    assert web.urls == [fetchers.CBI_FX_PAGE, "https://cbi.iq/static/uploads/up/file-1.xlsx"]


@pytest.mark.parametrize("page", [PAGE_144.split("</a>")[1] + "</a>", PAGE_144 + PAGE_144.split("</a>")[0] + "</a>"],
                         ids=["no_match", "two_matches"])
def test_cbi_fx_needs_exactly_one_matching_link(page, raw, tmp_path, monkeypatch):
    web = FakeWeb(lambda url: new_bytes("cbi_fx"), page_144=page)
    monkeypatch.setattr(downloads, "polite_get", web.get)
    with pytest.raises(ValueError, match="الدينار"):
        fetchers.fetch_cbi_fx(raw, TODAY, tmp_path / "m.yaml")


def test_cbi_fx_names_the_firewall(raw, tmp_path, monkeypatch):
    web = FakeWeb(lambda url: new_bytes("cbi_fx"),
                  page_144="<html><title>Blocked</title><div>You have been blocked</div></html>")
    monkeypatch.setattr(downloads, "polite_get", web.get)
    with pytest.raises(ValueError, match="firewall"):
        fetchers.fetch_cbi_fx(raw, TODAY, tmp_path / "m.yaml")


def test_cbi_fx_refuses_a_workbook_without_the_sheet(raw, tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="Daily Price basis"):
        run("cbi_fx", raw, tmp_path, monkeypatch, content_for=lambda url: damage.workbook_bytes(["Sheet1"]))
    assert not list((raw / "cbi" / "fx").glob("*_2026-10-24.xlsx")) if (raw / "cbi" / "fx").exists() else True


# ---------------------------------------------------------------------- caps and content checks

API_SOURCES = ["bis_lbs", "eia_intl", "fred_brent", "github_fx", "wb_oda"]


def _raw_files(raw):
    return sorted(p.relative_to(raw).as_posix() for p in raw.rglob("*") if p.is_file())


@pytest.mark.parametrize("source", API_SOURCES)
def test_an_html_page_is_refused_and_nothing_saved(source, raw, tmp_path, monkeypatch):
    before = _raw_files(raw)
    with pytest.raises(ValueError):
        run(source, raw, tmp_path, monkeypatch, content_for=lambda url: b"<!DOCTYPE html><html>busy</html>")
    assert _raw_files(raw) == before


@pytest.mark.parametrize("source", API_SOURCES)
def test_each_download_is_capped(source, raw, tmp_path, monkeypatch):
    _, web = run(source, raw, tmp_path, monkeypatch)
    assert web.caps and all(c == fetchers.MAX_BYTES[source] for c in web.caps)
    before = _raw_files(raw)
    with pytest.raises(ValueError, match="exceeds"):
        run(source, raw, tmp_path, monkeypatch, content_for=lambda url: b"x" * (fetchers.MAX_BYTES[source] + 1))
    assert _raw_files(raw) == before


@pytest.mark.parametrize("source, shrink", [
    ("fred_brent", lambda b: b"\n".join(b.split(b"\n")[:-50])),
    ("github_fx", lambda b: b"\n".join(b.split(b"\n")[:-50])),
    ("bis_lbs", lambda b: b"\n".join(b.split(b"\n")[:-5])),
])
def test_a_shrunk_file_is_refused(source, shrink, raw, tmp_path, monkeypatch):
    before = _raw_files(raw)
    with pytest.raises(ValueError, match="shrank"):
        run(source, raw, tmp_path, monkeypatch, content_for=lambda url: shrink(archived_bytes(raw, source, url)))
    assert _raw_files(raw) == before


def test_world_bank_indicator_comes_from_the_catalog(raw, tmp_path, monkeypatch):
    _, web = run("wb_oda", raw, tmp_path, monkeypatch)
    assert any("DT.ODA.ALLD.CD" in u for u in web.urls) and any("BX.GRT.EXTA.CD.WD" in u for u in web.urls)
    swapped = lambda url: archived_bytes(raw, "wb_oda", url.replace("DT.ODA.ALLD.CD", "X").replace(
        "BX.GRT.EXTA.CD.WD", "DT.ODA.ALLD.CD").replace("X", "BX.GRT.EXTA.CD.WD"))
    with pytest.raises(ValueError, match="indicator"):
        run("wb_oda", raw, tmp_path, monkeypatch, content_for=swapped)


# ---------------------------------------------------------------------- live verification (offline test)


def test_verify_fetchers_records_each_source_without_touching_raw(tmp_path, monkeypatch):
    import datetime as dt

    import verify_fetchers
    from conftest import hash_tree

    def ok(raw_root, today, manifest):
        downloads.polite_get("https://example.org/a.csv", timeout=5)
        return None

    def broken(raw_root, today, manifest):
        raise PermissionError("robots.txt disallows fetching")

    class Resp:
        status_code, content, url, headers = 200, b"abc", "https://example.org/final.csv", {"Content-Type": "text/csv"}

    monkeypatch.setattr(downloads, "polite_get", lambda url, **kw: Resp())
    before = hash_tree(RAW_DIR)
    records = verify_fetchers.verify(["a", "b"], dt.date(2026, 10, 26), fetcher_table={"a": ok, "b": broken})
    assert hash_tree(RAW_DIR) == before
    assert [(r["source"], r["status"]) for r in records] == [("a", "verified"), ("b", "failed")]
    assert records[0]["responses"][0] == {"url": "https://example.org/a.csv", "final_url": "https://example.org/final.csv",
                                          "status": 200, "content_type": "text/csv", "size": 3,
                                          "sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"}
    assert "robots.txt" in records[1]["reason"]
    out = tmp_path / "record.yaml"
    verify_fetchers.write_record(records, out)
    import yaml
    assert [r["source"] for r in yaml.safe_load(out.read_text(encoding="utf-8"))["sources"]] == ["a", "b"]
