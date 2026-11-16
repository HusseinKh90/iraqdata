"""
pipeline.parsers.parse_cbi_fx_auction
=====================================
CBI sales of foreign currency (the foreign-currency auction / window), monthly, in million USD.

- 2020-01 to 2023-12: the seed pipeline/seeds/cbi_fx_auction_monthly_seed.xlsx, monthly data the
  maintainer obtained directly from the CBI. The bulletin prints only annual totals for these years;
  each seed year must add up to them.
- 2024-01 on: sheet '3-a' of the CBI Monthly Statistical Bulletin (cbi.iq/page/122), the same
  workbook the monthly update check already downloads.

Series:
    fx.auction_cash       cash sales
    fx.auction_transfers  every non-cash sale (transfers, letters of credit, international
                          settlements, replenishing bank accounts abroad)
    fx.auction_total      total CBI sales of foreign currency

Output: pipeline/data/garden/fx_auction_monthly.parquet
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(repo_root / "src"))
sys.path.insert(0, str(repo_root / "pipeline"))

from iraqdata.schema import CANONICAL_COLUMNS  # noqa: E402
import flags  # noqa: E402
import source_io  # noqa: E402

TABLE = "fx_auction_monthly"
CASH, TRANSFERS, TOTAL = "fx.auction_cash", "fx.auction_transfers", "fx.auction_total"
UNIT = "MILLION_USD"
REALTIME_START = "2026-10-28"  # replaced by the merge's vintage
FIRST_BULLETIN_MONTH = "2024-01"
TOLERANCE = 2.5  # million USD: the bulletin rounds each of its five columns (as validate.FX_SALES_TOLERANCE)

SHEET = "3-a"
CASH_COL, TOTAL_COL = 2, 7          # B: Cash, G: CBI Sales of FC
NONCASH_COLS = (3, 4, 5, 6)         # C-F: Transfer, Letters of credit, International settlement, Replenishing
HEADER_ROW_MAX = 12
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}

SEED_COLUMNS = {"Cash (Million USD)": CASH, "Transfers (Million USD)": TRANSFERS, "Total (Million USD)": TOTAL}


def _row(date: str, series_id: str, value: float, source_hash: str) -> Dict:
    return {"date": date, "series_id": series_id, "value": float(value), "unit": UNIT,
            "status_flag": "A", "realtime_start": REALTIME_START, "source_hash": source_hash}


def _check_sum(path: Path, period: str, cash: float, transfers: float, total: float, sheet=None) -> None:
    if abs(cash + transfers - total) > TOLERANCE:
        raise source_io.ParseError(path, "cash + transfers = total", f"{cash} + {transfers} != {total}",
                                   sheet=sheet, period=period)


def read_seed(seed_path: Path) -> List[Dict]:
    """The seed's months before FIRST_BULLETIN_MONTH."""
    df = source_io.read_excel(seed_path)
    missing = [c for c in ["Date", *SEED_COLUMNS] if c not in df.columns]
    if missing:
        raise source_io.ParseError(seed_path, f"the columns {missing}", f"columns {list(df.columns)}")
    source_hash = source_io.file_hash(seed_path)
    rows = []
    for i, r in df.iterrows():
        date = str(r["Date"]).strip()[:7]
        if date >= FIRST_BULLETIN_MONTH:
            continue
        values = {sid: float(r[col]) for col, sid in SEED_COLUMNS.items()}
        _check_sum(seed_path, date, values[CASH], values[TRANSFERS], values[TOTAL])
        rows += [_row(date, sid, v, source_hash) for sid, v in values.items()]
    return rows


