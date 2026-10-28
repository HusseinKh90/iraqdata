"""
pipeline.catalog_check
======================
Checks that the series catalog agrees with the data it describes.

    python pipeline/catalog_check.py                      # catalog vs pipeline/data/garden
    python pipeline/catalog_check.py --tables DIR         # vs another set of tables (a release)

For every series the catalog's `start_date`, `unit`, `frequency` and table must match the rows,
every series in the data must have an entry, an active entry must have rows and a withdrawn one
(`status: withdrawn`) must have none. A withdrawn series' start date is checked against the
vintage history. Origin segments must start at `start_date`, follow each other without gaps or
overlaps, and cover the last published period. The output is sorted, so two runs on the same
inputs print the same lines.
"""

import argparse
import datetime as dt
import re
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "src"))
sys.path.insert(0, str(repo_root / "pipeline"))

import pandas as pd  # noqa: E402
import yaml  # noqa: E402

from iraqdata.catalog import SERIES_TO_TABLE  # noqa: E402

CATALOG_PATH = repo_root / "src" / "iraqdata" / "series_catalog.yaml"
GARDEN_DIR = repo_root / "pipeline" / "data" / "garden"
HISTORY_DIR = repo_root / "pipeline" / "data" / "history"
MANIFEST_PATH = repo_root / "pipeline" / "metadata" / "raw_manifest.yaml"
OPEN = "open"
WITHDRAWN = "withdrawn"

DATE_SHAPES = {
    "daily": re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    "monthly": re.compile(r"^\d{4}-\d{2}$"),
    "quarterly": re.compile(r"^\d{4}-Q[1-4]$"),
    "annual": re.compile(r"^\d{4}$"),
}


class Discrepancy(NamedTuple):
    rule: str            # start | unit | frequency | table | coverage | withdrawn | origin | source
    series_id: str
    field: str
    catalog_value: object
    data_value: object
    hint: str = ""


# =====================================================================
# Periods
# =====================================================================

def normalize_period(value, frequency: str) -> str:
    """A catalog or data period in the ISO form of its frequency.

    YAML reads `2004` as an int and an unquoted `2004-01-01` as a date; both compare equal to the
    string form.
    """
    if isinstance(value, dt.datetime):
        value = value.date()
    if isinstance(value, dt.date):
        text = value.isoformat()
        return text[:7] if frequency == "monthly" else text
    return str(value).strip()


def next_period(period: str, frequency: str) -> str:
    """The period right after `period`."""
    if frequency == "daily":
        return (dt.date.fromisoformat(period) + dt.timedelta(days=1)).isoformat()
    if frequency == "monthly":
        year, month = int(period[:4]), int(period[5:7])
        return f"{year + month // 12}-{month % 12 + 1:02d}"
    if frequency == "quarterly":
        year, q = int(period[:4]), int(period[-1])
        return f"{year + q // 4}-Q{q % 4 + 1}"
    return str(int(period) + 1)


# =====================================================================
# Loading
# =====================================================================

def load_catalog(path: Path = CATALOG_PATH) -> List[dict]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f).get("series", [])


def load_provenance(manifest_path: Path = None):
    """(raw manifest, provenance corrections) for the source rule; (None, ()) without a manifest."""
    import raw_audit

    manifest_path = MANIFEST_PATH if manifest_path is None else Path(manifest_path)
    if not manifest_path.is_file():
        return None, ()
    return raw_audit.load_manifest(manifest_path), raw_audit.load_corrections()


def load_tables(directory: Path) -> Dict[str, pd.DataFrame]:
    """{table: rows} from `*.parquet` in `directory`, or from `*.csv` when it holds no Parquet."""
    directory = Path(directory)
    if not directory.is_dir():
        raise FileNotFoundError(f"No such directory: {directory}")
    paths = sorted(directory.glob("*.parquet"))
    if paths:
        return {p.stem: pd.read_parquet(p) for p in paths}
    tables = {}
    for p in sorted(directory.glob("*.csv")):
        df = pd.read_csv(p, dtype=str, keep_default_na=False, na_values={"value": [""]}, encoding="utf-8")
        df["value"] = df["value"].astype("float64")
        tables[p.stem] = df
    return tables


# =====================================================================
# The check
# =====================================================================

def _rows_by_series(tables: Dict[str, pd.DataFrame]) -> Dict[str, Dict[str, pd.DataFrame]]:
    """{series_id: {table: that series' rows}}."""
    out: Dict[str, Dict[str, pd.DataFrame]] = {}
    for table, df in sorted(tables.items()):
        for sid, rows in df.groupby(df["series_id"].astype(str), sort=True):
            out.setdefault(sid, {})[table] = rows
    return out


def _first_value_date(rows: pd.DataFrame) -> Optional[str]:
    dates = rows.loc[rows["value"].notna(), "date"].astype(str)
    return dates.min() if len(dates) else None


