"""
pipeline.update_check
=====================
The weekly update check.

    python pipeline/update_check.py --workdir DIR --report-dir DIR [--sources ID ...] [--today YYYY-MM-DD]

1. Copy pipeline/raw, pipeline/seeds, pipeline/data/garden and the raw-file manifest into the
   (new or empty) --workdir.
2. For every source in pipeline/metadata/update_schedule.yaml: run its fetcher into the workdir
   (outcome new_release, no_change or fetch_failed), or report it as manual with its next due
   date. Downloaded files are copied to <report-dir>/downloads/ with their SHA-256, so the
   maintainer archives exactly the bytes that were reviewed.
3. For each source with a new release, merge its parsers' rebuild into the workdir tables
   (run_parsers.run_all with apply_to); a failure becomes parse_failed, naming the parser.
4. Gatekeep the workdir tables: Tier 1, Tier 2 with acknowledgements, and freshness at --today.
5. Classify every finding as an anomaly or routine, with a group identity: a spreadsheet
   source's new release always needs review; a fetch failure counts only from its source's failure_threshold of consecutive runs (earlier counts from --streaks). A
   downloaded release that nobody has applied becomes an anomaly after the source's
   pending_threshold runs, together with the published series that are overdue because of it.
   Half the sources failing in one run, or every source of one host, is an outage; a manual
   source due within two weeks gets a reminder.
6. Write report.json (with `findings`) and report.md to --report-dir; print
   `needs_review=true|false` (any anomaly) last and append it to $GITHUB_OUTPUT when set.
   Issues are opened, updated and closed by pipeline/update_issues.py, not here.

Nothing outside --workdir and --report-dir is written, git is never run, and all network access
goes through the fetchers (downloads.polite_get). Applying an update stays a maintainer step
(docs/collecting_data_doc.md, section 5, "Maintenance Runbook").

Exit status: 0 whenever a report was written, whatever it found; 1 if the check itself failed.
"""

import argparse
import datetime
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "src"))
sys.path.insert(0, str(repo_root / "pipeline" / "parsers"))
sys.path.insert(0, str(repo_root / "pipeline"))

import pandas as pd  # noqa: E402

import catalog_check  # noqa: E402
import downloads  # noqa: E402
import run_parsers  # noqa: E402
import validate  # noqa: E402
from fetchers import FETCHERS, HOSTS  # noqa: E402
from iraqdata.catalog import SERIES_TO_TABLE  # noqa: E402
from iraqdata.schema import validate_dataframe  # noqa: E402

RAW_DIR = repo_root / "pipeline" / "raw"
SEEDS_DIR = repo_root / "pipeline" / "seeds"
GARDEN_DIR = repo_root / "pipeline" / "data" / "garden"
MANIFEST = repo_root / "pipeline" / "metadata" / "raw_manifest.yaml"
MAX_ROWS = 50  # per Markdown table; report.json always has everything


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_workspace(workdir: Path) -> Dict[str, Path]:
    if workdir.exists() and any(workdir.iterdir()):
        raise FileExistsError(f"--workdir {workdir} must be new or empty")
    ws = {"raw": workdir / "raw", "seeds": workdir / "seeds", "garden": workdir / "garden",
          "history": workdir / "history", "manifest": workdir / "raw_manifest.yaml"}
    shutil.copytree(RAW_DIR, ws["raw"])
    shutil.copytree(SEEDS_DIR, ws["seeds"])
    shutil.copytree(GARDEN_DIR, ws["garden"])
    shutil.copyfile(MANIFEST, ws["manifest"])
    return ws


def load_tables(folder: Path) -> Dict[str, pd.DataFrame]:
    return {p.stem: pd.read_parquet(p) for p in sorted(folder.glob("*.parquet"))}


def _ack_match(w, acks: List[dict], dataset: str, today):
    """
    (index of the acknowledgement that silences w, or None; index of any that covers it).
    The gate's own rule (validate.match_warning): per period, value-tied, with a
    review-by date. An expired or changed acknowledgement covers w but does not silence it.
    """
    m = validate.match_warning(w, acks, dataset, today)
    if m is None:
        return None, None
    return (m.index if m.state in ("applies", "due") else None), m.index


