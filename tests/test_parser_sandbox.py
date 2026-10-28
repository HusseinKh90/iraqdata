"""
Deterministic parser runs in a sandbox.

All 11 parsers run twice, offline, into fresh temporary folders (the session fixture
``sandbox_runs``). The two runs must be byte-identical, equal the committed production and
seed tables, pass Tier-1 validation, and write nothing to pipeline/.
"""

import hashlib
import subprocess
import sys

import pandas as pd
import pytest

import run_parsers
from conftest import GARDEN_DIR, PRODUCTION_TABLES, REPO_ROOT, SEEDS_DIR, diff_trees
from iraqdata.schema import validate_dataframe

SNAPSHOTS = sorted(run_parsers.SNAPSHOT_TABLE)
OUTPUTS = [f"{t}.parquet" for t in PRODUCTION_TABLES] + [f"seeds/{s}.parquet" for s in SNAPSHOTS]
REGISTRY_ORDER = [
    "bis_lbs", "cbi_bop", "cbi_cpi", "cbi_exchange_rates", "fiscal_seed", "cbi_fiscal_bulletin",
    "cbi_money_banking", "cosit_gdp", "oecd_dac", "oil_daily", "oil_monthly",
]


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _committed(output: str):
    return SEEDS_DIR / output.split("/", 1)[1] if output.startswith("seeds/") else GARDEN_DIR / output


def diff_by_series(table: str, a: pd.DataFrame, b: pd.DataFrame) -> list:
    """(table, series_id, date, what) for every row added, removed or changed between a and b."""
    key = ["series_id", "date"]
    # A named indicator: itertuples renames fields that start with "_"
    merged = a.merge(b, on=key, how="outer", suffixes=("_a", "_b"), indicator="merge_status")
    out = []
    for row in merged.itertuples(index=False):
        if row.merge_status != "both":
            out.append((table, row.series_id, row.date, row.merge_status))
            continue
        changed = [c for c in a.columns if c not in key
                   and not (pd.isna(getattr(row, f"{c}_a")) and pd.isna(getattr(row, f"{c}_b")))
                   and getattr(row, f"{c}_a") != getattr(row, f"{c}_b")]
        if changed:
            out.append((table, row.series_id, row.date, ",".join(changed)))
    return out


def test_diff_by_series_reports_added_removed_changed():
    """Differences are listed, not raised as KeyError('_merge')."""
    def frame(rows):
        return pd.DataFrame([{"date": d, "series_id": "money.m2", "value": v, "unit": "BILLION_IQD",
                              "status_flag": "A", "realtime_start": "2026-10-22", "source_hash": "0" * 16}
                             for d, v in rows])
    a = frame([("2020-01", 1.0), ("2020-02", 2.0), ("2020-03", 3.0)])
    b = frame([("2020-02", 2.0), ("2020-03", 3.5), ("2020-04", 4.0)])
    assert sorted(diff_by_series("t", a, b)) == sorted([
        ("t", "money.m2", "2020-01", "left_only"),
        ("t", "money.m2", "2020-04", "right_only"),
        ("t", "money.m2", "2020-03", "value"),
    ])
    assert diff_by_series("t", a, a) == []


# =====================================================================
# Completion, isolation and network
# =====================================================================

def test_all_parsers_complete(sandbox_runs):
    for run in (sandbox_runs.run1, sandbox_runs.run2):
        missing = [o for o in OUTPUTS if not (run / o).exists()]
        assert missing == []


def test_no_network_calls(sandbox_runs):
    assert sandbox_runs.network_calls == []


def test_nothing_written_outside_sandbox(sandbox_runs):
    """No file under pipeline/raw, pipeline/seeds or pipeline/data was created, changed or deleted."""
    assert diff_trees(sandbox_runs.before, sandbox_runs.after) == []


# =====================================================================
# Determinism and reproduction
# =====================================================================

