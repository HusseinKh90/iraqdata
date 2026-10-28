"""
pipeline.check_fiscal_seed
==========================
Cross-checks the fiscal seed against a CBI document that prints the same years.

    python pipeline/check_fiscal_seed.py [--seed CSV] [--bulletin XLSX]

The seed (pipeline/seeds/iraq_fiscal_historical.csv, 2004-2023) was compiled from documents its
maintainer did not record, so every value carries status flag U. The archived CBI Monthly
Statistical Bulletin prints the annual budget table (sheet 6-1) for the same years, so each value
both print can be compared. Columns are matched by their English header text, never by position.

Every value must be identical, except where the bulletin itself is wrong and the exception is
listed in KNOWN_DIFFERENCES with the reason and with the evidence it needs: here the bulletin has
the 2012 current and investment revenue columns transposed (its 2012 "current" revenue is 78,495
and its "investment" revenue is 119,387,908, while the two sum to the total only the other way
round). An exception that no longer applies, because the bulletin was corrected, is also reported.

This is evidence for the seed, not a change of its status: the flag stays U because the origin is
still unknown. The check is not part of the build.

Exit status: 0 when every compared value is identical or a documented exception, 1 otherwise.
"""

import argparse
import csv
import re
import sys
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple

repo_root = Path(__file__).resolve().parent.parent

SEED = repo_root / "pipeline" / "seeds" / "iraq_fiscal_historical.csv"
BULLETIN = repo_root / "pipeline" / "raw" / "cbi" / "bulletin_latest.xlsx"
SHEET = "6-1"
HEADER_ROWS = 12

# the English header of each bulletin column (letters only, lower case) -> the seed's column
HEADERS = {
    "actualrevenues": "revenue_actual_total",
    "currentrevenues": "revenue_current",
    "investmentrevenues": "revenue_investment",
    "actualexpenditures": "expenditure_actual_total",
    "currentexpenditures": "expenditure_current",
    "investmentexpenditures": "expenditure_investment",
    "surplusdeficit": "fiscal_surplus_deficit",
}

# (series, year) -> why the bulletin's figure is not the seed's; both must be the transposed pair
KNOWN_DIFFERENCES = {
    ("revenue_current", 2012): "the bulletin has the 2012 current and investment revenue columns transposed",
    ("revenue_investment", 2012): "the bulletin has the 2012 current and investment revenue columns transposed",
}
TRANSPOSED = {"revenue_current": "revenue_investment", "revenue_investment": "revenue_current"}


def read_seed(path: Path = SEED) -> Dict[int, Dict[str, float]]:
    with open(path, encoding="utf-8", newline="") as f:
        return {int(row["year"]): {k: float(v) for k, v in row.items() if k != "year" and v != ""}
                for row in csv.DictReader(f)}


def read_bulletin(path: Path = BULLETIN, years=range(2004, 2024)) -> Dict[int, Dict[str, Optional[float]]]:
    """{year: {seed column: value or None}} for the annual rows of sheet 6-1, columns found by their header text."""
    import openpyxl
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sheet = openpyxl.load_workbook(path, data_only=True)[SHEET]
    columns: Dict[int, str] = {}
    header_row = 0
    for row in range(1, HEADER_ROWS + 1):
        found = {}
        for col in range(2, sheet.max_column + 1):
            text = sheet.cell(row, col).value
            key = re.sub(r"[^a-z]+", "", text.lower()) if isinstance(text, str) else ""
            if key in HEADERS:
                found[col] = HEADERS[key]
        if len(found) == len(HEADERS):
            columns, header_row = found, row
            break
    if not columns:
        raise ValueError(f"{path.name} sheet {SHEET!r}: no row in the first {HEADER_ROWS} holds the seven budget headers")
    out: Dict[int, Dict[str, Optional[float]]] = {}
    for row in range(header_row + 1, sheet.max_row + 1):
        year = sheet.cell(row, 1).value
        if isinstance(year, bool) or not isinstance(year, (int, float)) or int(year) != year or int(year) not in years:
            continue
        out[int(year)] = {name: (float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None)
                          for name, v in ((n, sheet.cell(row, c).value) for c, n in columns.items())}
    return out


def compare(seed: Dict[int, Dict[str, float]], bulletin: Dict[int, Dict[str, Optional[float]]]
            ) -> Tuple[Dict[str, int], List[str]]:
    """(counts by outcome, problems). Outcomes: identical, explained, not-printed, differs, stale-exception."""
    counts = {"identical": 0, "explained": 0, "not-printed": 0, "differs": 0, "stale-exception": 0}
    problems: List[str] = []
    for year in sorted(seed):
        for series, mine in sorted(seed[year].items()):
            theirs = bulletin.get(year, {}).get(series)
            known = KNOWN_DIFFERENCES.get((series, year))
            if theirs is None:
                counts["not-printed"] += 1
            elif abs(theirs - mine) <= 0.5:
                if known:
                    counts["stale-exception"] += 1
                    problems.append(f"{series} {year}: the bulletin now agrees with the seed, so the exception is stale")
                else:
                    counts["identical"] += 1
            elif known and abs(theirs - seed[year].get(TRANSPOSED[series], float("nan"))) <= 0.5:
                counts["explained"] += 1  # the bulletin prints the other column's number
            else:
                counts["differs"] += 1
                problems.append(f"{series} {year}: the seed has {mine:,.0f}, the bulletin {theirs:,.0f}")
    return counts, problems


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Cross-check the fiscal seed against the CBI bulletin.")
    parser.add_argument("--seed", type=Path, default=SEED)
    parser.add_argument("--bulletin", type=Path, default=BULLETIN)
    args = parser.parse_args(argv)
    counts, problems = compare(read_seed(args.seed), read_bulletin(args.bulletin))
    compared = sum(counts[k] for k in ("identical", "explained", "differs", "stale-exception"))
    print(f"Fiscal seed against {args.bulletin.name} sheet {SHEET}: {compared} values compared, "
          f"{counts['identical']} identical, {counts['explained']} explained, {counts['differs']} differ; "
          f"{counts['not-printed']} not printed by the bulletin")
    for (series, year), why in sorted(KNOWN_DIFFERENCES.items()):
        print(f"  EXPLAINED {series} {year}: {why}")
    for line in problems:
        print(f"  PROBLEM {line}")
    print("Fiscal seed check: " + ("OK" if not problems else f"{len(problems)} problem(s)"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
