"""
Provenance of every published number.

Every distinct source_hash in the production and seed tables must resolve to the archived
file (or declared input group) it was actually read from, or be listed in the known-findings
register. The register is checked both ways: unregistered gaps and stale entries both fail.
"""

from pathlib import Path

import pandas as pd
import pytest

from conftest import REPO_ROOT

PARSERS_DIR = REPO_ROOT / "pipeline" / "parsers"
PLACEHOLDER_HASH = "a1b2c3d4e5f60718"


def test_cosit_gdp_missing_raw_dir_raises(tmp_path):
    import parse_cosit_gdp

    missing = tmp_path / "absent"
    seed, out = tmp_path / "s.parquet", tmp_path / "o.parquet"
    with pytest.raises(FileNotFoundError) as excinfo:
        parse_cosit_gdp.parse_cosit_gdp(raw_dir=missing, seed_parquet_path=seed, output_parquet_path=out)
    assert str(missing) in str(excinfo.value)
    assert not seed.exists() and not out.exists()


def test_no_placeholder_hash_in_parsers():
    offenders = [p.name for p in sorted(PARSERS_DIR.glob("*.py"))
                 if PLACEHOLDER_HASH in p.read_text(encoding="utf-8")]
    assert offenders == [], f"placeholder source_hash still present in: {offenders}"


# =====================================================================
# Hash resolution, attribution and the known-findings register
# =====================================================================

import fnmatch
import re

import raw_audit
import run_parsers

REGISTERED_TOTAL = 0  # no published row is registered as unexplained


@pytest.fixture(scope="module")
def manifest():
    return raw_audit.load_manifest()


@pytest.fixture(scope="module")
def findings():
    return raw_audit.load_yaml(raw_audit.FINDINGS_PATH)


@pytest.fixture(scope="module")
def provenance(garden_tables, seed_tables, manifest, findings):
    return raw_audit.resolve_hashes(garden_tables, manifest, findings, seed_tables)


def test_every_published_hash_resolves_or_is_registered(provenance):
    """Every affected row must be registered; nothing else may be unresolved or misattributed."""
    shown = "\n".join(map(str, provenance.unregistered[:20]))
    assert provenance.unregistered == [], (
        f"{len(provenance.unregistered)} rows are unresolved, unsourced or misattributed "
        f"and not in known_findings.yaml:\n{shown}"
    )
    assert provenance.group_errors == []


def test_published_hashes_are_long_enough(provenance):
    """Short hashes must be prefixes of at least 16 hex characters."""
    short = [h for h in provenance.hash_cases if len(h) < raw_audit.MIN_PREFIX]
    assert short == []


@pytest.mark.parametrize("name", ["bis_lbs_all"])
def test_input_groups_recompute(manifest, name):
    """A derived series' combined hash is recomputable from its declared member files."""
    group = next(g for g in manifest["input_groups"] if g["name"] == name)
    assert raw_audit.recompute_group(group) == group["id"]


def test_register_matches_data_exactly(provenance, findings):
    """Every register entry counts exactly the rows it describes."""
    assert provenance.stale == []
    for entry in findings["provenance"]:
        assert provenance.registered[entry["id"]] == entry["count"], entry["id"]
    assert sum(provenance.registered.values()) == REGISTERED_TOTAL


def test_traced_and_registered_cover_production(provenance):
    """Every production observation is either traced to its source or registered."""
    assert provenance.resolved_rows + provenance.registered_rows == provenance.total_rows


def test_register_detects_new_gap(garden_tables, manifest, findings):
    oil = garden_tables["oil_monthly"].copy()
    idx = oil.index[oil["series_id"] == "crude_production_secondary"][0]
    oil.loc[idx, "source_hash"] = "f" * 16
    res = raw_audit.resolve_hashes({"oil_monthly": oil}, manifest, findings)
    flagged = [(s, d, st) for _, s, d, h, st in res.unregistered if h == "f" * 16]
    assert flagged == [("crude_production_secondary", oil.loc[idx, "date"], "unresolved")]


