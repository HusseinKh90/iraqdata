"""
pipeline.parsers.parse_cbi_govt_claims
======================================
Banking-system claims on, and deposits of, the central government: monthly end-of-period stocks,
in million IQD, from 2018-01.

- 2018-01 to 2023-12: the seed pipeline/seeds/cbi_govt_claims_monthly_seed.csv, monthly data the
  maintainer obtained from the CBI (its 2015-2017 rows predate the CBI's revision of its tables to
  the IMF methodology and are not read). The bulletin prints only year-end rows for these years;
  every seed December must match them.
- 2024-01 on: sheets '4' (Consolidated Statement of the CBI) and '5' (Consolidated Statement of
  Commercial Banks) of the CBI Monthly Statistical Bulletin (cbi.iq/page/122), the workbook the
  monthly update check already downloads.

Read (columns as the sheets number them; column 1 is the period):
    govt.cbi_claims_total   sheet 4, column 3   Claims on Government, Total (3+4)
    govt.cbi_tbills         sheet 4, column 4   Govt. T. Bills & Securities
    govt.cbi_loans          sheet 4, column 5   Loans & Advances to Govt.
    govt.cbi_deposits       sheet 4, column 12  Govt. Deposits
    govt.bank_claims        sheet 5, column 5   Claims on Central Govt.
    govt.bank_deposits      sheet 5, column 13  Govt. Deposits
Computed:
    govt.cbi_net_claims       = cbi_claims_total - cbi_deposits
    govt.bank_net_claims      = bank_claims - bank_deposits
    govt.system_debt_holdings = cbi_tbills + bank_claims
    govt.system_deposits      = cbi_deposits + bank_deposits
    govt.system_net_claims    = cbi_net_claims + bank_net_claims

Output: pipeline/data/garden/govt_claims_monthly.parquet
"""

import sys
from pathlib import Path
from typing import Dict, List

import pandas as pd

repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(repo_root / "src"))
sys.path.insert(0, str(repo_root / "pipeline"))

from iraqdata.schema import CANONICAL_COLUMNS  # noqa: E402
import flags  # noqa: E402
import source_io  # noqa: E402

TABLE = "govt_claims_monthly"
UNIT = "MILLION_IQD"
REALTIME_START = "2026-10-28"  # replaced by the merge's vintage
FIRST_MONTH = "2018-01"
FIRST_BULLETIN_MONTH = "2024-01"

CBI_CLAIMS, CBI_TBILLS, CBI_LOANS, CBI_DEPOSITS = (
    "govt.cbi_claims_total", "govt.cbi_tbills", "govt.cbi_loans", "govt.cbi_deposits")
BANK_CLAIMS, BANK_DEPOSITS = "govt.bank_claims", "govt.bank_deposits"
CBI_NET, BANK_NET = "govt.cbi_net_claims", "govt.bank_net_claims"
SYSTEM_DEBT, SYSTEM_DEPOSITS, SYSTEM_NET = "govt.system_debt_holdings", "govt.system_deposits", "govt.system_net_claims"

# {series: (sheet, column, a word its header carries)}
COLUMNS = {
    CBI_CLAIMS: ("4", 3, "total"),
    CBI_TBILLS: ("4", 4, "bills"),
    CBI_LOANS: ("4", 5, "loans"),
    CBI_DEPOSITS: ("4", 12, "deposits"),
    BANK_CLAIMS: ("5", 5, "claims on"),
    BANK_DEPOSITS: ("5", 13, "govt"),
}
SHEETS = ("4", "5")
SEED_COLUMNS = {"CBI_Gov_TBills": CBI_TBILLS, "CBI_Gov_Loans": CBI_LOANS, "CBI_Claims_Gov_Total": CBI_CLAIMS,
                "CBI_Gov_Deposits": CBI_DEPOSITS, "Bank_Claims_Gov": BANK_CLAIMS, "Bank_Gov_Deposits": BANK_DEPOSITS}