@pytest.mark.parametrize("output", OUTPUTS)
def test_runs_are_byte_identical(sandbox_runs, output):
    assert _sha256(sandbox_runs.run1 / output) == _sha256(sandbox_runs.run2 / output)


@pytest.mark.parametrize("output", OUTPUTS)
def test_sandbox_equals_committed(sandbox_runs, output):
    """
    A fresh build equals the committed table, or merging it into the committed table changes
    nothing. Every row carries the hash of the raw file it was read from, so no row depends on the
    pyarrow version.
    """
    table = run_parsers.SNAPSHOT_TABLE.get(output.split("/")[-1][:-8], output[:-8])
    sandbox = pd.read_parquet(sandbox_runs.run1 / output)
    committed = pd.read_parquet(_committed(output))
    if sandbox.equals(committed):
        return

    # Once production has been updated by a merge, the committed table holds later vintages and
    # keeps unchanged rows' original hash and vintage, so it is no longer a byte copy of a fresh
    # build. It is up to date when merging the build into it changes nothing: no row added,
    # revised, withdrawn, missing or re-flagged.
    import vintages
    writers = [spec.name for spec in run_parsers.writers_of(table)]
    merge = vintages.merge_vintages(committed, sandbox, run_parsers.input_vintage(writers), table)
    if not (merge.added or merge.revised or merge.missing or merge.withdrawn or merge.flag_updated):
        return

    diffs = diff_by_series(table, sandbox, committed)
    shown = "\n".join(map(str, diffs[:20]))
    pytest.fail(f"{output}: {len(diffs)} row(s) differ from the committed table:\n{shown}")


@pytest.mark.parametrize("output", OUTPUTS)
def test_sandbox_output_passes_tier1(sandbox_runs, output):
    """Zero Tier-1 errors."""
    df = pd.read_parquet(sandbox_runs.run1 / output)
    assert validate_dataframe(df, dataset_name=output) == []


# =====================================================================
# Run order
# =====================================================================

def test_registry_order_respects_after():
    names = [spec.name for spec in run_parsers.REGISTRY]
    assert names == REGISTRY_ORDER
    for spec in run_parsers.REGISTRY:
        for dep in spec.after:
            assert names.index(dep) < names.index(spec.name), (spec.name, dep)


def test_fiscal_bulletin_depends_on_fiscal_seed(sandbox_runs, tmp_path):
    """Without the seed's output, the bulletin parser produces a different fiscal_annual table."""
    spec = run_parsers.BY_NAME["cbi_fiscal_bulletin"]
    (tmp_path / "seeds").mkdir()
    spec.run(run_parsers.DEFAULT_RAW_ROOT, run_parsers.DEFAULT_SEEDS_ROOT, tmp_path, tmp_path / "seeds")
    alone = pd.read_parquet(tmp_path / "fiscal_annual.parquet")
    in_order = pd.read_parquet(sandbox_runs.run1 / "fiscal_annual.parquet")
    assert len(alone) < len(in_order)


def test_only_without_dependency_fails_clearly(tmp_path):
    # cbi_fiscal_bulletin runs after fiscal_seed (oil_monthly does not read oil_daily)
    with pytest.raises(RuntimeError, match="fiscal_annual.parquet"):
        run_parsers.run_all(out_dir=tmp_path, only=["cbi_fiscal_bulletin"])


def test_cli_runs_into_output_dir(tmp_path):
    proc = subprocess.run(
        [sys.executable, "pipeline/run_parsers.py", "--output-dir", str(tmp_path), "--only", "bis_lbs"],
        cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "bis_lbs_quarterly.parquet").exists()
    assert (tmp_path / "seeds" / "bis_lbs_quarterly_seed.parquet").exists()


def test_cli_rejects_unknown_parser(tmp_path):
    proc = subprocess.run(
        [sys.executable, "pipeline/run_parsers.py", "--output-dir", str(tmp_path), "--only", "nope"],
        cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 2
