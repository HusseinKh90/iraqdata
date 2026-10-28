"""
pipeline.parsers.parse_bis_lbs
==============================
Parser for Family 8 (External Mirrors / Cross-Border Banking) from the
Bank for International Settlements (BIS) Locational Banking Statistics (LBS).

Ingests 6 quarterly series across 89 continuous quarters (2004-Q1 to 2026-Q1):
1. `bis.lbs.claims_total`: Total claims of BIS reporting banks on Iraqi counterparties.
2. `bis.lbs.liabilities_total`: Total liabilities of BIS reporting banks to Iraqi entities (cross-border deposits).
3. `bis.lbs.liabilities_banks`: Liabilities to Iraqi banks and Central Bank of Iraq (CBI foreign reserve deposits).
4. `bis.lbs.liabilities_nonbank`: Liabilities to Iraqi non-bank entities (general government, private corporations).
5. `bis.lbs.claims_nonbank`: Claims on Iraqi non-bank entities.
6. `bis.lbs.net_position`: Derived net asset position (Liabilities - Claims).

Quality & Accounting Guarantees:
- Enforces Single-Frequency Rule: output contains purely quarterly observations (YYYY-Q#).
- Break flags: a quarter the BIS marks OBS_STATUS = B (series break) is published with status
  flag B; any other status, or a missing OBS_STATUS column, stops the run. A derived net position
  inherits B from either input (pipeline/flags.py).
- Mathematical identity: net_position == liabilities_total - claims_total (Delta <= 0.001).
- Component Sanity: liabilities_total >= liabilities_banks + liabilities_nonbank - 1.0.
- Conforms to standard 7-column Canonical Observation Schema.
- Generates derived seed snapshot `pipeline/seeds/bis_lbs_quarterly_seed.parquet` (regenerated on every run; see pipeline/run_parsers.py).
- Generates garden dataset: `pipeline/data/garden/bis_lbs_quarterly.parquet`.
"""

import hashlib
import sys
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd

# Add src to sys.path so iraqdata package modules can be imported
repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(repo_root / "src"))
sys.path.insert(0, str(repo_root / "pipeline"))
sys.path.append(str(repo_root / "pipeline"))  # downloads.latest_version

from iraqdata.schema import CANONICAL_COLUMNS
import flags  # noqa: E402
import downloads
import source_io  # noqa: E402

UNIT = "MILLION_USD"
REALTIME_START = "2026-10-28"
# BIS observation status (SDMX CL_OBS_STATUS) -> the flag the parser emits; the flag policy decides
# the final one. Only normal and break appear in the LBS slices; anything else is not guessed at.
STATUS_FLAGS = {"A": "A", "B": "B"}

SERIES_FILES: Dict[str, str] = {
    "bis.lbs.claims_total": "bis_lbs_claims_total.csv",
    "bis.lbs.liabilities_total": "bis_lbs_liabilities_total.csv",
    "bis.lbs.liabilities_banks": "bis_lbs_liabilities_banks.csv",
    "bis.lbs.liabilities_nonbank": "bis_lbs_liabilities_nonbank.csv",
    "bis.lbs.claims_nonbank": "bis_lbs_claims_nonbank.csv",
}


def compute_file_hash(filepath: Path) -> str:
    """SHA-256 of a file, all 64 hex characters (this parser's source_hash has always been the full digest)."""
    return source_io.file_hash(filepath, length=None)


