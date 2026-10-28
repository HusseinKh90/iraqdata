"""
tests.test_data_schema
======================
Every stored observation in the 10 production datasets meets the
canonical 7-column schema, and Tier-1 validation enforces it.
"""

import calendar
import json
import re

import numpy as np
import pandas as pd
import pytest

from conftest import (
    CANONICAL_COLUMNS,
    FREQ_OF,
    PRODUCTION_TABLES,
    RELEASE_DIR,
    VALID_FLAGS,
)
from iraqdata.schema import validate_dataframe

DATE_REGEX = {
    "daily": re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    "monthly": re.compile(r"^\d{4}-\d{2}$"),
    "quarterly": re.compile(r"^\d{4}-Q[1-4]$"),
    "annual": re.compile(r"^\d{4}$"),
}
REQUIRED_TEXT = ["date", "series_id", "unit", "realtime_start", "source_hash"]


def _is_real_period(s: str, freq: str) -> bool:
    year = int(s[:4])
    if freq == "annual":
        return True
    if freq == "quarterly":
        return s[6] in "1234"
    month = int(s[5:7])
    if not 1 <= month <= 12:
        return False
    if freq == "monthly":
        return True
    day = int(s[8:10])
    return 1 <= day <= calendar.monthrange(year, month)[1]


# =====================================================================
# Positive checks on the real production datasets
# =====================================================================

@pytest.mark.parametrize("name", PRODUCTION_TABLES)
def test_column_layout_and_types(garden_tables, name):
    df = garden_tables[name]
    assert list(df.columns) == CANONICAL_COLUMNS
    assert df["value"].dtype == "float64"
    for col in CANONICAL_COLUMNS:
        if col != "value":
            assert pd.api.types.is_string_dtype(df[col]) or df[col].dtype == object, col


@pytest.mark.parametrize("name", PRODUCTION_TABLES)
def test_required_fields_never_empty(garden_tables, name):
    df = garden_tables[name]
    for col in REQUIRED_TEXT:
        assert not df[col].isna().any(), f"{name}.{col} has nulls"
        assert not (df[col].astype(str).str.strip() == "").any(), f"{name}.{col} has empty strings"


@pytest.mark.parametrize("name", PRODUCTION_TABLES)
def test_missing_values_are_flagged(garden_tables, name):
    df = garden_tables[name]
    missing = df["value"].isna()
    assert df.loc[missing, "status_flag"].isin({"M", "U"}).all()
    # A flagged-missing observation must never carry a placeholder zero
    flagged = df["status_flag"].isin({"M", "U"})
    assert not (df.loc[flagged, "value"] == 0).any()


@pytest.mark.parametrize("name", PRODUCTION_TABLES)
def test_status_flags_are_uppercase_sdmx(garden_tables, name):
    assert set(garden_tables[name]["status_flag"]) <= VALID_FLAGS


@pytest.mark.parametrize("name", PRODUCTION_TABLES)
def test_dates_match_table_frequency_and_calendar(garden_tables, name):
    df = garden_tables[name]
    freq = FREQ_OF[name]
    dates = df["date"].astype(str)
    assert dates.str.match(DATE_REGEX[freq]).all(), f"{name}: dates not all {freq}"
    bad = [d for d in dates.unique() if not _is_real_period(d, freq)]
    assert bad == [], f"{name}: non-calendar periods {bad[:10]}"


@pytest.mark.parametrize("name", PRODUCTION_TABLES)
def test_realtime_start_is_real_iso_date(garden_tables, name):
    rts = garden_tables[name]["realtime_start"].astype(str)
    assert rts.str.match(DATE_REGEX["daily"]).all()
    assert pd.to_datetime(rts, format="%Y-%m-%d", errors="coerce").notna().all()


@pytest.mark.parametrize("name", PRODUCTION_TABLES)
def test_single_frequency_per_table(garden_tables, name):
    forms = set()
    for d in garden_tables[name]["date"].astype(str).unique():
        forms.update(f for f, rx in DATE_REGEX.items() if rx.match(d))
    assert forms == {FREQ_OF[name]}


@pytest.mark.parametrize("name", PRODUCTION_TABLES)
def test_uniqueness_keys(garden_tables, name):
    df = garden_tables[name]
    assert not df.duplicated(["date", "series_id", "realtime_start"]).any()
    latest = df[df["realtime_start"] == df["realtime_start"].max()]
    assert not latest.duplicated(["date", "series_id"]).any()


@pytest.mark.parametrize("name", PRODUCTION_TABLES)
def test_tier1_validator_passes(garden_tables, name):
    assert validate_dataframe(garden_tables[name], name) == []