def _check_described(sid: str, entry: dict, freq: str, start: str, rows: pd.DataFrame) -> List[Discrepancy]:
    """The start, unit and frequency rules on the rows a series published."""
    out: List[Discrepancy] = []
    first = _first_value_date(rows)
    if first is not None and first != start:
        out.append(Discrepancy("start", sid, "start_date", start, first,
                               f"set `start_date: {first}` and origin[0].from"))
    units = sorted(set(rows["unit"].astype(str)))
    if units != [str(entry.get("unit"))]:
        hint = f"set `unit: {units[0]}`" if len(units) == 1 else "the rows carry more than one unit"
        out.append(Discrepancy("unit", sid, "unit", entry.get("unit"), ", ".join(units), hint))
    shape = DATE_SHAPES.get(freq)
    bad = sorted(d for d in set(rows["date"].astype(str)) if shape is None or not shape.match(d))
    if bad:
        out.append(Discrepancy("frequency", sid, "frequency", freq, f"{len(bad)} dates such as {bad[0]}",
                               "set the frequency the dates have"))
    return out


def _check_origin(sid: str, entry: dict, freq: str, start: str, last: Optional[str]) -> List[Discrepancy]:
    out: List[Discrepancy] = []
    segments = entry.get("origin") or []
    if not segments:
        return [Discrepancy("origin", sid, "origin", None, None, "add at least one origin segment")]
    spans = [(normalize_period(s["from"], freq), normalize_period(s["to"], freq)) for s in segments]
    if spans[0][0] != start:
        out.append(Discrepancy("origin", sid, "origin[0].from", spans[0][0], start,
                               f"set origin[0].from to {start}"))
    for i, (frm, to) in enumerate(spans):
        if to == OPEN and i != len(spans) - 1:
            out.append(Discrepancy("origin", sid, f"origin[{i}].to", OPEN, None,
                                   "only the last segment may be open"))
        elif to != OPEN and to < frm:
            out.append(Discrepancy("origin", sid, f"origin[{i}]", f"{frm}..{to}", None,
                                   "a segment may not end before it starts"))
        prev_to = spans[i - 1][1] if i else OPEN
        shape = DATE_SHAPES.get(freq)
        # Periods not in the frequency's form are reported by the frequency rule, not here
        if prev_to != OPEN and shape and shape.match(prev_to) and shape.match(frm):
            expected = next_period(prev_to, freq)
            if frm != expected:
                out.append(Discrepancy("origin", sid, f"origin[{i}].from", frm, expected,
                                       "segments must follow each other without a gap or overlap"))
    final_to = spans[-1][1]
    if entry.get("status") == WITHDRAWN:
        if final_to == OPEN:
            out.append(Discrepancy("origin", sid, f"origin[{len(spans) - 1}].to", OPEN, None,
                                   "a withdrawn series' last segment must be closed"))
    elif last is not None and final_to != OPEN and final_to < last:
        out.append(Discrepancy("origin", sid, f"origin[{len(spans) - 1}].to", final_to, last,
                               f"extend the last segment to cover {last}"))
    return out


def _segment_index(spans, date: str) -> Optional[int]:
    for i, (frm, to) in enumerate(spans):
        if frm <= date and (to == OPEN or date <= to):
            return i
    return None


def _check_sources(sid: str, entry: dict, freq: str, rows: pd.DataFrame, manifest: dict,
                   corrections: Sequence[dict], counts: Dict[str, int]) -> List[Discrepancy]:
    """
    The source rule: every row's `source_hash` resolves, through the raw manifest, to
    files whose `source_ref` is the one the covering origin segment names. Derived segments take
    their sources from their inputs and are not checked here; unresolved hashes are counted.
    """
    import raw_audit

    files = manifest.get("files", [])
    refs_of = {e["path"]: e.get("source_ref") for e in files}
    groups = {g["id"]: g for g in manifest.get("input_groups", [])}
    members = {g["name"]: g["members"] for g in groups.values()}
    segments = entry.get("origin") or []
    spans = [(normalize_period(s["from"], freq), normalize_period(s["to"], freq)) for s in segments]
    found: Dict[int, set] = {}
    for h, date in rows[["source_hash", "date"]].astype(str).drop_duplicates().itertuples(index=False):
        i = _segment_index(spans, date)
        if i is None or segments[i].get("class") == "derived":
            continue
        case, target = raw_audit.classify_hash(h, files, groups, corrections)
        if case in ("unresolved", "ambiguous") or target is None:
            counts["unresolved"] = counts.get("unresolved", 0) + 1
            continue
        paths = members.get(target, []) if case == "group" else [target]
        found.setdefault(i, set()).update(refs_of.get(p) for p in paths)
    out = []
    for i, refs in sorted(found.items()):
        expected = segments[i].get("source_ref")
        if refs != {expected}:
            names = ", ".join(sorted(str(r) for r in refs))
            out.append(Discrepancy("source", sid, f"origin[{i}].source_ref", expected, names,
                                   f"the rows of {spans[i][0]}..{spans[i][1]} come from {names}"))
    return out


