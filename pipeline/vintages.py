"""
pipeline.vintages
=================
Merging a fresh parser build into the published tables without losing earlier values
.

A published table keeps exactly one row per (date, series_id): the latest vintage. A fresh build
is compared with it key by key:

- key only in the fresh build      -> added, stamped with the new vintage
- key in both, value/flag/unit equal -> unchanged: the published row is kept as it is, including
  its realtime_start and source_hash
- key in both, value or unit differ -> revised: the fresh row replaces the published one with the
  new vintage, and the published row moves to the vintage history
- key in both, only the status flag differs -> flag update: the published row takes the new flag
  in place and keeps its vintage and hash; nothing moves to the history. The flag is a property of
  the observation's position in the series (a period leaving the provisional window goes from P
  to A), not a new publication of the value, so it is not a revision.
- key only in the published table  -> missing from the new release: kept, and reported, except
  for the series and dates named in `complete_from`: there the fresh build is complete,
  so the published row is withdrawn - it leaves the table and moves to the vintage history like a
  revised row, followed by a marker row (value NaN, flag M, the new vintage, source_hash
  "withdrawn") recording that the value no longer exists from that vintage on. This is passed
  explicitly for a one-time source change, never by default.

NaN equals NaN. A hash-only change covered by a provenance correction is a revision. A revision
must carry a vintage later than the row it supersedes; otherwise the merge is refused, because the
history would hold two rows with the same (date, series_id, realtime_start) key.

`merge_vintages` is pure (no clock, no network, no files). `prepare_history` builds and checks a
history without writing it (a merge writes it through merge_txn); `append_history` is
the direct writer.
`as_of` rebuilds a table as it was published at an earlier vintage from the table and its history.
"""

import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "src"))

from iraqdata.schema import CANONICAL_COLUMNS

KEY = ["date", "series_id"]
HISTORY_KEY = ["date", "series_id", "realtime_start"]
# source_hash of the history row that records a withdrawal (value NaN, flag M, the withdrawal vintage)
WITHDRAWN = "withdrawn"


class MergeResult(NamedTuple):
    table: pd.DataFrame
    superseded: pd.DataFrame
    added: List[Tuple[str, str]]
    revised: List[Dict]
    missing: List[Tuple[str, str]]
    changed: bool
    withdrawn: List[Tuple[str, str]] = []
    # [{series_id, date, old_flag, new_flag}] rows whose only change is the status flag
    flag_updated: List[Dict] = []


def _canonical(df: pd.DataFrame) -> pd.DataFrame:
    out = df[CANONICAL_COLUMNS].copy()
    out["value"] = out["value"].astype("float64")
    return out.reset_index(drop=True)


def _sorted_by(df: pd.DataFrame, cols: List[str]) -> bool:
    keys = list(zip(*(df[c].astype(str) for c in cols)))
    return keys == sorted(keys)


def _order_like(previous: pd.DataFrame, table: pd.DataFrame) -> pd.DataFrame:
    """Sort the merged table the way the published table is already sorted."""
    for cols in (["date", "series_id"], ["series_id", "date"]):
        if _sorted_by(previous, cols):
            return table.sort_values(cols, kind="mergesort").reset_index(drop=True)
    return table.reset_index(drop=True)


def _corrections_for(keys, old_hashes, new_hashes, table_name: str, corrections: Sequence[dict]) -> Dict:
    """{(date, series_id): correction id} for the keys whose hash change a provenance correction covers."""
    out = {}
    for (date, sid), old_h, new_h in zip(keys, old_hashes, new_hashes):
        if old_h == new_h:
            continue
        for c in corrections:
            if (c["table"] == table_name and sid in c["series"] and str(c["from"]) <= date <= str(c["to"])
                    and old_h == c["published_hash"] and new_h == c["corrected_hash"]):
                out[(date, sid)] = c["id"]
                break
    return out


