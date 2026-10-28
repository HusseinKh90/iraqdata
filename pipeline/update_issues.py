"""
pipeline.update_issues
======================
Turns the weekly update check's findings into GitHub issues, and reads earlier runs' failure
counts.

    python pipeline/update_issues.py --streaks-out FILE --run-id ID
    python pipeline/update_issues.py --report DIR --run-url URL --run-id ID --maintainer-fallback LOGIN
                                     [--check-failed STEP] [--log FILE] [--dry-run]

The first form runs before the check: it reads the reports of the last runs of the workflow and
writes each source's consecutive fetch failures as JSON, for `update_check.py --streaks`. On any
API error it writes `{}`, so the check is never blocked.

The second form runs after the check, whatever happened (`if: always()`). There is one issue per
anomaly identity (`fetch_failed:<source>`, `review:<source>`, `revised:<table>`, ...). Issues are
found by a hidden marker in their body, never by title. The maintainer is @-mentioned when an
issue is created, reopened or its details change (except a `review:` issue, which mentions only
when it opens). An open issue whose anomaly is gone from a successful run is closed with a comment.
With --check-failed, or without report.json, only the `check-failed` issue is opened, and nothing
is closed.

Standard library only (urllib, json, zipfile): it must run on the bare runner Python even when
installing the package failed. The token comes from GITHUB_TOKEN and is never printed.
"""

import argparse
import hashlib
import http.client
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

LABEL = "data-update-check"
FAILURE_LABEL = "update-check-failure"
LABELS = {
    LABEL: ("0e8a16", "Opened and closed by the weekly update check"),
    FAILURE_LABEL: ("b60205", "The weekly update check itself failed"),
}
WORKFLOW_FILE = "update_check.yml"
ARTIFACT_NAME = "update-check-report"
CHECK_FAILED = "check-failed"
MARKER = re.compile(r"<!-- update-check id=(?P<id>\S+) fp=(?P<fp>[0-9a-f]+) -->")
API = "https://api.github.com"
RETRY_DELAYS_S = (2, 4)    # 3 attempts in total on 429, 5xx, rate-limited 403 and network errors (as downloads.py)
RETRY_AFTER_CAP_S = 60
MAX_ROWS = 50
LOG_TAIL_LINES = 40
LOG_TAIL_CHARS = 6000
REDACT_ENV = ("GITHUB_TOKEN", "HC_PING_URL", "HC_ALERT_URL")  # values that must never reach an issue


# ===================================================================== pure functions


def fingerprint(details: List[dict]) -> str:
    """The same canonical hash as update_check.fingerprint: independent of row order."""
    rows = sorted(json.dumps(r, sort_keys=True, ensure_ascii=False, default=str) for r in details)
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


def outcome_streaks(previous_reports: List[dict], outcomes: Sequence[str]) -> Dict[str, int]:
    """
    Consecutive earlier runs, newest first, in which a source's outcome was one of `outcomes`. A
    report that lacks a source (or a run without a report) does not break that source's streak;
    any other outcome ends it.
    """
    streaks: Dict[str, int] = {}
    ended: set = set()
    for report in previous_reports:
        for src in report.get("sources", []):
            sid = src.get("id")
            if sid in ended:
                continue
            if src.get("outcome") in outcomes:
                streaks[sid] = streaks.get(sid, 0) + 1
            else:
                streaks.setdefault(sid, 0)
                ended.add(sid)
    return {k: v for k, v in streaks.items() if v}


def failure_streaks(previous_reports: List[dict]) -> Dict[str, int]:
    """Consecutive fetch_failed outcomes per source in earlier reports."""
    return outcome_streaks(previous_reports, ("fetch_failed",))


def pending_streaks(previous_reports: List[dict]) -> Dict[str, int]:
    """Consecutive earlier runs in which a downloaded release was waiting to be applied (it was found again each week)."""
    return outcome_streaks(previous_reports, ("new_release", "parse_failed"))


def log_tail(text: str, environ=None) -> str:
    """The last lines of a log for an issue: secrets from the environment hidden, fences neutralised, capped."""
    environ = os.environ if environ is None else environ
    for name in REDACT_ENV:
        value = environ.get(name)
        if value:
            text = text.replace(value, "***")
    tail = "\n".join(text.rstrip().splitlines()[-LOG_TAIL_LINES:])[-LOG_TAIL_CHARS:]
    return re.sub(r"`{3,}", "'''", tail)


def check_failed_finding(step: str, log: str = "") -> dict:
    """The check-failed anomaly. The log tail is shown in the issue but is not part of its fingerprint."""
    details = [{"step": step}]
    finding = {"kind": "anomaly", "identity": CHECK_FAILED, "title": f"the update check failed at step '{step}'",
               "details": details, "fingerprint": fingerprint(details), "sources": []}
    if log.strip():
        finding["log"] = log_tail(log)
    return finding


