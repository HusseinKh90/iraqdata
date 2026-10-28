"""
iraqdata.schema
===============
Canonical Observation Schema and Validation Rules for Iraqi Macroeconomic Data.

Standard 7-Column Observation Schema:
1. date: ISO 8601 string (YYYY-MM-DD, YYYY-MM, YYYY-Qn, YYYY)
2. series_id: lowercase string, dot-separated or underscore-separated
3. value: float64 numeric value (NaN only when flagged missing 'M' or low reliability 'U')
4. unit: string standard unit (e.g. BILLION_IQD, USD_PER_BBL)
5. status_flag: uppercase SDMX observation status code (A, P, B, E, M, U)
6. realtime_start: ISO date string (YYYY-MM-DD)
7. source_hash: SHA-256 hash string (or first 8-16 chars)
"""

import calendar
import re
from dataclasses import dataclass
from typing import List, Optional, Set
import pandas as pd
import numpy as np

CANONICAL_COLUMNS: List[str] = [
    "date",
    "series_id",
    "value",
    "unit",
    "status_flag",
    "realtime_start",
    "source_hash",
]

# Standard SDMX Observation Status Flags (uppercase only)
# A: Normal
# P: Provisional / Preliminary
# B: Break in series / methodology change
# E: Estimated
# M: Missing value (data cannot exist or uncollected)
# U: Low reliability
VALID_STATUS_FLAGS: Set[str] = {"A", "P", "B", "E", "M", "U"}

# Flags that permit an empty (NaN) value
MISSING_VALUE_FLAGS: Set[str] = {"M", "U"}

# Text columns that must never be null or empty
REQUIRED_TEXT_COLUMNS: List[str] = ["date", "series_id", "unit", "realtime_start", "source_hash"]

# Maximum number of offending rows quoted in a single error message
MAX_EXAMPLES = 10

# Regex patterns for ISO dates
DATE_PATTERNS = {
    "daily": re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    "monthly": re.compile(r"^\d{4}-\d{2}$"),
    "quarterly": re.compile(r"^\d{4}-Q[1-4]$"),
    "annual": re.compile(r"^\d{4}$"),
}

# Series ID pattern: lowercase alphanumeric, underscore, and optional dots
# Supports both hierarchical IDs ('cbi.money.m2') and flat canonical IDs ('oil_price_brent')
SERIES_ID_PATTERN = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)*$")


def date_form(value: str) -> Optional[str]:
    """Return the frequency form ('daily', 'monthly', 'quarterly', 'annual') of an ISO period, or None."""
    for form, pattern in DATE_PATTERNS.items():
        if pattern.match(value):
            return form
    return None


def is_calendar_valid(value: str, form: str) -> bool:
    """Check that a pattern-valid ISO period is a real calendar period (month 1-12, real day)."""
    if form in ("annual", "quarterly"):
        return True
    year, month = int(value[0:4]), int(value[5:7])
    if not 1 <= month <= 12:
        return False
    if form == "monthly":
        return True
    day = int(value[8:10])
    return 1 <= day <= calendar.monthrange(year, month)[1]


def _format_error(dataset_name: str, rule: str, offending: pd.DataFrame) -> str:
    """Uniform error message: dataset, rule, offending-row count and up to MAX_EXAMPLES rows."""
    examples = offending.head(MAX_EXAMPLES).to_dict(orient="records")
    return f"[{dataset_name}] {rule}: {len(offending)} offending row(s). Examples: {examples}"


@dataclass(frozen=True)
class Observation:
    date: str
    series_id: str
    value: float
    unit: str
    status_flag: str = "A"
    realtime_start: Optional[str] = None
    source_hash: Optional[str] = None

    def validate(self) -> List[str]:
        """Validates a single observation against the canonical schema rules."""
        errors = []

        # 1. Date format check
        form = date_form(str(self.date))
        if form is None or not is_calendar_valid(str(self.date), form):
            errors.append(f"Invalid date format '{self.date}'. Must match YYYY-MM-DD, YYYY-MM, YYYY-Qn, or YYYY.")

        # 2. Series ID check
        if not SERIES_ID_PATTERN.match(str(self.series_id)):
            errors.append(f"Invalid series_id '{self.series_id}'. Must be lowercase alphanumeric, underscore, or dot-separated.")

        # 3. Numeric value check
        if not isinstance(self.value, (int, float, np.floating)):
            errors.append(f"Invalid value type '{type(self.value)}'. Must be float64 or NaN.")

        # 4. Status flag check (exact match: no empty or lowercase codes)
        if self.status_flag not in VALID_STATUS_FLAGS:
            errors.append(f"Invalid status_flag '{self.status_flag}'. Must be one of {sorted(VALID_STATUS_FLAGS)}.")

        # 5. Missing values must be explicitly flagged
        if isinstance(self.value, (float, np.floating)) and np.isnan(self.value) \
                and self.status_flag not in MISSING_VALUE_FLAGS:
            errors.append("Unflagged missing value: NaN requires status_flag 'M' or 'U'.")

        return errors


