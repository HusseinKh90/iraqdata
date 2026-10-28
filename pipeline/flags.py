"""
pipeline.flags
==============
The one place where observation status flags are decided.

Parsers emit `A`, `B` for a break they detected, and `P` only where the source file itself marks a
value provisional. `assign_flags` then sets the final flag of every row from two metadata files:

- src/iraqdata/series_catalog.yaml (the only catalog): each series' `origin` segments (observed, derived,
  modelled, transcribed, unknown) by period
- pipeline/metadata/flag_policy.yaml: the precedence of the codes, the flag each origin class
  implies, and each series' revision window

For each row the candidate flags are:

- `M` if the value is NaN
- `B` if the parser marked a break, or the policy's `breaks` list names the series and period: the
  first period measured on a changed definition, taken from the source's own footnote. Only entries
  with `status: confirmed` apply; a `proposed` entry was read from the footnote and waits for the
  maintainer
- the flag its origin class implies (`E` modelled, `U` transcribed or unknown; `derived` rows
  inherit the highest-precedence flag of the same-period rows of their `inputs`)
- `P` if the period is among the latest `revision_window` periods of its series (counted on the
  series' own latest period in the table, never the run date), or, for a `publisher` window, the
  parser emitted `P`
- `A` otherwise

and the candidate listed first in `precedence` wins. `assign_flags` is pure: no clock, no network,
no files other than the two metadata files.
"""

import functools
import math
import re
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import yaml

repo_root = Path(__file__).resolve().parent.parent
POLICY_PATH = repo_root / "pipeline" / "metadata" / "flag_policy.yaml"
CATALOG_PATH = repo_root / "src" / "iraqdata" / "series_catalog.yaml"
SOURCES_PATH = repo_root / "pipeline" / "metadata" / "sources.yaml"

ORIGIN_CLASSES = ("observed", "derived", "modelled", "transcribed", "unknown")
OPEN = "open"


