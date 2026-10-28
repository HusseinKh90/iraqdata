"""
tests.test_update_check
=======================
The weekly update check, end to end and offline. Fetchers are replaced by fakes that write into the check's scratch workspace.
"""

import hashlib
import json
import subprocess

import pandas as pd
import pytest

import update_check
from conftest import REPO_ROOT, hash_tree
from fixtures import rehearsal

pytestmark = pytest.mark.usefixtures("no_network")

TODAY = "2026-11-15"
# Cbi_fx is fetched automatically, and github_fx (the parallel rate from 2023) is new
MANUAL = {"fiscal_seed", "cosit", "opec_momr"}
AUTO = {"bis_lbs", "cbi_bop", "cbi_kfi", "cbi_bulletin", "wb_oda", "fred_brent", "eia_intl", "cbi_fx", "github_fx"}


def unchanged(raw, today, manifest):
    return None


def fred_next_release(raw, today, manifest):
    rehearsal.oil_daily(raw, None, today.isoformat())
    return [raw / "fred" / f"DCOILBRENTEU_{today.isoformat()}.csv"]


def wb_broken(raw, today, manifest):
    raise RuntimeError("TLS verification failed")


def kfi_corrupt(raw, today, manifest):
    path = raw / "cbi" / f"cbi_key_financial_indicators_{today.isoformat()}.xlsx"
    path.write_bytes(b"not a workbook" * 100)
    return [path]


def _repo_state():
    return hash_tree(REPO_ROOT / "pipeline", REPO_ROOT / "release", REPO_ROOT / ".github")


def _run(tmp_path, monkeypatch, fakes):
    monkeypatch.setattr(update_check, "FETCHERS", fakes)
    out = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    calls = []
    real_run, real_popen = subprocess.run, subprocess.Popen

    def record_run(*args, **kwargs):
        calls.append(args)
        return real_run(*args, **kwargs)

    def record_popen(*args, **kwargs):
        calls.append(args)
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", record_run)
    monkeypatch.setattr(subprocess, "Popen", record_popen)
    code = update_check.main(["--workdir", str(tmp_path / "work"), "--report-dir", str(tmp_path / "report"),
                              "--today", TODAY])
    report = json.loads((tmp_path / "report" / "report.json").read_text(encoding="utf-8"))
    return code, report, out.read_text(encoding="utf-8"), calls


