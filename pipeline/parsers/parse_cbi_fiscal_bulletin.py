"""
pipeline.parsers.parse_cbi_fiscal_bulletin
=========================================
Parser for CBI Monthly Statistical Bulletin (Sheet '6-1' - Public Finance).
Extracts closed annual public budget outturns for every completed year from 2024 on
from the cumulative December rows and updates the canonical Garden dataset:
pipeline/data/garden/fiscal_annual.parquet.

Quality & Schema Guarantees:
- Single-frequency rule: Produces purely annual observations.
- Conforms to standard 7-column Canonical Observation Schema.
- Status flag: 'P' (Provisional outturns pending audited final accounts).
- Full accounting identity compliance.
"""

import fnmatch
import re
import sys
import datetime
from datetime import date
from pathlib import Path
from typing import Optional, List, Dict
import pandas as pd
from openpyxl.utils import get_column_letter

# Add src to sys.path so iraqdata package modules can be imported
repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(repo_root / "src"))
sys.path.insert(0, str(repo_root / "pipeline"))

from iraqdata.schema import CANONICAL_COLUMNS
import flags  # noqa: E402
import source_io  # noqa: E402

FISCAL_SERIES_COLS = {
    "fiscal.revenue_total": 2,          # Col B: Actual Revenues
    "fiscal.revenue_current": 3,        # Col C: Current Revenues
    "fiscal.revenue_investment": 4,     # Col D: Investment Revenues
    "fiscal.expenditure_total": 5,      # Col E: Actual Expenditures
    "fiscal.expenditure_current": 6,    # Col F: Current Expenditures
    "fiscal.expenditure_investment": 7, # Col G: Investment Expenditures
    "fiscal.balance": 8,                # Col H: Surplus / Deficit
}

# The English header the parser expects above each column it reads, as header_key() normalises it
FISCAL_HEADERS = {
    "fiscal.revenue_total": "actual revenues",
    "fiscal.revenue_current": "current revenues",
    "fiscal.revenue_investment": "investment revenues",
    "fiscal.expenditure_total": "actual expenditures",
    "fiscal.expenditure_current": "current expenditures",
    "fiscal.expenditure_investment": "investment expenditures",
    "fiscal.balance": "surplus deficit",
}
HEADER_SEARCH_ROWS = 12  # the header sits in the first rows of the sheet (row 8 in the archived bulletin)

UNIT = "MILLION_IQD"
STATUS_FLAG = "P"  # Provisional outturn from CBI bulletin
REALTIME_START = "2026-10-28"
# The historical seed covers 2004-2023; the bulletin supplies every completed year after that
FIRST_BULLETIN_YEAR = 2024
SHEET = "6-1"
DECEMBER = {"dec.", "dec", "december"}  # the December row's label, after source_io.normalize_label
DATED_NAME_BULLETIN = re.compile(r"cbi_bulletin_\d{4}-\d{2}-\d{2}\.xlsx")


compute_file_hash = source_io.file_hash  # 16 hex characters of the file's SHA-256


def resolve_bulletin_input(raw_cbi_dir: Path) -> Optional[Path]:
    """
    Picks the CBI Monthly Statistical Bulletin to parse: the newest dated download
    (cbi_bulletin_<YYYY-MM-DD>.xlsx), else the legacy archived bulletin_latest.xlsx, else None.
    """
    dated = sorted(p for p in raw_cbi_dir.glob("cbi_bulletin_*.xlsx") if DATED_NAME_BULLETIN.fullmatch(p.name))
    if dated:
        return dated[-1]
    legacy = raw_cbi_dir / "bulletin_latest.xlsx"
    return legacy if legacy.exists() else None


