"""
pipeline.parsers.parse_cbi_exchange_rates
=========================================
Parser for Family 2 (Exchange Rates): the daily parallel and official dinar-per-dollar rates,
in the canonical 7-column observation schema. Sources:

- parallel_rate_iraq (IQD_PER_USD, Daily):
  - 2004-01-01 to 2022-12-31: the historical seed pipeline/seeds/cbi_exchange_rate_historical.xlsx,
    sheet 'Daily Market price' (CBI's published daily market rate);
  - from 2023-01-01: the Baghdad close (`baghdad_close`) of the newest archived
    pipeline/raw/github/daily_fx_<date>.csv, published by the GitHub repo
    HusseinKh90/Iraq-parallel-exchange-rate (CC-BY 4.0) from the dealer Telegram channels
    @dollariraqi, @iqborsa and @dollar_price. Days without a Baghdad close are omitted. The first
    value from this source is flagged B (break): the series changes source there.
- fx.official (IQD_PER_USD, Daily): the CBI's own workbook from https://cbi.iq/page/144, newest
  archived pipeline/raw/cbi/fx/cbi_fx_usd_<date>.xlsx, sheet 'Daily Price basis', whole history.

Quality & Schema Guarantees:
- Single-frequency rule: Produces purely daily observations (YYYY-MM-DD).
- Conforms to standard 7-column Canonical Observation Schema.
- Every rate must be a positive number; blank cells and the NO_VALUE texts are no value, and a rate
  on a calendar date that does not exist must be listed in source_exceptions.yaml.
- No run of more than 10 days without a rate unless listed in daily_gaps.yaml; range and
  jump limits are the gatekeeper's (plausibility_rules.yaml).
- Output: pipeline/data/garden/exchange_rates_daily.parquet
"""

import csv
import datetime
import io
import math
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional
from openpyxl.utils import get_column_letter
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

UNIT = "IQD_PER_USD"
STATUS_FLAG = "A"  # provisional; pipeline/flags.py sets the final flag
REALTIME_START = "2026-10-28"

PARALLEL_SHEET = "Daily Market price"  # in the seed
OFFICIAL_SHEET = "Daily Price basis"  # in the CBI workbook
SPLICE = "2023-01-01"  # parallel_rate_iraq comes from daily_fx.csv from this date on
DAILY_FX_COLUMNS = ("date", "baghdad_close")
ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
# Calendar cell texts that mean "no value": a dash, an ellipsis, the Arabic word
# for holiday, a weekday name; a run of the Arabic tatweel (ـ) is used like a dash. Blank cells are no value too.
NO_VALUE = {"-", "…", "عطلة", "Friday"}
TATWEEL = re.compile(r"ـ+")


compute_file_hash = source_io.file_hash  # 16 hex characters of the file's SHA-256


def _cell_value(raw, report: "source_io.Report", path: Path, sheet: str, row_idx: int, col_idx: int,
                period: str, series_id: str) -> Optional[float]:
    """One calendar cell: a value, or None for no value (blank, NO_VALUE text, a tatweel run)."""
    if isinstance(raw, str) and TATWEEL.fullmatch(raw.strip()):
        report.marker(path, "'ـ' run")
        return None
    return source_io.read_value(raw, report, path, markers=NO_VALUE, sheet=sheet,
                                location=f"cell {get_column_letter(col_idx + 1)}{row_idx + 1}",
                                period=period, series_id=series_id)


