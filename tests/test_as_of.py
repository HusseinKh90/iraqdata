"""
tests.test_as_of
================
as_of='YYYY-MM-DD' returns values as they were published on that date. The client's rule must
equal the pipeline's vintages.as_of on every table and vintage date. The published data has a
single vintage and no history, so the tests build a local data folder in which two tables have been
revised and trimmed by a later merge (the pipeline's own merge_vintages and prepare_history);
release history is served by the fake GitHub.
"""

import shutil
import warnings
from types import SimpleNamespace

import pandas as pd
import pytest

import iraqdata
import iraqdata.client as client
import iraqdata.storage as storage
import vintages as pipeline_vintages
from conftest import CANONICAL_COLUMNS, GARDEN_DIR, PINNED_TAG, build_release

FIRST_VINTAGE = "2026-10-28"
REVISION_VINTAGE = "2026-11-15"
HISTORY_TABLES = ["oil_monthly", "prices_monthly"]


@pytest.fixture(scope="module")
def revised(tmp_path_factory):
    """A local data folder with a history: one CPI value revised and three production months withdrawn on 2026-11-15."""
    folder = tmp_path_factory.mktemp("revised")
    for path in GARDEN_DIR.glob("*.parquet"):
        shutil.copy2(path, folder / path.name)
    (folder / "history").mkdir()

    prices = pd.read_parquet(GARDEN_DIR / "prices_monthly.parquet")
    fresh = prices.copy()
    row = fresh[fresh["series_id"] == "cpi_headline"].index[-1]
    key = (fresh.at[row, "date"], "cpi_headline")
    old, new = float(fresh.at[row, "value"]), float(fresh.at[row, "value"]) * 1.01
    fresh.at[row, "value"] = new
    prices_merge = pipeline_vintages.merge_vintages(prices, fresh, REVISION_VINTAGE, "prices_monthly")

    oil = pd.read_parquet(GARDEN_DIR / "oil_monthly.parquet")
    secondary = oil[oil["series_id"] == "crude_production_secondary"].sort_values("date")
    dropped = list(secondary["date"].iloc[-3:])
    oil_merge = pipeline_vintages.merge_vintages(
        oil, oil[~oil.index.isin(secondary.index[-3:])], REVISION_VINTAGE, "oil_monthly",
        complete_from={"crude_production_secondary": dropped[0]})

    for name, merge in (("prices_monthly", prices_merge), ("oil_monthly", oil_merge)):
        merge.table.to_parquet(folder / f"{name}.parquet", index=False)
        pipeline_vintages.prepare_history(folder / "history" / f"{name}.parquet", merge.superseded).to_parquet(
            folder / "history" / f"{name}.parquet", index=False)
    assert oil_merge.withdrawn == [("crude_production_secondary", d) for d in dropped]
    return SimpleNamespace(folder=folder, history=folder / "history", key=key, old=old, new=new, dropped=dropped)


@pytest.fixture
def checkout(monkeypatch, fresh_memory_cache, revised):
    """Unpinned, reading the local folder with the history."""
    monkeypatch.setenv("IRAQDATA_LOCAL_DIR", str(revised.folder))
    monkeypatch.delenv("IRAQDATA_RELEASE", raising=False)
    monkeypatch.setattr(storage, "_code_pin", None)


def _vintage_dates(revised, table: str) -> list[str]:
    stored = pd.read_parquet(revised.folder / f"{table}.parquet")
    history = pd.read_parquet(revised.history / f"{table}.parquet")
    dates = sorted(set(stored["realtime_start"].astype(str)) | set(history["realtime_start"].astype(str)))
    return ["2004-01-01", "2026-10-01"] + dates + ["2099-12-31"]


def _normalised(df: pd.DataFrame) -> pd.DataFrame:
    return df[CANONICAL_COLUMNS].sort_values(["date", "series_id"]).reset_index(drop=True)


@pytest.mark.parametrize("table", HISTORY_TABLES)
def test_as_of_equals_the_pipeline_rule(checkout, revised, table):
    stored = pd.read_parquet(revised.folder / f"{table}.parquet")
    history = pd.read_parquet(revised.history / f"{table}.parquet")
    for date in _vintage_dates(revised, table):
        expected = _normalised(pipeline_vintages.as_of(stored, history, date))
        got = _normalised(client.get_table(table, as_of=date, audit=True))
        pd.testing.assert_frame_equal(got, expected, obj=f"{table} as of {date}")


def test_revision_shows_old_value_before_and_new_value_after(checkout, revised):
    then = client.get_table("prices_monthly", as_of=FIRST_VINTAGE).set_index(["date", "series_id"])
    now = client.get_table("prices_monthly", as_of=REVISION_VINTAGE).set_index(["date", "series_id"])
    assert then.loc[revised.key, "value"] == revised.old
    assert now.loc[revised.key, "value"] == revised.new