def test_production_observation_count_matches_release(garden_tables):
    """Production has the release's row count: the release was exported from it and nothing was published since."""
    total = sum(len(df) for df in garden_tables.values())
    descriptor = json.loads((RELEASE_DIR / "datapackage.json").read_text(encoding="utf-8"))
    declared = sum(r["rows"] for r in descriptor["resources"] if r["path"].endswith(".parquet"))
    assert total == 23139
    assert total == declared


# =====================================================================
# Negative checks on corrupted temporary copies
# =====================================================================

DATASET = "money_banking_monthly"


@pytest.fixture
def monthly(garden_tables):
    return garden_tables[DATASET].copy()


@pytest.fixture
def daily(garden_tables):
    return garden_tables["exchange_rates_daily"].copy()


def _errors_matching(errors, *needles):
    return [e for e in errors if all(n in e for n in needles)]


def test_rejects_extra_column(monthly):
    monthly["foo"] = 1
    errors = validate_dataframe(monthly, DATASET)
    assert _errors_matching(errors, DATASET, "Column layout mismatch", "foo")


def test_rejects_reordered_columns(monthly):
    cols = list(monthly.columns)
    cols[0], cols[1] = cols[1], cols[0]
    errors = validate_dataframe(monthly[cols], DATASET)
    assert _errors_matching(errors, DATASET, "Column layout mismatch")


@pytest.mark.parametrize("bad", ["2024-13", "2024-Q5", "2023-02-30"])
def test_rejects_invalid_dates(monthly, bad):
    monthly.loc[0, "date"] = bad
    errors = validate_dataframe(monthly, DATASET)
    assert _errors_matching(errors, DATASET, "date", "1 offending row")


def test_rejects_non_leap_day_and_accepts_leap_day(daily):
    ok = daily[daily["date"] != "2024-02-29"].reset_index(drop=True)   # the one row moved there must not repeat a key
    ok.loc[0, "date"] = "2024-02-29"
    assert validate_dataframe(ok, "exchange_rates_daily") == []

    bad = daily.copy()
    bad.loc[0, "date"] = "2023-02-29"
    errors = validate_dataframe(bad, "exchange_rates_daily")
    assert _errors_matching(errors, "exchange_rates_daily", "date", "1 offending row")


def test_rejects_mixed_frequency(monthly):
    monthly.loc[0, "date"] = "2024-07-01"
    errors = validate_dataframe(monthly, DATASET)
    assert _errors_matching(errors, DATASET, "Mixed date frequencies")


def test_rejects_duplicate_rows(monthly):
    dup = pd.concat([monthly, monthly.iloc[[5]]], ignore_index=True)
    errors = validate_dataframe(dup, DATASET)
    assert _errors_matching(errors, DATASET, "Duplicate", "1 offending row")


def test_unflagged_nan_rejected_flagged_nan_accepted(monthly):
    unflagged = monthly.copy()
    unflagged.loc[3, "value"] = np.nan
    unflagged.loc[3, "status_flag"] = "A"
    errors = validate_dataframe(unflagged, DATASET)
    assert _errors_matching(errors, DATASET, "Unflagged missing value", "1 offending row")

    flagged = monthly.copy()
    flagged.loc[3, "value"] = np.nan
    flagged.loc[3, "status_flag"] = "M"
    assert validate_dataframe(flagged, DATASET) == []


@pytest.mark.parametrize("bad_flag", ["", "a", "X"])
def test_rejects_invalid_status_flags(monthly, bad_flag):
    monthly.loc[0, "status_flag"] = bad_flag
    errors = validate_dataframe(monthly, DATASET)
    assert _errors_matching(errors, DATASET, "status_flag", "1 offending row")


def test_rejects_empty_source_hash(monthly):
    monthly.loc[0, "source_hash"] = ""
    errors = validate_dataframe(monthly, DATASET)
    assert _errors_matching(errors, DATASET, "source_hash", "1 offending row")


def test_rejects_integer_value_dtype(monthly):
    monthly["value"] = monthly["value"].round().astype("int64")
    errors = validate_dataframe(monthly, DATASET)
    assert _errors_matching(errors, DATASET, "value", "float64")


def test_examples_capped_at_ten(monthly):
    monthly.loc[:14, "status_flag"] = "X"
    errors = _errors_matching(validate_dataframe(monthly, DATASET), DATASET, "status_flag")
    assert errors, "expected a status_flag error"
    msg = errors[0]
    assert "15 offending row(s)" in msg
    examples = msg.split("Examples:", 1)[1]
    assert examples.count("'date'") == 10
