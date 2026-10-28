"""
Real-time (as-of) views of a table for the iraqdata client.

`as_of` rebuilds a table as it was published on a past date from the table and its vintage
history. It applies the same rule as the pipeline's `pipeline/vintages.as_of`; the client cannot
import the pipeline, so a test keeps the two equal.
"""

from __future__ import annotations

import datetime as dt
import re

import pandas as pd

from iraqdata.schema import CANONICAL_COLUMNS

KEY = ["date", "series_id"]
# source_hash of the history row that records a withdrawal (value NaN, flag M, the withdrawal vintage)
WITHDRAWN = "withdrawn"

_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_as_of(text: str) -> str:
    """Validate an as-of date: a real calendar day written YYYY-MM-DD."""
    value = str(text).strip()
    try:
        if _ISO_DAY.match(value):
            dt.date.fromisoformat(value)
            return value
    except ValueError:
        pass
    raise ValueError(f"Invalid as_of '{text}'. Use YYYY-MM-DD.")


def _canonical(df: pd.DataFrame) -> pd.DataFrame:
    out = df[CANONICAL_COLUMNS].copy()
    out["value"] = out["value"].astype("float64")
    return out.reset_index(drop=True)


def _sorted_by(df: pd.DataFrame, cols: list[str]) -> bool:
    keys = list(zip(*(df[c].astype(str) for c in cols)))
    return keys == sorted(keys)


def _order_like(previous: pd.DataFrame, table: pd.DataFrame) -> pd.DataFrame:
    """Sort the rebuilt table the way the published table is sorted."""
    for cols in (["date", "series_id"], ["series_id", "date"]):
        if _sorted_by(previous, cols):
            return table.sort_values(cols, kind="mergesort").reset_index(drop=True)
    return table.reset_index(drop=True)


def as_of(table: pd.DataFrame, history: pd.DataFrame | None, vintage: str) -> pd.DataFrame:
    """
    The table as it was published at `vintage`: rows of the table and its history with
    realtime_start <= vintage, the latest vintage per (date, series_id), and keys whose latest
    row is a withdrawal marker left out. Sorted the way `table` is sorted; dtypes as in `table`.
    """
    rows = [_canonical(table)]
    if history is not None and len(history):
        rows.append(_canonical(history))
    pool = pd.concat(rows, ignore_index=True)
    pool = pool[pool["realtime_start"].astype(str) <= vintage]
    pool = pool.sort_values(["realtime_start"], kind="mergesort").drop_duplicates(KEY, keep="last")
    pool = pool[pool["source_hash"] != WITHDRAWN]
    out = _order_like(_canonical(table), pool.reset_index(drop=True))
    return out.astype(table[CANONICAL_COLUMNS].dtypes.to_dict())
