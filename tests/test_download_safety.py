"""
tests.test_download_safety
==========================
What the downloader refuses: anything but https, a URL with credentials, a redirect to another
host (or, in the weekly check, to a host that is not one of the source's), too many redirects, and
a zip that expands far beyond the file we expect. The project's contact address is in every
request's User-Agent. Offline: requests.get is a scripted fake.
"""

import io
import zipfile

import pytest
import requests

import download_checks
import downloads
import fetchers
import parse_oil_monthly
from conftest import block_network
from fixtures import damage
from source_io import ParseError

ROBOTS = b"User-agent: *\nAllow: /\n"


class Resp:
    def __init__(self, status=200, body=b"ok", headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}

    def iter_content(self, chunk_size=65536):
        yield self._body

    def close(self):
        pass

    @property
    def content(self):
        return self._content

    @property
    def text(self):
        return self._content.decode()


@pytest.fixture
def web(monkeypatch):
    """`web.routes` maps a URL to a Resp; every requested URL is recorded in `web.urls`."""
    class Web:
        routes, urls = {}, []

        def get(self, url, **kwargs):
            self.urls.append(url)
            assert kwargs.get("allow_redirects") is False       # redirects are followed here, not by requests
            if url.endswith("/robots.txt"):
                return Resp(body=ROBOTS)
            return self.routes[url]
    w = Web()
    w.routes, w.urls = {}, []
    monkeypatch.setattr(requests, "get", w.get)
    monkeypatch.setattr(downloads.time, "sleep", lambda s: None)
    downloads.reset_session()
    yield w
    downloads.reset_session()


def redirect(to, status=302):
    return Resp(status, b"", {"Location": to})


START = "https://data.example.org/a.csv"


def test_plain_http_is_refused(web):
    with pytest.raises(ValueError, match="only https"):
        downloads.polite_get("http://data.example.org/a.csv", timeout=5)
    assert web.urls == []


def test_credentials_in_the_url_are_refused(web):
    with pytest.raises(ValueError, match="credentials"):
        downloads.polite_get("https://user:pw@data.example.org/a.csv", timeout=5)


def test_a_redirect_on_the_same_host_is_followed(web):
    web.routes = {START: redirect("/files/b.csv"), "https://data.example.org/files/b.csv": Resp(body=b"data")}
    assert downloads.polite_get(START, timeout=5).content == b"data"
    assert web.urls[-1] == "https://data.example.org/files/b.csv"


def test_a_redirect_to_another_host_is_not_followed_by_default(web):
    web.routes = {START: redirect("https://elsewhere.example.net/b.csv")}
    with pytest.raises(PermissionError, match="elsewhere.example.net"):
        downloads.polite_get(START, timeout=5)
    assert "https://elsewhere.example.net/b.csv" not in web.urls


def test_a_redirect_to_http_is_refused(web):
    web.routes = {START: redirect("http://data.example.org/b.csv")}
    with pytest.raises(ValueError, match="only https"):
        downloads.polite_get(START, timeout=5)


def test_a_declared_host_may_be_redirected_to_and_its_robots_txt_is_read(web):
    web.routes = {START: redirect("https://www.example.org/b.csv"), "https://www.example.org/b.csv": Resp(body=b"data")}
    with downloads.restrict_hosts(["https://data.example.org/", "https://www.example.org/"]):
        assert downloads.polite_get(START, timeout=5).content == b"data"
    assert "https://www.example.org/robots.txt" in web.urls


def test_a_host_outside_the_declared_ones_is_refused_even_as_the_first_request(web):
    with downloads.restrict_hosts(["https://data.example.org/"]):
        with pytest.raises(PermissionError, match="not one of this source's hosts"):
            downloads.polite_get("https://other.example.net/a.csv", timeout=5)
    assert web.urls == []
    # the restriction ends with the block
    web.routes = {"https://other.example.net/a.csv": Resp(body=b"x")}
    assert downloads.polite_get("https://other.example.net/a.csv", timeout=5).content == b"x"