HEADER_ROW_MAX = 20
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def tolerance(value: float) -> float:
    """1 million IQD, or 0.01% of the value (the year-end rows of 2023 differ from the months by 692)."""
    return max(1.0, 1e-4 * abs(value))


def derive(v: Dict[str, float]) -> Dict[str, float]:
    """The five computed series from the six read ones."""
    cbi_net, bank_net = v[CBI_CLAIMS] - v[CBI_DEPOSITS], v[BANK_CLAIMS] - v[BANK_DEPOSITS]
    return {CBI_NET: cbi_net, BANK_NET: bank_net, SYSTEM_DEBT: v[CBI_TBILLS] + v[BANK_CLAIMS],
            SYSTEM_DEPOSITS: v[CBI_DEPOSITS] + v[BANK_DEPOSITS], SYSTEM_NET: cbi_net + bank_net}


def check_claims(path: Path, period: str, v: Dict[str, float]) -> None:
    """The CBI's claims on government = its T-bills and securities + its loans and advances."""
    if abs(v[CBI_TBILLS] + v[CBI_LOANS] - v[CBI_CLAIMS]) > tolerance(v[CBI_CLAIMS]):
        raise source_io.ParseError(path, f"{CBI_CLAIMS} = {CBI_TBILLS} + {CBI_LOANS}",
                                   f"{v[CBI_CLAIMS]} vs {v[CBI_TBILLS] + v[CBI_LOANS]}", period=period)


def read_seed(seed_path: Path) -> pd.DataFrame:
    df = source_io.read_csv(seed_path)
    missing = [c for c in ["Date", *SEED_COLUMNS] if c not in df.columns]
    if missing:
        raise source_io.ParseError(seed_path, f"the columns {missing}", f"columns {list(df.columns)}")
    df = df.assign(Date=df["Date"].astype(str).str.strip().str[:7]).set_index("Date")
    df = df[list(SEED_COLUMNS)].rename(columns=SEED_COLUMNS).astype(float)
    df = df[df.index >= FIRST_MONTH]
    for period, values in df.iterrows():
        check_claims(seed_path, period, values.to_dict())
    return df


def read_sheet(wb, path: Path, sheet: str, report) -> Dict[str, Dict[str, float]]:
    """{period: {series: value}}: year-end rows as YYYY-12, then the months."""
    ws = wb[sheet]
    header = next((r for r in range(1, HEADER_ROW_MAX + 1)
                   if source_io.normalize_label(ws.cell(r, 1).value) == "period"), None)
    if header is None:
        raise source_io.ParseError(path, "the header 'Period' in column A", "not found", sheet=sheet)
    cols = {sid: col for sid, (s, col, _) in COLUMNS.items() if s == sheet}
    for sid, (s, col, word) in COLUMNS.items():
        if s == sheet:
            # the header block ends a few rows below the "Period" label (sheet 5: rows 13-14)
            text = " ".join(source_io.normalize_label(ws.cell(r, col).value) for r in range(1, header + 3))
            if word not in text:
                raise source_io.ParseError(path, f"a header with {word!r} above column {col} ({sid})",
                                           repr(text.strip()), sheet=sheet)
    out, year = {}, None
    for r in range(header + 1, ws.max_row + 1):
        label = ws.cell(r, 1).value
        if label is None:
            continue
        text = source_io.normalize_label(label).strip(". ")
        if text.removesuffix(".0").isdigit() and len(text.removesuffix(".0")) == 4:
            year, period = text[:4], f"{text[:4]}-12"   # a year-end row; blank for years printed by month
        elif text[:3] in MONTHS and year is not None:
            period = f"{year}-{MONTHS[text[:3]]:02d}"
        else:
            continue  # the methodology note under the table
        values = {}
        for sid, c in cols.items():
            cell = ws.cell(r, c)
            v = source_io.read_value(cell.value, report, path, sheet=sheet, location=f"cell {cell.coordinate}",
                                     period=period)
            if v is not None:
                values[sid] = v
        if values:
            out[period] = values
    return out


