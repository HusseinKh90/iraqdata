"""
pipeline.download_checks
========================
Content checks a fetched file must pass before it is saved to the raw archive. Pure: bytes in, ValueError out; each message
names the URL and the reason. Workbooks keep their own check (downloads.check_workbook).

- check_fred_csv:  the FRED graph CSV of one series (header `observation_date,<series>`).
- check_bis_csv:   a BIS SDMX CSV with the key columns, TIME_PERIOD and OBS_VALUE.
- check_wb_json:   a World Bank indicator payload whose rows all carry the expected indicator id.
- check_eia_zip:   a zip archive containing the expected member.
- check_not_shrunk: the new file has at least as many data rows as the archived one and does not
  end earlier, so a truncated or partial release is never archived silently.
"""

import csv
import io
import json
import zipfile
from pathlib import Path
from typing import List, Optional, Sequence, Tuple


def _csv_rows(content: bytes, url: str) -> Tuple[List[str], List[List[str]]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{url}: not UTF-8 text ({exc})") from None
    if text.lstrip().lower().startswith(("<!doctype", "<html")):
        raise ValueError(f"{url}: an HTML page, not a CSV file")
    rows = [r for r in csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]
    if not rows:
        raise ValueError(f"{url}: empty file")
    return rows[0], rows[1:]


def check_fred_csv(content: bytes, url: str, series: str = "DCOILBRENTEU") -> None:
    header, data = _csv_rows(content, url)
    if header != ["observation_date", series]:
        raise ValueError(f"{url}: header is {header}, not ['observation_date', '{series}']")
    if not data:
        raise ValueError(f"{url}: no data rows")


def check_bis_csv(content: bytes, url: str, key_columns: Sequence[str]) -> None:
    header, data = _csv_rows(content, url)
    missing = [c for c in list(key_columns) + ["TIME_PERIOD", "OBS_VALUE"] if c not in header]
    if missing:
        raise ValueError(f"{url}: missing column(s) {missing}")
    if not data:
        raise ValueError(f"{url}: no data rows")


def check_wb_json(content: bytes, url: str, indicator_id: str) -> None:
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ValueError(f"{url}: not a JSON document") from None
    if not (isinstance(payload, list) and len(payload) == 2 and isinstance(payload[1], list) and payload[1]):
        raise ValueError(f"{url}: not a World Bank indicator payload (expected [metadata, non-empty rows])")
    found = sorted({str((row.get("indicator") or {}).get("id")) for row in payload[1] if isinstance(row, dict)})
    if found != [indicator_id]:
        raise ValueError(f"{url}: indicator {', '.join(found)}, not {indicator_id}")


EIA_MAX_MEMBERS = 10               # the archive holds one file
EIA_MAX_UNCOMPRESSED = 600_000_000  # INTL.txt is about 130 MB
EIA_MAX_RATIO = 100                 # uncompressed / compressed; today about 5


def check_eia_zip(content: bytes, url: str, member: str = "INTL.txt") -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            names = zf.namelist()
            infos = zf.infolist()
            total = sum(i.file_size for i in infos)
            packed = sum(i.compress_size for i in infos)
            # declared sizes are checked before anything is decompressed (a zip bomb)
            if len(infos) > EIA_MAX_MEMBERS:
                raise ValueError(f"{url}: zip has {len(infos)} members, more than {EIA_MAX_MEMBERS}")
            if total > EIA_MAX_UNCOMPRESSED or (packed and total / packed > EIA_MAX_RATIO):
                raise ValueError(f"{url}: zip expands to {total} bytes from {packed} (limits: {EIA_MAX_UNCOMPRESSED} "
                                 f"bytes, ratio {EIA_MAX_RATIO})")
            bad = zf.testzip()
    except zipfile.BadZipFile:
        raise ValueError(f"{url}: not a zip archive") from None
    if member not in names:
        raise ValueError(f"{url}: zip has no {member} (found: {', '.join(names[:5])})")
    if bad is not None:
        raise ValueError(f"{url}: zip member {bad} is corrupt")


def _extent(content: bytes, kind: str, url: str, period_column: Optional[str]) -> Tuple[int, str]:
    """(data rows, last period) of a CSV (by `period_column`) or a World Bank payload (non-null years)."""
    if kind == "csv":
        header, data = _csv_rows(content, url)
        if period_column not in header:
            raise ValueError(f"{url}: no {period_column!r} column")
        i = header.index(period_column)
        periods = [r[i] for r in data if len(r) > i and r[i].strip()]
        return len(data), max(periods, default="")
    if kind == "wb_json":
        rows = [r for r in json.loads(content.decode("utf-8"))[1] if r.get("value") is not None]
        return len(rows), max((str(r.get("date")) for r in rows), default="")
    raise ValueError(f"unknown kind {kind!r}")


def check_not_shrunk(new: bytes, archived: Path, kind: str, url: str, period_column: Optional[str] = None) -> None:
    """Refuse a file with fewer data rows, or an earlier last period, than the archived one."""
    archived = Path(archived)
    if not archived.exists():
        return
    old_rows, old_last = _extent(archived.read_bytes(), kind, str(archived), period_column)
    new_rows, new_last = _extent(new, kind, url, period_column)
    if new_rows < old_rows:
        raise ValueError(f"{url}: shrank from {old_rows} to {new_rows} data rows (archived {archived.name})")
    if new_last < old_last:
        raise ValueError(f"{url}: last period {new_last} is earlier than the archived {old_last} ({archived.name})")
