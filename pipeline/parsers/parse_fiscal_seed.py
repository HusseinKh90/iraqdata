"""
pipeline.parsers.parse_fiscal_seed
==================================
Parser for Family 5 (Government Finance / Fiscal) historical baseline seed.
Extracts 20-year annual public budget execution data (2004-2023) from
pipeline/seeds/iraq_fiscal_historical.xlsx and formats into the canonical
7-column observation schema.

Output:
    pipeline/data/garden/fiscal_annual.parquet
"""

import sys
from pathlib import Path
import pandas as pd

# Add src to sys.path so iraqdata package modules can be imported
repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(repo_root / "src"))
sys.path.insert(0, str(repo_root / "pipeline"))

from iraqdata.schema import CANONICAL_COLUMNS
import flags  # noqa: E402
import source_io  # noqa: E402

# Column mapping from seed table to canonical series IDs
FISCAL_SERIES_MAP = {
    "revenue_actual_total": "fiscal.revenue_total",
    "revenue_current": "fiscal.revenue_current",
    "revenue_investment": "fiscal.revenue_investment",
    "expenditure_actual_total": "fiscal.expenditure_total",
    "expenditure_current": "fiscal.expenditure_current",
    "expenditure_investment": "fiscal.expenditure_investment",
    "fiscal_surplus_deficit": "fiscal.balance",
}

UNIT = "MILLION_IQD"
STATUS_FLAG = "A"  # provisional; pipeline/flags.py sets the final flag (U, origin unknown)
REALTIME_START = "2026-10-28"


compute_file_hash = source_io.file_hash  # 16 hex characters of the file's SHA-256


def parse_fiscal_seed(
    seed_path: Path = None,
    output_path: Path = None
) -> pd.DataFrame:
    """Parses historical fiscal seed and outputs canonical observations."""
    if seed_path is None:
        seed_path = repo_root / "pipeline" / "seeds" / "iraq_fiscal_historical.xlsx"
        if not seed_path.exists():
            seed_path = repo_root / "pipeline" / "seeds" / "iraq_fiscal_historical.csv"

    if output_path is None:
        output_path = repo_root / "pipeline" / "data" / "garden" / "fiscal_annual.parquet"

    # Read seed file
    if seed_path.suffix == ".xlsx":
        df_raw = source_io.read_excel(seed_path)
    else:
        df_raw = source_io.read_csv(seed_path)
    source_hash = compute_file_hash(seed_path)
    report = source_io.Report("fiscal_seed")

    # Validate presence of expected columns
    expected_cols = ["year"] + list(FISCAL_SERIES_MAP.keys())
    missing_cols = [c for c in expected_cols if c not in df_raw.columns]
    if missing_cols:
        raise source_io.ParseError(seed_path, f"the columns {missing_cols}", f"columns {list(df_raw.columns)}")

    # Melt from wide format to long format; every cell must be a number
    rows = []
    for i, row in df_raw.iterrows():
        year = source_io.read_value(row["year"], report, seed_path, location=f"row {i + 2}, column year")
        if year is None or year != int(year):
            raise source_io.ParseError(seed_path, "a year", repr(row["year"]), location=f"row {i + 2}, column year")
        year_str = str(int(year))
        for col_name, series_id in FISCAL_SERIES_MAP.items():
            val = source_io.read_value(row[col_name], report, seed_path, location=f"row {i + 2}, column {col_name}",
                                       period=year_str, series_id=series_id)
            if val is None:
                raise source_io.ParseError(seed_path, "a number", "a blank cell",
                                           location=f"row {i + 2}, column {col_name}", period=year_str)
            rows.append({
                "date": year_str,
                "series_id": series_id,
                "value": val,
                "unit": UNIT,
                "status_flag": STATUS_FLAG,
                "realtime_start": REALTIME_START,
                "source_hash": source_hash,
            })

    df_canonical = pd.DataFrame(rows, columns=CANONICAL_COLUMNS)

    # Tier-1 internal validation check
    # Final status flags from the flag policy (pipeline/metadata/flag_policy.yaml)
    df_canonical = flags.assign_flags(df_canonical, "fiscal_annual")
    source_io.check_schema(df_canonical, seed_path, "fiscal_annual")
    report.finish()

    source_io.write_table(df_canonical, output_path)
    print(f"Successfully generated {output_path} ({len(df_canonical)} observations).")

    return df_canonical


if __name__ == "__main__":
    parse_fiscal_seed()
