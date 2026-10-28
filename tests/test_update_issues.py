"""
Update-check issues. Offline: planning is pure,
and the GitHub client runs against a fake opener.
"""

import io
import json
import subprocess
import sys
import urllib.error
import zipfile

import pytest

import update_issues as ui
from conftest import REPO_ROOT

RUN = {"url": "https://github.com/o/r/actions/runs/9", "id": "9", "date": "2026-11-02"}


def finding(identity, details=({"x": 1},), kind="anomaly", title=None):
    details = [dict(d) for d in details]
    return {"kind": kind, "identity": identity, "title": title or identity, "details": details,
            "fingerprint": ui.fingerprint(details), "sources": []}


def issue(number, identity, details=({"x": 1},), state="open"):
    f = finding(identity, details)
    return {"number": number, "state": state, "title": "t", "body": ui.issue_body(f, RUN)}


def ops(actions):
    return [(a["op"], a["identity"]) for a in actions]


# --- contract items 1-8 ---------------------------------------------------------------------

def test_new_anomaly_creates_and_mentions():
    actions = ui.plan_actions([finding("fetch_failed:wb_oda")], [], "me", RUN, True)
    assert ops(actions) == [("create", "fetch_failed:wb_oda"), ("comment", "fetch_failed:wb_oda")]
    assert actions[1]["body"].startswith("@me new:")
    assert ui.parse_marker(actions[0]["body"])[0] == "fetch_failed:wb_oda"
    assert actions[0]["labels"] == [ui.LABEL]


def test_same_fingerprint_edits_quietly():
    actions = ui.plan_actions([finding("gate:prices_monthly")], [issue(5, "gate:prices_monthly")], "me", RUN, True)
    assert ops(actions) == [("edit", "gate:prices_monthly")]


def test_changed_fingerprint_edits_and_mentions():
    old = issue(5, "revised:prices_monthly", details=({"x": 1},))
    actions = ui.plan_actions([finding("revised:prices_monthly", details=({"x": 2},))], [old], "me", RUN, True)
    assert ops(actions) == [("edit", "revised:prices_monthly"), ("comment", "revised:prices_monthly")]
    assert actions[1]["body"].startswith("@me changed:")


def test_review_issue_does_not_mention_while_open():
    """A newer spreadsheet file updates the open review issue silently."""
    old = issue(7, "review:cbi_fx", details=({"file": "a"},))
    actions = ui.plan_actions([finding("review:cbi_fx", details=({"file": "b"},))], [old], "me", RUN, True)
    assert ops(actions) == [("edit", "review:cbi_fx")]


def test_closed_issue_reopens_with_mention():
    actions = ui.plan_actions([finding("overdue:cbi_kfi")], [issue(3, "overdue:cbi_kfi", state="closed")],
                              "me", RUN, True)
    assert ops(actions) == [("reopen", "overdue:cbi_kfi"), ("edit", "overdue:cbi_kfi"), ("comment", "overdue:cbi_kfi")]
    assert actions[2]["body"].startswith("@me back:")


def test_resolved_issue_closes_only_after_a_good_report():
    existing = [issue(4, "fetch_failed:wb_oda")]
    assert ops(ui.plan_actions([], existing, "me", RUN, True)) == [("comment", "fetch_failed:wb_oda"),
                                                                    ("close", "fetch_failed:wb_oda")]
    assert ui.plan_actions([], existing, "me", RUN, False) == []


def test_routine_findings_make_no_actions():
    assert ui.plan_actions([finding("routine:fred_brent", kind="routine")], [], "me", RUN, True) == []


def test_review_issue_opens_and_closes():
    """6a: a spreadsheet release opens review:<source>; a later quiet run closes it."""
    first = ui.plan_actions([finding("review:cbi_kfi")], [], "me", RUN, True)
    assert ops(first)[0] == ("create", "review:cbi_kfi")
    later = ui.plan_actions([], [issue(8, "review:cbi_kfi")], "me", RUN, True)
    assert ops(later) == [("comment", "review:cbi_kfi"), ("close", "review:cbi_kfi")]


def test_check_failed_opens_then_closes():
    f = ui.check_failed_finding("install")
    actions = ui.plan_actions([f], [], "owner", RUN, False)
    assert ops(actions) == [("create", "check-failed"), ("comment", "check-failed")]
    assert actions[0]["labels"] == [ui.LABEL, ui.FAILURE_LABEL] and "install" in actions[0]["title"]
    assert ops(ui.plan_actions([], [issue(2, "check-failed")], "me", RUN, True)) == \
        [("comment", "check-failed"), ("close", "check-failed")]


