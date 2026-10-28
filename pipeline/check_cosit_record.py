"""
pipeline.check_cosit_record
===========================
Checks the COSIT GDP transcription record against the archived documents it cites.

    python pipeline/check_cosit_record.py [--record PATH]

Every row that cites an archived document says where its number is: a workbook cell
(`sheet '<name>' cell <ref>`) or a PDF page (`page <n>, table 1, column ...`), and its `notes`
give the number as printed (`printed=82,974,731`) or the subtraction that gives it
(`computed=82,974,731 - 52,311,241`, an oil value derived from the total and the non-oil total
the table prints). The check reads the document, never the parser, and fails when

- a workbook cell does not hold the value (or the printed text) the row gives;
- a workbook row is not the line the series means: GDP is the line COSIT labels "الناتج المحلي الإجمالي"
  (after the imputed bank service charge, as the early-warning reports print it), never the total by
  activities above it, and oil is the crude-oil line;
- a printed number is not on the cited PDF page;
- a computed value is not the difference of the two printed numbers it names.

A cited page that is a scan has no text to read. Its numbers are accepted when another archived
document prints the same number (each early-warning report also shows the previous quarter and
the same quarter a year earlier; only the pages the record cites are searched), and are otherwise
reported as not checked. Rows whose source is
not archived (the quarters before 2020 and a few later ones) are counted, not checked.

Exit status: 0 when no row disagrees with its document, 1 otherwise.
"""

import argparse
import csv
import re
import sys
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "pipeline" / "parsers"))

RAW_ROOT = repo_root / "pipeline" / "raw"
RECORDS = RAW_ROOT / "transcribed"
TOLERANCE = 0.06  # a computed value is rounded to one decimal
GDP_LINE, OIL_LINE = "الناتج المحلي الإجمالي", "النفط الخام"

_ARABIC = re.compile("[؀-ۿ]")
_CELL = re.compile(r"^sheet '(?P<sheet>.*)' cell (?P<ref>[A-Z]+[0-9]+)$")
_PAGE = re.compile(r"^page (?P<page>[0-9]+),")
_PRINTED = re.compile(r"^printed=(?P<text>\S+)$")
_COMPUTED = re.compile(r"^computed=(?P<a>\S+) - (?P<b>\S+)$")


def newest_record(folder: Path = RECORDS) -> Path:
    return sorted(folder.glob("cosit_gdp_quarterly_*.csv"))[-1]


def _number(text: str) -> float:
    return float(text.replace(",", ""))


class Documents:
    """Archived workbooks and PDFs, opened once."""

    def __init__(self, root: Path = RAW_ROOT):
        self.root = root
        self._cells: Dict[Tuple[str, str], object] = {}
        self._pages: Dict[Tuple[str, int], Optional[str]] = {}
        self.cited: set = set()  # (document, page) of every PDF page the record cites

    def cell(self, document: str, sheet: str, ref: str):
        path = self.root / document
        if path.suffix == ".xls":
            import xlrd
            from openpyxl.utils.cell import coordinate_to_tuple
            book = self._cells.setdefault((document, ""), xlrd.open_workbook(path))
            row, col = coordinate_to_tuple(ref)
            if sheet not in book.sheet_names():
                raise KeyError(f"no sheet {sheet!r}")
            return book.sheet_by_name(sheet).cell_value(row - 1, col - 1)
        import openpyxl
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            book = self._cells.setdefault((document, ""), openpyxl.load_workbook(path, data_only=True))
        sheets = {ws.title: ws for ws in book.worksheets}
        if sheet not in sheets:
            raise KeyError(f"no sheet {sheet!r}")
        return sheets[sheet][ref].value

    def row_label(self, document: str, sheet: str, ref: str) -> str:
        """The label of the row a cell is on: the first Arabic text in its first five columns (a code like 2-1 is not one)."""
        from openpyxl.utils.cell import coordinate_to_tuple
        row, _ = coordinate_to_tuple(ref)
        path = self.root / document
        if path.suffix == ".xls":
            import xlrd
            values = xlrd.open_workbook(path).sheet_by_name(sheet).row_values(row - 1)[:5]
        else:
            self.cell(document, sheet, ref)  # opens the workbook
            ws = {w.title: w for w in self._cells[(document, "")].worksheets}[sheet]
            values = [ws.cell(row, c).value for c in range(1, 6)]
        return next((v.strip() for v in values if isinstance(v, str) and _ARABIC.search(v)), "")

    def page_text(self, document: str, page: int) -> Optional[str]:
        """The text of a PDF page, or None when the page has none (a scan)."""
        key = (document, page)
        if key not in self._pages:
            import pdfplumber
            with pdfplumber.open(self.root / document) as pdf:
                text = (pdf.pages[page - 1].extract_text() or "").strip()
            self._pages[key] = text or None
        return self._pages[key]

    def corpus(self) -> str:
        """The text of the cited pages that have any, for numbers that appear on a scanned page."""
        return "\n".join(filter(None, (self.page_text(doc, page) for doc, page in sorted(self.cited))))


