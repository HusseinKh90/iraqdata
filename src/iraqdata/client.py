"""
Client Query Engine for iraqdata.

Provides the primary high-level data retrieval interface for researchers:
- get_series(): Retrieve one or more series by canonical ID or shortcut alias,
  with date slicing, multi-table joins, and wide vs. clean tidy formats (attaching direct sources).
  Wide requests spanning several frequencies return one table per frequency.
- get_table(): Retrieve an entire thematic table from the Garden layer.
Both accept as_of='YYYY-MM-DD' for values as published on that date; get_series(flags=True)
shows each wide value's status flag next to it.
"""

from __future__ import annotations

import calendar
import datetime as dt
import re
import warnings
from typing import Mapping, Sequence

import pandas as pd

from iraqdata.catalog import (
    DEPRECATED_IDS,
    source_for_observation,
    get_table_for_series,
    resolve_series_id,
)
from iraqdata.errors import FlagWarning
from iraqdata.storage import load_history, load_table
from iraqdata.vintages import as_of as table_as_of, parse_as_of

# Frequency keys of a mixed-frequency wide result, in output order
FREQUENCY_ORDER = ["daily", "monthly", "quarterly", "annual"]

TIDY_COLUMNS = ["date", "series_id", "value", "unit", "status_flag", "source"]
AUDIT_COLUMNS = ["realtime_start", "source_hash"]
FLAG_SUFFIX = "_flag"
# Flags announced by a FlagWarning when a wide result hides them
WARN_FLAGS = ["B", "P"]

_ANNUAL_RE = re.compile(r"^(\d{4})$")
_QUARTERLY_RE = re.compile(r"^(\d{4})-Q([1-4])$")
_MONTHLY_RE = re.compile(r"^(\d{4})-(\d{2})$")
_DAILY_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def _period_bounds(period: str) -> tuple[dt.date, dt.date]:
    """Return the first and last calendar day covered by an ISO period (YYYY, YYYY-Qn, YYYY-MM, YYYY-MM-DD)."""
    p = str(period).strip()
    try:
        if m := _ANNUAL_RE.match(p):
            year = int(m.group(1))
            return dt.date(year, 1, 1), dt.date(year, 12, 31)
        if m := _QUARTERLY_RE.match(p):
            year, quarter = int(m.group(1)), int(m.group(2))
            last_month = 3 * quarter
            return (
                dt.date(year, last_month - 2, 1),
                dt.date(year, last_month, calendar.monthrange(year, last_month)[1]),
            )
        if m := _MONTHLY_RE.match(p):
            year, month = int(m.group(1)), int(m.group(2))
            return dt.date(year, month, 1), dt.date(year, month, calendar.monthrange(year, month)[1])
        if m := _DAILY_RE.match(p):
            day = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return day, day
    except ValueError:
        pass
    raise ValueError(f"Invalid period '{period}'. Use YYYY, YYYY-Qn, YYYY-MM or YYYY-MM-DD.")