def download_latest_bulletin(
    destination_dir: Path,
    today: Optional[date] = None,
    manifest_path: Optional[Path] = None,
    manifest_root: Optional[Path] = None,
) -> Path:
    """
    Finds the latest statistical bulletin workbook on https://cbi.iq/page/122 and archives it as a new
    dated file, cbi_bulletin_<YYYY-MM-DD>.xlsx, in destination_dir, then adds it to the raw-file
    manifest. Never overwrites an existing file; TLS is verified and robots.txt respected.
    """
    import downloads
    import raw_audit

    target = Path(destination_dir) / f"cbi_bulletin_{(today or datetime.datetime.now(datetime.timezone.utc).date()).isoformat()}.xlsx"
    if target.exists():
        raise FileExistsError(target)

    page_url = "https://cbi.iq/page/122"
    response = downloads.polite_get(page_url, timeout=20, max_bytes=downloads.PAGE_MAX_BYTES)
    response.raise_for_status()

    # The workbook is chosen by its content (the sheet the parser reads), never by its position on
    # the page; an error page is never archived
    file_url, content = downloads.pick_workbook(page_url, response.text, sheets=(SHEET,))
    downloads.save_new_file(target, content)
    print(f"Downloaded bulletin from {file_url} ({len(content):,} bytes) -> {target}")
    raw_audit.manifest_add(
        target,
        manifest_path if manifest_path is not None else raw_audit.MANIFEST_PATH,
        root=manifest_root if manifest_root is not None else repo_root,
    )
    return target


def header_key(value) -> str:
    """A column header for comparison: case, spacing, '/' and '*' ignored ('Surplus /Deficit*' -> 'surplus deficit')."""
    return " ".join("".join(c if c.isalpha() else " " for c in str(value if value is not None else "").lower()).split())


def find_header_row(ws, path: Path) -> int:
    """
    The row holding the English column headers, after checking that every column the parser reads
    carries the header of its series (the label checks, applied to the fixed columns).
    """
    first = FISCAL_SERIES_COLS["fiscal.revenue_total"]
    row = next((r for r in range(1, HEADER_SEARCH_ROWS + 1)
                if header_key(ws.cell(r, first).value) == FISCAL_HEADERS["fiscal.revenue_total"]), None)
    if row is None:
        raise source_io.ParseError(path, "the header 'Actual Revenues' above the data",
                                   f"none in column {get_column_letter(first)} of rows 1-{HEADER_SEARCH_ROWS}",
                                   sheet=SHEET)
    for series_id, col in FISCAL_SERIES_COLS.items():
        cell = ws.cell(row, col)
        if header_key(cell.value) != FISCAL_HEADERS[series_id]:
            raise source_io.ParseError(path, f"the header {FISCAL_HEADERS[series_id]!r} for {series_id}",
                                       repr(cell.value), sheet=SHEET, location=f"cell {cell.coordinate}")
    return row


def _covers(rule: dict, series_id: str, period: str) -> bool:
    to = str(rule["to"])
    return fnmatch.fnmatch(series_id, rule["series"]) and str(rule["from"]) <= period and (to == "open" or period <= to)


def apply_precedence(df_existing: pd.DataFrame, df_new: pd.DataFrame, bulletin_path: Path,
                     report: "source_io.Report") -> pd.DataFrame:
    """
    The fiscal table: the seed's rows plus the bulletin's, where a period both supply is taken from
    the winner of a source_precedence.yaml rule covering it. Every such period where the values
    differ is reported; an overlap that no rule covers stops the run.
    """
    rules = source_io.load_precedence("fiscal_annual")
    existing = df_existing.set_index(["date", "series_id"])
    replaced, disagree = [], []
    for row in df_new.itertuples(index=False):
        key = (row.date, row.series_id)
        if key not in existing.index:
            continue
        rule = next((r for r in rules if _covers(r, row.series_id, row.date)), None)
        if rule is None or rule["winner"] != "cbi_fiscal_bulletin":
            raise source_io.ParseError(bulletin_path, f"no overlap with the seed outside a precedence rule for {row.series_id}",
                                       f"both sources give {row.date}", sheet=SHEET, period=row.date)
        replaced.append(key)
        old = existing.loc[key, "value"]
        if old != row.value:
            disagree.append(f"  {row.series_id} {row.date}: bulletin {row.value}, seed {old}")
    kept = df_existing[~df_existing.set_index(["date", "series_id"]).index.isin(replaced)]
    report.lines.append(f"[PRECEDENCE] fiscal_annual: cbi_fiscal_bulletin {df_new['date'].nunique()} periods, "
                        f"fiscal_seed {kept['date'].nunique()} periods; {len(disagree)} disagree")
    report.lines.extend(disagree)
    combined = pd.concat([kept, df_new], ignore_index=True)
    return combined.sort_values(by=["date", "series_id"]).reset_index(drop=True)