def _on_page(token: str, text: str) -> bool:
    return re.search(rf"(?<![0-9,.]){re.escape(token)}(?![0-9,]|\.[0-9])", text) is not None


def check_row(row: Dict[str, str], docs: Documents) -> Tuple[str, List[str]]:
    """(how the row was checked, problems). `how` is cell, page, corroborated, arithmetic, unchecked or not-archived."""
    document, where, notes = row["source_document"], row["page_or_table"], row["notes"]
    where_cell, where_page = _CELL.match(where), _PAGE.match(where)
    if not (where_cell or where_page):
        return "not-archived", []
    name = f"{row['series_id']} {row['period']}"
    if not (RAW_ROOT / document).is_file():
        return "unchecked", [f"{name}: {document} is not in the archive"]
    value = float(row["value"])
    printed, computed = _PRINTED.match(notes), _COMPUTED.match(notes)
    if not (printed or computed):
        return "unchecked", [f"{name}: the notes must be printed=<number> or computed=<a> - <b>, not {notes!r}"]
    problems: List[str] = []

    if where_cell:
        if not printed:
            return "cell", [f"{name}: a workbook row must give printed=<cell value>"]
        try:
            found = docs.cell(document, where_cell["sheet"], where_cell["ref"])
        except (KeyError, IndexError) as exc:
            return "cell", [f"{name}: {document} {where}: {exc}"]
        if not isinstance(found, (int, float)) or abs(float(found) - _number(printed["text"])) > 1e-6:
            problems.append(f"{name}: {document} {where} holds {found!r}, the row says {printed['text']}")
        elif abs(round(float(found), 1) - value) > 1e-6:
            problems.append(f"{name}: the row's value {value} is not the cell's {found!r} to one decimal")
        label = docs.row_label(document, where_cell["sheet"], where_cell["ref"])
        wanted = OIL_LINE if row["series_id"].endswith("_oil") else GDP_LINE
        if wanted not in label or label.startswith("المجموع") or "عدا" in label:
            problems.append(f"{name}: {where} is the line {label!r}, not the one for {row['series_id']} ({wanted})")
        return "cell", problems

    tokens = [printed["text"]] if printed else [computed["a"], computed["b"]]
    if computed and abs(_number(computed["a"]) - _number(computed["b"]) - value) > TOLERANCE:
        problems.append(f"{name}: {computed['a']} - {computed['b']} is not {value}")
    if printed and abs(_number(printed["text"]) - value) > 1e-6:
        problems.append(f"{name}: printed {printed['text']} is not the value {value}")
    text = docs.page_text(document, int(where_page["page"]))
    if text is None:
        corpus = docs.corpus()
        missing = [t for t in tokens if not _on_page(t, corpus)]
        if missing:
            return "unchecked", problems
        return "corroborated", problems
    problems += [f"{name}: {t} is not on {document} page {where_page['page']}" for t in tokens if not _on_page(t, text)]
    return "page", problems


def check_record(path: Path, root: Path = RAW_ROOT) -> Tuple[Dict[str, int], List[str]]:
    """(rows per way of checking, problems) for a record."""
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    docs = Documents(root)
    for row in rows:
        page = _PAGE.match(row["page_or_table"])
        if page and (root / row["source_document"]).is_file():
            docs.cited.add((row["source_document"], int(page["page"])))
    counts: Dict[str, int] = {}
    problems: List[str] = []
    for row in rows:
        how, found = check_row(row, docs)
        counts[how] = counts.get(how, 0) + 1
        problems += found
    return counts, problems


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Check the COSIT GDP record against the archived documents.")
    parser.add_argument("--record", type=Path, default=None, help="Default: the newest record.")
    args = parser.parse_args(argv)
    path = args.record or newest_record()
    counts, problems = check_record(path)
    print(f"{path.name}: " + ", ".join(f"{n} {how}" for how, n in sorted(counts.items())))
    for line in problems:
        print(f"  PROBLEM {line}")
    if counts.get("unchecked"):
        print(f"  {counts['unchecked']} row(s) cite a scanned page whose numbers no other archived document prints")
    print("COSIT record: " + ("OK" if not problems else f"{len(problems)} problem(s)"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