def gatekeep(tables: Dict[str, pd.DataFrame], schedule: dict, acks: List[dict], today) -> dict:
    """Tier 1, Tier 2 (with acknowledgements) and freshness on the updated tables."""
    errors, warnings, acknowledged, matched = [], [], 0, set()
    by_table: Dict[str, List[str]] = {}  # gate findings are grouped per table (gate:<table>)
    for name, df in tables.items():
        t1 = validate_dataframe(df, dataset_name=name)
        if t1:
            errors += t1
            by_table.setdefault(name, []).extend(f"ERROR: {e}" for e in t1)
            continue
        t2_errors, details = validate.validate_tier2_details(df, dataset_name=name)
        errors += t2_errors
        by_table.setdefault(name, []).extend(f"ERROR: {e}" for e in t2_errors)
        for w in details:
            if w.check == "break":
                continue
            i, covering = _ack_match(w, acks, name, today)
            if covering is not None:
                matched.add(covering)
            if i is None:
                warnings.append(w.message)
                by_table.setdefault(name, []).append(f"WARNING: {w.message}")
            else:
                acknowledged += 1
    # Cross-source sanity checks, reported as one group
    for w in validate.sanity_warnings(tables):
        i, covering = _ack_match(w, acks, w.dataset, today)
        if covering is not None:
            matched.add(covering)
        if i is None:
            warnings.append(w.message)
            by_table.setdefault(w.dataset, []).append(f"WARNING: {w.message}")
        else:
            acknowledged += 1
    statuses = validate.freshness_status(tables, schedule, acks, today, set(tables))
    matched.update(st.ack_index for st in statuses if st.ack_index is not None)
    stale = [f"{validate.ack_key(a)} ({', '.join(map(str, a.get('periods', [])))}): {a['reason']}"
             for i, a in enumerate(acks) if i not in matched]
    return {
        "errors": errors,
        "warnings": warnings,
        "acknowledged": acknowledged,
        "stale": stale,
        "by_table": by_table,
        "freshness": statuses,
        "catalog": catalog_findings(tables),
    }


def catalog_findings(tables: Dict[str, pd.DataFrame]) -> List[catalog_check.Discrepancy]:
    """
    The catalog against the rebuilt tables, so a source that backfills history is
    reported before the merge. Only series whose table was rebuilt are checked; withdrawn series
    are checked by CI against the vintage history.
    """
    entries = [e for e in catalog_check.load_catalog()
               if SERIES_TO_TABLE.get(e["series_id"]) in tables and e.get("status") != "withdrawn"]
    return catalog_check.check(entries, tables, history=None, info=[])


# ===================================================================== findings

ARTIFACT_DAYS = 90  # the workflow keeps the report artifact (with the downloads) this long
WAITING_OUTCOMES = ("new_release", "parse_failed")  # a downloaded release that is not part of the repository yet
MANUAL_HEADS_UP_DAYS = 14  # a manual source is reported this many days before it is due


def fingerprint(details: List[dict]) -> str:
    """sha256 of the canonical details: independent of run date, run link and row order."""
    rows = sorted(json.dumps(r, sort_keys=True, ensure_ascii=False, default=str) for r in details)
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


def _finding(kind: str, identity: str, title: str, details: List[dict], sources: List[str]) -> dict:
    return {"kind": kind, "identity": identity, "title": title, "details": details,
            "fingerprint": fingerprint(details), "sources": sorted(sources)}


def _source_tables(src: dict) -> List[str]:
    by_name = {spec.name: spec for spec in run_parsers.REGISTRY}
    return sorted({out[:-len(".parquet")] for p in src["parsers"] for out in by_name[p].outputs})


def _new_periods(src: dict, changes: Dict[str, dict]) -> List[dict]:
    """Per table this source feeds: how many keys the release adds, and their date range."""
    rows = []
    for table in _source_tables(src):
        added = changes.get(table, {}).get("added", [])
        if added:
            dates = sorted(str(k[1]) for k in added)
            rows.append({"table": table, "added": len(added), "first": dates[0], "last": dates[-1]})
    return rows