def parse_exchange_rates_sheet(
    df_sheet: pd.DataFrame,
    series_id: str,
    source_hash: str,
    years: Optional[List[int]] = None,
    report: Optional["source_io.Report"] = None,
    path: Optional[Path] = None,
    sheet: Optional[str] = None,
) -> List[Dict]:
    """
    Parses a calendar-block exchange rate sheet into canonical observation dictionaries. The year of
    every recognised year header is appended to `years`, when given.

    Every cell of a day row (1-31) under a month (Jan-Dec) is read: blank cells and
    NO_VALUE texts are no value (counted); a number on a calendar date that does not exist must be
    listed in source_exceptions.yaml; any other text, or a rate that is not positive, stops the run.
    """
    report = report if report is not None else source_io.Report("cbi_exchange_rates")
    path = Path(path) if path is not None else Path("<sheet>")
    observations: List[Dict] = []
    num_rows = len(df_sheet)

    for r in range(num_rows):
        val0 = str(df_sheet.iloc[r, 0])
        # Detect year header row
        m = re.search(r"\b(20\d\d)\b", val0)
        if m and any(kw in val0.lower() for kw in ["exchange", "date", "price", "market"]):
            year = int(m.group(1))
            if years is not None:
                years.append(year)

            # Scan rows beneath year header for day indices (1 to 31)
            for day_offset in range(1, 35):
                row_idx = r + day_offset
                if row_idx >= num_rows:
                    break

                cell_day = df_sheet.iloc[row_idx, 0]
                try:
                    day_int = int(cell_day)
                except (ValueError, TypeError):
                    continue

                if 1 <= day_int <= 31:
                    # Columns 1 to 12 represent months Jan (1) to Dec (12)
                    for month_idx in range(1, 13):
                        cell_val = df_sheet.iloc[row_idx, month_idx]
                        label = f"{year}-{month_idx:02d}-{day_int:02d}"
                        try:
                            dt = datetime.date(year, month_idx, day_int)
                        except ValueError:
                            dt = None  # the day does not exist in this month (e.g. Feb 30, Apr 31)
                        rate_val = _cell_value(cell_val, report, path, sheet, row_idx, month_idx, label,
                                               series_id if dt is not None else None)
                        if rate_val is None:
                            continue
                        if dt is None:
                            if report.listed(path, sheet, label, cell_val) is not None:
                                continue
                            raise source_io.ParseError(
                                path, "no value on a calendar date that does not exist", repr(cell_val), sheet=sheet,
                                location=f"cell {get_column_letter(month_idx + 1)}{row_idx + 1}", period=label)

                        iso_date = dt.isoformat()

                        # Enforce project start date boundary (2004-01-01)
                        if iso_date >= "2004-01-01":
                            observations.append({
                                "date": iso_date,
                                "series_id": series_id,
                                "value": rate_val,
                                "unit": UNIT,
                                "status_flag": STATUS_FLAG,
                                "realtime_start": REALTIME_START,
                                "source_hash": source_hash,
                                "_where": f"{path.name}, sheet '{sheet}', cell {get_column_letter(month_idx + 1)}{row_idx + 1}",
                            })

    return observations


def _check_workbook(path: Path, sheet_name: str) -> None:
    """
    The sheet exists, and no cell in it holds a formula whose result was never stored (such a cell
    reads as blank, so its day would silently disappear).
    """
    with_formulas = source_io.open_workbook(path, [sheet_name], read_only=True)
    with_values = source_io.open_workbook(path, [sheet_name], read_only=True, data_only=True)
    try:
        rows = zip(with_formulas[sheet_name].iter_rows(min_row=1, values_only=True),
                   with_values[sheet_name].iter_rows(min_row=1, values_only=True))
        for r, (formula_row, value_row) in enumerate(rows, start=1):
            for c, (f, v) in enumerate(zip(formula_row, value_row), start=1):
                if isinstance(f, str) and f.startswith("=") and v is None:
                    msg = (f"{path.name}: sheet '{sheet_name}': cell {get_column_letter(c)}{r} holds a formula with "
                           f"no stored result; recalculate and save the workbook in Excel before parsing")
                    raise ValueError(msg)
    finally:
        with_formulas.close()
        with_values.close()


def read_calendar_sheet(path: Path, sheet_name: str, series_id: str, source_hash: str,
                        report: Optional["source_io.Report"] = None) -> List[Dict]:
    """One calendar-block sheet, after the year-contiguity check."""
    print(f"Reading {path.name} sheet '{sheet_name}' for series '{series_id}' ...")
    df_sheet = source_io.read_excel(path, sheet_name=sheet_name, header=None)
    years: List[int] = []
    obs = parse_exchange_rates_sheet(df_sheet, series_id, source_hash, years, report=report, path=path,
                                     sheet=sheet_name)
    found = sorted(set(years))
    gaps = [y for y in range(found[0], found[-1] + 1) if y not in found] if found else []
    if gaps:
        msg = (f"{path.name}: sheet '{sheet_name}': no year block for {', '.join(map(str, gaps))} "
               f"between {found[0]} and {found[-1]}")
        raise ValueError(msg)
    print(f"  Extracted {len(obs):,} observations.")
    return obs