def parse_cbi_fiscal_bulletin(
    bulletin_path: Optional[Path] = None,
    garden_parquet_path: Optional[Path] = None
) -> pd.DataFrame:
    """
    Extracts December cumulative totals for completed years from FIRST_BULLETIN_YEAR on
    and updates pipeline/data/garden/fiscal_annual.parquet.
    """
    if bulletin_path is None:
        raw_cbi_dir = repo_root / "pipeline" / "raw" / "cbi"
        bulletin_path = resolve_bulletin_input(raw_cbi_dir)
        if bulletin_path is None:
            bulletin_path = download_latest_bulletin(raw_cbi_dir)

    if garden_parquet_path is None:
        garden_parquet_path = repo_root / "pipeline" / "data" / "garden" / "fiscal_annual.parquet"

    wb = source_io.open_workbook(bulletin_path, [SHEET], data_only=True)
    ws = wb[SHEET]
    source_hash = compute_file_hash(bulletin_path)
    report = source_io.Report("cbi_fiscal_bulletin")

    observations: List[Dict] = []
    current_year = None
    headers: List[str] = []  # year headers in sheet order
    december: set = set()  # years whose December row was read

    header_row = find_header_row(ws, bulletin_path)
    for row_idx in range(header_row + 1, ws.max_row + 1):
        cell_val = ws.cell(row_idx, 1).value
        if cell_val is None:
            continue

        if isinstance(cell_val, float) and cell_val.is_integer():
            cell_val = int(cell_val)  # a year typed as 2024.0
        cell_str = str(cell_val).strip().translate(source_io.ARABIC_INDIC)

        # Check if row is a year header (e.g. 2024, 2025, 2026)
        if re.fullmatch(r"[0-9]{4}", cell_str):  # ASCII digits only: str.isdigit() also accepts other scripts
            current_year = cell_str
            headers.append(cell_str)
            continue

        # Look for the cumulative December row of completed years: the label must be the month itself
        # ("dec" anywhere in the label, e.g. "Decrease", does not count)
        if current_year is not None and int(current_year) >= FIRST_BULLETIN_YEAR \
                and source_io.normalize_label(cell_str) in DECEMBER:
            if current_year in december:
                raise source_io.ParseError(bulletin_path, f"one December row for {current_year}", "two", sheet=SHEET,
                                           location=f"row {row_idx}", period=current_year)
            december.add(current_year)
            for series_id, col_idx in FISCAL_SERIES_COLS.items():
                cell = ws.cell(row_idx, col_idx)
                val_float = source_io.read_value(cell.value, report, bulletin_path, sheet=SHEET,
                                                 location=f"cell {cell.coordinate}", period=current_year,
                                                 series_id=series_id)
                if val_float is not None:
                    observations.append({
                        "date": current_year,
                        "series_id": series_id,
                        "value": val_float,
                        "unit": UNIT,
                        "status_flag": STATUS_FLAG,
                        "realtime_start": REALTIME_START,
                        "source_hash": source_hash,
                    })

    if not observations:
        raise ValueError(f"No December cumulative fiscal observations found for {FIRST_BULLETIN_YEAR} or later.")

    # A year followed by a later year header is completed and must have its December row
    for year, following in zip(headers, headers[1:]):
        if int(year) >= FIRST_BULLETIN_YEAR and int(following) > int(year) and year not in december:
            msg = f"{bulletin_path.name}: sheet '6-1': no Dec. row for completed year {year}"
            raise ValueError(msg)

    df_new = pd.DataFrame(observations, columns=CANONICAL_COLUMNS)

    # Validate new observations
    source_io.check_schema(df_new, bulletin_path, "bulletin_fiscal_patch")

    # Combine with the seed's table under the written precedence rule
    if garden_parquet_path.exists():
        df_existing = pd.read_parquet(garden_parquet_path)
        df_combined = apply_precedence(df_existing, df_new, bulletin_path, report)
    else:
        df_combined = df_new

    # Final validation on combined dataset
    # Final status flags from the flag policy (pipeline/metadata/flag_policy.yaml)
    df_combined = flags.assign_flags(df_combined, "fiscal_annual")
    source_io.check_schema(df_combined, bulletin_path, "fiscal_annual")
    report.finish()

    source_io.write_table(df_combined, garden_parquet_path)
    print(f"Updated {garden_parquet_path}: total {len(df_combined)} observations across {df_combined['series_id'].nunique()} series.")
    print(f"Time span: {df_combined['date'].min()} to {df_combined['date'].max()} (Years: {sorted(df_combined['date'].unique())})")

    return df_combined


if __name__ == "__main__":
    parse_cbi_fiscal_bulletin()