def stale_published(before: List, after: List, schedule: dict) -> Dict[str, List[dict]]:
    """
    Per source, the series that are overdue in the committed tables and no longer overdue once the
    downloaded release is merged: the data that is late only because nobody applied the release.
    (Series still overdue after the merge are reported as overdue:<source>.)
    """
    now = {st.series_id: st for st in after}
    out: Dict[str, List[dict]] = {}
    for st in before:
        if st.state != "overdue" or (now.get(st.series_id) is not None and now[st.series_id].state == "overdue"):
            continue
        sid = (schedule["series"].get(st.series_id) or {}).get("source", "unscheduled")
        out.setdefault(sid, []).append({"series_id": st.series_id, "published_latest": st.latest, "due": st.due})
    return out


def _host(source_id: str) -> Optional[str]:
    urls = HOSTS.get(source_id)
    return urlsplit(urls[0]).netloc if urls else None


def outage_finding(results: List[dict]) -> Optional[dict]:
    """
    One anomaly when the fetching itself looks broken rather than a single source: at least two
    sources and half of the automatic ones failed in this run, or every automatic source of a host
    that serves several of them did. A network or runner fault otherwise stays below every
    source's failure threshold for a whole extra week.
    """
    auto = [e for e in results if e["fetch"] != "manual"]
    failed = [e for e in auto if e["outcome"] == "fetch_failed"]
    by_host: Dict[str, List[dict]] = {}
    for e in auto:
        if _host(e["id"]):
            by_host.setdefault(_host(e["id"]), []).append(e)
    dark = sorted(h for h, es in by_host.items() if len(es) >= 2 and all(e["outcome"] == "fetch_failed" for e in es))
    if not ((len(failed) >= 2 and 2 * len(failed) >= len(auto)) or dark):
        return None
    rows = [{"source": e["id"], "host": _host(e["id"]) or ""} for e in sorted(failed, key=lambda e: e["id"])]
    return _finding("anomaly", "outage", f"{len(failed)} of {len(auto)} download sources failed in the same run",
                    rows, [e["id"] for e in failed])


def revision_percent(old, new) -> Optional[float]:
    """The size of a revision in percent of the old value; None when the old value is 0 or missing (no base)."""
    try:
        old, new = float(old), float(new)
    except (TypeError, ValueError):
        return None
    if old == 0 or old != old or new != new:
        return None
    return abs(new - old) / abs(old) * 100


def revised_rows(revised: List[dict], large_pct: float) -> Tuple[List[dict], int]:
    """
    The revised values as finding rows, largest first, each with its size in percent, and how many are
    large (at least `large_pct`, or from a value of 0, which has no base to compare with).
    """
    sized = [(revision_percent(r["old_value"], r["new_value"]), r) for r in revised]
    # a value revised from 0 has no base and is listed first, then the largest percentages
    sized.sort(key=lambda x: (x[0] is not None, -(x[0] or 0), x[1]["series_id"], str(x[1]["date"])))
    rows = [{"change": "revised", "series_id": r["series_id"], "date": r["date"], "old": r["old_value"],
             "new": r["new_value"], "size": "n/a" if pct is None else f"{pct:.1f}%",
             "old_flag": r["old_flag"], "new_flag": r["new_flag"]} for pct, r in sized]
    return rows, sum(1 for pct, _ in sized if pct is None or pct >= large_pct)