def _filter_date_range(
    df: pd.DataFrame,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """
    Keep observations whose period overlaps the inclusive window [start, end].

    Bounds may be given at any granularity, so e.g. start='2020-01' keeps the
    quarterly '2020-Q1' and end='2024-12' keeps the annual '2024'.
    """
    start_first = _period_bounds(start)[0] if start is not None else None
    end_last = _period_bounds(end)[1] if end is not None else None
    if start_first is not None and end_last is not None and start_first > end_last:
        raise ValueError(f"Date window start '{start}' is after end '{end}'.")

    if df.empty or (start is None and end is None):
        return df

    dates = df["date"].astype(str)
    bounds = {d: _period_bounds(d) for d in dates.unique()}
    mask = pd.Series(True, index=df.index)
    if start_first is not None:
        mask &= dates.map(lambda d: bounds[d][1] >= start_first)
    if end_last is not None:
        mask &= dates.map(lambda d: bounds[d][0] <= end_last)
    return df[mask]


def _frequency_of(canonical_id: str) -> str:
    """Frequency of a series, taken from its single-frequency table name suffix."""
    return get_table_for_series(canonical_id).rsplit("_", 1)[1]


def _load(table_name: str, as_of: str | None) -> pd.DataFrame:
    """A table as stored, or as published on `as_of` (from the table and its vintage history)."""
    df = load_table(table_name)
    if as_of is None:
        return df
    return table_as_of(df, load_history(table_name), as_of)


def _collect_observations(
    canonical_ids: list[str],
    start: str | None,
    end: str | None,
    as_of: str | None = None,
) -> pd.DataFrame:
    """Load and window the stored observations for the requested canonical series."""
    table_to_ids: dict[str, set[str]] = {}
    for canonical_id in canonical_ids:
        table_to_ids.setdefault(get_table_for_series(canonical_id), set()).add(canonical_id)

    collected: list[pd.DataFrame] = []
    for tbl, ids in table_to_ids.items():
        df_tbl = _load(tbl, as_of)
        present = set(df_tbl["series_id"].unique())
        # A release older than a rename holds the series under its old id: return those rows as stored
        ids = ids | {old for old, new in DEPRECATED_IDS.items() if new in ids and new not in present}
        sub = df_tbl[df_tbl["series_id"].isin(ids)].copy()
        sub = _filter_date_range(sub, start=start, end=end)
        if not sub.empty:
            collected.append(sub)

    if not collected:
        return pd.DataFrame()
    return pd.concat(collected, ignore_index=True)


def _sources(df: pd.DataFrame) -> list[str]:
    """The `source` column: each row's publisher, per period (from the catalog's origin segments)."""
    return [source_for_observation(s, d) for s, d in zip(df["series_id"], df["date"].astype(str))]


def _stored_ids(canonical_id: str) -> list[str]:
    """The canonical id, then its deprecated ids (rows of releases older than a rename)."""
    return [canonical_id] + [old for old, new in DEPRECATED_IDS.items() if new == canonical_id]


def _wide_frame(
    pairs: list[tuple[str, str]],
    observations: pd.DataFrame,
    flags: bool = False,
) -> pd.DataFrame:
    """
    Build a date-indexed wide matrix with one column per (label, canonical_id) pair; with
    `flags`, each value column is followed by '<label>_flag' holding its status flag.
    """
    labels = [label for label, _ in pairs]
    if flags:
        labels = [c for label in labels for c in (label, label + FLAG_SUFFIX)]
    if observations.empty:
        empty_df = pd.DataFrame(columns=labels)
        empty_df.index.name = "date"
        return empty_df

    pivoted = observations.pivot_table(
        index="date", columns="series_id", values="value", aggfunc="last", dropna=False
    )
    if flags:
        flag_table = observations.pivot_table(
            index="date", columns="series_id", values="status_flag", aggfunc="last"
        ).reindex(pivoted.index)
    wide_data: dict[str, pd.Series] = {}
    for label, canonical_id in pairs:
        column = next((s for s in _stored_ids(canonical_id) if s in pivoted.columns), None)
        if column is not None:
            wide_data[label] = pivoted[column]
        else:
            wide_data[label] = pd.Series(index=pivoted.index, dtype=float)
        if flags:
            if column in flag_table.columns:
                flag_column = flag_table[column].astype(object)
                wide_data[label + FLAG_SUFFIX] = flag_column.where(flag_column.notna(), None)
            else:
                wide_data[label + FLAG_SUFFIX] = pd.Series(None, index=pivoted.index, dtype=object)

    wide_df = pd.DataFrame(wide_data, index=pivoted.index)
    wide_df.index.name = "date"
    return wide_df.sort_index()


def get_series(
    series: str | Sequence[str] | Mapping[str, str],
    start: str | None = None,
    end: str | None = None,
    wide: bool = True,
    audit: bool = False,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    aliases: Mapping[str, str] | None = None,
    flags: bool = False,
    as_of: str | None = None,
) -> pd.DataFrame | dict[str, pd.DataFrame]:
    """
    Retrieve one or more macroeconomic time-series.

    Parameters
    ----------
    series : str, Sequence[str], or Mapping[str, str]
        The series to fetch. Can be:
        - A single canonical ID or alias (e.g. 'm2', 'fiscal.balance', 'parallel_rate').
        - A list of series IDs or aliases (e.g. ['m1', 'm2', 'cpi']).
        - A dictionary mapping custom column labels to series (e.g. {'M1': 'm1', 'M2': 'm2'}).
    start, start_date : str, optional
        Start of an inclusive date window, at any granularity ('2010', '2015-Q1',
        '2015-01', '2020-01-01'). Observations whose period overlaps the window are kept.
        The two spellings are equivalent; pass only one.
    end, end_date : str, optional
        End of the inclusive date window (e.g. '2024', '2024-06', '2024-12-31').
    wide : bool, default True
        If True, returns a wide matrix with 'date' as index and series as columns.
        If the requested series span several frequencies, returns a dict of such
        matrices keyed by frequency ('daily', 'monthly', 'quarterly', 'annual').
        If False, returns a clean long-form DataFrame showing the direct publication source.
    audit : bool, default False
        If True and wide=False, includes internal pipeline provenance columns
        ('realtime_start', 'source_hash') for backend auditing.
    aliases : Mapping[str, str], optional
        Custom column labels as {series_id_or_alias: label}. Cannot be combined with
        a dictionary passed as `series`. Unmapped series keep the name they were requested by.
    flags : bool, default False
        If True and wide=True, each value column is followed by a '<label>_flag' column with the
        observation's status flag (A normal, P provisional, B break, E estimated, M missing,
        U low reliability); empty where there is no observation. Without it, a FlagWarning says
        when the result contains break (B) or provisional (P) values.
    as_of : str, optional
        A date 'YYYY-MM-DD': return the values as they were published on that date (from the
        release's vintage history). Long output then includes 'realtime_start'.

    Returns
    -------
    pd.DataFrame or dict[str, pd.DataFrame]
        Requested time series observations.

    Raises
    ------
    TypeError
        If both spellings of a window bound are given, or `aliases` is combined with a dict `series`.
    ValueError
        If the window or `as_of` is invalid or reversed, two series share a label (including
        '<label>_flag' columns), or an `aliases` key matches no requested series.
    NoVintageHistoryError
        If `as_of` is given and the data source carries no vintage history.
    KeyError
        If a series or alias is unknown (the message suggests close matches).

    Examples
    --------
    >>> import iraqdata as id
    >>> df = id.get_series('m2')
    >>> df_fx = id.get_series(['official_rate', 'parallel_rate'], start='2020-01-01')
    >>> df_m2 = id.get_series('m2', start_date='2020-01', aliases={'m2': 'Broad Money'})
    >>> tables = id.get_series(['m2', 'official_rate'])   # {'daily': ..., 'monthly': ...}
    >>> df_tidy = id.get_series('cpi', wide=False)
    >>> df_flags = id.get_series('cpi', flags=True)          # columns 'cpi', 'cpi_flag'
    >>> df_then = id.get_series('cpi', as_of='2026-10-28')   # as published on that date
    """
    # 1. Reconcile the two spellings of the date window
    if start is not None and start_date is not None:
        raise TypeError("Pass either 'start' or 'start_date', not both.")
    if end is not None and end_date is not None:
        raise TypeError("Pass either 'end' or 'end_date', not both.")
    start = start if start is not None else start_date
    end = end if end is not None else end_date
    if as_of is not None:
        as_of = parse_as_of(as_of)

    # 2. Normalize input into ordered (label, canonical_id) pairs
    pairs: list[tuple[str, str]] = []
    if isinstance(series, str):
        pairs.append((series, resolve_series_id(series)))
    elif isinstance(series, Mapping):
        if aliases is not None:
            raise TypeError(
                "'aliases' cannot be combined with a dict passed as 'series'; use one renaming form."
            )
        for label, sid in series.items():
            pairs.append((str(label), resolve_series_id(str(sid))))
    elif isinstance(series, Sequence):
        for s in series:
            s_str = str(s)
            pairs.append((s_str, resolve_series_id(s_str)))
    else:
        raise TypeError(
            f"Argument 'series' must be a string, list of strings, or dict. Got {type(series).__name__}"
        )

    if not pairs:
        raise ValueError("No series specified.")

    # 3. Apply `aliases` renaming ({series_id_or_alias: label})
    if aliases:
        resolved = {resolve_series_id(str(k)): str(v) for k, v in aliases.items()}
        requested = {canonical_id for _, canonical_id in pairs}
        unmatched = [k for k in aliases if resolve_series_id(str(k)) not in requested]
        if unmatched:
            raise ValueError(f"'aliases' keys {unmatched} do not match any requested series.")
        pairs = [(resolved.get(canonical_id, label), canonical_id) for label, canonical_id in pairs]

    # 4. Reject labels shared by different series, drop exact repeats
    label_owner: dict[str, str] = {}
    unique_pairs: list[tuple[str, str]] = []
    for label, canonical_id in pairs:
        if label in label_owner:
            if label_owner[label] != canonical_id:
                raise ValueError(
                    f"Column label '{label}' is assigned to both '{label_owner[label]}' and '{canonical_id}'."
                )
            continue
        label_owner[label] = canonical_id
        unique_pairs.append((label, canonical_id))
    pairs = unique_pairs
    if wide and flags:
        clashes = [label + FLAG_SUFFIX for label in label_owner if label + FLAG_SUFFIX in label_owner]
        if clashes:
            raise ValueError(f"Flag column(s) {clashes} would have the same name as a requested series label.")

    # 5. Load and filter observations (raises KeyError with suggestions for unknown series)
    observations = _collect_observations([c for _, c in pairs], start, end, as_of)
    if as_of is not None:
        _warn_unpublished(pairs, observations, as_of)

    # 6. Tidy layout: one long table, frequencies may mix
    if not wide:
        out_cols = TIDY_COLUMNS + (AUDIT_COLUMNS if audit else ["realtime_start"] if as_of else [])
        if observations.empty:
            return pd.DataFrame(columns=out_cols)
        observations["source"] = _sources(observations)
        return observations[out_cols].sort_values(by=["date", "series_id"]).reset_index(drop=True)

    if not flags:
        _warn_hidden_flags(pairs, observations)

    # 7. Wide layout: one matrix per frequency, never resampled
    by_frequency: dict[str, list[tuple[str, str]]] = {}
    for label, canonical_id in pairs:
        by_frequency.setdefault(_frequency_of(canonical_id), []).append((label, canonical_id))

    def _frame_for(freq_pairs: list[tuple[str, str]]) -> pd.DataFrame:
        ids = {c for _, c in freq_pairs}
        ids |= {old for old, new in DEPRECATED_IDS.items() if new in ids}  # rows of releases older than a rename
        subset = observations[observations["series_id"].isin(ids)] if not observations.empty else observations
        return _wide_frame(freq_pairs, subset, flags=flags)

    if len(by_frequency) == 1:
        return _frame_for(pairs)
    return {freq: _frame_for(by_frequency[freq]) for freq in FREQUENCY_ORDER if freq in by_frequency}


def _warn_unpublished(pairs: list[tuple[str, str]], observations: pd.DataFrame, as_of: str) -> None:
    present = set(observations["series_id"]) if not observations.empty else set()
    for label, canonical_id in pairs:
        if not present.intersection(_stored_ids(canonical_id)):
            warnings.warn(f"'{label}' had not yet been published as of {as_of}.", UserWarning, stacklevel=3)


def _warn_hidden_flags(pairs: list[tuple[str, str]], observations: pd.DataFrame) -> None:
    """One FlagWarning naming the break (B) and provisional (P) counts a wide result hides."""
    if observations.empty:
        return
    parts = []
    for label, canonical_id in pairs:
        flags = observations.loc[observations["series_id"].isin(_stored_ids(canonical_id)), "status_flag"]
        counts = [f"{int((flags == f).sum())} {f}" for f in WARN_FLAGS if (flags == f).any()]
        if counts:
            parts.append(f"{label} {', '.join(counts)}")
    if parts:
        warnings.warn(
            FlagWarning(
                "Result contains break (B) or provisional (P) values: "
                f"{'; '.join(parts)}. Pass flags=True to see them."
            ),
            stacklevel=3,
        )


def get_table(
    table_name: str,
    start: str | None = None,
    end: str | None = None,
    audit: bool = False,
    *,
    as_of: str | None = None,
) -> pd.DataFrame:
    """
    Retrieve an entire thematic table from the Garden layer.

    Parameters
    ----------
    table_name : str
        Canonical table name (e.g. 'prices_monthly', 'fiscal_annual', 'gdp_quarterly').
    start : str, optional
        Start date/period filter (e.g. '2010', '2015-01'); inclusive period-overlap semantics.
    end : str, optional
        End date/period filter (e.g. '2024').
    audit : bool, default False
        If True, includes internal pipeline provenance columns ('realtime_start', 'source_hash').
    as_of : str, optional
        A date 'YYYY-MM-DD': the table as it was published on that date (from the release's
        vintage history); the output then includes 'realtime_start'.

    Returns
    -------
    pd.DataFrame
        Complete dataset for the requested table showing direct publication source.
    """
    if as_of is not None:
        as_of = parse_as_of(as_of)
    df = _load(table_name, as_of)
    df = _filter_date_range(df, start=start, end=end)
    df["source"] = _sources(df)

    out_cols = TIDY_COLUMNS + (AUDIT_COLUMNS if audit else ["realtime_start"] if as_of else [])
    return df[out_cols].sort_values(by=["date", "series_id"]).reset_index(drop=True)
