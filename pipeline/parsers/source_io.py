"""
pipeline.parsers.source_io
==========================
Reading, checking and writing for every parser.

A parser reads its inputs through these helpers so that a missing, empty, corrupt or unexpected
input stops it with a ParseError naming the file, sheet, row or column and period, instead of a
library traceback, a skipped cell or a guessed value:

- require_file, open_workbook, read_excel, read_csv, read_text, read_json, open_zip: safe readers
- read_value: a cell as a number; a stated "no value" marker gives None (counted); anything else that
  is not a number, or a value of the wrong sign (the series' `sign` in plausibility_rules.yaml), raises. Known bad source cells are listed in
  pipeline/metadata/source_exceptions.yaml
- collapse_duplicates: identical rows for one (date, series_id) are collapsed and reported; rows
  that differ raise
- check_schema: the canonical schema check, raising on any error
- check_daily_coverage: no run of more than 10 calendar days without a value, unless listed in
  pipeline/metadata/daily_gaps.yaml
- write_table: atomic Parquet output (a .part file, then a rename)

Every report line (markers, exceptions, duplicates, precedence) is collected by a Report and printed
once per parser; report lines never change the exit code.
"""

import fnmatch
import functools
import hashlib
import json
import math
import os
import sys
import zipfile
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import pandas as pd
import yaml

repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(repo_root / "src"))

from iraqdata.schema import validate_dataframe  # noqa: E402

METADATA = repo_root / "pipeline" / "metadata"
EXCEPTIONS_PATH = METADATA / "source_exceptions.yaml"
DAILY_GAPS_PATH = METADATA / "daily_gaps.yaml"
PRECEDENCE_PATH = METADATA / "source_precedence.yaml"
RULES_PATH = METADATA / "plausibility_rules.yaml"
MAX_GAP_DAYS = 10  # more consecutive calendar days than this without a value is a gap
BLANK = "blank"
ARABIC_INDIC = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


# =====================================================================
# Errors
# =====================================================================

def display(path) -> str:
    """A path as it appears in messages: relative to the repository when inside it, else its name."""
    return _display(str(path))


@functools.lru_cache(maxsize=None)
def _display(path: str) -> str:
    p = Path(path)
    try:
        return p.resolve().relative_to(repo_root).as_posix()
    except ValueError:
        return p.name or str(p)


class ParseError(ValueError):
    """An input the parser cannot use, located as precisely as the source allows."""

    def __init__(self, file, expected: str, found: str, sheet: Optional[str] = None,
                 location: Optional[str] = None, period: Optional[str] = None):
        self.file, self.expected, self.found = display(file), expected, found
        self.sheet, self.location, self.period = sheet, location, period
        where = [self.file]
        if sheet is not None:
            where.append(f"sheet '{sheet}'")
        if location:
            where.append(location)
        if period:
            where.append(f"period {period}")
        super().__init__(f"{', '.join(where)}: expected {expected}, found {found}")


class MissingInputError(ParseError, FileNotFoundError):
    """An input file that does not exist (also a FileNotFoundError, as callers expect)."""


# =====================================================================
# Readers
# =====================================================================

def file_hash(path, length: Optional[int] = 16) -> str:
    """
    SHA-256 of a file as lowercase hex, cut to `length` characters (None keeps all 64). Every
    parser stamps its rows with this: 16 characters, except bis_lbs and oecd_dac, whose published
    source_hash has always been the full digest.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest() if length is None else h.hexdigest()[:length]


def require_file(path, what: str = "the archived file") -> Path:
    path = Path(path)
    if not path.is_file():
        raise MissingInputError(path, what, "nothing (missing)")
    if path.stat().st_size == 0:
        raise ParseError(path, what, "an empty file (0 bytes)")
    return path


def _not_a(path, kind: str, exc: BaseException):
    return ParseError(path, kind, f"a file that cannot be read as one ({type(exc).__name__}: {exc})")


def open_workbook(path, sheets: Sequence[str] = (), **kwargs):
    """An openpyxl workbook that has every sheet in `sheets`."""
    import openpyxl
    from openpyxl.utils.exceptions import InvalidFileException

    path = require_file(path)
    try:
        wb = openpyxl.load_workbook(path, **kwargs)
    except (zipfile.BadZipFile, InvalidFileException, KeyError, OSError, ValueError) as exc:
        raise _not_a(path, "an Excel workbook", exc) from None
    for name in sheets:
        if name not in wb.sheetnames:
            raise ParseError(path, "the sheet", f"sheets {wb.sheetnames}", sheet=name)
    return wb


def read_excel(path, sheet_name=0, **kwargs) -> pd.DataFrame:
    """pandas.read_excel with the file's problems named; a named sheet must exist."""
    path = require_file(path)
    try:
        return pd.read_excel(path, sheet_name=sheet_name, **kwargs)
    except (zipfile.BadZipFile, KeyError, OSError, ValueError) as exc:
        if isinstance(sheet_name, str) and "not found" in str(exc).lower():
            raise ParseError(path, "the sheet", "no such sheet", sheet=sheet_name) from None
        raise _not_a(path, "an Excel workbook", exc) from None