def build_findings(results: List[dict], changes: Dict[str, dict], gate: dict, freshness: List[dict],
                   schedule: dict, streaks: Dict[str, int], expires: str, *,
                   pending: Optional[Dict[str, int]] = None,
                   published_late: Optional[Dict[str, List[dict]]] = None,
                   today: Optional[datetime.date] = None) -> List[dict]:
    """
    Classify every finding as anomaly or routine with group identities.
    `streaks` holds each source's consecutive fetch_failed count before this run, and
    `pending` the consecutive earlier runs in which a downloaded release was waiting to be applied;
    each results entry gets failure_streak, failure_threshold, pending_streak and pending_threshold
    here, so classification happens once. `published_late` is stale_published(); `today` enables
    the manual-source reminders.
    """
    pending, published_late = pending or {}, published_late or {}
    sources = {s["id"]: s for s in schedule["sources"]}
    findings: List[dict] = []
    for e in results:
        src = sources[e["id"]]
        e["failure_threshold"] = src.get("failure_threshold", validate.DEFAULT_FAILURE_THRESHOLD)
        e["failure_streak"] = int(streaks.get(e["id"], 0)) + 1 if e["outcome"] == "fetch_failed" else 0
        e["pending_threshold"] = src.get("pending_threshold", validate.DEFAULT_PENDING_THRESHOLD)
        e["pending_streak"] = int(pending.get(e["id"], 0)) + 1 if e["outcome"] in WAITING_OUTCOMES else 0
        sid = e["id"]
        if e["pending_streak"] >= e["pending_threshold"]:
            # The note is stable while the same series are late, so a waiting release is one issue
            # that is updated quietly, not a new mention every week.
            rows = published_late.get(sid) or [{"note": f"The downloaded files are kept in each run's artifact for "
                                                         f"{ARTIFACT_DAYS} days; apply or archive them before then."}]
            findings.append(_finding("anomaly", f"pending:{sid}",
                                     f"{sid}: a downloaded release has waited {e['pending_streak']} runs to be applied",
                                     rows, [sid]))
        if e["outcome"] == "fetch_failed":
            details = [{"reason": e["detail"]}]
            if e["failure_streak"] >= e["failure_threshold"]:
                findings.append(_finding("anomaly", f"fetch_failed:{sid}",
                                         f"{sid}: download failing for {e['failure_streak']} run(s)", details, [sid]))
            else:
                findings.append(_finding("routine", f"routine:{sid}",
                                         f"{sid}: download failed {e['failure_streak']} of {e['failure_threshold']} run(s)",
                                         details, [sid]))
        elif e["outcome"] == "parse_failed":
            findings.append(_finding("anomaly", f"parse_failed:{sid}", f"{sid}: parser failed",
                                     [{"reason": e["detail"]}], [sid]))
        elif e["outcome"] == "new_release":
            details = ([{"file": f["path"], "size": f["size"], "sha256": f["sha256"], "available_until": expires}
                        for f in e["files"]] + _new_periods(src, changes))
            if src.get("kind") == "spreadsheet":
                # PDF and spreadsheet sources always open a review issue
                findings.append(_finding("anomaly", f"review:{sid}", f"{sid}: new release to review", details, [sid]))
            else:
                findings.append(_finding("routine", f"routine:{sid}", f"{sid}: new data", details, [sid]))
        elif e["outcome"] == "manual":
            findings.append(_finding("routine", f"routine:{sid}", f"{sid}: manual source, next due {e['next_due'] or 'n/a'}",
                                     [{"reason": e["detail"], "next_due": e["next_due"]}], [sid]))
            if today and e["next_due"] and 0 <= (datetime.date.fromisoformat(e["next_due"]) - today).days <= MANUAL_HEADS_UP_DAYS:
                # Once the date has passed, the overdue:<source> anomaly takes over
                findings.append(_finding("anomaly", f"manual-due:{sid}", f"{sid}: manual update due {e['next_due']}",
                                         [{"reason": e["detail"], "next_due": e["next_due"]}], [sid]))
    outage = outage_finding(results)
    if outage:
        findings.append(outage)
    large_pct = float(schedule.get("large_revision_pct", validate.DEFAULT_LARGE_REVISION_PCT))
    for table, c in sorted(changes.items()):
        revised, large = revised_rows(c["revised"], large_pct)
        rows = revised + [{"change": "withdrawn", "series_id": k[0], "date": k[1]} for k in c["withdrawn"]]
        if rows:
            marked = f" ({large} of {large_pct:g}% or more)" if large else ""
            findings.append(_finding("anomaly", f"revised:{table}",
                                     f"{table}: {len(c['revised'])} revised{marked}, {len(c['withdrawn'])} withdrawn value(s)",
                                     rows, [s for s in sources if table in _source_tables(sources[s])]))
    for table, c in sorted(changes.items()):
        # Published rows the new release no longer contains need a decision
        if c.get("missing"):
            findings.append(_finding("anomaly", f"missing:{table}",
                                     f"{table}: {len(c['missing'])} published row(s) missing from the new release",
                                     [{"series_id": k[0], "date": k[1]} for k in c["missing"]],
                                     [s for s in sources if table in _source_tables(sources[s])]))
    for table, msgs in sorted(gate["by_table"].items()):
        if msgs:
            findings.append(_finding("anomaly", f"gate:{table}", f"{table}: {len(msgs)} gate finding(s)",
                                     [{"message": m} for m in msgs], []))
    by_series: Dict[str, List[dict]] = {}
    for d in gate.get("catalog", []):
        by_series.setdefault(d.series_id, []).append(
            {"rule": d.rule, "field": d.field, "catalog": str(d.catalog_value), "data": str(d.data_value)})
    for series_id, rows in sorted(by_series.items()):
        # E.g. a source backfilled history, so the catalog start date is now wrong
        findings.append(_finding("anomaly", f"catalog:{series_id}",
                                 f"{series_id}: the series catalog disagrees with the rebuilt data", rows, []))
    if gate["stale"]:
        findings.append(_finding("anomaly", "gate:acknowledgements",
                                 f"{len(gate['stale'])} stale acknowledgement(s)",
                                 [{"message": f"STALE: {s}"} for s in gate["stale"]], []))
    late: Dict[str, List[dict]] = {}
    for f in freshness:
        if f["state"] in ("overdue", "unchecked"):
            src_id = (schedule["series"].get(f["series_id"]) or {}).get("source", "unscheduled")
            late.setdefault(src_id, []).append({"series_id": f["series_id"], "state": f["state"],
                                                "latest": f["latest"], "due": f["due"]})
    for src_id, rows in sorted(late.items()):
        findings.append(_finding("anomaly", f"overdue:{src_id}", f"{src_id}: {len(rows)} series overdue or unchecked",
                                 rows, [src_id]))
    return findings


