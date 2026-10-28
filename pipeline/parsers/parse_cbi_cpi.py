"""
pipeline.parsers.parse_cbi_cpi
==============================
Parser for Family 4 (Prices / Inflation) from the Central Bank of Iraq (CBI)
Key Financial Indicators workbook (https://cbi.iq/news/view/94).

Extracts 10 monthly price indicators:
- 8 Native Base Series:
  1. cpi.headline_1993 (Base 1993 = 100, Row 3)
  2. cpi.core_1993     (Base 1993 = 100, Row 4)
  3. cpi.headline_2007 (Base 2007 = 100, Row 5)
  4. cpi.core_2007     (Base 2007 = 100, Row 6)
  5. cpi.headline_2012 (Base 2012 = 100, Row 7)
  6. cpi.core_2012     (Base 2012 = 100, Row 8)
  7. cpi.headline_2022 (Base 2022 = 100, Row 9)
  8. cpi.core_2022     (Base 2022 = 100, Row 10)
- 2 Linked Continuous Series (on the 2022 base's scale; "2022 = 100" is approximate):
  9. cpi_headline          (Continuous 2004–2026)
  10. cpi_core             (Continuous 2004–2026; its core definition changes at the 1993 -> 2007 splice)

Linking Method (pipeline/cpi_linking.py):
December one-month overlap. Each older base is used through December of its overlap year (the last
year it and the next base both cover in full) and the series switches to the next base the
following January (2010-01, 2016-01, 2024-01), each flagged 'B'. The newest base is not rescaled.
Factors, continuity checks and the post-splice gaps are generated into
docs/linked_inflation_method.md by pipeline/docs_cpi.py.

Quality & Schema Guarantees:
- Single-frequency rule: Produces purely monthly observations (YYYY-MM).
- Conforms to standard 7-column Canonical Observation Schema.
- Output: pipeline/data/garden/prices_monthly.parquet
"""

import re
import sys
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd

# Add src to sys.path so iraqdata package modules can be imported
repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(repo_root / "src"))
sys.path.insert(0, str(repo_root / "pipeline"))

from iraqdata.schema import CANONICAL_COLUMNS
import cpi_linking  # noqa: E402
import flags  # noqa: E402
import kfi_timeline  # noqa: E402
import source_io  # noqa: E402

CPI_NATIVE_ROWS = [
    ("cpi.headline_1993", 3, "headline", "1993"),
    ("cpi.core_1993",     4, "core",     "1993"),
    ("cpi.headline_2007", 5, "headline", "2007"),
    ("cpi.core_2007",     6, "core",     "2007"),
    ("cpi.headline_2012", 7, "headline", "2012"),
    ("cpi.core_2012",     8, "core",     "2012"),
    ("cpi.headline_2022", 9, "headline", "2022"),
    ("cpi.core_2022",    10, "core",     "2022"),
]

UNIT = "INDEX"
REALTIME_START = "2026-10-28"
SHEET = "Sheet1"  # the only sheet of the Key Financial Indicators workbook (read by name)
NO_VALUE = {"-", "…"}  # cell texts that mean "no value"; blank cells are no value too


compute_file_hash = source_io.file_hash  # 16 hex characters of the file's SHA-256


def extract_raw_series(ws, col_dates: Dict[int, str], row_idx: int, report: "source_io.Report",
                       path: Path, series_id: str) -> pd.Series:
    """
    Extracts a series indexed by ISO date string (YYYY-MM). A blank or NO_VALUE cell is no value
    (counted); any other cell that is not a positive number stops the run.
    """
    data = {}
    for col, dt in col_dates.items():
        cell = ws.cell(row_idx, col)
        num = source_io.read_value(cell.value, report, path, markers=NO_VALUE, sheet=SHEET,
                                   location=f"cell {cell.coordinate}", period=dt, series_id=series_id)
        if num is not None:
            data[dt] = num
    return pd.Series(data)


