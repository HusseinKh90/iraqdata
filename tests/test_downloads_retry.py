"""
Retries and size caps in pipeline/downloads.py. Offline: requests.get is a scripted fake and time.sleep is recorded.
"""

import pytest
import requests

import downloads

ROBOTS = "User-agent: *\nAllow: /\n"


class Resp:
    def __init__(self, status=200, body=b"ok", headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}
        self.closed = False

    def iter_content(self, chunk_size=65536):
        for i in range(0, len(self._body), 4):
            yield self._body[i:i + 4]

    def close(self):
        self.closed = True

    @property
    def content(self):
        return self._content

    @property
    def text(self):
        return self._content.decode()


@pytest.fixture
def web(monkeypatch):
    """`web.script` is a list of results for the data URL: Resp, or an exception to raise."""
    class Web:
        script, calls, sleeps = [], [], []

        def get(self, url, **kwargs):
            if url.endswith("/robots.txt"):
                return Resp(body=ROBOTS.encode())
            self.calls.append((url, kwargs))
            result = self.script.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
    w = Web()
    w.script, w.calls, w.sleeps = [], [], []
    monkeypatch.setattr(requests, "get", w.get)
    monkeypatch.setattr(downloads.time, "sleep", w.sleeps.append)
    monkeypatch.setattr(downloads, "REQUEST_DELAY_S", 0)  # so recorded sleeps are retry waits only
    downloads.reset_session()
    yield w
    downloads.reset_session()


URL = "https://example.org/data.csv"


def waits(web):
    """Retry waits only (pacing is set to 0 in the fixture)."""
    return [s for s in web.sleeps if s]


def test_timeout_then_success(web):
    web.script = [requests.exceptions.Timeout("slow"), Resp(body=b"fine")]
    assert downloads.polite_get(URL, timeout=5).content == b"fine"
    assert len(web.calls) == 2 and waits(web) == [2]
    assert web.calls[0][1]["stream"] is True


def test_server_error_three_times_gives_up(web):
    web.script = [Resp(503), Resp(503), Resp(503)]
    assert downloads.polite_get(URL, timeout=5).status_code == 503
    assert len(web.calls) == 3 and waits(web) == [2, 4]


def test_connection_errors_exhaust_and_raise(web):
    web.script = [requests.exceptions.ConnectionError("reset")] * 3
    with pytest.raises(requests.exceptions.ConnectionError):
        downloads.polite_get(URL, timeout=5)
    assert len(web.calls) == 3


def test_retry_after_is_honoured_up_to_the_cap(web):
    web.script = [Resp(429, headers={"Retry-After": "120"}), Resp(body=b"x")]
    downloads.polite_get(URL, timeout=5)
    assert waits(web) == [downloads.RETRY_AFTER_CAP_S]


def test_client_errors_are_not_retried(web):
    web.script = [Resp(404)]
    assert downloads.polite_get(URL, timeout=5).status_code == 404
    assert len(web.calls) == 1


def test_tls_errors_are_not_retried(web):
    web.script = [requests.exceptions.SSLError("bad cert")]
    with pytest.raises(RuntimeError, match="TLS verification failed"):
        downloads.polite_get(URL, timeout=5)
    assert len(web.calls) == 1


def test_body_over_the_cap_is_refused(web):
    web.script = [Resp(body=b"x" * 100)]
    with pytest.raises(ValueError, match=r"example.org/data.csv: response exceeds 50 bytes"):
        downloads.polite_get(URL, timeout=5, max_bytes=50)


def test_declared_length_over_the_cap_is_refused_before_reading(web):
    big = Resp(body=b"x", headers={"Content-Length": "10000"})
    web.script = [big]
    with pytest.raises(ValueError, match="Content-Length 10000"):
        downloads.polite_get(URL, timeout=5, max_bytes=50)
    assert big.closed


def test_body_within_the_cap_is_read_whole(web):
    web.script = [Resp(body=b"0123456789")]
    assert downloads.polite_get(URL, timeout=5, max_bytes=10).content == b"0123456789"


def test_robots_is_fetched_once_per_host(web, monkeypatch):
    robots_calls = []
    real = web.get

    def counting(url, **kwargs):
        if url.endswith("/robots.txt"):
            robots_calls.append(url)
        return real(url, **kwargs)
    monkeypatch.setattr(requests, "get", counting)
    web.script = [Resp(), Resp()]
    downloads.polite_get(URL, timeout=5)
    downloads.polite_get(URL + "?2", timeout=5)
    assert robots_calls == ["https://example.org/robots.txt"]