def read_daily_fx(path: Path, source_hash: str) -> List[Dict]:
    """
    parallel_rate_iraq from SPLICE on: the Baghdad close of daily_fx.csv.
    Every row is checked, including those before SPLICE; rows without a close are skipped; the
    first value kept is flagged B.
    """
    observations: List[Dict] = []
    seen = set()
    with io.StringIO(source_io.read_text(path, encoding="utf-8-sig"), newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in DAILY_FX_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            msg = f"{path.name}: missing column(s) {', '.join(missing)} (found: {', '.join(reader.fieldnames or [])})"
            raise ValueError(msg)
        for line, row in enumerate(reader, start=2):
            day = (row["date"] or "").strip()
            try:
                real_day = bool(ISO_DAY.fullmatch(day)) and datetime.date.fromisoformat(day) is not None
            except ValueError:
                real_day = False
            if not real_day:
                msg = f"{path.name}: row {line}: date {day!r} is not a real day (YYYY-MM-DD)"
                raise ValueError(msg)
            if day in seen:
                msg = f"{path.name}: row {line}: date {day} occurs twice"
                raise ValueError(msg)
            seen.add(day)
            close = (row["baghdad_close"] or "").strip()
            if not close:
                continue
            try:
                value = float(close)
            except ValueError:
                value = float("nan")
            if not (math.isfinite(value) and value > 0):
                msg = f"{path.name}: row {line}: {day}: baghdad_close {close!r} is not a positive number"
                raise ValueError(msg)
            if day < SPLICE:
                continue
            observations.append({
                "date": day,
                "series_id": "parallel_rate_iraq",
                "value": value,
                "unit": UNIT,
                "status_flag": "B" if not observations else STATUS_FLAG,
                "realtime_start": REALTIME_START,
                "source_hash": source_hash,
                "_where": f"{path.name}, row {line}",
            })
    print(f"Read {path.name}: {len(observations):,} Baghdad closes from {SPLICE}.")
    return observations


def parse_cbi_exchange_rates(
    seed_path: Optional[Path] = None,
    cbi_workbook_path: Optional[Path] = None,
    daily_fx_path: Optional[Path] = None,
    output_parquet_path: Optional[Path] = None,
) -> pd.DataFrame:
    """
    Builds pipeline/data/garden/exchange_rates_daily.parquet from the seed (parallel rate up to
    2022), daily_fx.csv (parallel rate from 2023) and the CBI workbook (official rate).
    """
    if seed_path is None:
        seed_path = repo_root / "pipeline" / "seeds" / "cbi_exchange_rate_historical.xlsx"
    if cbi_workbook_path is None:
        cbi_workbook_path = downloads.latest_version(repo_root / "pipeline" / "raw" / "cbi" / "fx" / "cbi_fx_usd.xlsx")
    if daily_fx_path is None:
        daily_fx_path = downloads.latest_version(repo_root / "pipeline" / "raw" / "github" / "daily_fx.csv")
    if output_parquet_path is None:
        output_parquet_path = repo_root / "pipeline" / "data" / "garden" / "exchange_rates_daily.parquet"

    for path in (seed_path, cbi_workbook_path, daily_fx_path):
        source_io.require_file(path)

    _check_workbook(seed_path, PARALLEL_SHEET)
    _check_workbook(cbi_workbook_path, OFFICIAL_SHEET)

    report = source_io.Report("cbi_exchange_rates")
    parallel = [o for o in read_calendar_sheet(seed_path, PARALLEL_SHEET, "parallel_rate_iraq",
                                               compute_file_hash(seed_path), report) if o["date"] < SPLICE]
    official = read_calendar_sheet(cbi_workbook_path, OFFICIAL_SHEET, "fx.official", compute_file_hash(cbi_workbook_path),
                                   report)
    recent = read_daily_fx(daily_fx_path, compute_file_hash(daily_fx_path))

    rows = parallel + recent + official
    df = pd.DataFrame(rows, columns=CANONICAL_COLUMNS)

    # A repeated (date, series_id) is collapsed only when identical, and reported
    df = source_io.collapse_duplicates(df, cbi_workbook_path, report, where=[r["_where"] for r in rows])
    df = df.sort_values(by=["series_id", "date"]).reset_index(drop=True)

    # No run of more than 10 days without a rate, unless listed in daily_gaps.yaml
    source_io.check_daily_coverage(df[df["series_id"] == "parallel_rate_iraq"], f"{seed_path.name} + {daily_fx_path.name}")
    source_io.check_daily_coverage(df[df["series_id"] == "fx.official"], cbi_workbook_path)

    # Tier-1 validation
    # Final status flags from the flag policy (pipeline/metadata/flag_policy.yaml)
    df = flags.assign_flags(df, "exchange_rates_daily")
    source_io.check_schema(df, cbi_workbook_path, "exchange_rates_daily")
    report.finish()

    source_io.write_table(df, output_parquet_path)
    print(f"Successfully saved {output_parquet_path} ({len(df):,} observations across {df['series_id'].nunique()} series).")
    print(f"Date range: {df['date'].min()} to {df['date'].max()}.")

    return df


if __name__ == "__main__":
    parse_cbi_exchange_rates()