def read_csv(path, **kwargs) -> pd.DataFrame:
    path = require_file(path)
    try:
        return pd.read_csv(path, **kwargs)
    except (pd.errors.EmptyDataError, pd.errors.ParserError, UnicodeDecodeError) as exc:
        raise _not_a(path, "a CSV file", exc) from None


def read_text(path, encoding: str = "utf-8") -> str:
    path = require_file(path)
    try:
        return path.read_bytes().decode(encoding)
    except UnicodeDecodeError as exc:
        raise _not_a(path, f"a {encoding} text file", exc) from None


def read_json(path):
    text = read_text(path)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise _not_a(path, "a JSON file", exc) from None


def open_zip(path, member: str) -> zipfile.ZipFile:
    """An open ZIP archive that contains `member`."""
    path = require_file(path)
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise _not_a(path, "a ZIP archive", exc) from None
    if member not in z.namelist():
        z.close()
        raise ParseError(path, f"the member {member}", f"members {z.namelist()[:5]}")
    return z


# =====================================================================
# Labels and values
# =====================================================================

def normalize_label(value) -> str:
    """Case-folded, whitespace collapsed, Arabic-Indic digits as Western digits."""
    return " ".join(str(value if value is not None else "").translate(ARABIC_INDIC).casefold().split())


@functools.lru_cache(maxsize=None)
def series_signs(path: Path = RULES_PATH) -> Dict[str, str]:
    """{series_id: sign} from the plausibility rules: positive, non_negative or any."""
    rules = (yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}).get("series", {})
    return {sid: str((rule or {}).get("sign", "any")) for sid, rule in rules.items()}


def _wrong_sign(series_id: Optional[str], value: float) -> Optional[str]:
    sign = series_signs().get(series_id or "", "any")
    if sign == "positive" and value <= 0:
        return f"a positive value ({series_id})"
    if sign == "non_negative" and value < 0:
        return f"a value of at least 0 ({series_id})"
    return None


