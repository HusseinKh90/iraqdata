"""
Publishing Pipeline & Release Artifact Generator for iraqdata.

Automates the packaging of clean Garden datasets into release artifacts:
1. Exports clean, standard CSV mirrors for researchers using Stata, R, Excel, or EViews.
2. Packages production Parquet files for Python, Julia, and Arrow ecosystems.
3. Generates the standard Frictionless Data Package descriptor ('datapackage.json').
4. Generates cryptographic checksum manifests ('checksums.sha256') for academic verification.
5. Lists the GitHub upload name of every release file ('release-assets.txt'); release assets are
   flat, so 'history/<table>.parquet' is uploaded as 'history.<table>.parquet'.

Before writing anything it runs the CI gate (validate.py --release) on the tables it is about to
export, and stops when the gate fails, or when the series catalog disagrees with those
tables (pipeline/catalog_check.py).

The output is deterministic: the same garden data and code version give byte-identical
files on every run and platform. CSVs always end lines with CRLF, checksums.sha256 and
datapackage.json with LF; the descriptor records the building code version and carries a
"created" time only when SOURCE_DATE_EPOCH is set.

A release that exists is never rewritten: --tag is required, and the export refuses a target
folder that already holds files, so a mistyped or reused tag cannot overwrite published bytes.

Usage:
    python pipeline/export_release.py --tag data-YYYY-MM [--output-dir DIR]
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

# Add src (iraqdata) and pipeline (validate) to sys.path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "src"))
sys.path.append(str(repo_root / "pipeline"))

import pandas as pd
import pyarrow.parquet as pq
import yaml

from iraqdata.catalog import SERIES_DIRECT_SOURCES, get_catalog, is_official, list_tables
from iraqdata.schema import validate_dataframe

import catalog_check
import iraqdata
import validate

# The client reads the newest data-YYYY-MM tag as "latest"
TAG_PATTERN = re.compile(r"data-\d{4}-(0[1-9]|1[0-2])")

# RFC 4180; matches the published data-2026-10 bytes
CSV_LINE_TERMINATOR = "\r\n"

# Release path -> GitHub asset name, one tab-separated pair per line
RELEASE_ASSETS = "release-assets.txt"


class ReleaseGateError(RuntimeError):
    """The CI gate failed on the tables to be exported; nothing was written."""


class ReleaseExistsError(RuntimeError):
    """The target folder already holds files; a release is never rewritten."""


def release_tag(text: str) -> str:
    """argparse type: a tag of the form data-YYYY-MM."""
    if not TAG_PATTERN.fullmatch(text):
        raise argparse.ArgumentTypeError(f"{text!r} is not a release tag of the form data-YYYY-MM")
    return text


def compute_sha256(file_path: Path) -> str:
    """Compute the SHA-256 cryptographic hash of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def asset_name(release_path: str) -> str:
    """GitHub asset name of a release file: release assets are flat, so '/' becomes '.'."""
    return release_path.replace("/", ".")


def release_assets(release_paths: list[str]) -> dict[str, str]:
    """{release path: asset name}, sorted by path. Two paths with the same asset name raise ValueError."""
    assets: dict[str, str] = {}
    owner: dict[str, str] = {}
    for path in sorted(release_paths):
        name = asset_name(path)
        if name in owner:
            raise ValueError(f"Release files '{owner[name]}' and '{path}' would both be uploaded as '{name}'.")
        owner[name] = path
        assets[path] = name
    return assets


