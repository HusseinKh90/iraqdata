"""
pipeline.parsers.transcription
==============================
Reads transcription records: archived CSV files of values that were typed in by hand from a
publication.

A record is a raw file like any other: it is archived under pipeline/raw/transcribed/, registered
in the raw manifest and never edited (a correction is a new file with a later date in its name).
Every row read from it carries the record's own hash as source_hash.
"""

import csv
import math
from pathlib import Path
from typing import Dict, Iterable

import pandas as pd

import source_io

COLUMNS = ["series_id", "period", "value", "unit", "source_document", "page_or_table",
           "transcriber", "transcribed_on", "notes"]


def file_hash(path: Path) -> str:
    """The 16-hex source_hash of a file, as every parser stamps it."""
    return source_io.file_hash(path)


def catalog_record_name(series_id: str) -> str:
    """The file name of the record the series catalog names for `series_id` (its last origin segment that has one)."""
    import flags  # the catalog reader; imported here so reading a record needs nothing else

    names = [Path(seg["record"]).name for seg in flags.load_catalog()[series_id].get("origin") or [] if seg.get("record")]
    if not names:
        raise ValueError(f"{series_id}: the series catalog names no transcription record (origin[].record)")
    return names[-1]


def newest(folder: Path, pattern: str, series_id: str = "") -> Path:
    """
    The newest dated record matching `pattern` (names end in _YYYY-MM-DD.csv, so name order is date order).
    With a `series_id`, it must be the record the series catalog names: if the named record is missing the
    next newest would be read silently, and a newer record that the catalog does not name yet is a step
    left undone (change `record:` in src/iraqdata/series_catalog.yaml, then run pipeline/docs_origin.py).
    """
    found = sorted(Path(folder).glob(pattern))
    if not found:
        raise FileNotFoundError(f"No transcription record {pattern} in {folder}")
    if series_id and found[-1].name != catalog_record_name(series_id):
        raise FileNotFoundError(
            f"The series catalog names {catalog_record_name(series_id)} as the record of {series_id}, but the newest "
            f"{pattern} in {folder} is {found[-1].name}")
    return found[-1]


def read_transcription(path: Path, units: Dict[str, str], series: Iterable[str] = ()) -> pd.DataFrame:
    """
    Rows of a record as (series_id, period, value, unit, source_hash). `units` maps every series
    the record may contain to its catalog unit; `series`, if given, keeps only those series.
    Raises ValueError naming the file and line for a wrong header, a duplicated key, a value that
    is not a number or a unit that differs from the catalog.
    """
    path = Path(path)
    try:
        return _read(path, units, series)
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValueError(f"{path}: not a readable UTF-8 transcription record ({exc})") from None


def _read(path: Path, units: Dict[str, str], series: Iterable[str]) -> pd.DataFrame:
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != COLUMNS:
            raise ValueError(f"{path}:1: header must be {','.join(COLUMNS)}, found {reader.fieldnames}")
        rows, seen = [], set()
        for line, row in enumerate(reader, start=2):
            sid, per = row["series_id"], row["period"]
            if sid not in units:
                raise ValueError(f"{path}:{line}: unexpected series {sid!r}")
            if (sid, per) in seen:
                raise ValueError(f"{path}:{line}: duplicate key ({sid}, {per})")
            seen.add((sid, per))
            try:
                value = float(row["value"])
            except ValueError:
                raise ValueError(f"{path}:{line}: value {row['value']!r} is not a number") from None
            if math.isnan(value):
                raise ValueError(f"{path}:{line}: value is NaN")
            if row["unit"] != units[sid]:
                raise ValueError(f"{path}:{line}: unit {row['unit']!r} differs from the catalog's {units[sid]!r}")
            rows.append((sid, per, value, row["unit"]))
    keep = set(series)
    df = pd.DataFrame(rows, columns=["series_id", "period", "value", "unit"])
    if keep:
        df = df[df["series_id"].isin(keep)].reset_index(drop=True)
    df["source_hash"] = file_hash(path)
    return df
