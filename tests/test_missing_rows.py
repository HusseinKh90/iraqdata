"""
tests.test_missing_rows
=======================
Published rows missing from a new release are not kept
silently. A production merge refuses unless each is withdrawn or kept with a recorded reason;
a scratch merge (the update check) reports them.

Production is never touched: refusal is exercised on a sandbox with allow_missing=False, which
is what a production merge does by default.
"""

import hashlib
import shutil
from pathlib import Path

import pandas as pd
import pytest
import yaml

import run_parsers
from conftest import GARDEN_DIR, RAW_DIR, SEEDS_DIR

pytestmark = pytest.mark.usefixtures("no_network")

PARSER = "oecd_dac"
TABLE = "oecd_dac_annual"


def tree(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(root).rglob("*")) if p.is_file()}


@pytest.fixture
def sandbox(tmp_path):
    raw, seeds, garden = tmp_path / "raw", tmp_path / "seeds", tmp_path / "garden"
    shutil.copytree(RAW_DIR / "oecd", raw / "oecd")
    shutil.copytree(SEEDS_DIR, seeds)
    shutil.copytree(GARDEN_DIR, garden)
    latest = pd.read_parquet(garden / f"{TABLE}.parquet")["date"].max()
    return tmp_path, raw, seeds, garden, str(latest)


def drop(date):
    def hook(table, df):
        return df[df["date"] != date] if table == TABLE else df
    return hook


def missing_keys(garden, date):
    df = pd.read_parquet(garden / f"{TABLE}.parquet")
    return sorted((s, d) for s, d in zip(df["series_id"], df["date"]) if d == date)


def merge(raw, seeds, garden, date, **kw):
    return run_parsers.run_all(only=[PARSER], raw_root=raw, seeds_root=seeds, apply_to=garden,
                               vintage="2026-11-15", _fresh_hook=drop(date), **kw)


def test_refused_before_anything_is_written(sandbox):
    root, raw, seeds, garden, latest = sandbox
    before = tree(root)
    with pytest.raises(run_parsers.MissingRowsError) as exc:
        merge(raw, seeds, garden, latest, allow_missing=False)
    message = str(exc.value)
    assert f"missing from the new release of {TABLE}" in message and latest in message
    assert "--withdraw-missing" in message and "--keep-missing" in message
    assert tree(root) == before


def test_scratch_merge_reports_them(sandbox):
    root, raw, seeds, garden, latest = sandbox
    report = merge(raw, seeds, garden, latest)  # a sandbox target: allowed by default
    assert sorted(tuple(k) for k in report["tables"][TABLE]["missing"]) == missing_keys(garden, latest)


def test_withdrawn_rows_are_not_refused(sandbox):
    root, raw, seeds, garden, latest = sandbox
    keys = missing_keys(garden, latest)
    report = merge(raw, seeds, garden, latest, allow_missing=False, withdraw={s: latest for s, _ in keys})
    assert sorted(tuple(k) for k in report["tables"][TABLE]["withdrawn"]) == keys


def test_kept_rows_need_a_recorded_reason(sandbox, monkeypatch):
    root, raw, seeds, garden, latest = sandbox
    keys = missing_keys(garden, latest)
    with pytest.raises(run_parsers.MissingRowsError, match="kept_missing.yaml"):
        merge(raw, seeds, garden, latest, allow_missing=False, keep=keys)

    listed = root / "kept_missing.yaml"
    listed.write_text(yaml.safe_dump({"kept": [
        {"table": TABLE, "series_id": s, "date": d, "reason": "source revised its series", "reviewer": "t",
         "date_decided": "2026-11-15"} for s, d in keys]}), encoding="utf-8")
    monkeypatch.setattr(run_parsers, "KEPT_MISSING_PATH", listed)
    report = merge(raw, seeds, garden, latest, allow_missing=False, keep=keys)
    assert sorted(tuple(k[1:]) for k in report["kept_missing"]) == keys


def test_allow_missing_is_refused_for_production():
    with pytest.raises(run_parsers.MissingRowsError, match="scratch"):
        run_parsers.run_all(apply_to=run_parsers.DEFAULT_OUT_DIR, allow_missing=True)


def test_cli_exit_2_names_the_rows(sandbox, monkeypatch, capsys):
    root, raw, seeds, garden, latest = sandbox
    real = run_parsers.merge_into

    def refusing(*a, **kw):
        kw.update(_fresh_hook=drop(latest), allow_missing=False)
        return real(*a, **kw)

    monkeypatch.setattr(run_parsers, "merge_into", refusing)
    code = run_parsers.main(["--apply-to", str(garden), "--only", PARSER, "--raw-root", str(raw),
                             "--seeds-root", str(seeds), "--vintage", "2026-11-15"])
    assert code == 2
    assert latest in capsys.readouterr().err


def test_kept_missing_file_is_valid():
    assert isinstance(run_parsers.load_kept_missing(), list)