@pytest.fixture(scope="module")
def mixed(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("update_check")
    mp = pytest.MonkeyPatch()
    before = _repo_state()
    try:
        fakes = {s: unchanged for s in AUTO}
        fakes.update(fred_brent=fred_next_release, wb_oda=wb_broken, cbi_kfi=kfi_corrupt)
        result = _run(tmp, mp, fakes)
    finally:
        mp.undo()
    return tmp, before, result


def outcomes(report):
    return {s["id"]: s for s in report["sources"]}


def test_every_source_reported_once(mixed):
    _, _, (code, report, _, _) = mixed
    assert code == 0
    ids = [s["id"] for s in report["sources"]]
    assert sorted(ids) == sorted(AUTO | MANUAL) and len(ids) == 12


def test_new_release_lists_changes_and_keeps_the_download(mixed):
    tmp, _, (_, report, _, _) = mixed
    fred = outcomes(report)["fred_brent"]
    assert fred["outcome"] == "new_release"
    (entry,) = fred["files"]
    assert entry["path"] == "fred/DCOILBRENTEU_2026-11-15.csv"
    download = tmp / "report" / "downloads" / entry["path"]
    assert hashlib.sha256(download.read_bytes()).hexdigest() == entry["sha256"]
    oil = report["changes"]["oil_daily"]
    assert len(oil["added"]) == 1
    assert [(r["series_id"], r["date"]) for r in oil["revised"]] == [("oil_price_brent", "2026-10-01")]


def test_unchanged_failed_and_manual_sources(mixed):
    tmp, _, (_, report, _, _) = mixed
    got = outcomes(report)
    assert got["bis_lbs"]["outcome"] == "no_change"
    assert not (tmp / "report" / "downloads" / "bis").exists()
    assert got["wb_oda"]["outcome"] == "fetch_failed" and "TLS" in got["wb_oda"]["detail"]
    assert got["cbi_kfi"]["outcome"] == "parse_failed"
    assert got["cbi_kfi"]["detail"].startswith(("cbi_cpi:", "cbi_money_banking:"))
    for source in MANUAL:
        assert got[source]["outcome"] == "manual" and got[source]["detail"]
    assert got["cosit"]["next_due"] == "2027-03-27"   # 2026-Q1 is the latest quarter: 2026-Q2 ends 06-30, plus 270 days


def test_report_files_and_review_flag(mixed):
    tmp, _, (_, report, github_output, _) = mixed
    md = (tmp / "report" / "report.md").read_text(encoding="utf-8")
    assert "## Gatekeeper" in md and "## Sources" in md and "## Freshness" in md
    assert report["needs_review"] is True
    assert github_output.strip() == "needs_review=true"
    # At 2026-11-15 the bank rates (due 2026-10-29) and Brent (latest 2026-10-21 after the fake
    # release, due 2026-10-29) have joined the two exchange-rate series
    overdue = sorted(f["series_id"] for f in report["freshness"] if f["state"] == "overdue")
    assert overdue == ["fx.official", "money.bank_deposit_rate", "money.bank_lending_rate",
                       "oil_price_brent", "parallel_rate_iraq"]


def test_repository_untouched_and_no_git(mixed):
    _, before, (_, _, _, calls) = mixed
    assert _repo_state() == before
    assert not any("git" in " ".join(map(str, call[0] if call and isinstance(call[0], (list, tuple)) else call))
                   for call in calls)


def test_quiet_week_still_flags_overdue_series(tmp_path, monkeypatch):
    code, report, github_output, _ = _run(tmp_path, monkeypatch, {s: unchanged for s in AUTO})
    assert code == 0
    assert {s["outcome"] for s in report["sources"]} == {"no_change", "manual"}
    assert report["changes"] == {}
    assert report["needs_review"] is True  # at 2026-11-15 several series are overdue (see test_report_files_and_review_flag)
    assert github_output.strip() == "needs_review=true"


def test_workdir_must_be_new_or_empty(tmp_path):
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "x").write_text("x")
    with pytest.raises(FileExistsError):
        update_check.main(["--workdir", str(tmp_path / "work"), "--report-dir", str(tmp_path / "r"),
                           "--today", TODAY])


# ---------------------------------------------------------------------- exchange-rate sources