def read_streaks(path: Optional[Path]) -> Tuple[Dict[str, int], Dict[str, int]]:
    """
    (fetch failures, waiting releases) per source from the --streaks file written by
    update_issues.py --streaks-out: {"failures": {...}, "pending": {...}}. A flat {source: count}
    file is read as failures only. Missing or unreadable means nothing is counted.
    """
    if path is None:
        return {}, {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if "failures" in data or "pending" in data:
            return ({str(k): int(v) for k, v in data.get("failures", {}).items()},
                    {str(k): int(v) for k, v in data.get("pending", {}).items()})
        return {str(k): int(v) for k, v in data.items()}, {}
    except (OSError, ValueError, AttributeError, TypeError):
        print(f"WARNING: could not read failure streaks from {path}; counting from this run only")
        return {}, {}


def load_streaks(path: Optional[Path]) -> Dict[str, int]:
    """Earlier consecutive fetch failures per source (see read_streaks)."""
    return read_streaks(path)[0]


def _next_due(source_id: str, schedule: dict, statuses) -> Optional[str]:
    mine = {sid for sid, rule in schedule["series"].items() if rule["source"] == source_id}
    dues = [st.due for st in statuses if st.series_id in mine and st.due]
    return min(dues) if dues else None


def run_check(workdir: Path, report_dir: Path, today: datetime.date,
              only_sources: Optional[Sequence[str]] = None, streaks: Optional[Dict[str, int]] = None,
              pending: Optional[Dict[str, int]] = None) -> dict:
    ws = make_workspace(workdir)
    schedule = validate.load_update_schedule()
    acks = validate.load_acknowledgements()
    sources = [s for s in schedule["sources"] if not only_sources or s["id"] in only_sources]

    before = load_tables(ws["garden"])
    before_status = validate.freshness_status(before, schedule, acks, today, set(before))

    report_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for src in sources:
        entry = {"id": src["id"], "fetch": src["fetch"], "parsers": src["parsers"], "outcome": None,
                 "detail": "", "files": [], "next_due": None}
        if src["fetch"] == "manual":
            entry.update(outcome="manual", detail=src["reason"],
                         next_due=_next_due(src["id"], schedule, before_status))
        else:
            try:
                with downloads.restrict_hosts(HOSTS.get(src["id"])):
                    saved = FETCHERS[src["id"]](ws["raw"], today, ws["manifest"])
            except Exception as exc:
                entry.update(outcome="fetch_failed", detail=f"{type(exc).__name__}: {exc}")
            else:
                if not saved:
                    entry["outcome"] = "no_change"
                else:
                    entry["outcome"] = "new_release"
                    for path in saved:
                        rel = Path(path).relative_to(ws["raw"])
                        dst = report_dir / "downloads" / rel
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(path, dst)
                        entry["files"].append({"path": rel.as_posix(), "size": dst.stat().st_size,
                                               "sha256": _sha(dst)})
                    entry["detail"] = ", ".join(f["path"] for f in entry["files"])
        results.append(entry)

    order = {spec.name: i for i, spec in enumerate(run_parsers.REGISTRY)}
    changes: Dict[str, dict] = {}
    for entry in sorted((e for e in results if e["outcome"] == "new_release"),
                        key=lambda e: min(order[p] for p in e["parsers"])):
        try:
            merged = run_parsers.run_all(only=entry["parsers"], raw_root=ws["raw"], seeds_root=ws["seeds"],
                                         apply_to=ws["garden"], history_dir=ws["history"],
                                         allow_missing=True)  # reported below, never refused
        except Exception as exc:
            where = getattr(exc, "parser", "merge")
            entry.update(outcome="parse_failed", detail=f"{where}: {type(exc).__name__}: {exc}")
            continue
        for table, info in merged["tables"].items():
            agg = changes.setdefault(table, {"added": [], "revised": [], "withdrawn": [], "missing": [],
                                             "flag_updated": []})
            for key in ("added", "revised", "withdrawn", "flag_updated"):
                agg[key] += info.get(key, [])
            agg["missing"] = info["missing"]

    gate = gatekeep(load_tables(ws["garden"]), schedule, acks, today)
    after_status = gate.pop("freshness")
    freshness = [st._asdict() for st in after_status if st.state != "current"]
    expires = (today + datetime.timedelta(days=ARTIFACT_DAYS)).isoformat()
    findings = build_findings(results, changes, gate, freshness, schedule, streaks or {}, expires,
                              pending=pending, published_late=stale_published(before_status, after_status, schedule),
                              today=today)
    report = {
        "run_date": today.isoformat(),
        "large_revision_pct": schedule.get("large_revision_pct", validate.DEFAULT_LARGE_REVISION_PCT),
        "maintainer": schedule["notify"]["github"],
        "artifact_expires": expires,
        "sources": results,
        "changes": {t: c for t, c in changes.items()
                    if c["added"] or c["revised"] or c["withdrawn"] or c["missing"] or c.get("flag_updated")},
        "gatekeeper": gate,
        "freshness": freshness,
        "findings": findings,
        # Review is needed exactly when there is an anomaly
        "needs_review": any(f["kind"] == "anomaly" for f in findings),
    }
    (report_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str),
                                            encoding="utf-8")
    (report_dir / "report.md").write_text(render_markdown(report), encoding="utf-8")
    return report