def read_bulletin(bulletin_path: Path) -> Dict[str, Dict[str, float]]:
    wb = source_io.open_workbook(bulletin_path, list(SHEETS), data_only=True)
    report = source_io.Report("cbi_govt_claims")
    merged: Dict[str, Dict[str, float]] = {}
    for sheet in SHEETS:
        for period, values in read_sheet(wb, bulletin_path, sheet, report).items():
            merged.setdefault(period, {}).update(values)
    report.finish()
    return merged


def _rows(period: str, values: Dict[str, float], source_hash: str) -> List[Dict]:
    return [{"date": period, "series_id": sid, "value": float(v), "unit": UNIT, "status_flag": "A",
             "realtime_start": REALTIME_START, "source_hash": source_hash}
            for sid, v in {**values, **derive(values)}.items()]


def parse_cbi_govt_claims(seed_path: Path, bulletin_path: Path, output_parquet_path: Path) -> pd.DataFrame:
    seed_path, bulletin_path = source_io.require_file(seed_path), source_io.require_file(bulletin_path)
    seed = read_seed(seed_path)
    bulletin = read_bulletin(bulletin_path)

    # Every seed December must match the bulletin's year-end row
    for period in [p for p in seed.index if p.endswith("-12") and p < FIRST_BULLETIN_MONTH]:
        official = bulletin.get(period, {})
        if set(official) != set(COLUMNS):
            raise source_io.ParseError(bulletin_path, f"{period[:4]} year-end values for all six series",
                                       f"only {sorted(official)}", sheet=", ".join(SHEETS), period=period)
        for sid, value in official.items():
            if abs(seed.at[period, sid] - value) > tolerance(value):
                raise source_io.ParseError(seed_path, f"{sid} {period} equal to the bulletin's {value}",
                                           f"{seed.at[period, sid]}", period=period)

    seed_hash, bulletin_hash = source_io.file_hash(seed_path), source_io.file_hash(bulletin_path)
    rows: List[Dict] = []
    for period, values in seed[seed.index < FIRST_BULLETIN_MONTH].iterrows():
        rows += _rows(period, values.to_dict(), seed_hash)
    months = sorted(p for p in bulletin if p >= FIRST_BULLETIN_MONTH)
    if not months:
        raise source_io.ParseError(bulletin_path, f"monthly rows from {FIRST_BULLETIN_MONTH}", "none", sheet="4")
    for period in months:
        values = bulletin[period]
        if set(values) != set(COLUMNS):
            raise source_io.ParseError(bulletin_path, f"all six series for {period}", f"only {sorted(values)}",
                                       sheet=", ".join(SHEETS), period=period)
        check_claims(bulletin_path, period, values)
        rows += _rows(period, values, bulletin_hash)

    df = pd.DataFrame(rows, columns=CANONICAL_COLUMNS).sort_values(["date", "series_id"]).reset_index(drop=True)
    df = flags.assign_flags(df, TABLE)
    source_io.check_schema(df, bulletin_path, TABLE)
    source_io.write_table(df, output_parquet_path)
    print(f"Wrote {output_parquet_path}: {len(df)} observations, {df['date'].min()} to {df['date'].max()}.")
    return df


if __name__ == "__main__":
    import parse_cbi_fiscal_bulletin
    parse_cbi_govt_claims(
        seed_path=repo_root / "pipeline" / "seeds" / "cbi_govt_claims_monthly_seed.csv",
        bulletin_path=parse_cbi_fiscal_bulletin.resolve_bulletin_input(repo_root / "pipeline" / "raw" / "cbi"),
        output_parquet_path=repo_root / "pipeline" / "data" / "garden" / f"{TABLE}.parquet",
    )