def check(catalog, tables: Dict[str, pd.DataFrame], history: Optional[Dict[str, pd.DataFrame]] = None,
          table_of: Optional[Dict[str, str]] = None, info: Optional[List[str]] = None,
          manifest: Optional[dict] = None, corrections: Sequence[dict] = ()) -> List[Discrepancy]:
    """
    Every disagreement between `catalog` (a list of entries, or the loaded YAML document) and
    `tables`, sorted by (series_id, rule). `history` holds the vintage history tables; without it
    the withdrawn start-date rule is skipped and noted in `info`. With the raw `manifest`, the source
    rule also checks that each segment's `source_ref` is the source its rows were parsed from.
    """
    entries = catalog.get("series", []) if isinstance(catalog, dict) else list(catalog)
    table_of = SERIES_TO_TABLE if table_of is None else table_of
    info = [] if info is None else info
    data = _rows_by_series(tables)
    past = _rows_by_series(history) if history is not None else None
    if past is None:
        info.append("no vintage history given: withdrawn series' start dates not checked")
    out: List[Discrepancy] = []
    counts: Dict[str, int] = {}

    known = {e["series_id"] for e in entries}
    for sid in sorted(set(data) - known):
        out.append(Discrepancy("coverage", sid, "series_id", None, ", ".join(sorted(data[sid])),
                               "add a catalog entry for this series"))

    for entry in entries:
        sid = entry["series_id"]
        freq = str(entry.get("frequency", ""))
        start = normalize_period(entry.get("start_date", ""), freq)
        withdrawn = entry.get("status") == WITHDRAWN
        by_table = data.get(sid, {})
        rows = pd.concat(by_table.values()) if by_table else None

        if withdrawn and rows is not None:
            out.append(Discrepancy("withdrawn", sid, "status", WITHDRAWN,
                                   f"{len(rows)} rows in {', '.join(sorted(by_table))}",
                                   "remove the rows or drop `status: withdrawn`"))
        if not withdrawn and rows is None:
            out.append(Discrepancy("coverage", sid, "rows", "active", "no rows",
                                   "publish the series or mark it `status: withdrawn`"))

        if rows is not None:
            expected = table_of.get(sid)
            if sorted(by_table) != [expected]:
                out.append(Discrepancy("table", sid, "table", expected, ", ".join(sorted(by_table)),
                                       "update SERIES_TO_TABLE in src/iraqdata/catalog.py"))

        # A withdrawn series is described by what it published: its values in the vintage history
        described = rows
        if withdrawn and rows is None and past is not None and table_of.get(sid) not in history:
            info.append(f"{sid}: no vintage history for table {table_of.get(sid)}: withdrawn start date not checked")
        elif withdrawn and rows is None and past is not None:
            hist = past.get(sid)
            described = pd.concat(hist.values()) if hist else None
            if described is None or _first_value_date(described) is None:
                out.append(Discrepancy("withdrawn", sid, "history", start, "no rows",
                                       "a withdrawn series must have published values in the vintage history"))
                described = None
            else:
                described = described[described["value"].notna()]

        last = None
        if described is not None:
            out.extend(_check_described(sid, entry, freq, start, described))
            if not withdrawn:
                values = described.loc[described["value"].notna(), "date"].astype(str)
                last = values.max() if len(values) else None
        out.extend(_check_origin(sid, entry, freq, start, last))
        if manifest is not None and rows is not None:
            out.extend(_check_sources(sid, entry, freq, rows, manifest, corrections, counts))

    if manifest is None:
        info.append("no raw manifest given: segment sources not checked")
    elif counts.get("unresolved"):
        info.append(f"source check: {counts['unresolved']} (hash, date) pairs with unresolved hashes skipped "
                    "(see raw_audit.py provenance)")
    return sorted(out, key=lambda d: (d.series_id, d.rule, d.field))


def format_line(d: Discrepancy) -> str:
    hint = f" -> {d.hint}" if d.hint else ""
    return f"[CATALOG] {d.series_id} {d.rule}: {d.field} catalog {d.catalog_value}, data {d.data_value}{hint}"


# =====================================================================
# CLI
# =====================================================================

def main(argv: Optional[Sequence[str]] = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Check the series catalog against the data.")
    parser.add_argument("--tables", type=Path, default=GARDEN_DIR, help="tables to check against")
    parser.add_argument("--history", type=Path, default=HISTORY_DIR, help="vintage history (withdrawn series)")
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH, help="catalog to check")
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH, help="raw manifest (source rule)")
    args = parser.parse_args(argv)
    try:
        catalog = load_catalog(args.catalog)
        tables = load_tables(args.tables)
        history = load_tables(args.history) if args.history.is_dir() else None
        manifest, corrections = load_provenance(args.manifest)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if not tables:
        print(f"ERROR: no tables in {args.tables}", file=sys.stderr)
        return 2
    info: List[str] = []
    problems = check(catalog, tables, history, info=info, manifest=manifest, corrections=corrections)
    for d in problems:
        print(format_line(d))
    for line in info:
        print(f"[INFO] {line}")
    print(f"Catalog check: {len(problems)} discrepancies in {len(catalog)} series")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