def merge_vintages(
    previous: Optional[pd.DataFrame],
    fresh: pd.DataFrame,
    vintage: str,
    table_name: str = "table",
    complete_from: Optional[Dict[str, str]] = None,
    corrections: Sequence[dict] = (),
) -> MergeResult:
    """
    Merge a fresh build into the published table. See the module docstring for the rules.
    `corrections` are provenance corrections (pipeline/metadata/provenance_corrections.yaml):
    a row they cover whose only change is its source_hash becomes a revision.
    """
    fresh = _canonical(fresh)
    if fresh.duplicated(KEY).any():
        dup = fresh[fresh.duplicated(KEY, keep=False)].head(3)[KEY].values.tolist()
        raise ValueError(f"{table_name}: fresh build has duplicate (date, series_id) keys, e.g. {dup}")

    empty = fresh.iloc[0:0].copy()
    if previous is None or len(previous) == 0:
        table = fresh.copy()
        table["realtime_start"] = vintage
        table = table.sort_values(KEY, kind="mergesort").reset_index(drop=True)
        added = list(zip(table["series_id"], table["date"]))
        return MergeResult(table, empty, added, [], [], bool(added))

    previous = _canonical(previous)
    prev_i = previous.set_index(KEY)
    fresh_i = fresh.set_index(KEY)

    added_keys = fresh_i.index.difference(prev_i.index, sort=False)
    missing_keys = prev_i.index.difference(fresh_i.index, sort=False)
    common = prev_i.index.intersection(fresh_i.index, sort=False)

    old = prev_i.loc[common]
    new = fresh_i.loc[common]
    v_old = old["value"].to_numpy(dtype="float64")
    v_new = new["value"].to_numpy(dtype="float64")
    same_value = (v_old == v_new) | (np.isnan(v_old) & np.isnan(v_new))
    same_flag = old["status_flag"].to_numpy() == new["status_flag"].to_numpy()
    same_unit = old["unit"].to_numpy() == new["unit"].to_numpy()
    correction_of = _corrections_for(common, old["source_hash"].to_numpy(), new["source_hash"].to_numpy(),
                                     table_name, corrections)
    covered = np.array([k in correction_of for k in common], dtype=bool)
    is_revision = ~(same_value & same_unit) | covered
    revised_keys = common[is_revision]
    flag_only_keys = common[~is_revision & ~same_flag]

    # Missing rows of a series the fresh build is complete for (from a date) are withdrawn
    complete_from = complete_from or {}
    in_scope = [s in complete_from and d >= complete_from[s] for d, s in missing_keys]
    withdrawn_keys = missing_keys[in_scope] if len(missing_keys) else missing_keys
    missing_keys = missing_keys.difference(withdrawn_keys, sort=False)

    stale = [k for k in revised_keys.append(withdrawn_keys) if str(prev_i.at[k, "realtime_start"]) >= vintage]
    if stale:
        date, series_id = stale[0]
        raise ValueError(
            f"{table_name}: {series_id} {date} changed or was withdrawn, but the new vintage {vintage} is not later "
            f"than its published vintage {prev_i.at[stale[0], 'realtime_start']} "
            f"({len(stale)} revised row(s) affected). Pass --vintage YYYY-MM-DD "
            "(the date the new source was acquired)."
        )

    revised = [
        {
            "series_id": s, "date": d,
            "old_value": float(prev_i.at[(d, s), "value"]), "old_flag": prev_i.at[(d, s), "status_flag"],
            "new_value": float(fresh_i.at[(d, s), "value"]), "new_flag": fresh_i.at[(d, s), "status_flag"],
            "old_hash": prev_i.at[(d, s), "source_hash"], "new_hash": fresh_i.at[(d, s), "source_hash"],
            **({"correction": correction_of[(d, s)]} if (d, s) in correction_of else {}),
        }
        for d, s in revised_keys
    ]
    added = [(s, d) for d, s in added_keys]
    missing = [(s, d) for d, s in missing_keys]
    withdrawn = sorted((s, d) for d, s in withdrawn_keys)
    flag_updated = [
        {"series_id": s, "date": d, "old_flag": prev_i.at[(d, s), "status_flag"],
         "new_flag": fresh_i.at[(d, s), "status_flag"]}
        for d, s in flag_only_keys
    ]
    changed = bool(len(added_keys) or len(revised_keys) or len(withdrawn_keys) or flag_updated)

    if not changed:
        return MergeResult(previous, empty, [], [], missing, False)

    superseded = prev_i.loc[revised_keys.append(withdrawn_keys)].reset_index()[CANONICAL_COLUMNS]
    if len(withdrawn_keys):
        # A withdrawal is itself a vintage: from `vintage` on, the value no longer exists
        markers = prev_i.loc[withdrawn_keys].reset_index()[CANONICAL_COLUMNS]
        markers = markers.assign(value=np.nan, status_flag="M", realtime_start=vintage, source_hash=WITHDRAWN)
        superseded = pd.concat([superseded, markers], ignore_index=True)

    replacements = fresh_i.loc[revised_keys].copy()
    replacements["realtime_start"] = vintage
    kept = prev_i.drop(index=revised_keys.append(withdrawn_keys))
    if len(flag_only_keys):  # the published row keeps its value, hash and vintage; only the flag moves
        kept.loc[flag_only_keys, "status_flag"] = fresh_i.loc[flag_only_keys, "status_flag"].to_numpy()
    additions = fresh_i.loc[added_keys].copy()
    additions["realtime_start"] = vintage

    table = pd.concat([kept, replacements, additions]).reset_index()[CANONICAL_COLUMNS]
    table["value"] = table["value"].astype("float64")
    table = _order_like(previous, table)
    return MergeResult(table, superseded.reset_index(drop=True), added, revised, missing, True, withdrawn,
                       flag_updated)