def read_bulletin(bulletin_path: Path):
    """(monthly rows from FIRST_BULLETIN_MONTH on, {year: (cash, transfers, total)} annual rows)."""
    ws = source_io.open_workbook(bulletin_path, [SHEET], data_only=True)[SHEET]
    header = next((r for r in range(1, HEADER_ROW_MAX + 1)
                   if source_io.normalize_label(ws.cell(r, CASH_COL).value) == "cash"), None)
    if header is None or "sales" not in source_io.normalize_label(ws.cell(header, TOTAL_COL).value):
        raise source_io.ParseError(bulletin_path, "the headers 'Cash' (column B) and 'CBI Sales of FC' (column G)",
                                   "not found", sheet=SHEET)
    source_hash = source_io.file_hash(bulletin_path)
    report = source_io.Report("cbi_fx_auction")

    def number(row, col, period):
        cell = ws.cell(row, col)
        v = source_io.read_value(cell.value, report, bulletin_path, sheet=SHEET,
                                 location=f"cell {cell.coordinate}", period=period)
        return 0.0 if v is None else v

    rows, annual, year = [], {}, None
    for r in range(header + 2, ws.max_row + 1):
        label = ws.cell(r, 1).value
        if label is None:
            continue
        text = source_io.normalize_label(label).rstrip(".")
        if text.replace(".0", "").isdigit() and len(text.replace(".0", "")) == 4:
            year = text[:4]
            if ws.cell(r, TOTAL_COL).value is not None:     # a whole-year row (to 2023)
                cash = number(r, CASH_COL, year)
                annual[year] = (cash, sum(number(r, c, year) for c in NONCASH_COLS), number(r, TOTAL_COL, year))
            continue
        if text == "total":
            continue
        month = MONTHS.get(text[:3])
        if month is None or year is None:
            raise source_io.ParseError(bulletin_path, "a year, a month or 'Total'", repr(label),
                                       sheet=SHEET, location=f"cell A{r}")
        date = f"{year}-{month:02d}"
        if date < FIRST_BULLETIN_MONTH:
            continue
        cash = number(r, CASH_COL, date)
        transfers = sum(number(r, c, date) for c in NONCASH_COLS)
        total = number(r, TOTAL_COL, date)
        _check_sum(bulletin_path, date, cash, transfers, total, sheet=SHEET)
        rows += [_row(date, CASH, cash, source_hash), _row(date, TRANSFERS, transfers, source_hash),
                 _row(date, TOTAL, total, source_hash)]
    report.finish()
    if not rows:
        raise source_io.ParseError(bulletin_path, f"monthly rows from {FIRST_BULLETIN_MONTH}", "none", sheet=SHEET)
    return rows, annual


def check_seed_against_bulletin(seed_rows: List[Dict], annual: Dict, seed_path: Path) -> None:
    """Every seed year must add up to the bulletin's annual total for that year."""
    df = pd.DataFrame(seed_rows)
    df["year"] = df["date"].str[:4]
    sums = df.groupby(["year", "series_id"])["value"].sum()
    for year in sorted(df["year"].unique()):
        if year not in annual:
            raise source_io.ParseError(seed_path, f"a {year} annual row in bulletin sheet {SHEET}", "none", period=year)
        for sid, official in zip((CASH, TRANSFERS, TOTAL), annual[year]):
            if abs(sums[(year, sid)] - official) > TOLERANCE:
                raise source_io.ParseError(seed_path, f"{sid} {year} adding up to the bulletin's {official}",
                                           f"{sums[(year, sid)]:.2f}", period=year)


def parse_cbi_fx_auction(seed_path: Path, bulletin_path: Path, output_parquet_path: Path) -> pd.DataFrame:
    seed_path, bulletin_path = source_io.require_file(seed_path), source_io.require_file(bulletin_path)
    seed_rows = read_seed(seed_path)
    bulletin_rows, annual = read_bulletin(bulletin_path)
    check_seed_against_bulletin(seed_rows, annual, seed_path)

    df = pd.DataFrame(seed_rows + bulletin_rows, columns=CANONICAL_COLUMNS)
    df = df.sort_values(["date", "series_id"]).reset_index(drop=True)
    df = flags.assign_flags(df, TABLE)
    source_io.check_schema(df, bulletin_path, TABLE)
    source_io.write_table(df, output_parquet_path)
    print(f"Wrote {output_parquet_path}: {len(df)} observations, {df['date'].min()} to {df['date'].max()}.")
    return df


if __name__ == "__main__":
    import parse_cbi_fiscal_bulletin
    parse_cbi_fx_auction(
        seed_path=repo_root / "pipeline" / "seeds" / "cbi_fx_auction_monthly_seed.xlsx",
        bulletin_path=parse_cbi_fiscal_bulletin.resolve_bulletin_input(repo_root / "pipeline" / "raw" / "cbi"),
        output_parquet_path=repo_root / "pipeline" / "data" / "garden" / f"{TABLE}.parquet",
    )
