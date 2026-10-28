"""
tests.test_release_integrity
============================
The published data release is complete, checksum-exact,
CSV/Parquet-identical, identical to the production datasets, and described by
a valid Frictionless Data Package v1 descriptor.

The release is verified as published and is never modified.
"""

import hashlib
import json
import shutil
from pathlib import Path

import jsonschema
import numpy as np
import pandas as pd
import pytest

from conftest import (
    CANONICAL_COLUMNS,
    GARDEN_DIR,
    PRODUCTION_TABLES,
    RELEASE_DIR,
    REPO_ROOT,
    read_release_csv,
)

DATA_FILES = sorted(
    [f"{t}.parquet" for t in PRODUCTION_TABLES] + [f"{t}.csv" for t in PRODUCTION_TABLES]
)
SCHEMA_PATH = REPO_ROOT / "tests" / "fixtures" / "frictionless" / "tabular-data-package.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_table(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path) if path.suffix == ".parquet" else read_release_csv(path)


def verify_checksums(directory: Path) -> list[str]:
    """Return problems found comparing checksums.sha256 with the data files in `directory`."""
    listed: dict[str, str] = {}
    for line in (directory / "checksums.sha256").read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if not parts:
            continue
        digest, name = parts[0].lower(), parts[-1].lstrip("*")
        listed[name] = digest

    present = {p.name for p in directory.iterdir() if p.suffix in (".parquet", ".csv")}
    problems = [f"missing file listed in checksums: {n}" for n in sorted(set(listed) - present)]
    problems += [f"data file not listed in checksums: {n}" for n in sorted(present - set(listed))]
    for name in sorted(set(listed) & present):
        if _sha256(directory / name) != listed[name]:
            problems.append(f"checksum mismatch: {name}")
    return problems


@pytest.fixture(scope="module")
def descriptor() -> dict:
    return json.loads((RELEASE_DIR / "datapackage.json").read_text(encoding="utf-8"))


# =====================================================================
# Completeness
# =====================================================================

def test_release_contains_exactly_the_expected_files():
    assert sorted(p.name for p in RELEASE_DIR.glob("*.parquet")) == [f"{t}.parquet" for t in PRODUCTION_TABLES]
    assert sorted(p.name for p in RELEASE_DIR.glob("*.csv")) == [f"{t}.csv" for t in PRODUCTION_TABLES]
    assert (RELEASE_DIR / "checksums.sha256").is_file()
    assert (RELEASE_DIR / "datapackage.json").is_file()


# =====================================================================
# Checksums
# =====================================================================

def test_checksums_cover_and_match_all_data_files():
    assert verify_checksums(RELEASE_DIR) == []
    lines = [ln for ln in (RELEASE_DIR / "checksums.sha256").read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 20
    assert sorted(ln.split()[-1].lstrip("*") for ln in lines) == DATA_FILES


def test_tampered_file_is_detected(tmp_path):
    copy = tmp_path / "release"
    shutil.copytree(RELEASE_DIR, copy)
    target = copy / "fiscal_annual.csv"
    data = bytearray(target.read_bytes())
    data[-2] ^= 0x01
    target.write_bytes(bytes(data))
    assert verify_checksums(copy) == ["checksum mismatch: fiscal_annual.csv"]


# =====================================================================
# CSV <-> Parquet and release <-> production
# =====================================================================

@pytest.mark.parametrize("table", PRODUCTION_TABLES)
def test_csv_and_parquet_are_identical(table):
    pq_df = pd.read_parquet(RELEASE_DIR / f"{table}.parquet")
    csv_df = read_release_csv(RELEASE_DIR / f"{table}.csv")
    assert len(csv_df) == len(pq_df)
    assert list(csv_df.columns) == list(pq_df.columns)
    for col in pq_df.columns:
        if col == "value":
            np.testing.assert_array_equal(csv_df[col].to_numpy(), pq_df[col].to_numpy())  # NaN == NaN here
        else:
            assert csv_df[col].astype(str).tolist() == pq_df[col].astype(str).tolist(), col


RELEASE_VINTAGE = "2026-10-28"  # the one vintage of the first release: every value was first published then


@pytest.mark.parametrize("table", PRODUCTION_TABLES)
def test_release_parquet_matches_production(table):
    """The release equals the production table exactly: one vintage, no history, nothing superseded."""
    released = pd.read_parquet(RELEASE_DIR / f"{table}.parquet").reset_index(drop=True)
    production = pd.read_parquet(GARDEN_DIR / f"{table}.parquet")
    assert released.equals(production.reset_index(drop=True))
    assert set(released["realtime_start"]) == {RELEASE_VINTAGE}


def test_the_first_release_has_no_vintage_history():
    assert not (RELEASE_DIR / "history").exists()
    assert not (GARDEN_DIR.parent / "history").exists()


# =====================================================================
# Frictionless descriptor
# =====================================================================

def test_descriptor_is_valid_v1_tabular_data_package(descriptor):
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft4Validator(schema).validate(descriptor)
    assert descriptor["profile"] == "tabular-data-package"


def test_descriptor_records_building_code_version(descriptor):
    import iraqdata
    assert descriptor["version"] == iraqdata.__version__


def test_descriptor_lists_one_resource_per_data_file(descriptor):
    assert len(descriptor["resources"]) == 20
    assert sorted(r["path"] for r in descriptor["resources"]) == DATA_FILES


@pytest.mark.parametrize("filename", DATA_FILES)
def test_descriptor_resource_matches_file(descriptor, filename):
    resource = next(r for r in descriptor["resources"] if r["path"] == filename)
    path = RELEASE_DIR / filename
    df = _load_table(path)

    assert path.is_file()
    assert resource["rows"] == len(df)
    assert resource["hash"] == f"sha256:{_sha256(path)}"
    assert [f["name"] for f in resource["schema"]["fields"]] == CANONICAL_COLUMNS

    key = resource["schema"]["primaryKey"]
    if df["realtime_start"].nunique() == 1:
        assert key == ["date", "series_id"]
    else:
        assert key == ["date", "series_id", "realtime_start"]
    assert not df.duplicated(key).any()