def _table(header: List[str], rows: List[List[str]]) -> List[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c).replace("|", "\\|") for c in row) + " |" for row in rows[:MAX_ROWS]]
    if len(rows) > MAX_ROWS:
        out.append(f"\n_{len(rows) - MAX_ROWS} more row(s) in report.json._")
    return out


def _detail_text(row: dict) -> str:
    return ", ".join(f"{k}: {v}" for k, v in row.items() if v not in (None, ""))


def render_findings(findings: List[dict], kind: str) -> List[str]:
    """Bullets for one kind of finding: a title per finding, then its detail rows."""
    lines = []
    for f in (f for f in findings if f["kind"] == kind):
        lines.append(f"- **{f['title']}**" + (f" (`{f['identity']}`)" if kind == "anomaly" else ""))
        lines += [f"  - {_detail_text(r)}" for r in f["details"][:MAX_ROWS]]
        if len(f["details"]) > MAX_ROWS:
            lines.append(f"  - _{len(f['details']) - MAX_ROWS} more in report.json_")
    return lines or ["None."]


def render_markdown(report: dict) -> str:
    lines = [f"# Data update check, {report['run_date']}", "",
             f"**Needs review: {'yes' if report['needs_review'] else 'no'}**", "",
             "## Anomalies", ""]
    lines += render_findings(report["findings"], "anomaly")
    # Routine findings go to the run summary, never to issues
    lines += ["", "## Routine updates", "",
              f"Downloads in this run's artifact are available until {report['artifact_expires']}.", ""]
    lines += render_findings(report["findings"], "routine")
    lines += ["", "## Sources", ""]
    lines += _table(["Source", "Fetch", "Outcome", "Detail", "Next due"],
                    [[s["id"], s["fetch"], s["outcome"], s["detail"], s["next_due"] or ""] for s in report["sources"]])
    lines += ["", "## Changes", ""]
    if not report["changes"]:
        lines.append("No published value would change.")
    for table, c in report["changes"].items():
        lines += [f"### {table}", "",
                  f"{len(c['added'])} added, {len(c['revised'])} revised, {len(c['withdrawn'])} withdrawn, "
                  f"{len(c['missing'])} missing from the new release, {len(c.get('flag_updated', []))} flag update(s) "
                  "(a period leaving the provisional window; routine, not a revision).", ""]
        if c["revised"]:
            rows, _ = revised_rows(c["revised"], float(report.get("large_revision_pct", validate.DEFAULT_LARGE_REVISION_PCT)))
            lines += _table(["Series", "Period", "Old", "New", "Size"],
                            [[r["series_id"], r["date"], f"{r['old']} ({r['old_flag']})", f"{r['new']} ({r['new_flag']})",
                              r["size"]] for r in rows]) + [""]
    g = report["gatekeeper"]
    lines += ["", "## Gatekeeper", "",
              f"{len(g['errors'])} error(s), {len(g['warnings'])} unacknowledged warning(s), "
              f"{g['acknowledged']} acknowledged, {len(g['stale'])} stale acknowledgement(s).", ""]
    lines += [f"- ERROR: {e}" for e in g["errors"][:MAX_ROWS]]
    lines += [f"- WARNING: {w}" for w in g["warnings"][:MAX_ROWS]]
    lines += [f"- STALE: {s}" for s in g["stale"]]
    lines += ["", "## Freshness", ""]
    lines += _table(["Series", "Table", "Latest", "Due", "Days overdue", "State", "Note"],
                    [[f["series_id"], f["dataset"], f["latest"], f["due"] or "", f["days_overdue"], f["state"],
                      f["reason"]] for f in report["freshness"]])
    lines += ["", "## Applying an update", "",
              "Nothing has been committed. To apply: download this run's artifact, copy `downloads/<path>` "
              "into `pipeline/raw/<path>`, check each SHA-256 against `report.json`, then follow "
              "section 5 (\"Maintenance Runbook\") of docs/collecting_data_doc.md.", ""]
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Weekly update check (report only; never commits).")
    parser.add_argument("--workdir", type=Path, required=True, help="New or empty scratch folder.")
    parser.add_argument("--report-dir", type=Path, required=True, help="Where report.md/json and downloads go.")
    parser.add_argument("--sources", nargs="+", default=None, help="Only these source ids.")
    parser.add_argument("--today", default=None, metavar="YYYY-MM-DD",
                        help="Run date (default: today, UTC); fixes dated names, vintage and freshness.")
    parser.add_argument("--streaks", type=Path, default=None,
                        help="JSON from update_issues.py --streaks-out: earlier consecutive fetch failures and "
                             "waiting releases per source.")
    args = parser.parse_args(argv)
    try:
        today = (datetime.date.fromisoformat(args.today) if args.today
                 else datetime.datetime.now(datetime.timezone.utc).date())
    except ValueError:
        parser.error(f"--today must be YYYY-MM-DD, not {args.today!r}")

    failures, waiting = read_streaks(args.streaks)
    report = run_check(args.workdir, args.report_dir, today, args.sources, failures, waiting)
    for s in report["sources"]:
        print(f"[{s['outcome'].upper()}] {s['id']}: {s['detail']}")
    flag = "true" if report["needs_review"] else "false"
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"needs_review={flag}\n")
    print(f"needs_review={flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
