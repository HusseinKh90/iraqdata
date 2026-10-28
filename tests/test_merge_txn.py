"""
tests.test_merge_txn
====================
A merge is all-or-nothing,
writes the vintage history before the tables, and an interrupted merge can be recovered.

- Unit level: a merge_txn.Transaction over several tables, histories and snapshots, with a crash
  or an error injected at every step.
- Merge level: run_parsers.run_all on a sandbox copy (the oecd_dac parser: a table, its history
  and its seed snapshot), compared byte for byte with the plain sequential procedure.
"""

import hashlib
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

import merge_txn
import run_parsers
import vintages
from conftest import GARDEN_DIR, RAW_DIR, SEEDS_DIR

pytestmark = pytest.mark.usefixtures("no_network")

COLUMNS = ["date", "series_id", "value", "unit", "status_flag", "source_hash", "realtime_start"]


class Crash(BaseException):
    """A simulated process crash: no cleanup code runs."""


def tree(root):
    """SHA-256 of every file under root, by relative path."""
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(root).rglob("*")) if p.is_file()}


def frame(values, vintage="2026-10-22"):
    return pd.DataFrame({
        "date": [f"2024-{m:02d}" for m in range(1, len(values) + 1)],
        "series_id": "s.x", "value": [float(v) for v in values], "unit": "IQD",
        "status_flag": "A", "source_hash": "h", "realtime_start": vintage,
    })[COLUMNS]


# =====================================================================
# Unit level: merge_txn.Transaction
# =====================================================================

@pytest.fixture
def store(tmp_path):
    """Published files in three folders, and the new versions a merge writes."""
    root = tmp_path / "data"
    garden, history, seeds = root / "garden", root / "history", root / "seeds"
    for d in (garden, history, seeds):
        d.mkdir(parents=True)
    frame([1, 2, 3]).to_parquet(garden / "a.parquet", index=False)
    frame([5, 6]).to_parquet(garden / "b.parquet", index=False)
    frame([9]).to_parquet(history / "a.parquet", index=False)
    frame([1, 2, 3]).to_parquet(seeds / "a_seed.parquet", index=False)
    new = [
        ("history", history / "a.parquet", frame([9, 3])),
        ("history", history / "b.parquet", frame([6])),  # a new history file
        ("table", garden / "a.parquet", frame([1, 2, 4], "2026-11-15")),
        ("table", garden / "b.parquet", frame([5, 7], "2026-11-15")),
        ("snapshot", seeds / "a_seed.parquet", frame([1, 2, 4], "2026-11-15")),
    ]
    return root, garden, new


def expected_after(tmp_path, root, new):
    """The files an uninterrupted merge leaves: each new frame written with to_parquet."""
    ref = tmp_path / "ref"
    shutil.copytree(root, ref)
    for _, target, df in new:
        df.to_parquet(ref / target.relative_to(root), index=False)
    return tree(ref)


def transaction(garden, new, hook=None):
    txn = merge_txn.Transaction(garden, "2026-11-15", _hook=hook)
    for kind, target, df in new:
        txn.add(kind, target, df)
    return txn


def all_steps(tmp_path, store):
    """Every hook step of a full commit, recorded on a copy."""
    root, garden, new = store
    copy = tmp_path / "steps"
    shutil.copytree(root, copy)
    moved = [(k, copy / t.relative_to(root), df) for k, t, df in new]
    steps = []
    transaction(copy / "garden", moved, hook=steps.append).commit()
    return steps


def test_commit_matches_direct_writes(tmp_path, store):
    root, garden, new = store
    after = expected_after(tmp_path, root, new)
    transaction(garden, new).commit()
    assert tree(root) == after  # byte-identical, and no .new, .old or journal left


def test_commit_order_is_histories_tables_snapshots(tmp_path, store):
    steps = all_steps(tmp_path, store)
    kinds = [s.split()[2].split(":")[0] for s in steps if s.startswith("commit new ")]
    assert kinds == ["history", "history", "table", "table", "snapshot"]


def test_crash_at_every_step_recovers_to_before_or_after(tmp_path, store):
    root, garden, new = store
    before = tree(root)
    after = expected_after(tmp_path, root, new)
    steps = all_steps(tmp_path, store)
    assert len(steps) > 10
    for i, step in enumerate(steps):
        work = tmp_path / f"crash{i}"
        shutil.copytree(root, work)
        moved = [(k, work / t.relative_to(root), df) for k, t, df in new]

        def hook(s, step=step):
            if s == step:
                raise Crash(step)

        with pytest.raises(Crash):
            transaction(work / "garden", moved, hook=hook).commit()
        outcome = merge_txn.recover(work / "garden")
        assert outcome in {"rolled forward", "rolled back", "nothing to recover"}, step
        assert tree(work) in (before, after), step
        assert not (work / "garden" / merge_txn.JOURNAL).exists()


def test_error_at_every_step_rolls_back(tmp_path, store):
    root, garden, new = store
    before = tree(root)
    steps = all_steps(tmp_path, store)
    # an ordinary error during staging or committing leaves the published files exactly as before
    for i, step in enumerate(s for s in steps if not s.startswith("finish")):
        work = tmp_path / f"error{i}"
        shutil.copytree(root, work)
        moved = [(k, work / t.relative_to(root), df) for k, t, df in new]

        def hook(s, step=step):
            if s == step:
                raise OSError(f"disk full at {step}")

        with pytest.raises(OSError):
            transaction(work / "garden", moved, hook=hook).commit()
        assert tree(work) == before, step


def test_refuses_while_journal_exists(store):
    root, garden, new = store
    (garden / merge_txn.JOURNAL).write_text("{}", encoding="utf-8")
    with pytest.raises(merge_txn.MergeInterrupted, match="--recover"):
        transaction(garden, new).commit()