@functools.lru_cache(maxsize=None)
def load_policy(path: Path = POLICY_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


@functools.lru_cache(maxsize=None)
def source_ids(path: Path = SOURCES_PATH) -> frozenset:
    """The ids of the terms-of-reuse records."""
    with open(path, encoding="utf-8") as f:
        return frozenset(s["id"] for s in (yaml.safe_load(f) or {}).get("sources", []))


@functools.lru_cache(maxsize=None)
def load_catalog(path: Path = CATALOG_PATH) -> Dict[str, dict]:
    """{series_id: catalog entry}."""
    with open(path, encoding="utf-8") as f:
        catalog = {s["series_id"]: s for s in yaml.safe_load(f).get("series", [])}
    check_catalog_fields(catalog)
    return catalog


def check_catalog_fields(catalog: Dict[str, dict]) -> None:
    """
    Optional fields: `source_indicator` is a non-empty string; `replaced_by` names
    another entry with the same unit and frequency. `status` is `active` or `withdrawn`,
    `withdrawn_in` (a non-empty string) is given exactly when the status is `withdrawn`, and
    `summary` (the docs/series.md description) is one line without '|', and every origin segment
    except a derived one names its terms-of-reuse record (`source_ref`, pipeline/metadata/sources.yaml).
    Raises ValueError naming the series.
    """
    for sid, entry in catalog.items():
        status = entry.get("status", "active")
        if status not in ("active", "withdrawn"):
            raise ValueError(f"{sid}: status must be active or withdrawn, not {status!r} (series_catalog.yaml)")
        if status == "withdrawn":
            when = entry.get("withdrawn_in")
            if not isinstance(when, str) or not when.strip():
                raise ValueError(f"{sid}: a withdrawn series needs withdrawn_in, e.g. 'data-2026-12' (series_catalog.yaml)")
        elif "withdrawn_in" in entry:
            raise ValueError(f"{sid}: withdrawn_in is set but status is not withdrawn (series_catalog.yaml)")
        summary = entry.get("summary")
        if not isinstance(summary, str) or not summary.strip() or "\n" in summary or "|" in summary:
            raise ValueError(f"{sid}: summary must be one non-empty line without '|' (series_catalog.yaml)")
        for i, seg in enumerate(entry.get("origin") or []):
            ref = seg.get("source_ref")
            if seg.get("class") == "derived" and ref is None:
                continue  # derived segments take their sources from their inputs
            if ref not in source_ids():
                raise ValueError(f"{sid}: origin[{i}].source_ref {ref!r} is not a record in "
                                 f"pipeline/metadata/sources.yaml (series_catalog.yaml)")
        if "source_indicator" in entry:
            ind = entry["source_indicator"]
            if not isinstance(ind, str) or not ind.strip():
                raise ValueError(f"{sid}: source_indicator must be a non-empty string (series_catalog.yaml)")
        if "replaced_by" in entry:
            new = catalog.get(entry["replaced_by"])
            if new is None:
                raise ValueError(f"{sid}: replaced_by names unknown series {entry['replaced_by']!r} (series_catalog.yaml)")
            for field in ("unit", "frequency"):
                if new.get(field) != entry.get(field):
                    raise ValueError(f"{sid}: replaced_by {new['series_id']} has {field} {new.get(field)!r}, "
                                     f"not {entry.get(field)!r} (series_catalog.yaml)")


def period(value) -> str:
    """A catalog period as an ISO string (YAML reads 2004 as an int and 2004-01-01 as a date)."""
    return str(value)


def segment_for(entry: dict, date: str) -> dict:
    """The origin segment of a series that covers `date`."""
    for seg in entry.get("origin") or []:
        to = period(seg["to"])
        if period(seg["from"]) <= date and (to == OPEN or date <= to):
            return seg
    raise ValueError(f"{entry['series_id']}: no origin segment covers {date} (series_catalog.yaml)")


BREAK_STATUSES = ("proposed", "confirmed")


def confirmed_breaks(policy: dict, catalog: Optional[Dict[str, dict]] = None) -> Dict[tuple, dict]:
    """
    {(series_id, period): entry} for the policy's confirmed breaks. Every entry, proposed or
    confirmed, is checked: a known series, a period of its frequency, a status, a source and a note,
    and no repeats. Raises ValueError naming the entry.
    """
    seen, out = set(), {}
    for i, entry in enumerate(policy.get("breaks") or []):
        where = f"flag_policy.yaml breaks[{i}]"
        sid, when = entry.get("series"), period(entry.get("period"))
        if entry.get("status") not in BREAK_STATUSES:
            raise ValueError(f"{where}: status must be one of {BREAK_STATUSES}, not {entry.get('status')!r}")
        for field in ("source", "note"):
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                raise ValueError(f"{where}: {field} must be the source's own words (non-empty)")
        if catalog is not None:
            if sid not in catalog:
                raise ValueError(f"{where}: series {sid!r} is not in series_catalog.yaml")
            shapes = {"monthly": r"\d{4}-\d{2}", "quarterly": r"\d{4}-Q[1-4]", "annual": r"\d{4}",
                      "daily": r"\d{4}-\d{2}-\d{2}"}
            if not re.fullmatch(shapes[catalog[sid]["frequency"]], when):
                raise ValueError(f"{where}: period {when!r} is not a {catalog[sid]['frequency']} period")
        if (sid, when) in seen:
            raise ValueError(f"{where}: {sid} {when} is listed twice")
        seen.add((sid, when))
        if entry["status"] == "confirmed":
            out[(sid, when)] = entry
    return out


def revision_window(series_id: str, frequency: str, policy: dict):
    """An int (latest N periods are provisional) or 'publisher' (only the source's own marking)."""
    rule = (policy.get("series") or {}).get(series_id)
    if rule is not None:
        return rule["revision_window"]
    return policy["default_windows"][frequency]


def _strongest(candidates: List[str], precedence: List[str]) -> str:
    return min(candidates, key=precedence.index)


def assign_flags(df: pd.DataFrame, table: str, policy: Optional[dict] = None,
                 catalog: Optional[Dict[str, dict]] = None) -> pd.DataFrame:
    """A copy of `df` with every `status_flag` set by the flag policy; nothing else changes."""
    policy = policy if policy is not None else load_policy()
    catalog = catalog if catalog is not None else load_catalog()
    precedence = list(policy["precedence"])
    class_flags = policy["class_flags"]

    out = df.copy()
    flags = out["status_flag"].astype(str).tolist()
    dates = out["date"].astype(str).tolist()
    series = out["series_id"].astype(str).tolist()
    values = out["value"].tolist()

    unknown = sorted(set(series) - set(catalog))
    if unknown:
        raise ValueError(f"{table}: series not in series_catalog.yaml: {unknown}")

    # Latest `window` periods of each series, on the series' own dates
    provisional = set()
    publisher = set()
    for sid in sorted(set(series)):
        entry = catalog[sid]
        window = revision_window(sid, entry["frequency"], policy)
        if window == "publisher":
            publisher.add(sid)
            continue
        if int(window) > 0:
            own = sorted({d for d, s in zip(dates, series) if s == sid})
            provisional.update((sid, d) for d in own[-int(window):])

    breaks = confirmed_breaks(policy, catalog)
    final: List[Optional[str]] = [None] * len(out)
    derived_rows = []
    for i, (sid, date, flag, value) in enumerate(zip(series, dates, flags, values)):
        seg = segment_for(catalog[sid], date)
        if seg["class"] not in ORIGIN_CLASSES:
            raise ValueError(f"{sid}: unknown origin class {seg['class']!r}")
        candidates = ["A"]
        if value is None or (isinstance(value, float) and math.isnan(value)):
            candidates.append("M")
        if flag == "B" or (sid, date) in breaks:
            candidates.append("B")
        if (sid, date) in provisional or (sid in publisher and flag == "P"):
            candidates.append("P")
        if seg["class"] == "derived":
            derived_rows.append((i, seg, candidates))
            continue
        candidates.append(class_flags[seg["class"]])
        final[i] = _strongest(candidates, precedence)

    # Derived rows inherit from their inputs in the same period; repeat for derived-of-derived
    by_key = {(s, d): i for i, (s, d) in enumerate(zip(series, dates))}
    pending = derived_rows
    while pending:
        still = []
        for i, seg, candidates in pending:
            inputs = [by_key.get((s, dates[i])) for s in seg.get("inputs") or []]
            inputs = [j for j in inputs if j is not None]
            if any(final[j] is None for j in inputs):
                still.append((i, seg, candidates))
                continue
            final[i] = _strongest(candidates + [final[j] for j in inputs], precedence)
        if len(still) == len(pending):
            raise ValueError(f"{table}: derived series with circular inputs: "
                             f"{sorted({series[i] for i, _, _ in still})}")
        pending = still

    out["status_flag"] = final
    return out
