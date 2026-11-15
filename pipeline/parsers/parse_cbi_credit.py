"""
pipeline.parsers.parse_cbi_credit
=================================
Commercial bank direct cash credit by sector, monthly end-of-period stocks, in million IQD.

- 2015-01 to 2023-12: the seed pipeline/seeds/cbi_credit_monthly_seed.xlsx, monthly data the
  maintainer obtained from the CBI. The bulletin prints only year-end rows for these years; every
  seed December must match them.
- 2024-01 on: sheets '8-a' (all commercial banks), '8-b' (state-owned banks) and '8-c' (private
  banks) of the CBI Monthly Statistical Bulletin (cbi.iq/page/122), the workbook the weekly update
  check already downloads.

Series (each the sum of overdrafts, discounted bills, loans and advances, and past-due debts):
    credit.private_total          8-a "Private Sector"
    credit.private_state_banks    8-b "Private Sector"
    credit.private_private_banks  8-c "Private Sector"
    credit.central_gov            8-a "Central Govt."
    credit.public_institutions    8-a "Public Institutions"
    credit.total                  8-a "Total of Cash Credit Commercial Banks"

Output: pipeline/data/garden/credit_monthly.parquet
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

TABLE = "credit_monthly"
UNIT = "MILLION_IQD"
REALTIME_START = "2026-10-28"  # replaced by the merge's vintage
FIRST_BULLETIN_MONTH = "2024-01"
TOLERANCE = 1.0  # million IQD: the bulletin stores some figures with tiny fractions

PRIVATE, STATE, PRIVATE_BANKS = "credit.private_total", "credit.private_state_banks", "credit.private_private_banks"
CENTRAL, PUBLIC, TOTAL = "credit.central_gov", "credit.public_institutions", "credit.total"

# {series: (sheet, English header the column carries)}
COLUMNS = {
    CENTRAL: ("8-a", "central govt"),
    PUBLIC: ("8-a", "public institutions"),
    PRIVATE: ("8-a", "private sector"),
    TOTAL: ("8-a", "total of cash credit"),
    STATE: ("8-b", "private sector"),
    PRIVATE_BANKS: ("8-c", "private sector"),
}
SHEETS = ("8-a", "8-b", "8-c")
SEED_COLUMNS = {"CPS_Total": PRIVATE, "CPS_StateBanks": STATE, "CPS_PrivateBanks": PRIVATE_BANKS,
                "Credit_CentralGov": CENTRAL, "Credit_PublicInst": PUBLIC, "Credit_Total": TOTAL}
# The year-end rows the seed's Decembers must match. Central government and public institutions are
# left out: in 2022 the bulletin moves 14,986 between them (the total is the same), and both are
# still covered by the identity for credit.total.
YEAR_END_CHECKED = (PRIVATE, STATE, PRIVATE_BANKS, TOTAL)
HEADER_ROW_MAX = 12
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def _row(date: str, series_id: str, value: float, source_hash: str) -> Dict:
    return {"date": date, "series_id": series_id, "value": float(value), "unit": UNIT,
            "status_flag": "A", "realtime_start": REALTIME_START, "source_hash": source_hash}


def check_identities(path: Path, period: str, v: Dict[str, float]) -> None:
    """Private = state + private banks; total = private + central government + public institutions."""
    for whole, parts in ((PRIVATE, (STATE, PRIVATE_BANKS)), (TOTAL, (PRIVATE, CENTRAL, PUBLIC))):
        if abs(sum(v[p] for p in parts) - v[whole]) > TOLERANCE:
            raise source_io.ParseError(path, f"{whole} = {' + '.join(parts)}",
                                       f"{v[whole]} vs {sum(v[p] for p in parts)}", period=period)


def read_seed(seed_path: Path) -> pd.DataFrame:
    """The seed as {period: {series: value}} rows (all months), checked for the two identities."""
    df = source_io.read_excel(seed_path)
    missing = [c for c in ["Date", *SEED_COLUMNS] if c not in df.columns]
    if missing:
        raise source_io.ParseError(seed_path, f"the columns {missing}", f"columns {list(df.columns)}")
    df = df.assign(Date=df["Date"].astype(str).str.strip().str[:7]).set_index("Date")
    df = df[list(SEED_COLUMNS)].rename(columns=SEED_COLUMNS).astype(float)
    for period, values in df.iterrows():
        check_identities(seed_path, period, values.to_dict())
    return df


def _header(ws, path: Path, sheet: str) -> int:
    row = next((r for r in range(1, HEADER_ROW_MAX + 1)
                if source_io.normalize_label(ws.cell(r, 1).value).startswith("end of period")), None)
    if row is None:
        raise source_io.ParseError(path, "the header 'End of Period' in column A", "not found", sheet=sheet)
    return row


def _column(ws, row: int, label: str, path: Path, sheet: str) -> int:
    """The last column whose header names `label` (8-a has one 'Private Sector' total, after the parts)."""
    found = [c for c in range(1, ws.max_column + 1) if label in source_io.normalize_label(ws.cell(row, c).value)]
    if not found:
        raise source_io.ParseError(path, f"a column headed {label!r}", "none", sheet=sheet, location=f"row {row}")
    return found[-1]


def read_sheet(wb, path: Path, sheet: str, report) -> Dict[str, Dict[str, float]]:
    """{period: {series: value}} for the series read from `sheet`: year-end rows as YYYY-12, then months."""
    ws = wb[sheet]
    header = _header(ws, path, sheet)
    cols = {sid: _column(ws, header, label, path, sheet) for sid, (s, label) in COLUMNS.items() if s == sheet}
    out, year = {}, None
    for r in range(header + 1, ws.max_row + 1):
        label = ws.cell(r, 1).value
        if label is None:
            continue
        text = source_io.normalize_label(label)
        if text.removesuffix(".0").isdigit() and len(text.removesuffix(".0")) == 4:
            year = text[:4]
            period = f"{year}-12"   # a year-end row; blank for years printed month by month
        else:
            month = MONTHS.get(text[:3])
            if month is None or year is None:
                raise source_io.ParseError(path, "a year or a month", repr(label), sheet=sheet, location=f"cell A{r}")
            period = f"{year}-{month:02d}"
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
    """{period: {series: value}} merged over the three sheets."""
    wb = source_io.open_workbook(bulletin_path, list(SHEETS), data_only=True)
    report = source_io.Report("cbi_credit")
    merged: Dict[str, Dict[str, float]] = {}
    for sheet in SHEETS:
        for period, values in read_sheet(wb, bulletin_path, sheet, report).items():
            merged.setdefault(period, {}).update(values)
    report.finish()
    return merged


def parse_cbi_credit(seed_path: Path, bulletin_path: Path, output_parquet_path: Path) -> pd.DataFrame:
    seed_path, bulletin_path = source_io.require_file(seed_path), source_io.require_file(bulletin_path)
    seed = read_seed(seed_path)
    bulletin = read_bulletin(bulletin_path)

    # Every seed December before the bulletin's months must match the bulletin's year-end row
    for period in [p for p in seed.index if p.endswith("-12") and p < FIRST_BULLETIN_MONTH]:
        official = bulletin.get(period, {})
        if not set(YEAR_END_CHECKED) <= set(official):
            raise source_io.ParseError(bulletin_path, f"{period[:4]} year-end values for {list(YEAR_END_CHECKED)}",
                                       f"only {sorted(official)}", sheet=", ".join(SHEETS), period=period)
        for sid in YEAR_END_CHECKED:
            if abs(seed.at[period, sid] - official[sid]) > TOLERANCE:
                raise source_io.ParseError(seed_path, f"{sid} {period} equal to the bulletin's {official[sid]}",
                                           f"{seed.at[period, sid]}", period=period)

    seed_hash, bulletin_hash = source_io.file_hash(seed_path), source_io.file_hash(bulletin_path)
    rows: List[Dict] = []
    for period, values in seed[seed.index < FIRST_BULLETIN_MONTH].iterrows():
        rows += [_row(period, sid, v, seed_hash) for sid, v in values.items()]
    months = sorted(p for p in bulletin if p >= FIRST_BULLETIN_MONTH)
    if not months:
        raise source_io.ParseError(bulletin_path, f"monthly rows from {FIRST_BULLETIN_MONTH}", "none", sheet="8-a")
    for period in months:
        values = bulletin[period]
        if set(values) != set(COLUMNS):
            raise source_io.ParseError(bulletin_path, f"all six series for {period}",
                                       f"only {sorted(values)}", sheet=", ".join(SHEETS), period=period)
        check_identities(bulletin_path, period, values)
        rows += [_row(period, sid, v, bulletin_hash) for sid, v in values.items()]

    df = pd.DataFrame(rows, columns=CANONICAL_COLUMNS).sort_values(["date", "series_id"]).reset_index(drop=True)
    df = flags.assign_flags(df, TABLE)
    source_io.check_schema(df, bulletin_path, TABLE)
    source_io.write_table(df, output_parquet_path)
    print(f"Wrote {output_parquet_path}: {len(df)} observations, {df['date'].min()} to {df['date'].max()}.")
    return df


if __name__ == "__main__":
    import parse_cbi_fiscal_bulletin
    parse_cbi_credit(
        seed_path=repo_root / "pipeline" / "seeds" / "cbi_credit_monthly_seed.xlsx",
        bulletin_path=parse_cbi_fiscal_bulletin.resolve_bulletin_input(repo_root / "pipeline" / "raw" / "cbi"),
        output_parquet_path=repo_root / "pipeline" / "data" / "garden" / f"{TABLE}.parquet",
    )