def test_redirect_loops_and_missing_locations_stop(web):
    web.routes = {START: redirect(START)}
    with pytest.raises(ValueError, match="more than 5 redirects"):
        downloads.polite_get(START, timeout=5)
    assert len([u for u in web.urls if not u.endswith("robots.txt")]) == downloads.MAX_REDIRECTS + 1
    web.routes = {START: Resp(301, b"", {})}
    with pytest.raises(ValueError, match="without a Location"):
        downloads.polite_get(START, timeout=5)


@pytest.mark.parametrize("href, expected", [
    ("/static/f.xlsx", "https://cbi.iq/static/f.xlsx"),
    ("f.xlsx", "https://cbi.iq/page/f.xlsx"),
    ("https://cbi.iq/static/f.xlsx", "https://cbi.iq/static/f.xlsx"),
    ("http://cbi.iq/static/f.xlsx", "https://cbi.iq/static/f.xlsx"),                  # same host: upgraded
    ("http://other.example/f.xlsx", "http://other.example/f.xlsx"),                  # kept, so it is refused later
    ("//other.example/f.xlsx", "https://other.example/f.xlsx"),
    (" /static/f.xlsx ", "https://cbi.iq/static/f.xlsx"),
])
def test_page_links_are_resolved_against_the_page(href, expected):
    assert downloads.page_link("https://cbi.iq/page/145", href) == expected


def test_a_link_to_another_host_is_refused_in_the_weekly_check(web):
    link = downloads.page_link("https://cbi.iq/page/145", "//attacker.example/f.xlsx")
    with downloads.restrict_hosts(fetchers.HOSTS["cbi_bop"]):
        with pytest.raises(PermissionError, match="attacker.example"):
            downloads.polite_get(link, timeout=5)


def test_every_fetcher_has_https_hosts():
    assert set(fetchers.HOSTS) == set(fetchers.FETCHERS)
    for source, hosts in fetchers.HOSTS.items():
        assert hosts and all(h.startswith("https://") for h in hosts), source


def test_eia_redirect_host_is_declared():
    """api.eia.gov/bulk/INTL.zip redirects to www.eia.gov (pipeline/metadata/fetcher_verification.yaml)."""
    assert "https://www.eia.gov/" in fetchers.HOSTS["eia_intl"]


def test_user_agent_names_the_project_and_a_contact():
    assert downloads.PROJECT_URL in downloads.USER_AGENT and downloads.CONTACT_EMAIL in downloads.USER_AGENT
    assert "@" in downloads.CONTACT_EMAIL


# ------------------------------------------------------------------------------ the EIA archive


def _zip(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_a_normal_eia_archive_passes():
    lines = [f'{{"series_id": "INTL.{i}-{i * 7919 % 1000}", "data": [["2020{i % 12 + 1:02d}", {i * 31 % 977}]]}}'
             for i in range(2000)]                       # text like the real file: a ratio of about 5
    download_checks.check_eia_zip(_zip({"INTL.txt": "\n".join(lines).encode()}), "u")


def test_an_archive_that_expands_too_far_is_refused_before_it_is_read(monkeypatch):
    monkeypatch.setattr(download_checks, "EIA_MAX_UNCOMPRESSED", 1000)
    with pytest.raises(ValueError, match="expands to"):
        download_checks.check_eia_zip(_zip({"INTL.txt": b"x" * 5000}), "u")


def test_a_compression_ratio_far_beyond_text_is_refused():
    with pytest.raises(ValueError, match="ratio"):
        download_checks.check_eia_zip(_zip({"INTL.txt": b"\0" * 5_000_000}), "u")


def test_an_archive_with_many_members_is_refused():
    members = {f"f{i}.txt": b"x" for i in range(download_checks.EIA_MAX_MEMBERS)}
    members["INTL.txt"] = b"x"
    with pytest.raises(ValueError, match="members"):
        download_checks.check_eia_zip(_zip(members), "u")


def test_the_parser_stops_at_an_overlong_eia_line(tmp_path, monkeypatch):
    raw, seeds = damage.copy_inputs("oil_monthly", tmp_path)
    monkeypatch.setattr(parse_oil_monthly, "EIA_MAX_LINE", 1000)   # the real file has lines of about 39 KB
    with block_network(), pytest.raises(ParseError) as info:
        damage.run_parser("oil_monthly", raw, seeds, tmp_path / "out")
    assert "INTL.txt line" in str(info.value) and "longer line" in str(info.value)