def _created_from_source_date_epoch() -> str | None:
    """The descriptor's "created" time from SOURCE_DATE_EPOCH (reproducible-builds.org), or None."""
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if not epoch:
        return None
    moment = datetime.datetime.fromtimestamp(int(epoch), tz=datetime.timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_frictionless_schema() -> dict[str, Any]:
    """Define the Frictionless Table Schema matching the Canonical Observation Schema."""
    return {
        "fields": [
            {
                "name": "date",
                "type": "string",
                "description": "ISO period representation (YYYY-MM-DD daily, YYYY-MM monthly, YYYY-Qn quarterly, YYYY annual)",
            },
            {
                "name": "series_id",
                "type": "string",
                "description": "Canonical indicator code in dataset.series format (e.g. money.m2, fiscal.balance)",
            },
            {
                "name": "value",
                "type": "number",
                "description": "Pure numeric float value without formatting, commas, or placeholders",
            },
            {
                "name": "unit",
                "type": "string",
                "description": "Native unit and scale as published (e.g. BILLION_IQD, MILLION_USD, INDEX)",
            },
            {
                "name": "status_flag",
                "type": "string",
                "description": (
                    "SDMX observation status: A = normal, P = provisional, B = break, E = estimated, "
                    "M = missing, U = low reliability (includes hand-transcribed values whose source "
                    "document is not archived)"
                ),
            },
            {
                "name": "realtime_start",
                "type": "string",
                "description": "ISO publication/release snapshot date tracking vintage provenance",
            },
            {
                "name": "source_hash",
                "type": "string",
                "description": "SHA-256 fingerprint of the raw source file for 100% provenance verification",
            },
        ],
        "primaryKey": ["date", "series_id"],
    }


SOURCES_PATH = Path(__file__).resolve().parent / "metadata" / "sources.yaml"


def load_sources() -> list[dict[str, Any]]:
    """The terms-of-reuse records, as datapackage.json `sources`."""
    with open(SOURCES_PATH, encoding="utf-8") as f:
        records = yaml.safe_load(f).get("sources", [])
    return [{"id": r["id"], "title": f"{r['publisher']}, {r['title']}", "path": r["url"], "terms": r["terms"],
             "licence": r["licence"], "status": r["status"], "redistribution": " ".join(str(r["redistribution"]).split()),
             "attribution": r["attribution"], "checked": str(r["checked"])} for r in records]


def series_source_refs(s: dict[str, Any], by_id: dict[str, dict[str, Any]] | None = None,
                       _seen: frozenset = frozenset()) -> list[str]:
    """Sorted terms-of-reuse ids of a series' origin segments; a derived segment takes its inputs'."""
    by_id = by_id if by_id is not None else {e["series_id"]: e for e in get_catalog().get("series", [])}
    refs: set[str] = set()
    for seg in s.get("origin", []):
        if seg.get("source_ref"):
            refs.add(seg["source_ref"])
        for sid in seg.get("inputs") or []:
            if sid in by_id and sid not in _seen:
                refs.update(series_source_refs(by_id[sid], by_id, _seen | {s["series_id"]}))
    return sorted(refs)


def series_catalog_entry(s: dict[str, Any], by_id: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """One seriesCatalog entry of datapackage.json, from a series_catalog.yaml entry."""
    return {
        "series_id": s["series_id"],
        "name_en": s.get("name_en", ""),
        "name_ar": s.get("name_ar", ""),
        "category": s.get("category", ""),
        "frequency": s.get("frequency", ""),
        "unit": s.get("unit", ""),
        "source": SERIES_DIRECT_SOURCES.get(s["series_id"], ""),
        "startDate": s.get("start_date", ""),
        # Definitions such as the BIS net position's sign travel with the release
        "description": s.get("description", ""),
        "origin": [{k: (str(v) if k in ("from", "to") else v) for k, v in seg.items()}
                   for seg in s.get("origin", [])],
        "official": is_official(s.get("origin", [])),
        "status": s.get("status", "active"),
        # Ids into the package-level `sources` (terms of reuse)
        "sources": series_source_refs(s, by_id),
    }


def export_history(
    tables: list[str],
    history_path: Path,
    out_path: Path,
    resources: list[dict[str, Any]],
    checksum_lines: list[str],
) -> int:
    """
    Export each table's vintage history as history/<table>.{parquet,csv},
    with a datapackage resource keyed on (date, series_id, realtime_start) and checksum lines.
    Tables without a history file are skipped; returns the number of files written.
    """
    written = 0
    for tbl_name in sorted(tables):
        src = history_path / f"{tbl_name}.parquet"
        if not src.is_file():
            continue
        df = pq.read_table(src).to_pandas()
        errors = validate_dataframe(df, dataset_name=f"history/{tbl_name}")
        if errors:
            raise ValueError(f"Vintage history {src} fails Tier 1:\n" + "\n".join(errors))
        (out_path / "history").mkdir(parents=True, exist_ok=True)
        schema = build_frictionless_schema()
        schema["primaryKey"] = ["date", "series_id", "realtime_start"]
        for fmt, mediatype in (("parquet", "application/vnd.apache.parquet"), ("csv", "text/csv")):
            dst = out_path / "history" / f"{tbl_name}.{fmt}"
            if fmt == "parquet":
                shutil.copy2(src, dst)
            else:
                df.to_csv(dst, index=False, encoding="utf-8", lineterminator=CSV_LINE_TERMINATOR)
            digest = compute_sha256(dst)
            checksum_lines.append(f"{digest}  history/{tbl_name}.{fmt}")
            resources.append({
                "name": f"{tbl_name}-history-{fmt}",
                "path": f"history/{tbl_name}.{fmt}",
                "profile": "tabular-data-resource",
                "format": fmt,
                "mediatype": mediatype,
                "bytes": dst.stat().st_size,
                "hash": f"sha256:{digest}",
                "rows": len(df),
                "description": f"Superseded vintages of {tbl_name} (append-only vintage history)",
                "schema": schema,
            })
            written += 1
        print(f"  [EXPORTED] history/{tbl_name:22} | {len(df):6} rows")
    return written


def export_release(
    tag: str,
    output_dir: Path | None = None,
    garden_dir: Path | None = None,
    history_dir: Path | None = None,
    reference_copy: bool = True,
) -> dict[str, Any]:
    """
    Export all Garden tables to Parquet and CSV, accompanied by datapackage.json.

    Parameters
    ----------
    tag : str
        Release version tag (e.g. 'data-2026-10').
    output_dir : Path, optional
        Target output directory. Defaults to 'release/<tag>/'. It must not exist or must be empty.
    garden_dir : Path, optional
        Directory containing clean Parquet datasets. Defaults to 'pipeline/data/garden/'.
    history_dir : Path, optional
        Directory of vintage histories. Defaults to 'pipeline/data/history/'; tables
        without a history file are skipped, so a release without revisions is unchanged.
    reference_copy : bool
        Also copy datapackage.json to pipeline/data/ (default True; tests pass False).

    Returns
    -------
    dict[str, Any]
        The compiled datapackage.json dictionary.
    """
    repo_root = Path(__file__).resolve().parent.parent
    garden_path = garden_dir or (repo_root / "pipeline" / "data" / "garden")
    out_path = output_dir or (repo_root / "release" / tag)
    if out_path.exists() and (not out_path.is_dir() or any(out_path.iterdir())):
        raise ReleaseExistsError(f"{out_path} already exists and is not empty. A release is never rewritten: "
                                 "export under a new tag, or into an empty folder.")

    # The CI gate on the tables about to be exported, before anything is written
    gate_files = [garden_path / f"{t}.parquet" for t in sorted(list_tables())]
    gate_files += sorted((repo_root / "pipeline" / "seeds").glob("*.parquet"))
    code = validate.run_gatekeeper(gate_files, validate.load_acknowledgements(), release=True, freshness=False,
                                   as_of=validate.today_utc(), all_datasets=True)
    if code != 0:
        raise ReleaseGateError("Release gate failed; nothing was exported. Fix or acknowledge the issues listed above.")

    # The series metadata must agree with the tables it is shipped with
    catalog = get_catalog()
    history_path = history_dir or (repo_root / "pipeline" / "data" / "history")
    release_tables = {t: pd.read_parquet(garden_path / f"{t}.parquet") for t in sorted(list_tables())}
    history_tables = catalog_check.load_tables(history_path) if history_path.is_dir() else None
    manifest, corrections = catalog_check.load_provenance()
    problems = catalog_check.check(catalog, release_tables, history_tables, manifest=manifest,
                                   corrections=corrections)
    if problems:
        lines = "\n".join(catalog_check.format_line(d) for d in problems)
        raise ReleaseGateError(f"The series catalog disagrees with the data; nothing was exported.\n{lines}")

    out_path.mkdir(parents=True, exist_ok=True)
    series_catalog_list = catalog.get("series", [])

    print("=" * 70)
    print(f"iraqdata Release Artifacts Exporter — [{tag}]")
    print(f"Source Garden Directory: {garden_path}")
    print(f"Target Output Directory: {out_path}")
    print("=" * 70)

    resources: list[dict[str, Any]] = []
    checksum_lines: list[str] = []
    total_observations = 0

    tables = list_tables()

    for tbl_name in sorted(tables):
        src_parquet = garden_path / f"{tbl_name}.parquet"
        if not src_parquet.is_file():
            raise FileNotFoundError(f"Missing garden dataset: {src_parquet}")

        # Read dataset
        arrow_tbl = pq.read_table(src_parquet)
        df = arrow_tbl.to_pandas()
        row_count = len(df)
        total_observations += row_count
        unique_series = sorted(df["series_id"].unique().tolist())
        min_date = str(df["date"].min())
        max_date = str(df["date"].max())

        # Determine frequency from dates
        dates = df["date"].astype(str)
        if dates.str.match(r"^\d{4}-\d{2}-\d{2}$").any():
            freq = "daily"
        elif dates.str.match(r"^\d{4}-\d{2}$").any():
            freq = "monthly"
        elif dates.str.match(r"^\d{4}-Q[1-4]$").any():
            freq = "quarterly"
        else:
            freq = "annual"

        # 1. Export Parquet artifact
        dst_parquet = out_path / f"{tbl_name}.parquet"
        shutil.copy2(src_parquet, dst_parquet)
        pq_hash = compute_sha256(dst_parquet)
        pq_bytes = dst_parquet.stat().st_size
        checksum_lines.append(f"{pq_hash}  {tbl_name}.parquet")

        # 2. Export CSV artifact (UTF-8, without index)
        dst_csv = out_path / f"{tbl_name}.csv"
        df.to_csv(dst_csv, index=False, encoding="utf-8", lineterminator=CSV_LINE_TERMINATOR)
        csv_hash = compute_sha256(dst_csv)
        csv_bytes = dst_csv.stat().st_size
        checksum_lines.append(f"{csv_hash}  {tbl_name}.csv")

        print(f"  [EXPORTED] {tbl_name:30} | {row_count:6} rows | Parquet ({pq_bytes/1024:.1f} KB) | CSV ({csv_bytes/1024:.1f} KB)")

        # Record resource definitions
        table_schema = build_frictionless_schema()

        # Parquet resource
        resources.append({
            "name": f"{tbl_name}-parquet",
            "path": f"{tbl_name}.parquet",
            "profile": "tabular-data-resource",
            "format": "parquet",
            "mediatype": "application/vnd.apache.parquet",
            "bytes": pq_bytes,
            "hash": f"sha256:{pq_hash}",
            "rows": row_count,
            "frequency": freq,
            "temporal": {"start": min_date, "end": max_date},
            "seriesCount": len(unique_series),
            "series": unique_series,
            "schema": table_schema,
        })

        # CSV resource
        resources.append({
            "name": f"{tbl_name}-csv",
            "path": f"{tbl_name}.csv",
            "profile": "tabular-data-resource",
            "format": "csv",
            "mediatype": "text/csv",
            "bytes": csv_bytes,
            "hash": f"sha256:{csv_hash}",
            "rows": row_count,
            "frequency": freq,
            "temporal": {"start": min_date, "end": max_date},
            "seriesCount": len(unique_series),
            "series": unique_series,
            "schema": table_schema,
        })

    history_files = export_history(
        sorted(tables), history_dir or (repo_root / "pipeline" / "data" / "history"),
        out_path, resources, checksum_lines,
    )
    assets = release_assets([line.split("  ", 1)[1] for line in checksum_lines] + ["checksums.sha256", "datapackage.json"])

    # 3. Write Checksums File
    checksum_file = out_path / "checksums.sha256"
    checksum_file.write_text("\n".join(checksum_lines) + "\n", encoding="utf-8", newline="\n")
    print(f"\n  [CHECKSUMS] Saved SHA-256 manifest to: {checksum_file.name}")

    # 4. Compile Frictionless datapackage.json
    datapackage: dict[str, Any] = {
        "profile": "tabular-data-package",
        "name": "iraqdata",
        "title": "Iraq Macroeconomic Data Package",
        "description": (
            "Open, documented, and reproducible macroeconomic data package for Iraq. "
            "Covers monetary aggregates, official and parallel exchange rates, crude oil production "
            "and prices, consumer price inflation, public finances, balance of payments, merchandise "
            "trade, quarterly national accounts (GDP), and external cross-border banking. "
            "Compiled and derived data are licensed CC-BY-4.0; source data remain subject to each "
            "publisher's terms, listed under `sources`."
        ),
        "version": iraqdata.__version__,
        "release": tag,
        "homepage": f"https://github.com/{iraqdata.storage.DEFAULT_REPO}",
        "contributors": [
            {
                "title": "Hussein Khalid",
                "role": "author",
            }
        ],
        "licenses": [
            {
                "name": "CC-BY-4.0",
                "title": "Creative Commons Attribution 4.0 International",
                "path": "https://creativecommons.org/licenses/by/4.0/",
                "scope": "Compiled and derived data. Source data keep their publishers' terms (see sources).",
            }
        ],
        "sources": load_sources(),
        "keywords": [
            "iraq",
            "macroeconomics",
            "time-series",
            "central-bank-of-iraq",
            "cosit",
            "oil",
            "inflation",
            "exchange-rates",
            "fiscal",
            "gdp",
        ],
        "seriesCatalog": {
            "totalSeries": len(series_catalog_list),
            "series": [
                series_catalog_entry(s, {e["series_id"]: e for e in series_catalog_list})
                for s in series_catalog_list
            ],
        },
        "resources": resources,
    }
    created = _created_from_source_date_epoch()
    if created is not None:
        # Keep "created" right after "release", where earlier releases had it
        datapackage = {k: v for item in datapackage.items()
                       for k, v in ([item, ("created", created)] if item[0] == "release" else [item])}

    datapackage_path = out_path / "datapackage.json"
    with open(datapackage_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(datapackage, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"  [DESCRIPTOR] Compiled Frictionless Data Package to: {datapackage_path.name}")

    # 5. Upload names: GitHub release assets are flat
    assets_path = out_path / RELEASE_ASSETS
    assets_path.write_text("".join(f"{path}\t{name}\n" for path, name in assets.items()),
                           encoding="utf-8", newline="\n")
    print(f"  [ASSETS] Saved upload names to: {assets_path.name}")

    # Also keep a copy at repo root / pipeline/data for reference
    if reference_copy:
        pipeline_dp = repo_root / "pipeline" / "data" / "datapackage.json"
        shutil.copy2(datapackage_path, pipeline_dp)

    print("=" * 70)
    print(f"RELEASE COMPLETE: {len(tables)*2 + history_files} files exported ({total_observations:,} total observations).")
    print(f"Frictionless Manifest: {datapackage_path}")
    print("=" * 70)

    return datapackage


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export iraqdata release artifacts.")
    parser.add_argument("--tag", required=True, type=release_tag, help="Release version tag, data-YYYY-MM")
    parser.add_argument("--output-dir", type=Path, default=None,
                        help="Target release directory (default release/<tag>; must be new or empty)")
    args = parser.parse_args()

    try:
        export_release(tag=args.tag, output_dir=args.output_dir)
    except (ReleaseGateError, ReleaseExistsError) as exc:
        print(f"\n{exc}")
        sys.exit(1)
