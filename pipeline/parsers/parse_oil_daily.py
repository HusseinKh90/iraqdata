"""
pipeline.parsers.parse_oil_daily
================================
Parser for Family 3 (Oil) - Daily Brent Spot Crude Price (`oil_price_brent`).
Sourced from U.S. EIA via FRED (`DCOILBRENTEU`).

Ingestion & Cleansing Rules:
- Enforces Single-Frequency Rule: output contains purely daily observations.
- Coerces missing market holiday markers ('.') to NaN and drops them.
- Restricts to canonical sample period: date >= 2004-01-01.
- Validates Tier-1 Canonical Observation Schema.
- Validates Tier-2 plausibility envelope: [10.0, 250.0] USD_PER_BBL.
- Output: pipeline/data/garden/oil_daily.parquet
"""

import sys
from pathlib import Path
from typing import Optional
import pandas as pd

# Add src to sys.path so iraqdata package modules can be imported
repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(repo_root / "src"))
sys.path.insert(0, str(repo_root / "pipeline"))

from iraqdata.schema import CANONICAL_COLUMNS
import flags  # noqa: E402
import source_io  # noqa: E402

SERIES_ID = "oil_price_brent"
NO_VALUE = {"."}  # FRED's "no price that day"; empty cells are no value too
UNIT = "USD_PER_BBL"
REALTIME_START = "2026-10-28"
START_DATE = "2004-01-01"


compute_file_hash = source_io.file_hash  # 16 hex characters of the file's SHA-256


def parse_oil_daily(
    raw_csv_path: Optional[Path] = None,
    output_parquet_path: Optional[Path] = None
) -> pd.DataFrame:
    """
    Parses FRED DCOILBRENTEU.csv and writes pipeline/data/garden/oil_daily.parquet.
    """
    if raw_csv_path is None:
        raw_csv_path = repo_root / "pipeline" / "raw" / "fred" / "DCOILBRENTEU.csv"

    if output_parquet_path is None:
        output_parquet_path = repo_root / "pipeline" / "data" / "garden" / "oil_daily.parquet"

    # Read as text, so that every value is checked (an unreadable value is an error,
    # not a blank); FRED marks a day without a price with "." or leaves it empty
    df_raw = source_io.read_csv(raw_csv_path, dtype=str, keep_default_na=False)
    source_hash = compute_file_hash(raw_csv_path)
    report = source_io.Report("oil_daily")
    # Expected columns: observation_date, DCOILBRENTEU (or DATE, DCOILBRENTEU)
    date_col = "DATE" if "DATE" in df_raw.columns else "observation_date"
    val_col = "DCOILBRENTEU"
    for column in (date_col, val_col):
        if column not in df_raw.columns:
            raise source_io.ParseError(raw_csv_path, f"a {column} column", f"columns {list(df_raw.columns)}")

    observations = []
    for i, row in df_raw.iterrows():
        d_str = str(row[date_col]).strip()
        if d_str < START_DATE:
            continue
        value = source_io.read_value(row[val_col], report, raw_csv_path, markers=NO_VALUE,
                                     location=f"row {i + 2}", period=d_str, series_id=SERIES_ID)
        if value is None:
            continue
        v_num = round(value, 2)
        observations.append({
            "date": d_str,
            "series_id": SERIES_ID,
            "value": v_num,
            "unit": UNIT,
            "status_flag": "A",
            "realtime_start": REALTIME_START,
            "source_hash": source_hash,
        })

    df_out = pd.DataFrame(observations, columns=CANONICAL_COLUMNS)
    df_out = source_io.collapse_duplicates(df_out, raw_csv_path, report)
    df_out = df_out.sort_values(by="date").reset_index(drop=True)
    source_io.check_daily_coverage(df_out, raw_csv_path)

    # Tier-1 Validation
    # Final status flags from the flag policy (pipeline/metadata/flag_policy.yaml)
    df_out = flags.assign_flags(df_out, "oil_daily")
    source_io.check_schema(df_out, raw_csv_path, "oil_daily")
    report.finish()

    source_io.write_table(df_out, output_parquet_path)
    print(f"Successfully saved {output_parquet_path} ({len(df_out):,} daily observations).")
    print(f"Date range: {df_out['date'].min()} to {df_out['date'].max()}.")

    return df_out


if __name__ == "__main__":
    parse_oil_daily()