def parse_cbi_cpi(
    workbook_path: Optional[Path] = None,
    output_parquet_path: Optional[Path] = None
) -> pd.DataFrame:
    """
    Parses Key Financial Indicators workbook, extracts native CPI series,
    links them (pipeline/cpi_linking.py), and saves prices_monthly.parquet.
    """
    if workbook_path is None:
        workbook_path = repo_root / "pipeline" / "raw" / "cbi" / "key_financial_indicators.xlsx"

    if output_parquet_path is None:
        output_parquet_path = repo_root / "pipeline" / "data" / "garden" / "prices_monthly.parquet"

    wb = source_io.open_workbook(workbook_path, [SHEET], data_only=True)
    ws = wb[SHEET]
    source_hash = compute_file_hash(workbook_path)
    report = source_io.Report("cbi_cpi")

    # 0. Each fixed CPI row must carry its measure and base year, so an
    #    inserted or swapped row stops the run instead of shifting the series
    for series_id, row_idx, series_type, base_year in CPI_NATIVE_ROWS:
        label = str(ws.cell(row_idx, 2).value or "")
        text = " ".join(label.lower().split())
        base = re.search(r"\(\s*(\d{4})\s*=\s*100\s*\)", label)
        is_core = re.search(r"\bcore\b", text) is not None
        if "consumer price index" not in text or base is None or base.group(1) != base_year or is_core != (series_type == "core"):
            msg = (f"{workbook_path.name}: sheet '{ws.title}': row {row_idx} should hold the {series_type} consumer price index "
                   f"({base_year} = 100) for {series_id}, but its label is {label.strip()!r}")
            raise ValueError(msg)

    # 1. Resolve the timeline columns (every month header must be recognised and consecutive)
    col_dates: Dict[int, str] = kfi_timeline.resolve(ws, workbook_path)

    observations: List[Dict] = []
    extracted_series: Dict[str, pd.Series] = {}

    # 2. Extract 8 native series
    for series_id, row_idx, series_type, base_year in CPI_NATIVE_ROWS:
        s = extract_raw_series(ws, col_dates, row_idx, report, workbook_path, series_id)
        extracted_series[series_id] = s
        for dt, val in s.items():
            observations.append({
                "date": dt,
                "series_id": series_id,
                "value": round(float(val), 4),
                "unit": UNIT,
                "status_flag": "A",
                "realtime_start": REALTIME_START,
                "source_hash": source_hash,
            })

    # 3. Link the bases (pipeline/cpi_linking.py): each older base runs through December of
    #    its overlap year and the series switches base the following January. The published natives
    #    (rounded to 4 decimals) are linked, so anyone can recompute the linked series from them.
    for kind in ("headline", "core"):
        natives = {sid: extracted_series[sid].round(4) for sid, _, k, _ in CPI_NATIVE_ROWS if k == kind}
        splices = cpi_linking.splices(natives, kind)
        print(f"{kind.capitalize()} linking (December one-month overlap) to the 2022 base:")
        for s in splices:
            print(f"  {s.old_base} -> {s.new_base}: overlap {s.overlap_year}, step {s.step_factor:.7g}, "
                  f"chain {s.chain_factor:.7g}, switch {s.splice_month}")
        breaks = set(cpi_linking.splice_months(natives, kind))
        for dt, val in cpi_linking.link(natives, kind).items():
            observations.append({
                "date": dt,
                "series_id": f"cpi_{kind}",
                "value": round(float(val), 4),
                "unit": UNIT,
                # B on every month where the linked series switches base
                "status_flag": "B" if dt in breaks else "A",
                "realtime_start": REALTIME_START,
                "source_hash": source_hash,
            })

    df = pd.DataFrame(observations, columns=CANONICAL_COLUMNS)
    df = source_io.collapse_duplicates(df, workbook_path, report)
    df = df.sort_values(by=["series_id", "date"]).reset_index(drop=True)

    # 5. Tier-1 Validation Check
    # Final status flags from the flag policy (pipeline/metadata/flag_policy.yaml)
    df = flags.assign_flags(df, "prices_monthly")
    source_io.check_schema(df, workbook_path, "prices_monthly")
    report.finish()

    source_io.write_table(df, output_parquet_path)
    print(f"Successfully saved {output_parquet_path} ({len(df):,} observations across {df['series_id'].nunique()} series).")
    print(f"Date range: {df['date'].min()} to {df['date'].max()}.")

    return df


if __name__ == "__main__":
    parse_cbi_cpi()