def as_of(table: pd.DataFrame, history: Optional[pd.DataFrame], vintage: str) -> pd.DataFrame:
    """
    The table as it was published at `vintage`: its rows with realtime_start <= vintage,
    plus history rows with realtime_start <= vintage for keys that have no such row in the table
    (values later revised or withdrawn). Where several rows of a key qualify, the latest vintage
    wins; a key whose latest row is a withdrawal marker is left out. Sorted the way `table` is
    sorted; dtypes as in `table`.
    """
    rows = [_canonical(table)]
    if history is not None and len(history):
        rows.append(_canonical(history))
    pool = pd.concat(rows, ignore_index=True)
    pool = pool[pool["realtime_start"].astype(str) <= vintage]
    pool = pool.sort_values(["realtime_start"], kind="mergesort").drop_duplicates(KEY, keep="last")
    pool = pool[pool["source_hash"] != WITHDRAWN]  # withdrawn by then
    out = _order_like(_canonical(table), pool.reset_index(drop=True))
    return out.astype(table[CANONICAL_COLUMNS].dtypes.to_dict())


def prepare_history(path: Path, rows: pd.DataFrame) -> Optional[pd.DataFrame]:
    """
    The vintage history at `path` with the superseded `rows` appended, checked but not written
. Existing rows are never changed or reordered; new rows go after them,
    sorted by (date, series_id, realtime_start). Raises if a (date, series_id, realtime_start)
    key would repeat. Returns None when `rows` is empty.
    """
    if rows is None or len(rows) == 0:
        return None
    path = Path(path)
    new = _canonical(rows).sort_values(HISTORY_KEY, kind="mergesort")
    existing = pd.read_parquet(path) if path.exists() else new.iloc[0:0]
    combined = pd.concat([_canonical(existing), new], ignore_index=True)
    if combined.duplicated(HISTORY_KEY).any():
        dup = combined[combined.duplicated(HISTORY_KEY, keep=False)].head(3)[HISTORY_KEY].values.tolist()
        raise ValueError(f"{path.name}: vintage history would repeat a (date, series_id, realtime_start) key, e.g. {dup}")
    return combined


def append_history(path: Path, rows: pd.DataFrame) -> None:
    """
    Append superseded rows to a table's vintage history (prepare_history, then write it).
    Does nothing when `rows` is empty.
    """
    combined = prepare_history(path, rows)
    if combined is None:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    combined.to_parquet(tmp, index=False)
    tmp.replace(path)