@functools.lru_cache(maxsize=None)
def _load_list(path: Path, key: str) -> tuple:
    p = Path(path)
    return tuple((yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get(key) or []) if p.exists() else ()


def _same(listed, raw) -> bool:
    """A listed value equals a cell: as numbers when both are numbers (1170 == 1170.0), else as text."""
    try:
        return float(str(listed)) == float(str(raw))
    except ValueError:
        return str(listed).strip() == str(raw).strip()


def _blank(raw) -> bool:
    return raw is None or (isinstance(raw, float) and raw != raw)


class Report:
    """The run report of one parser: counted markers, applied exceptions, duplicates, precedence lines."""

    def __init__(self, parser: str, exceptions_path: Optional[Path] = None):
        self.parser = parser
        self.markers: Dict[str, Counter] = {}
        self.lines: List[str] = []
        self.exceptions_path = Path(exceptions_path) if exceptions_path is not None else EXCEPTIONS_PATH
        self.exceptions = [e for e in _load_list(self.exceptions_path, "exceptions") if e.get("parser") == parser]
        self._used = set()

    def marker(self, file, kind: str) -> None:
        self.markers.setdefault(str(file), Counter())[kind] += 1  # displayed once, in finish()

    def listed(self, file, sheet: Optional[str], period: Optional[str], raw) -> Optional[dict]:
        """The source exception for this cell, if listed (matched on file name, sheet, period and value)."""
        name = Path(file).name
        for i, e in enumerate(self.exceptions):
            if (fnmatch.fnmatch(name, e["file"]) and e.get("sheet") == sheet and str(e.get("period")) == str(period)
                    and _same(e["value"], raw)):
                self._used.add(i)
                self.lines.append(f"[EXCEPTION] {display(file)} {sheet}!{e.get('cell', '?')} {period}: "
                                  f"{raw} ({e['reason']})")
                return e
        return None

    def finish(self) -> None:
        """Print the report; a listed exception that matched no cell stops the run (stale)."""
        stale = [e for i, e in enumerate(self.exceptions) if i not in self._used]
        if stale:
            e = stale[0]
            raise ParseError(self.exceptions_path, f"the listed exception {e['file']} {e.get('sheet')} "
                             f"{e.get('period')} = {e['value']} in the source", "no such cell (remove or update the entry)")
        for file, counts in sorted(self.markers.items(), key=lambda item: display(item[0])):
            parts = ", ".join(f"{k}: {n}" for k, n in sorted(counts.items()))
            print(f"[MARKERS] {display(file)}: {sum(counts.values())} no-value cells ({parts})")
        for line in self.lines:
            print(line)


def read_value(raw, report: Report, file, markers: Iterable[str] = (), sheet: Optional[str] = None,
               location: Optional[str] = None, period: Optional[str] = None,
               series_id: Optional[str] = None) -> Optional[float]:
    """
    A source cell as a float, or None when it holds no value. A blank cell, or one whose text is a
    stated marker, is no value and is counted. A listed source exception is left out and reported.
    Anything else that is not a number raises, as does a value of the wrong sign for `series_id`.
    """
    if _blank(raw):
        report.marker(file, BLANK)
        return None
    text = str(raw).strip()
    if text == "" or text in markers:
        report.marker(file, BLANK if text == "" else f"'{text}'")
        return None
    try:
        value = float(text.replace(",", "").translate(ARABIC_INDIC))
    except ValueError:
        if report.listed(file, sheet, period, raw) is not None:
            return None
        raise ParseError(file, "a number", repr(raw), sheet=sheet, location=location, period=period) from None
    if not math.isfinite(value):  # nan, inf and -inf all parse as floats but are not values
        raise ParseError(file, "a number", repr(raw), sheet=sheet, location=location, period=period)
    wrong = _wrong_sign(series_id, value)
    if wrong:
        raise ParseError(file, wrong, repr(raw), sheet=sheet, location=location, period=period)
    return value


# =====================================================================
# Tables
# =====================================================================

KEY = ["date", "series_id"]


def collapse_duplicates(df: pd.DataFrame, file, report: Report, where: Optional[Sequence[str]] = None) -> pd.DataFrame:
    """
    Rows repeating a (date, series_id) with the same value, unit and flag are collapsed to the
    first and reported; rows that differ raise, naming both values (and both locations from `where`,
    a list aligned with df's rows).
    """
    df = df.reset_index(drop=True)
    repeated = df.duplicated(KEY, keep=False)
    if not repeated.any():
        return df
    for (date, sid), rows in df[repeated].groupby(KEY, sort=True):
        if rows[["value", "unit", "status_flag"]].astype(str).drop_duplicates().shape[0] > 1:
            places = [f"{v} ({where[i]})" if where is not None else str(v) for i, v in zip(rows.index, rows["value"])]
            raise ParseError(file, f"one value for {sid} {date}", " and ".join(places))
        report.lines.append(f"[DUPLICATE] {display(file)}: {sid} {date} x{len(rows)}")
    return df.drop_duplicates(subset=KEY).reset_index(drop=True)


def check_schema(df: pd.DataFrame, file, dataset_name: str) -> None:
    errors = validate_dataframe(df, dataset_name=dataset_name)
    if errors:
        raise ParseError(file, f"a valid {dataset_name} table",
                         f"Tier-1 validation failed on {dataset_name}:\n" + "\n".join(errors))


def check_daily_coverage(df: pd.DataFrame, file, path: Optional[Path] = None) -> None:
    """
    Between a daily series' first and last published dates, a run of more than 10
    consecutive calendar days without a value raises, unless listed in daily_gaps.yaml. A listed gap
    of a series in `df` that is not found raises as stale.
    """
    path = Path(path) if path is not None else DAILY_GAPS_PATH
    listed = [g for g in _load_list(path, "gaps")]
    for sid, rows in df[df["value"].notna()].groupby("series_id", sort=True):
        dates = sorted(pd.to_datetime(rows["date"]))
        found = set()
        for a, b in zip(dates, dates[1:]):
            missing = (b - a).days - 1
            if missing > MAX_GAP_DAYS:
                key = (a.date().isoformat(), b.date().isoformat())
                if not any(g["series"] == sid and (str(g["from"]), str(g["to"])) == key for g in listed):
                    raise ParseError(file, f"no run of more than {MAX_GAP_DAYS} days without a value in {sid}",
                                     f"{missing} days without a value (not listed in daily_gaps.yaml)",
                                     period=f"{key[0]}..{key[1]}")
                found.add(key)
        for g in listed:
            if g["series"] == sid and (str(g["from"]), str(g["to"])) not in found:
                raise ParseError(path, f"the listed gap {sid} {g['from']}..{g['to']} in the data",
                                 "no such gap (remove or update the entry)")


def load_precedence(table: str, path: Optional[Path] = None) -> List[dict]:
    path = Path(path) if path is not None else PRECEDENCE_PATH
    return [r for r in _load_list(path, "rules") if r.get("table") == table]


def write_table(df: pd.DataFrame, path) -> None:
    """Writes `path` atomically: the bytes of df.to_parquet(path, index=False), via <path>.part."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    df.to_parquet(part, index=False)
    os.replace(part, path)