def test_register_detects_stale_entry(garden_tables, manifest, findings):
    """An entry that no longer matches any row is reported stale (synthetic entry: the register is empty)."""
    fake = {"id": "FX1", "table": "oil_monthly", "series": ["crude_production_direct"], "from": "2024-04",
            "to": "2026-06", "count": 27, "published_hash": "0" * 16}
    res = raw_audit.resolve_hashes({"oil_monthly": garden_tables["oil_monthly"]}, manifest,
                                   {**findings, "provenance": [fake]})
    assert any(msg.startswith("FX1:") for msg in res.stale)


def test_attribution_catches_wrong_file_within_parser(garden_tables, manifest, findings):
    """H1: a valid input of the same parser, but the wrong file for this row, is misattributed."""
    jodi_2010 = next(e["sha256"] for e in manifest["files"] if e["path"].endswith("jodi_iraq_2010.csv"))
    oil = garden_tables["oil_monthly"].copy()
    idx = oil.index[oil["series_id"] == "crude_production_secondary"][0]
    oil.loc[idx, "source_hash"] = jodi_2010[:16]
    res = raw_audit.resolve_hashes({"oil_monthly": oil}, manifest, findings)
    flagged = [st for _, s, d, h, st in res.unregistered if h == jodi_2010[:16]]
    assert flagged == ["misattributed"]


@pytest.mark.parametrize("snapshot, table", sorted(run_parsers.SNAPSHOT_TABLE.items()))
def test_seed_snapshots_mirror_production(seed_tables, garden_tables, snapshot, table):
    """H2: the seed snapshots repeat their production tables, so the register covers them."""
    pd.testing.assert_frame_equal(
        seed_tables[snapshot].reset_index(drop=True), garden_tables[table].reset_index(drop=True)
    )


def test_series_inputs_stay_within_declared_inputs(garden_tables):
    """
    Every file a series claims to come from is one of its parser's declared input globs, or of
    a parser it runs after (a series derived from an intermediate garden file carries the hash
    of the raw file behind it, e.g. Basrah from oil_daily's FRED CSV).
    """
    problems = []
    for table, df in garden_tables.items():
        for spec in run_parsers.writers_of(table):
            globs = list(spec.inputs) + [g for dep in spec.after for g in run_parsers.BY_NAME[dep].inputs]
            for series_id, dates in df.groupby("series_id")["date"]:
                source = spec.series_inputs.get(series_id, spec.series_inputs.get("*"))
                if source is None:
                    continue
                for date in dates.unique():
                    value = source(date)
                    if not isinstance(value, list):
                        continue
                    for path in value:
                        if not any(fnmatch.fnmatch(path, glob) for glob in globs):
                            problems.append((spec.name, series_id, date, path))
    assert problems == []


def test_manifest_fields_complete(manifest):
    """Every manifest entry has all fields; computed fields match the file.
    Every entry has `source_ref`, and an entry with an unknown download date has `held_by`."""
    fields = ["path", "size", "sha256", "origin", "acquired", "source_ref", "consumers", "status"]
    held = ["path", "size", "sha256", "origin", "acquired", "held_by", "held_by_basis", "source_ref",
            "consumers", "status"]
    for entry in manifest["files"]:
        assert list(entry) == (held if entry["acquired"] == "unknown" else fields), entry["path"]
        path = REPO_ROOT / entry["path"]
        assert entry["size"] == path.stat().st_size, entry["path"]
        assert entry["sha256"] == raw_audit.sha256_file(path), entry["path"]
        assert re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
        for key in ("origin", "acquired", "source_ref"):
            assert str(entry[key]).strip(), (entry["path"], key)
        assert entry["acquired"] == "unknown" or re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(entry["acquired"]))
        assert entry["status"] in {"parsed", "archived-not-parsed", "superseded"}