def test_failure_streaks():
    def rep(**outcomes):
        return {"sources": [{"id": k, "outcome": v} for k, v in outcomes.items()]}
    newest_first = [rep(a="fetch_failed", b="fetch_failed"), {"sources": []},     # crashed run: no report rows
                    rep(a="fetch_failed", b="new_release"), rep(a="no_change", b="fetch_failed")]
    assert ui.failure_streaks(newest_first) == {"a": 2, "b": 1}
    assert ui.failure_streaks([]) == {}


def test_pending_streaks_count_runs_that_found_the_release_again():
    def rep(**outcomes):
        return {"sources": [{"id": k, "outcome": v} for k, v in outcomes.items()]}
    newest_first = [rep(a="new_release", b="parse_failed", c="new_release"), {"sources": []},
                    rep(a="new_release", b="new_release", c="no_change"), rep(a="no_change", b="new_release")]
    # a run that is waiting again (or still fails to parse) continues the streak; no_change ends it
    assert ui.pending_streaks(newest_first) == {"a": 2, "b": 3, "c": 1}


def test_issue_body_lists_details_and_expiry():
    f = finding("review:cbi_fx", details=({"file": "cbi/fx/x.xlsx", "sha256": "ab", "available_until": "2027-01-31"},))
    body = ui.issue_body(f, RUN)
    assert body.splitlines()[0].startswith("<!-- update-check id=review:cbi_fx fp=")
    assert "cbi/fx/x.xlsx" in body and "until 2027-01-31" in body and RUN["url"] in body


# --- client: labels, apply, previous reports (items 9-10) ------------------------------------

class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    """Records requests; `script` maps (method, path-prefix) to a body, an HTTP code, or a callable."""

    def __init__(self, script):
        self.script, self.calls = script, []

    def __call__(self, req, timeout=None):
        path = req.full_url.replace(ui.API, "")
        self.calls.append((req.get_method(), path, req.data, dict(req.header_items())))
        for (method, prefix), result in self.script.items():
            if req.get_method() == method and path.startswith(prefix):
                if callable(result):
                    result = result(req)
                if isinstance(result, int):
                    raise urllib.error.HTTPError(req.full_url, result, "err", {}, io.BytesIO(b""))
                return FakeResp(result if isinstance(result, bytes) else json.dumps(result).encode())
        raise AssertionError(f"unexpected request {req.get_method()} {path}")


def test_labels_are_created_and_existing_ones_are_fine():
    opener = FakeOpener({("POST", "/repos/o/r/labels"): 422})
    ui.GitHub("tok", "o/r", opener=opener).ensure_labels()
    assert [c[1] for c in opener.calls] == ["/repos/o/r/labels"] * 2


def test_apply_runs_actions_in_order_and_never_leaks_the_token():
    opener = FakeOpener({("POST", "/repos/o/r/issues/"): {"id": 1}, ("POST", "/repos/o/r/issues"): {"number": 41},
                         ("PATCH", "/repos/o/r/issues/"): {}})
    actions = ui.plan_actions([finding("fetch_failed:wb_oda")], [issue(4, "gate:t")], "me", RUN, True)
    errors = ui.GitHub("s3cr3t-token", "o/r", opener=opener).apply(actions)
    assert errors == []
    assert [(m, p) for m, p, _, _ in opener.calls] == [
        ("POST", "/repos/o/r/issues"), ("POST", "/repos/o/r/issues/41/comments"),
        ("POST", "/repos/o/r/issues/4/comments"), ("PATCH", "/repos/o/r/issues/4")]
    assert all(b"s3cr3t-token" not in (data or b"") for _, _, data, _ in opener.calls)


def test_server_errors_are_retried():
    attempts = []

    def flaky(req):
        attempts.append(1)
        return 503 if len(attempts) < 3 else {"number": 1}
    opener = FakeOpener({("POST", "/repos/o/r/issues"): flaky})
    gh = ui.GitHub("t", "o/r", opener=opener, sleep=lambda s: None)
    assert gh.request("POST", "/repos/o/r/issues", {}) == {"number": 1} and len(attempts) == 3


# --- network failures that are not HTTP errors (a read timeout, a reset connection) ----------

def _raising_then(exc, result, failures=1):
    attempts = []

    def run(req):
        attempts.append(1)
        if len(attempts) <= failures:
            raise exc
        return result
    run.attempts = attempts
    return run


@pytest.mark.parametrize("exc", [TimeoutError("The read operation timed out"), ConnectionResetError("reset"),
                                 __import__("http.client").client.IncompleteRead(b"x")],
                         ids=["read_timeout", "connection_reset", "incomplete_read"])
def test_failures_while_reading_the_body_are_retried(exc):
    flaky = _raising_then(exc, {"number": 1})
    gh = ui.GitHub("t", "o/r", opener=FakeOpener({("GET", "/x"): flaky}), sleep=lambda s: None)
    assert gh.request("GET", "/x") == {"number": 1} and len(flaky.attempts) == 2