def test_recover_without_journal(store):
    root, garden, new = store
    before = tree(root)
    assert merge_txn.recover(garden) == "nothing to recover"
    assert tree(root) == before


def test_damaged_journal_is_never_guessed(store):
    root, garden, new = store
    (garden / merge_txn.JOURNAL).write_text("{not json", encoding="utf-8")
    before = tree(root)
    with pytest.raises(merge_txn.RecoveryError, match="restore from backup"):
        merge_txn.recover(garden)
    assert tree(root) == before


def test_unknown_file_content_is_never_guessed(tmp_path, store):
    root, garden, new = store
    step = next(s for s in all_steps(tmp_path, store) if s.startswith("commit new table:"))

    def hook(s):
        if s == step:
            raise Crash(s)

    with pytest.raises(Crash):
        transaction(garden, new, hook=hook).commit()
    frame([0]).to_parquet(garden / "a.parquet", index=False)  # neither the old nor the new version
    before = tree(root)
    with pytest.raises(merge_txn.RecoveryError, match="a.parquet"):
        merge_txn.recover(garden)
    assert tree(root) == before


# =====================================================================
# Merge level: run_parsers on a sandbox
# =====================================================================

PARSER = "oecd_dac"
TABLE = "oecd_dac_annual"
SNAPSHOT = "oecd_dac_annual_seed"
VINTAGE = "2026-11-15"


def sandbox(tmp_path):
    raw, seeds, garden = tmp_path / "raw", tmp_path / "seeds", tmp_path / "garden"
    shutil.copytree(RAW_DIR / "oecd", raw / "oecd")
    shutil.copytree(SEEDS_DIR, seeds)
    shutil.copytree(GARDEN_DIR, garden)
    return raw, seeds, garden


def next_release(table, df):
    """A revised value and a new period in the fresh build."""
    if table != TABLE:
        return df
    df = df.copy()
    df.loc[df.index[0], "value"] = df.loc[df.index[0], "value"] + 1.0
    extra = df[df["date"] == df["date"].max()].copy()
    extra["date"] = str(int(extra["date"].iloc[0]) + 1)
    return pd.concat([df, extra], ignore_index=True)


def legacy_merge(tmp_path, raw, seeds, garden):
    """The plain sequential write sequence (table, then history, then snapshot)."""
    build = tmp_path / "build"
    run_parsers.run_all(out_dir=build, only=run_parsers.expand_only([PARSER]), raw_root=raw, seeds_root=seeds)
    fresh = next_release(TABLE, pd.read_parquet(build / f"{TABLE}.parquet"))
    res = vintages.merge_vintages(pd.read_parquet(garden / f"{TABLE}.parquet"), fresh, VINTAGE, TABLE)
    assert res.changed
    res.table.to_parquet(garden / f"{TABLE}.parquet", index=False)
    vintages.append_history(garden.parent / "history" / f"{TABLE}.parquet", res.superseded)
    res.table.to_parquet(seeds / f"{SNAPSHOT}.parquet", index=False)


def test_merge_is_byte_identical_to_the_legacy_procedure(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    raw_a, seeds_a, garden_a = sandbox(a)
    raw_b, seeds_b, garden_b = sandbox(b)
    report = run_parsers.run_all(only=[PARSER], raw_root=raw_a, seeds_root=seeds_a, apply_to=garden_a,
                                 vintage=VINTAGE, _fresh_hook=next_release)
    assert report["tables"][TABLE]["changed"]
    assert report["transaction"]["files"] == 3
    legacy_merge(b, raw_b, seeds_b, garden_b)
    for sub in ("garden", "history", "seeds"):
        assert tree(a / sub) == tree(b / sub), sub


def test_duplicate_history_key_stops_before_anything_is_written(tmp_path):
    raw, seeds, garden = sandbox(tmp_path)
    published = pd.read_parquet(garden / f"{TABLE}.parquet")
    # the history already holds the row the revision would supersede
    history = tmp_path / "history"
    history.mkdir()
    published.to_parquet(history / f"{TABLE}.parquet", index=False)
    before = tree(tmp_path)
    with pytest.raises(ValueError, match="would repeat"):
        run_parsers.run_all(only=[PARSER], raw_root=raw, seeds_root=seeds, apply_to=garden,
                            vintage=VINTAGE, _fresh_hook=next_release)
    assert tree(tmp_path) == before
    assert not (garden / merge_txn.JOURNAL).exists()


def test_cli_refuses_while_journal_exists_and_recovers(tmp_path, capsys):
    raw, seeds, garden = sandbox(tmp_path)
    journal = garden / merge_txn.JOURNAL
    journal.write_text(json.dumps({"vintage": VINTAGE, "state": "staged", "files": []}), encoding="utf-8")
    args = ["--apply-to", str(garden), "--only", PARSER, "--raw-root", str(raw), "--seeds-root", str(seeds)]
    assert run_parsers.main(args) == 2
    assert "--recover" in capsys.readouterr().err
    assert run_parsers.main(["--apply-to", str(garden), "--recover"]) == 0
    assert "rolled back" in capsys.readouterr().out
    assert not journal.exists()
    assert run_parsers.main(["--apply-to", str(garden), "--recover"]) == 0
    assert "nothing to recover" in capsys.readouterr().out


def test_cli_recover_exit_3_on_damaged_journal(tmp_path, capsys):
    garden = tmp_path / "garden"
    garden.mkdir()
    (garden / merge_txn.JOURNAL).write_text("{not json", encoding="utf-8")
    assert run_parsers.main(["--apply-to", str(garden), "--recover"]) == 3
    assert "restore from backup" in capsys.readouterr().err