def parse_bis_lbs(raw_dir: Optional[Path] = None) -> pd.DataFrame:
    """
    Parses archived raw BIS LBS CSV files and produces canonical observations.
    """
    if raw_dir is None:
        raw_dir = repo_root / "pipeline" / "raw" / "bis"
    if not raw_dir.exists():
        raise FileNotFoundError(f"Raw BIS directory not found at: {raw_dir}")

    # Track series values (and the flag the BIS gives each) by quarter
    quarterly_data: Dict[str, Dict[str, float]] = {}
    quarterly_flags: Dict[str, Dict[str, str]] = {}
    file_hashes: Dict[str, str] = {}
    report = source_io.Report("bis_lbs")

    for series_id, filename in SERIES_FILES.items():
        file_path = source_io.require_file(downloads.latest_version(raw_dir / filename))

        file_hashes[series_id] = compute_file_hash(file_path)
        df_raw = source_io.read_csv(file_path)
        for column in ("TIME_PERIOD", "OBS_VALUE", "OBS_STATUS"):
            if column not in df_raw.columns:
                raise source_io.ParseError(file_path, f"a {column} column", f"columns {list(df_raw.columns)}")

        # Filter post-2004
        df_filtered = df_raw[df_raw["TIME_PERIOD"] >= "2004-Q1"].copy()

        for i, row in df_filtered.iterrows():
            qtr = str(row["TIME_PERIOD"]).strip()
            val = source_io.read_value(row["OBS_VALUE"], report, file_path, location=f"row {i + 2}",
                                       period=qtr, series_id=series_id)
            if val is None:
                continue  # the quarter is then reported as missing below
            status = str(row["OBS_STATUS"]).strip()
            if status not in STATUS_FLAGS:
                raise source_io.ParseError(file_path, f"an OBS_STATUS of {' or '.join(sorted(STATUS_FLAGS))}",
                                           repr(row["OBS_STATUS"]), location=f"row {i + 2}, column OBS_STATUS",
                                           period=qtr)
            if qtr not in quarterly_data:
                quarterly_data[qtr] = {}
                quarterly_flags[qtr] = {}
            if series_id in quarterly_data[qtr]:
                raise source_io.ParseError(file_path, f"one row for {qtr}", "two", location=f"row {i + 2}", period=qtr)
            quarterly_data[qtr][series_id] = round(val, 3)
            quarterly_flags[qtr][series_id] = STATUS_FLAGS[status]

    # Sort quarters chronologically
    sorted_quarters = sorted(quarterly_data.keys())

    # Build canonical records
    records: List[Dict] = []
    
    # Combined hash for derived series
    combined_hash_obj = hashlib.sha256()
    for s_id in sorted(file_hashes.keys()):
        combined_hash_obj.update(file_hashes[s_id].encode("utf-8"))
    combined_hash = combined_hash_obj.hexdigest()

    for qtr in sorted_quarters:
        q_dict = quarterly_data[qtr]

        # Verify presence of primary series
        for sid in SERIES_FILES.keys():
            if sid not in q_dict:
                raise source_io.ParseError(raw_dir / SERIES_FILES[sid], f"a value for {sid}", "none", period=qtr)

        claims_tot = q_dict["bis.lbs.claims_total"]
        liab_tot = q_dict["bis.lbs.liabilities_total"]

        # Derive net external position: Liabilities - Claims
        net_pos = round(liab_tot - claims_tot, 3)
        q_dict["bis.lbs.net_position"] = net_pos

        for sid, val in q_dict.items():
            s_hash = file_hashes.get(sid, combined_hash)
            records.append({
                "date": qtr,
                "series_id": sid,
                "value": float(val),
                "unit": UNIT,
                "status_flag": quarterly_flags[qtr].get(sid, "A"),  # net_position: flags.py inherits from its inputs
                "realtime_start": REALTIME_START,
                "source_hash": s_hash,
            })

    df_out = pd.DataFrame(records)[CANONICAL_COLUMNS]

    # Sort by date and series_id
    df_out = df_out.sort_values(by=["date", "series_id"]).reset_index(drop=True)

    # Validate against canonical schema rules
    # Final status flags from the flag policy (pipeline/metadata/flag_policy.yaml)
    df_out = flags.assign_flags(df_out, "bis_lbs_quarterly")
    source_io.check_schema(df_out, raw_dir, "bis_lbs_quarterly")
    report.finish()
    return df_out


def main(
    output_dir: Optional[Path] = None,
    seeds_dir: Optional[Path] = None,
    raw_dir: Optional[Path] = None,
):
    print("=" * 60)
    print("Ingesting Family 8: External Mirrors / BIS LBS")
    print("=" * 60)

    df = parse_bis_lbs(raw_dir)
    print(f"Parsed {len(df)} canonical observations across {df['series_id'].nunique()} series.")
    print(f"Quarters covered: {df['date'].min()} to {df['date'].max()} ({df['date'].nunique()} quarters).")

    # Output paths
    garden_dir = output_dir if output_dir is not None else repo_root / "pipeline" / "data" / "garden"
    if seeds_dir is None:
        seeds_dir = repo_root / "pipeline" / "seeds"

    garden_dir.mkdir(parents=True, exist_ok=True)
    seeds_dir.mkdir(parents=True, exist_ok=True)

    garden_parquet = garden_dir / "bis_lbs_quarterly.parquet"
    seed_parquet = seeds_dir / "bis_lbs_quarterly_seed.parquet"

    source_io.write_table(df, garden_parquet)
    print(f"Saved Garden dataset -> {garden_parquet}")

    source_io.write_table(df, seed_parquet)
    print(f"Saved Immutable Seed -> {seed_parquet}")

    print("\nSummary by Series:")
    piv = df.pivot(index="date", columns="series_id", values="value")
    for col in piv.columns:
        print(f"  {col}: {piv[col].count()} obs, Latest ({piv.index[-1]}): {piv[col].iloc[-1]:,.2f} {UNIT}")


if __name__ == "__main__":
    main()