def test_a_persistent_read_timeout_gives_up_after_three_attempts():
    flaky = _raising_then(TimeoutError("timed out"), {}, failures=99)
    gh = ui.GitHub("t", "o/r", opener=FakeOpener({("GET", "/x"): flaky}), sleep=lambda s: None)
    with pytest.raises(TimeoutError):
        gh.request("GET", "/x")
    assert len(flaky.attempts) == 3


def _http_error(code, headers):
    return urllib.error.HTTPError("https://api.github.com/x", code, "err", headers, io.BytesIO(b""))


def test_rate_limited_403_is_retried_after_the_advised_wait():
    waits = []
    flaky = _raising_then(_http_error(403, {"Retry-After": "7"}), {"ok": True})
    gh = ui.GitHub("t", "o/r", opener=FakeOpener({("GET", "/x"): flaky}), sleep=waits.append)
    assert gh.request("GET", "/x") == {"ok": True} and waits == [7]


def test_exhausted_rate_limit_403_is_retried():
    flaky = _raising_then(_http_error(403, {"X-RateLimit-Remaining": "0"}), {"ok": True})
    gh = ui.GitHub("t", "o/r", opener=FakeOpener({("GET", "/x"): flaky}), sleep=lambda s: None)
    assert gh.request("GET", "/x") == {"ok": True}


def test_a_permission_403_is_not_retried():
    flaky = _raising_then(_http_error(403, {"X-RateLimit-Remaining": "4000"}), {}, failures=99)
    gh = ui.GitHub("t", "o/r", opener=FakeOpener({("GET", "/x"): flaky}), sleep=lambda s: None)
    with pytest.raises(urllib.error.HTTPError):
        gh.request("GET", "/x")
    assert len(flaky.attempts) == 1


def test_apply_reports_a_timeout_and_carries_on():
    opener = FakeOpener({("POST", "/repos/o/r/issues/4/comments"): {"id": 1}, ("PATCH", "/repos/o/r/issues/4"): {},
                         ("POST", "/repos/o/r/issues"): _raising_then(TimeoutError("t"), {"number": 5}, failures=99)})
    actions = ui.plan_actions([finding("fetch_failed:wb_oda")], [issue(4, "gate:t")], "me", RUN, True)
    errors = ui.GitHub("t", "o/r", opener=opener, sleep=lambda s: None).apply(actions)
    assert any("create fetch_failed:wb_oda: TimeoutError" in e for e in errors)
    assert any("comment fetch_failed:wb_oda: skipped" in e for e in errors)  # no comment on an issue that was not created
    assert not any("None" in c[1] for c in opener.calls)
    assert any(c[1] == "/repos/o/r/issues/4/comments" for c in opener.calls)  # the later action still ran


def test_streaks_lookup_never_blocks_the_check(tmp_path, monkeypatch):
    """The docstring promise: any failure while reading earlier runs writes {} and exits 0."""
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")

    def boom(self, run_id, n=8):
        raise TimeoutError("The read operation timed out")
    monkeypatch.setattr(ui.GitHub, "previous_reports", boom)
    out = tmp_path / "s.json"
    assert ui.main(["--streaks-out", str(out), "--run-id", "9"]) == 0
    assert json.loads(out.read_text()) == {"failures": {}, "pending": {}}


def _zip(report):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("report.json", json.dumps(report))
    return buf.getvalue()


def test_previous_reports_skip_the_current_run_and_missing_artifacts():
    runs = {"workflow_runs": [{"id": 9}, {"id": 8}, {"id": 7}, {"id": 6}]}
    arts = {8: {"artifacts": [{"name": ui.ARTIFACT_NAME, "expired": False, "archive_download_url": f"{ui.API}/dl/8"}]},
            7: {"artifacts": []},
            6: {"artifacts": [{"name": ui.ARTIFACT_NAME, "expired": False, "archive_download_url": f"{ui.API}/dl/6"}]}}
    script = {("GET", "/repos/o/r/actions/workflows/"): runs,
              ("GET", "/dl/8"): _zip({"sources": [{"id": "a", "outcome": "fetch_failed"}]}),
              ("GET", "/dl/6"): _zip({"sources": [{"id": "a", "outcome": "fetch_failed"}]})}
    script.update({("GET", f"/repos/o/r/actions/runs/{k}/artifacts"): v for k, v in arts.items()})
    reports = ui.GitHub("t", "o/r", opener=FakeOpener(script)).previous_reports("9")
    assert len(reports) == 2 and ui.failure_streaks(reports) == {"a": 2}


# --- CLI ------------------------------------------------------------------------------------