def github_fx_next_day(raw, today, manifest):
    """The next daily_fx.csv: one more trading day (written as the fetcher would)."""
    import csv

    import downloads

    src = downloads.latest_version(raw / "github" / "daily_fx.csv")
    with open(src, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fields, rows = reader.fieldnames, list(reader)
    import pandas as pd
    new_day = (pd.Timestamp(rows[-1]["date"]) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    rows.append(dict(rows[-1], date=new_day, baghdad_close="1600.0"))
    target = raw / "github" / f"daily_fx_{today.isoformat()}.csv"
    with open(target, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return [target]


def test_new_parallel_rate_day_is_reported(tmp_path, monkeypatch):
    fakes = {s: unchanged for s in AUTO}
    fakes["github_fx"] = github_fx_next_day
    _, report, _, _ = _run(tmp_path, monkeypatch, fakes)
    assert outcomes(report)["github_fx"]["outcome"] == "new_release"
    added = report["changes"]["exchange_rates_daily"]["added"]
    assert [tuple(a)[0] for a in added] == ["parallel_rate_iraq"]


def test_cbi_fx_page_without_the_link_is_fetch_failed(tmp_path, monkeypatch):
    """The real fetch_cbi_fx against a page 144 without the workbook link."""
    import downloads
    import fetchers

    class Page:
        status_code, content = 200, b""
        text = '<a href="/up/file-9.xlsx">Gold prices</a>'

        def raise_for_status(self):
            pass

    monkeypatch.setattr(downloads, "polite_get", lambda url, **kw: Page())
    fakes = {s: unchanged for s in AUTO}
    fakes["cbi_fx"] = fetchers.fetch_cbi_fx
    _, report, _, _ = _run(tmp_path, monkeypatch, fakes)
    got = outcomes(report)["cbi_fx"]
    assert got["outcome"] == "fetch_failed" and "الدينار" in got["detail"]


# ---------------------------------------------------------------------- findings


def findings_by_id(report):
    return {f["identity"]: f for f in report["findings"]}


def test_findings_classify_the_mixed_run(mixed):
    """API new data is routine, a first fetch failure is routine below its
    threshold, a parse failure and overdue series are anomalies, grouped per source."""
    _, _, (_, report, _, _) = mixed
    f = findings_by_id(report)
    assert f["routine:fred_brent"]["kind"] == "routine"                     # kind: api, add-only
    assert f["routine:wb_oda"]["kind"] == "routine"                         # failed 1 of 2 runs
    assert outcomes(report)["wb_oda"]["failure_streak"] == 1
    assert outcomes(report)["wb_oda"]["failure_threshold"] == 2
    assert f["parse_failed:cbi_kfi"]["kind"] == "anomaly"
    overdue = {k for k in f if k.startswith("overdue:")}
    assert overdue == {"overdue:cbi_fx", "overdue:cbi_kfi", "overdue:fred_brent", "overdue:github_fx"}
    assert {r["series_id"] for r in f["overdue:cbi_kfi"]["details"]} == {"money.bank_deposit_rate",
                                                                       "money.bank_lending_rate"}
    assert report["needs_review"] is True
    assert report["maintainer"] == "HusseinKh90"
    assert report["artifact_expires"] == "2027-02-13"
    fred = f["routine:fred_brent"]["details"]
    assert any("sha256" in r and r["available_until"] == "2027-02-13" for r in fred)
    md = (mixed[0] / "report" / "report.md").read_text(encoding="utf-8")
    assert "## Anomalies" in md and "## Routine updates" in md and "available until 2027-02-13" in md


def test_failure_at_threshold_is_an_anomaly(tmp_path, monkeypatch):
    """The streak file from earlier runs pushes a second failure over the threshold."""
    streaks = tmp_path / "streaks.json"
    streaks.write_text(json.dumps({"wb_oda": 1}), encoding="utf-8")
    monkeypatch.setattr(update_check, "FETCHERS", {**{s: unchanged for s in AUTO}, "wb_oda": wb_broken})
    update_check.main(["--workdir", str(tmp_path / "w"), "--report-dir", str(tmp_path / "r"),
                       "--today", TODAY, "--streaks", str(streaks)])
    report = json.loads((tmp_path / "r" / "report.json").read_text(encoding="utf-8"))
    assert outcomes(report)["wb_oda"]["failure_streak"] == 2
    assert findings_by_id(report)["fetch_failed:wb_oda"]["kind"] == "anomaly"


def cbi_fx_same_bytes(raw, today, manifest):
    """A 'new' CBI FX workbook whose content is the archived one: parses, changes nothing."""
    import downloads
    src = downloads.latest_version(raw / "cbi" / "fx" / "cbi_fx_usd.xlsx")
    target = raw / "cbi" / "fx" / f"cbi_fx_usd_{today.isoformat()}.xlsx"
    target.write_bytes(src.read_bytes())
    return [target]


def test_spreadsheet_release_always_gets_a_review_issue(tmp_path, monkeypatch):
    """A spreadsheet source's new release is a review anomaly, even add-only."""
    code, report, _, _ = _run(tmp_path, monkeypatch, {**{s: unchanged for s in AUTO}, "cbi_fx": cbi_fx_same_bytes})
    f = findings_by_id(report)
    assert outcomes(report)["cbi_fx"]["outcome"] == "new_release"
    assert f["review:cbi_fx"]["kind"] == "anomaly"
    assert any(r.get("file", "").startswith("cbi/fx/") for r in f["review:cbi_fx"]["details"])


def test_revisions_and_gate_findings_group_per_table():
    schedule = {"sources": [{"id": "src", "parsers": ["cbi_cpi"], "kind": "api", "failure_threshold": 2}],
                "series": {}, "notify": {"github": "x"}}
    changes = {"prices_monthly": {"added": [], "missing": [], "withdrawn": [["cpi_core", "2009-01"]],
                                  "revised": [{"series_id": "cpi_core", "date": "2004-01", "old_value": 1.0,
                                               "new_value": 2.0, "old_flag": "A", "new_flag": "A"}]}}
    gate = {"by_table": {"prices_monthly": ["WARNING: jump"]}, "stale": ["money.m2 (2020-01): old"]}
    found = {f["identity"]: f for f in update_check.build_findings([], changes, gate, [], schedule, {}, "2027-01-01")}
    assert set(found) == {"revised:prices_monthly", "gate:prices_monthly", "gate:acknowledgements"}
    assert found["revised:prices_monthly"]["sources"] == ["src"]
    assert all(f["kind"] == "anomaly" for f in found.values())


def test_flag_updates_alone_raise_no_revision_anomaly():
    """A period leaving the provisional window changes its flag in place: routine, not a revision."""
    schedule = {"sources": [{"id": "src", "parsers": ["cbi_cpi"], "kind": "api", "failure_threshold": 2}],
                "series": {}, "notify": {"github": "x"}}
    changes = {"prices_monthly": {"added": [["cpi_core", "2026-09"]], "missing": [], "withdrawn": [], "revised": [],
                                  "flag_updated": [{"series_id": "cpi_core", "date": "2025-09",
                                                    "old_flag": "P", "new_flag": "A"}]}}
    gate = {"by_table": {}, "stale": []}
    found = update_check.build_findings([], changes, gate, [], schedule, {}, "2027-01-01")
    assert found == []


def test_missing_rows_are_an_anomaly():
    """Rows a new release no longer contains give a missing:<table> anomaly."""
    import update_issues
    schedule = {"sources": [{"id": "src", "parsers": ["cbi_cpi"], "kind": "api", "failure_threshold": 2}],
                "series": {}, "notify": {"github": "x"}}
    changes = {"prices_monthly": {"added": [], "revised": [], "withdrawn": [],
                                  "missing": [["cpi_core", "2026-08"], ["cpi_headline", "2026-08"]]}}
    gate = {"by_table": {}, "stale": []}
    found = {f["identity"]: f for f in update_check.build_findings([], changes, gate, [], schedule, {}, "2027-01-01")}
    f = found["missing:prices_monthly"]
    assert f["kind"] == "anomaly" and f["sources"] == ["src"]
    assert f["details"] == [{"series_id": "cpi_core", "date": "2026-08"}, {"series_id": "cpi_headline", "date": "2026-08"}]
    body = update_issues.issue_body(f, {"url": "u", "date": "2026-11-02"})
    assert "missing from the new release" in body and "cpi_headline" in body and "2026-08" in body


def test_catalog_mismatch_is_an_anomaly(garden_tables):
    """A rebuilt table that starts earlier than the catalog says gives catalog:<series>."""
    import update_issues
    money = garden_tables["money_banking_monthly"]
    m2 = money[money["series_id"] == "money.m2"].sort_values("date")
    earlier = m2.head(1).assign(date="2003-12")
    rebuilt = {"money_banking_monthly": pd.concat([money, earlier], ignore_index=True)}
    gate = {"by_table": {}, "stale": [], "catalog": update_check.catalog_findings(rebuilt)}
    schedule = {"sources": [], "series": {}, "notify": {"github": "x"}}
    found = {f["identity"]: f for f in update_check.build_findings([], {}, gate, [], schedule, {}, "2027-01-01")}
    assert set(found) == {"catalog:money.m2"}
    f = found["catalog:money.m2"]
    assert f["kind"] == "anomaly"
    assert {"rule": "start", "field": "start_date", "catalog": "2004-01", "data": "2003-12"} in f["details"]
    assert "money.m2" in update_issues.issue_body(f, {"url": "u", "date": "2026-11-02"})
    assert update_check.catalog_findings({"money_banking_monthly": money}) == []


def test_fingerprint_ignores_order_but_not_values():
    a = [{"series_id": "x", "date": "2020"}, {"series_id": "y", "date": "2021"}]
    assert update_check.fingerprint(a) == update_check.fingerprint(list(reversed(a)))
    assert update_check.fingerprint(a) != update_check.fingerprint([{"series_id": "x", "date": "2022"}])


def test_unreadable_streaks_file_counts_from_this_run(tmp_path):
    bad = tmp_path / "s.json"
    bad.write_text("not json", encoding="utf-8")
    assert update_check.load_streaks(bad) == {}
    assert update_check.load_streaks(None) == {}


# ---------------------------------------------------------------------- a release nobody applies


def _result(sid, outcome, **extra):
    return {"id": sid, "fetch": "auto", "parsers": [], "outcome": outcome, "detail": "", "files": [],
            "next_due": None, **extra}


def _schedule(*ids, **by_source):
    return {"sources": [{"id": i, "parsers": ["cbi_cpi"], "kind": "api", **by_source.get(i, {})} for i in ids],
            "series": {}, "notify": {"github": "x"}}


def _build(results, schedule, **kw):
    gate = {"by_table": {}, "stale": []}
    return {f["identity"]: f for f in update_check.build_findings(results, {}, gate, [], schedule, {}, "2027-01-01", **kw)}


def test_release_waiting_for_the_threshold_is_an_anomaly():
    """An unapplied release is routine for a few runs, then one anomaly per source."""
    sched = _schedule("a")
    below = _build([_result("a", "new_release")], sched, pending={"a": 2})
    assert "pending:a" not in below                                      # the third run of the default four
    at = _build([_result("a", "new_release")], sched, pending={"a": 3})
    f = at["pending:a"]
    assert f["kind"] == "anomaly" and "waited 4 runs" in f["title"] and f["sources"] == ["a"]
    assert f["details"][0]["note"].endswith("before then.") and "90 days" in f["details"][0]["note"]


def test_pending_threshold_is_per_source_and_a_failed_parse_counts():
    sched = _schedule("a", "b", a={"pending_threshold": 2})
    results = [_result("a", "parse_failed"), _result("b", "new_release")]
    found = _build(results, sched, pending={"a": 1, "b": 1})
    assert "pending:a" in found and "pending:b" not in found
    assert found["parse_failed:a"]["kind"] == "anomaly"


def test_pending_anomaly_names_the_published_series_that_are_late_because_of_it():
    sched = _schedule("a")
    late = [{"series_id": "s.one", "published_latest": "2026-05", "due": "2026-08-31"}]
    f = _build([_result("a", "new_release")], sched, pending={"a": 5}, published_late={"a": late})["pending:a"]
    assert f["details"] == late and "waited 6 runs" in f["title"]
    # the fingerprint does not move with the run count, so the open issue is updated without a new mention
    g = _build([_result("a", "new_release")], sched, pending={"a": 6}, published_late={"a": late})["pending:a"]
    assert f["fingerprint"] == g["fingerprint"]


def test_stale_published_lists_series_the_release_would_bring_up_to_date():
    from validate import FreshnessStatus
    schedule = {"series": {"s.one": {"source": "a"}, "s.two": {"source": "a"}, "s.three": {"source": "b"}}}
    before = [FreshnessStatus("t", "s.one", "2026-05", "2026-08-31", 30, "overdue", "", None),
              FreshnessStatus("t", "s.two", "2026-05", "2026-08-31", 30, "overdue", "", None),
              FreshnessStatus("t", "s.three", "2026-05", "2026-08-31", 30, "acknowledged", "x", 0)]
    after = [FreshnessStatus("t", "s.one", "2026-08", "2026-11-30", 0, "current", "", None),
             FreshnessStatus("t", "s.two", "2026-05", "2026-08-31", 30, "overdue", "", None),
             FreshnessStatus("t", "s.three", "2026-05", "2026-08-31", 30, "acknowledged", "x", 0)]
    assert update_check.stale_published(before, after, schedule) == {
        "a": [{"series_id": "s.one", "published_latest": "2026-05", "due": "2026-08-31"}]}


def test_streaks_file_has_two_parts_and_the_flat_format_still_reads(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"failures": {"a": 1}, "pending": {"b": 3}}), encoding="utf-8")
    assert update_check.read_streaks(path) == ({"a": 1}, {"b": 3})
    path.write_text(json.dumps({"a": 1}), encoding="utf-8")                  # the earlier format
    assert update_check.read_streaks(path) == ({"a": 1}, {})
    assert update_check.load_streaks(path) == {"a": 1}


def test_waiting_release_in_a_run_uses_the_streaks_file(tmp_path, monkeypatch):
    streaks = tmp_path / "streaks.json"
    streaks.write_text(json.dumps({"failures": {}, "pending": {"fred_brent": 3}}), encoding="utf-8")
    monkeypatch.setattr(update_check, "FETCHERS", {**{s: unchanged for s in AUTO}, "fred_brent": fred_next_release})
    update_check.main(["--workdir", str(tmp_path / "w"), "--report-dir", str(tmp_path / "r"),
                       "--today", TODAY, "--streaks", str(streaks)])
    report = json.loads((tmp_path / "r" / "report.json").read_text(encoding="utf-8"))
    assert outcomes(report)["fred_brent"]["pending_streak"] == 4
    f = findings_by_id(report)["pending:fred_brent"]
    # the one fake day does not bring oil_price_brent up to date, so it stays under overdue:fred_brent
    assert "note" in f["details"][0] and "overdue:fred_brent" in findings_by_id(report)


# ---------------------------------------------------------------------- outages and manual reminders


def test_half_the_sources_failing_is_one_outage():
    results = [_result("bis_lbs", "fetch_failed"), _result("wb_oda", "fetch_failed"), _result("fred_brent", "no_change"),
               _result("eia_intl", "no_change")]
    found = _build(results, _schedule("bis_lbs", "wb_oda", "fred_brent", "eia_intl"))
    f = found["outage"]
    assert f["kind"] == "anomaly" and f["title"] == "2 of 4 download sources failed in the same run"
    assert [r["source"] for r in f["details"]] == ["bis_lbs", "wb_oda"]
    assert found["routine:bis_lbs"]["kind"] == "routine"          # each failure is still counted on its own


def test_one_failing_source_is_not_an_outage():
    results = [_result("bis_lbs", "fetch_failed"), _result("wb_oda", "no_change"), _result("fred_brent", "no_change")]
    assert "outage" not in _build(results, _schedule("bis_lbs", "wb_oda", "fred_brent"))


def test_every_source_of_one_host_failing_is_an_outage():
    cbi = ("cbi_bop", "cbi_kfi", "cbi_bulletin", "cbi_fx")
    results = [_result(s, "fetch_failed") for s in cbi] + [_result(s, "no_change") for s in
                                                            ("bis_lbs", "wb_oda", "fred_brent", "eia_intl", "github_fx")]
    found = _build(results, _schedule(*cbi, "bis_lbs", "wb_oda", "fred_brent", "eia_intl", "github_fx"))
    assert {r["host"] for r in found["outage"]["details"]} == {"cbi.iq"}
    # one CBI source working means the site is up
    results[0] = _result("cbi_bop", "no_change")
    assert "outage" not in _build(results, _schedule(*cbi, "bis_lbs", "wb_oda", "fred_brent", "eia_intl", "github_fx"))


def test_a_manual_source_due_within_two_weeks_is_an_anomaly_until_it_is_overdue():
    import datetime
    sched = _schedule("m")
    today = datetime.date(2026, 11, 15)

    def with_due(due):
        return _build([_result("m", "manual", fetch="manual", next_due=due, detail="by hand")], sched, today=today)

    assert with_due("2026-11-29")["manual-due:m"]["kind"] == "anomaly"      # 14 days
    assert with_due("2026-11-15")["manual-due:m"]["details"][0]["next_due"] == "2026-11-15"
    assert "manual-due:m" not in with_due("2026-11-30")                     # 15 days
    assert "manual-due:m" not in with_due("2026-11-14")                     # overdue: overdue:<source> reports it
    assert "manual-due:m" not in with_due(None)
    assert with_due("2026-11-30")["routine:m"]["kind"] == "routine"


# ---------------------------------------------------------------------- how big a revision is


def _revision(series, date, old, new):
    return {"series_id": series, "date": date, "old_value": old, "new_value": new, "old_flag": "A", "new_flag": "A"}


def test_revision_percent_is_the_change_over_the_old_value():
    assert update_check.revision_percent(100, 105) == pytest.approx(5.0)
    assert update_check.revision_percent(-50, -40) == pytest.approx(20.0)
    assert update_check.revision_percent(0, 3) is None and update_check.revision_percent(None, 3) is None
    assert update_check.revision_percent(float("nan"), 3) is None


def test_revised_rows_are_largest_first_and_counted():
    revised = [_revision("a", "2026-01", 100, 101), _revision("b", "2026-01", 100, 130),
               _revision("c", "2026-01", 0, 4), _revision("d", "2026-01", 100, 105)]
    rows, large = update_check.revised_rows(revised, 5.0)
    assert [r["series_id"] for r in rows] == ["c", "b", "d", "a"]      # no base, 30%, 5%, 1%
    assert [r["size"] for r in rows] == ["n/a", "30.0%", "5.0%", "1.0%"]
    assert large == 3                                                  # the 5% one counts: at least the threshold
    assert update_check.revised_rows(revised, 50.0)[1] == 1            # only the one with no base


def test_the_issue_title_counts_the_large_revisions_and_the_threshold_is_configurable():
    schedule = {"sources": [{"id": "src", "parsers": ["cbi_cpi"], "kind": "api", "failure_threshold": 2}],
                "series": {}, "notify": {"github": "x"}}
    changes = {"prices_monthly": {"added": [], "missing": [], "withdrawn": [],
                                  "revised": [_revision("cpi_core", "2025-01", 100, 130), _revision("cpi_core", "2025-02", 100, 101)]}}
    gate = {"by_table": {}, "stale": []}

    def title(extra):
        found = update_check.build_findings([], changes, gate, [], {**schedule, **extra}, {}, "2027-01-01")
        return found[0]["title"], found[0]["details"]

    text, rows = title({})                                              # the default threshold is 5%
    assert text == "prices_monthly: 2 revised (1 of 5% or more), 0 withdrawn value(s)"
    assert rows[0]["date"] == "2025-01" and rows[0]["size"] == "30.0%"   # the large one is first, and says so
    assert title({"large_revision_pct": 0.5})[0] == "prices_monthly: 2 revised (2 of 0.5% or more), 0 withdrawn value(s)"
    assert title({"large_revision_pct": 90})[0] == "prices_monthly: 2 revised, 0 withdrawn value(s)"


def test_the_threshold_in_the_schedule_is_validated(tmp_path):
    import validate
    text = (REPO_ROOT / "pipeline" / "metadata" / "update_schedule.yaml").read_text(encoding="utf-8")
    assert validate.load_update_schedule()["large_revision_pct"] == 5
    for bad in ("0", "-1", "'five'", "true"):
        path = tmp_path / "schedule.yaml"
        path.write_text(text.replace("large_revision_pct: 5", f"large_revision_pct: {bad}"), encoding="utf-8")
        with pytest.raises(ValueError, match="large_revision_pct"):
            validate.load_update_schedule(path)


def test_the_report_markdown_shows_each_revisions_size(mixed):
    md = (mixed[0] / "report" / "report.md").read_text(encoding="utf-8")
    assert "| Series | Period | Old | New | Size |" in md