def test_withdrawn_value_is_absent_after_withdrawal(checkout, revised):
    before = client.get_table("oil_monthly", as_of=FIRST_VINTAGE)
    after = client.get_table("oil_monthly", as_of=REVISION_VINTAGE)
    gone = {("crude_production_secondary", d) for d in revised.dropped}
    assert gone <= set(zip(before["series_id"], before["date"]))
    assert not gone & set(zip(after["series_id"], after["date"]))


def test_series_not_yet_published_is_empty_with_warning(checkout):
    with pytest.warns(UserWarning, match="had not yet been published as of 2000-01-01"):
        df = client.get_series("cpi", as_of="2000-01-01")
    assert df.empty


def test_long_output_shows_the_vintage(checkout):
    df = client.get_series("cpi", wide=False, as_of=FIRST_VINTAGE)
    assert "realtime_start" in df.columns
    assert (df["realtime_start"].astype(str) <= FIRST_VINTAGE).all()


def test_as_of_combines_with_every_option(checkout):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", iraqdata.FlagWarning)
        out = client.get_series(["m2", "official_rate"], start="2020", end="2024", as_of="2026-11-01",
                                aliases={"m2": "Broad"}, flags=True)
    assert list(out["monthly"].columns) == ["Broad", "Broad_flag"]
    assert list(out["daily"].columns) == ["official_rate", "official_rate_flag"]
    assert out["monthly"].index.min() >= "2020-01" and out["monthly"].index.max() <= "2024-12"


def test_release_without_history_is_refused(fake_github):
    storage.set_release(PINNED_TAG)
    with pytest.raises(iraqdata.NoVintageHistoryError, match=PINNED_TAG):
        client.get_series("cpi", as_of=FIRST_VINTAGE)


def test_the_published_data_has_no_history_so_as_of_is_refused(fresh_memory_cache, monkeypatch):
    monkeypatch.delenv("IRAQDATA_LOCAL_DIR", raising=False)
    monkeypatch.delenv("IRAQDATA_RELEASE", raising=False)
    monkeypatch.setattr(storage, "_code_pin", None)
    with pytest.raises(iraqdata.NoVintageHistoryError):
        client.get_series("cpi", as_of=FIRST_VINTAGE)


def test_release_history_is_downloaded_verified_and_applied(fake_github, tmp_path, revised):
    history = revised.history / "prices_monthly.parquet"
    folder = build_release(tmp_path / "with-history", files={"history/prices_monthly.parquet": history})
    fake_github.add_release(PINNED_TAG, folder)
    storage.set_release(PINNED_TAG)

    got = _normalised(client.get_table("prices_monthly", as_of=FIRST_VINTAGE, audit=True))
    stored = pd.read_parquet(folder / "prices_monthly.parquet")
    expected = _normalised(pipeline_vintages.as_of(stored, pd.read_parquet(folder / "history" / "prices_monthly.parquet"),
                                                   FIRST_VINTAGE))
    pd.testing.assert_frame_equal(got, expected)
    assert fake_github.requests_to(r"/history\.prices_monthly\.parquet$")
    cached = storage.get_cache_dir() / PINNED_TAG / "history" / "prices_monthly.parquet"
    assert cached.read_bytes() == (folder / "history" / "prices_monthly.parquet").read_bytes()

    # A table without a history entry had no revisions: its current rows, filtered by vintage
    oil = client.get_table("oil_daily", as_of="2099-12-31", audit=True)
    assert len(oil) == len(pd.read_parquet(folder / "oil_daily.parquet"))


def test_damaged_release_history_is_rejected(fake_github, tmp_path, revised):
    folder = build_release(tmp_path / "with-history",
                           files={"history/prices_monthly.parquet": revised.history / "prices_monthly.parquet"})
    fake_github.add_release(PINNED_TAG, folder)
    fake_github.corrupt.add("history.prices_monthly.parquet")
    storage.set_release(PINNED_TAG)
    with pytest.raises(iraqdata.ChecksumMismatchError, match="history/prices_monthly.parquet"):
        client.get_table("prices_monthly", as_of=FIRST_VINTAGE)


@pytest.mark.parametrize("bad", ["2026-10", "26-10-2026", "2026-02-30"])
def test_malformed_as_of_is_rejected(checkout, bad):
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        client.get_series("cpi", as_of=bad)


def test_local_folder_without_history_is_refused(fresh_memory_cache, monkeypatch, tmp_path):
    local = tmp_path / "local"
    local.mkdir()
    (local / "prices_monthly.parquet").write_bytes((GARDEN_DIR / "prices_monthly.parquet").read_bytes())
    monkeypatch.setenv("IRAQDATA_LOCAL_DIR", str(local))
    monkeypatch.delenv("IRAQDATA_RELEASE", raising=False)
    monkeypatch.setattr(storage, "_code_pin", None)
    with pytest.raises(iraqdata.NoVintageHistoryError, match="history"):
        client.get_table("prices_monthly", as_of=FIRST_VINTAGE)