def test_dry_run_on_a_report(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    (tmp_path / "report.json").write_text(json.dumps({
        "run_date": "2026-11-02", "maintainer": "me",
        "findings": [finding("routine:fred_brent", kind="routine"), finding("review:cbi_kfi")]}), encoding="utf-8")
    assert ui.main(["--report", str(tmp_path), "--run-url", RUN["url"], "--run-id", "9", "--dry-run"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert [(a["op"], a["identity"]) for a in printed] == [("create", "review:cbi_kfi"), ("comment", "review:cbi_kfi")]


def test_missing_report_means_check_failed(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert ui.main(["--report", str(tmp_path), "--run-id", "9", "--maintainer-fallback", "owner",
                    "--check-failed", "install", "--dry-run"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed[0]["identity"] == "check-failed" and printed[1]["body"].startswith("@owner new:")


LOG = "\n".join(f"line {i}" for i in range(1, 101)) + "\nTraceback (most recent call last):\nValueError: boom"


def test_check_failed_issue_shows_the_end_of_the_log():
    f = ui.check_failed_finding("update check", LOG)
    body = ui.issue_body(f, RUN)
    assert "```text" in body and "ValueError: boom" in body and "line 100" in body
    assert "line 61" not in body  # only the last 40 lines
    assert f["fingerprint"] == ui.check_failed_finding("update check")["fingerprint"]  # the log is not identity


def test_log_tail_hides_secrets_and_cannot_break_out_of_its_fence():
    env = {"GITHUB_TOKEN": "ghs_secret123", "HC_PING_URL": "https://hc-ping.com/abc-def"}
    tail = ui.log_tail("curl https://hc-ping.com/abc-def failed\nBearer ghs_secret123\n```\n@someone look", env)
    assert "ghs_secret123" not in tail and "hc-ping.com/abc-def" not in tail and "***" in tail
    assert "```" not in tail


def test_log_tail_is_capped():
    assert len(ui.log_tail("x" * 50_000, {})) <= ui.LOG_TAIL_CHARS


def test_cli_reads_the_log_for_a_check_failed_issue(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    log = tmp_path / "check.log"
    log.write_text(LOG, encoding="utf-8")
    assert ui.main(["--report", str(tmp_path), "--run-id", "9", "--maintainer-fallback", "owner",
                    "--check-failed", "update check", "--log", str(log), "--dry-run"]) == 0
    created = json.loads(capsys.readouterr().out)[0]
    assert created["op"] == "create" and "ValueError: boom" in created["body"]


def test_cli_without_a_log_file_still_opens_the_issue(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert ui.main(["--report", str(tmp_path), "--run-id", "9", "--maintainer-fallback", "owner",
                    "--check-failed", "install", "--log", str(tmp_path / "missing.log"), "--dry-run"]) == 0
    created = json.loads(capsys.readouterr().out)[0]
    assert created["op"] == "create" and "```" not in created["body"]


def test_streaks_out_without_api_writes_empty(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    out = tmp_path / "s.json"
    assert ui.main(["--streaks-out", str(out), "--run-id", "9"]) == 0
    assert json.loads(out.read_text()) == {"failures": {}, "pending": {}}


def test_runs_without_requests_or_yaml():
    """Item 11: the reporter works on a bare Python where the package install failed."""
    code = ("import sys; sys.modules['requests'] = None; sys.modules['yaml'] = None; "
            "sys.path.insert(0, 'pipeline'); import update_issues as ui; "
            "f = ui.check_failed_finding('install'); "
            "print(len(ui.plan_actions([f], [], 'o', {'url': 'u', 'date': 'd'}, False)))")
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "2"


def test_step_summary_carries_the_routine_section(tmp_path, monkeypatch):
    """Routine updates reach the run's summary page, never an issue."""
    import update_check
    md = ("# Data update check\n\n## Anomalies\n\nNone.\n\n## Routine updates\n\n"
          "Downloads in this run's artifact are available until 2027-02-13.\n\n"
          "- **fred_brent: new data**\n  - file: fred/x.csv, sha256: ab\n"
          "- **wb_oda: download failed 1 of 2 run(s)**\n\n## Sources\n\n| x |\n")
    (tmp_path / "report.md").write_text(md, encoding="utf-8")
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    ui.write_summary(tmp_path, [], [finding("routine:fred_brent", kind="routine")], RUN)
    text = summary.read_text(encoding="utf-8")
    assert "0 anomaly(ies); issue actions: none" in text
    assert "fred_brent: new data" in text and "sha256: ab" in text and "2027-02-13" in text
    assert "failed 1 of 2 run(s)" in text and "## Sources" not in text
    assert update_check.render_findings([], "routine") == ["None."]
