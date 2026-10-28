"""
pipeline.parsers.parse_cbi_bop
==============================
Parser for Family 6 (Balance of Payments & Foreign Trade) from the
Central Bank of Iraq (CBI) Balance of Payments Data Archive (https://cbi.iq/page/145).

Extracts 15 quarterly indicators (2013-Q1 to 2026-Q1, 53 quarters):
- Core Balance of Payments (8 series, BPM6, MILLION_USD):
  1. bop.current_account
  2. bop.trade_balance
  3. bop.services_net
  4. bop.income_net
  5. bop.transfers_net
  6. bop.capital_account
  7. bop.financial_account
  8. bop.reserve_assets_change
- Merchandise Trade Disaggregation (7 series, MILLION_USD):
  9. trade.exports_total
  10. trade.exports_crude_oil
  11. trade.exports_oil_products
  12. trade.exports_nonoil
  13. trade.imports_total
  14. trade.imports_government
  15. trade.imports_private

Quality & Schema Guarantees:
- Single-frequency rule: Produces purely quarterly observations (YYYY-Qn).
- Conforms to standard 7-column Canonical Observation Schema.
- Output: pipeline/data/garden/bop_trade_quarterly.parquet
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
sys.path.append(str(repo_root / "pipeline"))  # downloads.latest_version

from iraqdata.schema import CANONICAL_COLUMNS
import flags  # noqa: E402
import downloads
import source_io  # noqa: E402

UNIT = "MILLION_USD"
REALTIME_START = "2026-10-28"

PATTERNS = {
    "bop.current_account": r"first\s*-\s*current\s*account",
    "bop.trade_balance": r"1-\s*trade\s*balance",
    "trade.exports_total": r"exports\s*\(f\.?o\.?b\)",
    "trade.imports_total": r"^\s*imports\b",
    "trade.imports_government": r"1[\.-]\s*government\s*imports",
    "trade.imports_private": r"2[\.-]\s*private\s*sector",
    "bop.services_net": r"2-\s*services\s*account",
    "bop.income_net": r"3-\s*primary\s*incom",
    "bop.transfers_net": r"4-\s*secondary\s*incom",
    "bop.capital_account": r"second[\s-]*capital\s*account",
    "bop.financial_account": r"third[\s-]*financial\s*account",
    "bop.reserve_assets_change": r"4-\s*reserve\s*assets",
}


# The 15 series every quarter must yield: the PATTERNS rows plus the
# three export components read between the Exports and Imports headers
EXPECTED_SERIES = sorted(list(PATTERNS) + ["trade.exports_crude_oil", "trade.exports_oil_products", "trade.exports_nonoil"])

_BOP_NAME = re.compile(r"^(?P<base>bop_\d{4}(?:_\d{4})?)(?:_(?P<date>\d{4}-\d{2}-\d{2}))?$")


def bop_inputs(bop_dir: Path) -> Dict[str, Path]:
    """
    One workbook per base name: `bop_2013_2016` and `bop_YYYY`. A dated
    re-download `bop_YYYY_<date>.xlsx` replaces its base, the newest date winning; a dated file
    with no undated base (a new year) stands for that year. A dated file is never an extra year.
    """
    best: Dict[str, tuple] = {}
    for path in bop_dir.glob("bop_*.xlsx"):
        m = _BOP_NAME.match(path.stem)
        if not m:
            continue
        dated = m.group("date")
        if dated is not None and downloads.vintage_of(path) is None:
            continue
        rank = dated or ""  # any valid dated copy beats the undated original
        base = m.group("base")
        if base not in best or rank > best[base][0]:
            best[base] = (rank, path)
    return {base: best[base][1] for base in sorted(best)}


compute_file_hash = source_io.file_hash  # 16 hex characters of the file's SHA-256


def find_label_col(df: pd.DataFrame) -> int:
    """Detects whether labels are in Column 0 or Column 1 (defensive against leading blank columns)."""
    for c in range(min(3, df.shape[1])):
        col_vals = [str(df.iloc[r, c]).strip().lower() for r in range(min(25, len(df)))]
        if any("first -current account" in v or "items" in v or "trade balance" in v for v in col_vals):
            return c
    return 0


def parse_df_block(df_block: pd.DataFrame, path: Optional[Path] = None, sheet: Optional[str] = None,
                   period: Optional[str] = None) -> Dict[str, float]:
    """
    Extracts the 15 canonical series from a quarterly table slice. The first row whose label matches
    a series must hold a number: a blank or text value stops the run instead of falling
    through to a later row.
    """
    lc = find_label_col(df_block)
    vc = lc + 1
    res: Dict[str, float] = {}
    rows = []

    for r in range(len(df_block)):
        lbl = str(df_block.iloc[r, lc]).strip()
        val = df_block.iloc[r, vc] if vc < df_block.shape[1] else None
        rows.append((r, lbl, val))

    exp_idx = next((r for r, l, v in rows if re.search(r"exports\s*\(f\.?o\.?b\)", l, re.I)), None)
    imp_idx = next((r for r, l, v in rows if re.search(r"^\s*imports\b", l, re.I)), None)

    for r, l, v in rows:
        try:
            num = round(float(str(v).replace(",", "").strip()), 1)
        except (ValueError, TypeError):
            num = None

        matched = [sid for sid, pat in PATTERNS.items() if re.search(pat, l, re.I) and sid not in res]
        # Disambiguate exports sub-components (strictly between Exports header and Imports header)
        if exp_idx and imp_idx and exp_idx < r < imp_idx:
            if re.search(r"crude\s*oil", l, re.I) and "trade.exports_crude_oil" not in res:
                matched.append("trade.exports_crude_oil")
            elif re.search(r"oil\s*products", l, re.I) and "trade.exports_oil_products" not in res:
                matched.append("trade.exports_oil_products")
            elif re.search(r"other\s*exports", l, re.I) and "trade.exports_nonoil" not in res:
                matched.append("trade.exports_nonoil")
        if matched and (num is None or num != num):
            raise source_io.ParseError(path or "<block>", f"a number for {', '.join(matched)}", repr(v), sheet=sheet,
                                       location=f"row {int(df_block.index[r]) + 1}, label {l!r}", period=period)
        for sid in matched:
            res[sid] = num

    return res


QUARTER_TITLE = re.compile(r"balance of payments\s*\(bpm6\)\s*q([1-4])\s+(\d{4})")

# What every quarter table states above its data (the label checks, applied to the header):
# the title with its quarter and year, the unit line and the header of the value column
SHEET_TITLE = re.compile(r"balance of payments\s*\(bpm6\)\s*(?:primary\s+)?q([1-4])\s*(\d{4})")
UNIT_LINE = re.compile(r"million\s*of\s*u\.?\s*s\.?\s*\$")
VALUE_HEADERS = {"fob", "amount"}  # '(FOB)', '( FOB )'; the 2019 Q1 sheet says 'Amount'
HEADER_ROWS = 15


def _text(value) -> str:
    return " ".join(str(value).split()).lower() if isinstance(value, str) else ""


def check_table_header(df: pd.DataFrame, path: Path, sheet: str, period: str) -> None:
    """
    The first rows of a quarter table must carry the title for `period` (YYYY-Qn), the unit line
    "Million Of U.S $" and, under "Items", a value-column header of FOB (or Amount). Raises a
    ParseError naming the sheet, the row and the period.
    """
    year, quarter = period.split("-Q")
    rows = df.iloc[:HEADER_ROWS]
    first = int(df.index[0]) if len(df) else 0
    where = lambda r: f"row {int(df.index[r]) + 1}"  # noqa: E731  (sheet row of the table's r-th row)
    titles = [(r, SHEET_TITLE.search(_text(v))) for r in range(len(rows)) for v in rows.iloc[r, :3]]
    titles = [(r, m) for r, m in titles if m]
    if not titles:
        raise source_io.ParseError(path, f"a title 'IRAQI BALANCE OF PAYMENTS (BPM6) Q{quarter} {year}' in the first "
                                   f"{HEADER_ROWS} rows", "none", sheet=sheet, location=f"from row {first + 1}", period=period)
    for r, m in titles:
        if (m.group(1), m.group(2)) != (quarter, year):
            raise source_io.ParseError(path, f"a title for Q{quarter} {year}", f"the title of q{m.group(1)} {m.group(2)}",
                                       sheet=sheet, location=where(r), period=period)
    cells = rows.iloc[:, :3].to_numpy().ravel()
    if not any(UNIT_LINE.search(_text(v).replace(" ", "")) for v in cells):
        near = next((v.strip() for v in cells if isinstance(v, str) and "$" in v), None)
        raise source_io.ParseError(path, "the unit line 'Million Of U.S $' in the first rows",
                                   repr(near) if near else "no unit line", sheet=sheet,
                                   location=f"from row {first + 1}", period=period)
    for r in range(len(rows)):
        for c in range(min(3, df.shape[1] - 1)):
            if _text(rows.iloc[r, c]) == "items":
                header = rows.iloc[r, c + 1]
                key = "".join(ch for ch in _text(header) if ch.isalpha())
                if key not in VALUE_HEADERS:
                    raise source_io.ParseError(path, "the value column headed '(FOB)' next to 'Items'", repr(header),
                                               sheet=sheet, location=where(r), period=period)
                return
    raise source_io.ParseError(path, "a row 'Items' with the value-column header '(FOB)' in the first rows", "none",
                               sheet=sheet, location=f"from row {first + 1}", period=period)
SOURCE_LINE = re.compile(r"^source\s*:")


def quarter_blocks(df: pd.DataFrame, path: Path, sheet: str, year: str) -> Dict[int, pd.DataFrame]:
    """
    The four quarter blocks of one sheet of the stacked 2013-2016 workbook: each
    starts at its first title row "IRAQI BALANCE OF PAYMENTS(BPM6)qN YYYY" (a continuation page
    repeats the title) and ends at the next "Source :" line. A block without a quarter in its title
    (the annual table) is not read. Each quarter must appear exactly once, with the sheet's year.
    """
    labels = [source_io.normalize_label(v) for v in df.iloc[:, 0]]
    starts: Dict[int, int] = {}
    current = None
    for r, text in enumerate(labels):
        if SOURCE_LINE.match(text):
            current = None
            continue
        m = QUARTER_TITLE.search(text)
        if m is None:
            continue
        q, y = int(m.group(1)), m.group(2)
        if y != year:
            raise source_io.ParseError(path, f"a quarter title for {year}", repr(df.iloc[r, 0]), sheet=sheet,
                                       location=f"row {r + 1}")
        if current == q:
            continue  # the title repeated on the block's continuation page
        if q in starts:
            raise source_io.ParseError(path, f"one block titled '... (BPM6) q{q} {year}'", "two",
                                       sheet=sheet, location=f"rows {starts[q] + 1} and {r + 1}")
        starts[q], current = r, q
    blocks: Dict[int, pd.DataFrame] = {}
    for q in range(1, 5):
        if q not in starts:
            raise source_io.ParseError(path, f"one block titled '... (BPM6) q{q} {year}'", "none", sheet=sheet)
        end = next((r for r in range(starts[q] + 1, len(labels)) if SOURCE_LINE.match(labels[r])), None)
        if end is None:
            raise source_io.ParseError(path, f"a 'Source :' line ending the q{q} {year} block", "none", sheet=sheet,
                                       location=f"after row {starts[q] + 1}")
        blocks[q] = df.iloc[starts[q]:end + 1]
    return blocks


def parse_cbi_bop(
    bop_dir: Optional[Path] = None,
    output_parquet_path: Optional[Path] = None
) -> pd.DataFrame:
    """
    Parses all archived CBI BOP workbooks and generates
    pipeline/data/garden/bop_trade_quarterly.parquet.
    """
    if bop_dir is None:
        bop_dir = repo_root / "pipeline" / "raw" / "cbi" / "bop"

    if output_parquet_path is None:
        output_parquet_path = repo_root / "pipeline" / "data" / "garden" / "bop_trade_quarterly.parquet"

    if not bop_dir.exists():
        raise FileNotFoundError(f"BOP archive directory not found at: {bop_dir}")

    observations: List[Dict] = []
    where: List[str] = []  # the workbook and sheet of each observation, for duplicate messages
    inputs = bop_inputs(bop_dir)
    quarters: Dict[int, set] = {}  # year -> quarters parsed
    files: Dict[int, str] = {}  # year -> workbook that holds it
    report = source_io.Report("cbi_bop")

    # 1. Process multi-year stacked workbook (2013-2016); quarter blocks are found by their titles
    f_stacked = inputs.get("bop_2013_2016")
    if f_stacked is not None:
        wb_stacked = source_io.open_workbook(f_stacked, data_only=True)
        hash_stacked = compute_file_hash(f_stacked)
        for sheet in wb_stacked.sheetnames:
            m = re.search(r"201\d", sheet)
            if not m:
                continue
            yr = m.group(0)
            df = source_io.read_excel(f_stacked, sheet_name=sheet, header=None)
            for q, df_sub in quarter_blocks(df, f_stacked, sheet, yr).items():
                q_name = f"Q{q}"
                period = f"{yr}-{q_name}"
                check_table_header(df_sub, f_stacked, sheet, period)
                res = parse_df_block(df_sub, f_stacked, sheet, period)
                missing = [sid for sid in EXPECTED_SERIES if sid not in res]
                if missing:
                    msg = f"{f_stacked.name}: sheet '{sheet}' ({period}): series not found: {', '.join(missing)}"
                    raise ValueError(msg)
                quarters.setdefault(int(yr), set()).add(int(q_name[1]))
                files[int(yr)] = f_stacked.name
                for sid, val in res.items():
                    observations.append({
                        "date": period,
                        "series_id": sid,
                        "value": val,
                        "unit": UNIT,
                        "status_flag": "A",
                        "realtime_start": REALTIME_START,
                        "source_hash": hash_stacked,
                    })
                    where.append(f"{f_stacked.name}, sheet '{sheet}'")

    # 2. Process single-year workbooks (2017 onwards)
    for base, fpath in inputs.items():
        if base == "bop_2013_2016":
            continue
        yr = int(base[4:])
        wb = source_io.open_workbook(fpath, data_only=True)
        source_hash = compute_file_hash(fpath)
        for sheet in wb.sheetnames:
            clean = sheet.strip().upper()
            m = re.search(r"Q([1-4])", clean)
            if m and "ANNU" not in clean and "YEAR" not in clean:
                q_name = f"Q{m.group(1)}"
                period = f"{yr}-{q_name}"
                df = source_io.read_excel(fpath, sheet_name=sheet, header=None)
                check_table_header(df, fpath, sheet, period)
                res = parse_df_block(df, fpath, sheet, period)
                missing = [sid for sid in EXPECTED_SERIES if sid not in res]
                if missing:
                    msg = f"{fpath.name}: sheet '{sheet}' ({period}): series not found: {', '.join(missing)}"
                    raise ValueError(msg)
                quarters.setdefault(yr, set()).add(int(m.group(1)))
                files[yr] = fpath.name
                flag = "A"  # provisional; pipeline/flags.py sets the final flag from the flag policy
                for sid, val in res.items():
                    observations.append({
                        "date": period,
                        "series_id": sid,
                        "value": val,
                        "unit": UNIT,
                        "status_flag": flag,
                        "realtime_start": REALTIME_START,
                        "source_hash": source_hash,
                    })
                    where.append(f"{fpath.name}, sheet '{sheet}'")

    # 3. No gap between the first and last period: every year present, Q1-Q4 for all but the last
    #    year, which may be partly published (its newest quarter is the freshness check's job)
    if quarters:
        first, last = min(quarters), max(quarters)
        for year in range(first, last + 1):
            if year not in quarters:
                expected = f"bop_{year}.xlsx" if year >= 2017 else f"a {year} sheet in bop_2013_2016.xlsx"
                msg = f"{bop_dir.name}: no BOP workbook for {year} between {first} and {last}: expected {expected}"
                raise ValueError(msg)
            required = set(range(1, 5)) if year < last else set(range(1, max(quarters[year]) + 1))
            gaps = sorted(required - quarters[year])
            if gaps:
                msg = f"{files[year]}: BOP {year} has no sheet for quarter(s) {', '.join(f'Q{q}' for q in gaps)}"
                raise ValueError(msg)

    df_out = pd.DataFrame(observations, columns=CANONICAL_COLUMNS)
    df_out = source_io.collapse_duplicates(df_out, bop_dir, report, where=where)
    df_out = df_out.sort_values(by=["series_id", "date"]).reset_index(drop=True)

    # 3. Tier-1 Validation
    # Final status flags from the flag policy (pipeline/metadata/flag_policy.yaml)
    df_out = flags.assign_flags(df_out, "bop_trade_quarterly")
    source_io.check_schema(df_out, bop_dir, "bop_trade_quarterly")
    report.finish()

    source_io.write_table(df_out, output_parquet_path)
    print(f"Successfully saved {output_parquet_path} ({len(df_out):,} observations across {df_out['series_id'].nunique()} series).")
    print(f"Time span: {df_out['date'].min()} to {df_out['date'].max()} ({df_out['date'].nunique()} quarters).")

    return df_out


if __name__ == "__main__":
    parse_cbi_bop()
