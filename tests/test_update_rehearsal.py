"""
tests.test_update_rehearsal
===========================
For each of the 11 parsers, a "next release"
of its input is fed through the merge, offline, in a sandbox copy of the raw archive, the seeds
and the published tables:

1. next release - the new period appears with the new vintage; the revised value replaces the
   published one, whose earlier vintage moves to the history; every other row is unchanged
   (except the parser's own provisional-flag policy moving the previous latest period P -> A);
2. identical re-delivery - nothing is added, revised or rewritten;
3. omitted period - the published row is kept and reported as missing.

Builders live in tests/fixtures/rehearsal.py.
"""

import shutil
from pathlib import Path

import pandas as pd
import pytest

import run_parsers
from conftest import GARDEN_DIR, RAW_DIR, SEEDS_DIR
from fixtures import rehearsal

pytestmark = pytest.mark.usefixtures("no_network")


def hash_tree(root):
    """SHA-256 of every file under a sandbox folder (conftest.hash_tree is repository-relative)."""
    import hashlib
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(root).rglob("*")) if p.is_file()}

DATE = "2026-11-15"
PARSERS = [spec.name for spec in run_parsers.REGISTRY]
KEY = ["date", "series_id"]


def sandbox(tmp_path, parser):
    """Copy the raw folders the expanded parser set reads, the seeds and the published tables."""
    raw, seeds, garden = tmp_path / "raw", tmp_path / "seeds", tmp_path / "garden"
    folders = set()
    for name in run_parsers.expand_only([parser]):
        for glob in run_parsers.BY_NAME[name].inputs:
            if glob.startswith("pipeline/raw/"):
                folders.add(glob[len("pipeline/raw/"):].split("/")[0])
    for folder in folders:
        shutil.copytree(RAW_DIR / folder, raw / folder)
    raw.mkdir(exist_ok=True)
    shutil.copytree(SEEDS_DIR, seeds)
    shutil.copytree(GARDEN_DIR, garden)
    return raw, seeds, garden


def table_of(parser):
    return run_parsers.BY_NAME[parser].outputs[0][: -len(".parquet")]


def keyed(df):
    return df.set_index(KEY).sort_index()


def _cosit_next_release(table, df):
    if table != "gdp_quarterly":
        return df
    last = df[df["date"] == "2026-Q1"].copy()
    last["date"] = "2026-Q2"
    df = pd.concat([df, last], ignore_index=True)
    i = df.index[(df["date"] == "2025-Q3") & (df["series_id"] == "gdp.nominal")][0]
    df.loc[i, "value"] = df.loc[i, "value"] + 1000.0
    return df


@pytest.mark.parametrize("parser", PARSERS)
def test_next_release(parser, tmp_path):
    raw, seeds, garden = sandbox(tmp_path, parser)
    table = table_of(parser)
    original = pd.read_parquet(garden / f"{table}.parquet")

    if parser == "cosit_gdp":
        expect = rehearsal.Expectation(("gdp.real", "2026-Q2"), ("gdp.nominal", "2025-Q3", None), [], DATE)
        hook = _cosit_next_release
    else:
        expect = rehearsal.BUILDERS[parser](raw, seeds, DATE)
        hook = None
    report = run_parsers.run_all(only=[parser], raw_root=raw, seeds_root=seeds, apply_to=garden,
                                 vintage=expect.vintage, _fresh_hook=hook)
    assert report["vintage"] == DATE
    merged = keyed(pd.read_parquet(garden / f"{table}.parquet"))
    before = keyed(original)

    new_sid, new_date = expect.new
    assert merged.at[(new_date, new_sid), "realtime_start"] == DATE

    rev_sid, rev_date, rev_value = expect.revised
    row = merged.loc[(rev_date, rev_sid)]
    assert row["realtime_start"] == DATE
    if rev_value is not None:
        assert row["value"] == pytest.approx(rev_value, rel=1e-9, abs=1e-6)
    else:
        assert row["value"] != before.at[(rev_date, rev_sid), "value"]
    history = keyed(pd.read_parquet(tmp_path / "history" / f"{table}.parquet"))
    # the superseded row keeps the vintage it was published with (the single vintage, 2026-10-28)
    assert history.loc[(rev_date, rev_sid), "realtime_start"] == before.at[(rev_date, rev_sid), "realtime_start"]
    assert history.loc[(rev_date, rev_sid), "value"] == before.at[(rev_date, rev_sid), "value"]

    # Every other row is unchanged, apart from listed knock-on changes and P -> A flag moves
    info = report["tables"][table]
    allowed = {(new_sid, new_date), (rev_sid, rev_date)} | set(expect.also)
    for sid, date in (tuple(k) for k in info["added"]):
        assert date == new_date or (sid, date) in allowed, (sid, date)
    for r in info["revised"]:
        assert (r["series_id"], r["date"]) in allowed, r
    # A period leaving the provisional window changes its flag in place: not a revision, no history row
    for r in info["flag_updated"]:
        assert (r["old_flag"], r["new_flag"]) == ("P", "A"), r
        assert merged.at[(r["date"], r["series_id"]), "status_flag"] == "A"
        assert merged.at[(r["date"], r["series_id"]), "realtime_start"] == before.at[(r["date"], r["series_id"]), "realtime_start"]
        assert merged.at[(r["date"], r["series_id"]), "value"] == before.at[(r["date"], r["series_id"]), "value"]
    changed = ({(r["date"], r["series_id"]) for r in info["revised"]} | {(d, s) for s, d in info["added"]}
               | {(r["date"], r["series_id"]) for r in info["flag_updated"]})
    unchanged = before.index.difference(pd.MultiIndex.from_tuples(sorted(changed)) if changed else before.index[:0])
    pd.testing.assert_frame_equal(merged.loc[unchanged], before.loc[unchanged])

    # Tables rebuilt only because they share a parser run stay as they were
    for other, other_info in report["tables"].items():
        if other != table:
            assert not other_info["changed"], other


@pytest.mark.parametrize("parser", PARSERS)
def test_identical_redelivery_changes_nothing(parser, tmp_path):
    raw, seeds, garden = sandbox(tmp_path, parser)
    vintage = rehearsal.identical_copy(parser, raw, seeds, DATE)
    before = hash_tree(garden)
    report = run_parsers.run_all(only=[parser], raw_root=raw, seeds_root=seeds, apply_to=garden, vintage=vintage)
    for table, info in report["tables"].items():
        assert (info["changed"], info["added"], info["revised"]) == (False, [], []), table
    assert hash_tree(garden) == before
    assert not (tmp_path / "history").exists()


@pytest.mark.parametrize("parser", PARSERS)
def test_omitted_period_is_kept_and_reported(parser, tmp_path):
    raw, seeds, garden = sandbox(tmp_path, parser)
    table = table_of(parser)
    latest = pd.read_parquet(garden / f"{table}.parquet")["date"].max()

    def drop_latest(name, df):
        return df[df["date"] != latest] if name == table else df

    before = hash_tree(garden)
    report = run_parsers.run_all(only=[parser], raw_root=raw, seeds_root=seeds, apply_to=garden,
                                 _fresh_hook=drop_latest)
    missing = report["tables"][table]["missing"]
    assert missing and all(date == latest for _, date in missing)
    assert hash_tree(garden) == before