def parse_marker(body: Optional[str]):
    m = MARKER.search(body or "")
    return (m.group("id"), m.group("fp")) if m else None


def _cell(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def issue_body(finding: dict, run: dict) -> str:
    rows = finding["details"]
    keys = sorted({k for r in rows for k in r}, key=lambda k: (k != "change", k))
    lines = [f"<!-- update-check id={finding['identity']} fp={finding['fingerprint']} -->",
             f"## {finding['title']}", ""]
    if finding["sources"]:
        lines += ["Sources: " + ", ".join(f"`{s}`" for s in finding["sources"]), ""]
    if rows:
        lines += ["| " + " | ".join(keys) + " |", "|" + "---|" * len(keys)]
        lines += ["| " + " | ".join(_cell(r.get(k, "")) for k in keys) + " |" for r in rows[:MAX_ROWS]]
        if len(rows) > MAX_ROWS:
            lines.append(f"\n_{len(rows) - MAX_ROWS} more row(s) in the run's report.json._")
        lines.append("")
    if finding.get("log"):
        lines += ["Last lines of the log:", "", "```text", finding["log"], "```", ""]
    lines.append(f"Last seen in run {run['url']} on {run['date']}.")
    expires = sorted({r["available_until"] for r in rows if r.get("available_until")})
    if expires:
        lines.append(f"The downloaded files are in that run's artifact until {expires[-1]}; archive the exact "
                     "bytes (check each SHA-256) before then, as in docs/collecting_data_doc.md section 5.")
    lines += ["", "_Opened, updated and closed by the weekly update check (pipeline/update_issues.py)._"]
    return "\n".join(lines)


def plan_actions(findings: List[dict], existing: List[dict], maintainer: str, run: dict,
                 report_ok: bool) -> List[dict]:
    """
    The issue actions for this run: create, edit, comment, reopen, close. Each
    action carries the identity; `issue` is the existing issue number (None for a new issue).
    """
    anomalies = {f["identity"]: f for f in findings if f["kind"] == "anomaly"}
    issues: Dict[str, dict] = {}
    for issue in sorted(existing, key=lambda i: i["number"]):
        marker = parse_marker(issue.get("body"))
        if marker and marker[0] not in issues:
            issues[marker[0]] = issue
    mention = f"@{maintainer}"
    actions: List[dict] = []
    for identity in sorted(anomalies):
        f = anomalies[identity]
        labels = [LABEL] + ([FAILURE_LABEL] if identity == CHECK_FAILED else [])
        title = f"Update check: {f['title']}"
        body = issue_body(f, run)
        issue = issues.get(identity)
        if issue is None:
            actions += [{"op": "create", "identity": identity, "issue": None, "title": title, "body": body,
                         "labels": labels},
                        {"op": "comment", "identity": identity, "issue": None,
                         "body": f"{mention} new: {f['title']} ({run['url']})"}]
        elif issue["state"] == "closed":
            actions += [{"op": "reopen", "identity": identity, "issue": issue["number"]},
                        {"op": "edit", "identity": identity, "issue": issue["number"], "title": title, "body": body},
                        {"op": "comment", "identity": identity, "issue": issue["number"],
                         "body": f"{mention} back: {f['title']} ({run['url']})"}]
        else:
            actions.append({"op": "edit", "identity": identity, "issue": issue["number"], "title": title, "body": body})
            changed = parse_marker(issue.get("body"))[1] != f["fingerprint"]
            # A review issue mentions only when it opens; newer files just update it
            if changed and not identity.startswith("review:"):
                actions.append({"op": "comment", "identity": identity, "issue": issue["number"],
                                "body": f"{mention} changed: {f['title']} ({run['url']})"})
    if report_ok:
        for identity, issue in sorted(issues.items()):
            if issue["state"] == "open" and identity not in anomalies:
                actions += [{"op": "comment", "identity": identity, "issue": issue["number"],
                             "body": f"Resolved: not found in run {run['url']} on {run['date']}. Closing."},
                            {"op": "close", "identity": identity, "issue": issue["number"]}]
    return actions


# ===================================================================== GitHub client


def _retryable(err: urllib.error.HTTPError) -> bool:
    """429 and 5xx, and a 403 that is GitHub's rate limit (a Retry-After header, or no calls left)."""
    if err.code == 429 or err.code >= 500:
        return True
    headers = err.headers or {}
    return err.code == 403 and (bool(headers.get("Retry-After")) or headers.get("X-RateLimit-Remaining") == "0")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Artifact downloads redirect to signed storage URLs that must not get the GitHub token."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHub:
    def __init__(self, token: str, repo: str, api: str = API,
                 opener: Optional[Callable] = None, sleep: Callable[[float], None] = time.sleep):
        self.token, self.repo, self.api = token, repo, api
        self._open = opener or urllib.request.build_opener(_NoRedirect).open
        self._sleep = sleep

    def request(self, method: str, path: str, data: Optional[dict] = None, raw: bool = False):
        url = path if path.startswith("http") else f"{self.api}{path}"
        body = json.dumps(data).encode("utf-8") if data is not None else None
        for attempt in range(len(RETRY_DELAYS_S) + 1):
            req = urllib.request.Request(url, data=body, method=method, headers={
                "Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "iraqdata-update-check",
                **({"Content-Type": "application/json"} if body is not None else {})})
            try:
                with self._open(req, timeout=30) as resp:
                    content = resp.read()
                return content if raw else (json.loads(content) if content else None)
            except urllib.error.HTTPError as err:  # before OSError: HTTPError is a URLError is an OSError
                if not _retryable(err) or attempt == len(RETRY_DELAYS_S):
                    raise
                wait = RETRY_DELAYS_S[attempt]
                if err.headers and str(err.headers.get("Retry-After", "")).isdigit():
                    wait = min(int(err.headers["Retry-After"]), RETRY_AFTER_CAP_S)
                self._sleep(wait)
            except (OSError, http.client.HTTPException):
                # a URLError, but also what urllib does not wrap while reading the body: a read
                # timeout, a reset connection, a short read
                if attempt == len(RETRY_DELAYS_S):
                    raise
                self._sleep(RETRY_DELAYS_S[attempt])

    def ensure_labels(self) -> None:
        for name, (color, description) in LABELS.items():
            try:
                self.request("POST", f"/repos/{self.repo}/labels",
                             {"name": name, "color": color, "description": description})
            except urllib.error.HTTPError as err:
                if err.code != 422:  # 422: the label already exists
                    raise

    def list_issues(self) -> List[dict]:
        issues, page = [], 1
        while True:
            batch = self.request("GET", f"/repos/{self.repo}/issues?labels={LABEL}&state=all&per_page=100&page={page}")
            issues += [i for i in batch if "pull_request" not in i]
            if len(batch) < 100:
                return issues
            page += 1

    def _download(self, url: str) -> bytes:
        """Follow the artifact's redirect by hand, without the token."""
        try:
            return self.request("GET", url, raw=True)
        except urllib.error.HTTPError as err:
            if err.code in (301, 302, 303, 307, 308) and err.headers.get("Location"):
                with urllib.request.urlopen(err.headers["Location"], timeout=60) as resp:
                    return resp.read()
            raise

    def previous_reports(self, current_run_id: str, n: int = 8) -> List[dict]:
        """report.json of the last n earlier runs of the workflow, newest first; runs without one are skipped."""
        runs = self.request("GET", f"/repos/{self.repo}/actions/workflows/{WORKFLOW_FILE}/runs?per_page={n + 1}")
        reports = []
        for run in runs.get("workflow_runs", []):
            if str(run["id"]) == str(current_run_id):
                continue
            if len(reports) >= n:
                break
            try:
                arts = self.request("GET", f"/repos/{self.repo}/actions/runs/{run['id']}/artifacts")
                art = next((a for a in arts.get("artifacts", [])
                            if a["name"] == ARTIFACT_NAME and not a.get("expired")), None)
                if art is None:
                    continue
                data = self._download(art["archive_download_url"])
                with zipfile.ZipFile(io.BytesIO(data)) as zf:
                    reports.append(json.loads(zf.read("report.json")))
            except (OSError, http.client.HTTPException, KeyError, zipfile.BadZipFile, ValueError):
                continue  # one unreadable earlier run does not stop the lookup
        return reports

    def apply(self, actions: List[dict]) -> List[str]:
        """Apply the actions in order; returns the error messages (empty when all succeeded)."""
        numbers: Dict[str, int] = {}
        errors = []
        for a in actions:
            number = a["issue"] or numbers.get(a["identity"])
            if number is None and a["op"] != "create":
                errors.append(f"{a['op']} {a['identity']}: skipped, the issue was not created")
                continue
            try:
                if a["op"] == "create":
                    created = self.request("POST", f"/repos/{self.repo}/issues",
                                           {"title": a["title"], "body": a["body"], "labels": a["labels"]})
                    numbers[a["identity"]] = created["number"]
                elif a["op"] == "comment":
                    self.request("POST", f"/repos/{self.repo}/issues/{number}/comments", {"body": a["body"]})
                elif a["op"] == "edit":
                    self.request("PATCH", f"/repos/{self.repo}/issues/{number}", {"title": a["title"], "body": a["body"]})
                elif a["op"] == "reopen":
                    self.request("PATCH", f"/repos/{self.repo}/issues/{number}", {"state": "open"})
                elif a["op"] == "close":
                    self.request("PATCH", f"/repos/{self.repo}/issues/{number}",
                                 {"state": "closed", "state_reason": "completed"})
            except (OSError, http.client.HTTPException, KeyError, ValueError) as exc:
                errors.append(f"{a['op']} {a['identity']}: {type(exc).__name__}: {exc}")
        return errors


# ===================================================================== CLI


def _section(markdown: str, heading: str) -> str:
    """One `## heading` section of report.md, up to the next `## `."""
    m = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", markdown, re.S | re.M)
    return f"## {heading}\n{m.group(1)}" if m else ""


def write_summary(report_dir: Path, actions: List[dict], findings: List[dict], run: dict) -> None:
    """The routine updates (and what happened to issues) on the run's summary page."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    md_path = Path(report_dir) / "report.md"
    md = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
    anomalies = [f for f in findings if f["kind"] == "anomaly"]
    acted = sorted({(a["op"], a["identity"]) for a in actions if a["op"] != "comment"})
    lines = [f"# Update check, {run['date']}", "",
             f"{len(anomalies)} anomaly(ies); issue actions: "
             + (", ".join(f"{op} `{ident}`" for op, ident in acted) or "none"), "",
             _section(md, "Routine updates") or "No report was produced; see the check-failed issue."]
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _client(dry_run: bool) -> Optional[GitHub]:
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if dry_run and not (token and repo):
        return None
    if not (token and repo):
        raise SystemExit("GITHUB_TOKEN and GITHUB_REPOSITORY must be set (or use --dry-run)")
    return GitHub(token, repo)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Reconcile update-check issues.")
    parser.add_argument("--streaks-out", type=Path, help="Write earlier consecutive fetch failures as JSON, then stop.")
    parser.add_argument("--report", type=Path, help="The check's report directory (report.json may be missing).")
    parser.add_argument("--run-url", default="")
    parser.add_argument("--run-id", default="0")
    parser.add_argument("--run-date", default=time.strftime("%Y-%m-%d", time.gmtime()))
    parser.add_argument("--maintainer-fallback", default="", help="Used when there is no report (the repository owner).")
    parser.add_argument("--check-failed", metavar="STEP", help="The step that failed; opens the check-failed issue.")
    parser.add_argument("--log", type=Path, help="The check's log; its last lines go into the check-failed issue.")
    parser.add_argument("--dry-run", action="store_true", help="Print the actions as JSON; call no write API.")
    args = parser.parse_args(argv)

    if args.streaks_out:
        try:
            client = _client(dry_run=False)
            earlier = client.previous_reports(args.run_id)
            streaks = {"failures": failure_streaks(earlier), "pending": pending_streaks(earlier)}
        except (SystemExit, Exception) as exc:  # whatever went wrong, the check must still run
            print(f"WARNING: could not read earlier runs ({type(exc).__name__}); counts start at 1")
            streaks = {"failures": {}, "pending": {}}
        args.streaks_out.write_text(json.dumps(streaks, sort_keys=True), encoding="utf-8")
        print(f"failure streaks: {streaks['failures'] or 'none'}; waiting releases: {streaks['pending'] or 'none'}")
        return 0

    if args.report is None:
        parser.error("--report is required unless --streaks-out is given")
    report_path = args.report / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else None
    findings = list(report["findings"]) if report else []
    report_ok = report is not None and not args.check_failed
    if not report_ok:
        log = args.log.read_text(encoding="utf-8", errors="replace") if args.log and args.log.is_file() else ""
        findings.append(check_failed_finding(args.check_failed or "update check (no report.json)", log))
    maintainer = (report or {}).get("maintainer") or args.maintainer_fallback
    if not maintainer:
        parser.error("no maintainer: report.json has none and --maintainer-fallback is empty")
    run = {"url": args.run_url, "id": args.run_id, "date": (report or {}).get("run_date", args.run_date)}

    client = _client(args.dry_run)
    existing = client.list_issues() if client else []
    actions = plan_actions(findings, existing, maintainer, run, report_ok)
    if args.dry_run:
        print(json.dumps(actions, indent=2, ensure_ascii=False))
        return 0
    client.ensure_labels()
    errors = client.apply(actions)
    write_summary(args.report, actions, findings, run)
    for a in actions:
        print(f"{a['op']}: {a['identity']}" + (f" (#{a['issue']})" if a["issue"] else ""))
    for e in errors:
        print(f"ERROR: {e}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