def validate_dataframe(df: pd.DataFrame, dataset_name: str = "dataset") -> List[str]:
    """
    Executes Tier-1 schema validation across an entire DataFrame.
    Returns a list of error strings. If list is empty, validation passed.
    """
    errors: List[str] = []

    # 1. Check exact columns and ordering
    if list(df.columns) != CANONICAL_COLUMNS:
        missing = [c for c in CANONICAL_COLUMNS if c not in df.columns]
        extra = [c for c in df.columns if c not in CANONICAL_COLUMNS]
        msg = f"[{dataset_name}] Column layout mismatch."
        if missing:
            msg += f" Missing: {missing}."
        if extra:
            msg += f" Unexpected: {extra}."
        if not missing and not extra:
            msg += f" Column order is incorrect. Expected: {CANONICAL_COLUMNS}, got: {list(df.columns)}"
        errors.append(msg)
        return errors  # Cannot safely proceed with row-level checks if schema is misaligned

    if df.empty:
        errors.append(f"[{dataset_name}] DataFrame is empty (0 observations).")
        return errors

    # 2. Value type check (must be float64)
    if df["value"].dtype != np.float64:
        errors.append(f"[{dataset_name}] 'value' column must be float64 dtype, found: {df['value'].dtype}")

    # 3. Required text fields are never null or empty
    for col in REQUIRED_TEXT_COLUMNS:
        empty = df[col].isna() | (df[col].astype(str).str.strip() == "")
        if empty.any():
            errors.append(_format_error(dataset_name, f"Empty required field '{col}'", df[empty]))

    # 4. Status flag check (exact uppercase SDMX codes)
    invalid_flags = ~df["status_flag"].isin(VALID_STATUS_FLAGS)
    if invalid_flags.any():
        errors.append(_format_error(
            dataset_name,
            f"Invalid status_flag (allowed: {', '.join(sorted(VALID_STATUS_FLAGS))})",
            df[invalid_flags],
        ))

    # 5. Missing values must carry a missing-value flag
    unflagged = df["value"].isna() & ~df["status_flag"].isin(MISSING_VALUE_FLAGS)
    if unflagged.any():
        errors.append(_format_error(
            dataset_name, "Unflagged missing value (NaN requires status_flag M or U)", df[unflagged]
        ))

    # 6. Date format and calendar validity
    dates = df["date"].astype(str)
    forms = dates.map(date_form)
    calendar_ok = pd.Series(
        # Series.map turns None into NaN, so test for a real form string
        [isinstance(f, str) and is_calendar_valid(d, f) for d, f in zip(dates, forms)], index=df.index
    )
    if (~calendar_ok).any():
        errors.append(_format_error(
            dataset_name,
            "Invalid date (must be a real YYYY-MM-DD, YYYY-MM, YYYY-Qn or YYYY period)",
            df[~calendar_ok],
        ))

    # 7. Single-frequency rule
    form_counts = forms.dropna().value_counts()
    if len(form_counts) > 1:
        errors.append(f"[{dataset_name}] Mixed date frequencies: {form_counts.to_dict()}")

    # 8. realtime_start must be a real YYYY-MM-DD date
    rts = df["realtime_start"]
    present = rts.notna() & (rts.astype(str).str.strip() != "")
    rts_ok = rts.astype(str).map(lambda s: date_form(s) == "daily" and is_calendar_valid(s, "daily"))
    bad_rts = present & ~rts_ok
    if bad_rts.any():
        errors.append(_format_error(dataset_name, "Invalid realtime_start (must be YYYY-MM-DD)", df[bad_rts]))

    # 9. Series ID naming pattern
    invalid_sids = ~df["series_id"].astype(str).str.match(SERIES_ID_PATTERN)
    if invalid_sids.any():
        errors.append(_format_error(dataset_name, "Invalid series_id", df[invalid_sids]))

    # 10. Uniqueness: full vintage key, then (date, series_id) within the latest vintage
    dup_full = df.duplicated(subset=["date", "series_id", "realtime_start"])
    if dup_full.any():
        errors.append(_format_error(
            dataset_name, "Duplicate key (date, series_id, realtime_start)", df[dup_full]
        ))

    latest = df[df["realtime_start"] == df["realtime_start"].max()]
    dup_latest = latest.duplicated(subset=["date", "series_id"]) & ~dup_full.loc[latest.index]
    if dup_latest.any():
        errors.append(_format_error(
            dataset_name, "Duplicate key (date, series_id) within latest vintage", latest[dup_latest]
        ))

    return errors
