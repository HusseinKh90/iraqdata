"""
tests.test_vintages
===================
The merge rules that keep one latest vintage per value in a published
table and move superseded values to the vintage history.
"""

import numpy as np
import pandas as pd
import pytest

from iraqdata.schema import CANONICAL_COLUMNS, validate_dataframe
from vintages import append_history, as_of, merge_vintages

pytestmark = pytest.mark.usefixtures("no_network")

OLD = "2026-10-22"
NEW = "2026-11-15"


def frame(rows):
    """rows: (date, series_id, value, flag[, unit[, realtime_start[, source_hash]]])"""
    out = []
    for r in rows:
        date, sid, value, flag = r[:4]
        unit = r[4] if len(r) > 4 else "INDEX"
        rts = r[5] if len(r) > 5 else OLD
        sh = r[6] if len(r) > 6 else "a" * 64
        out.append({"date": date, "series_id": sid, "value": value, "unit": unit,
                    "status_flag": flag, "realtime_start": rts, "source_hash": sh})
    df = pd.DataFrame(out, columns=CANONICAL_COLUMNS)
    df["value"] = df["value"].astype("float64")
    return df


@pytest.fixture
def previous():
    return frame([
        ("2026-01", "x.a", 1.0, "A"),
        ("2026-01", "x.b", np.nan, "M"),
        ("2026-02", "x.a", 2.0, "P"),
        ("2026-02", "x.b", 5.0, "A"),
    ])


def test_added_rows_get_the_new_vintage(previous):
    fresh = pd.concat([previous, frame([("2026-03", "x.a", 3.0, "P", "INDEX", OLD, "b" * 64)])])
    res = merge_vintages(previous, fresh, NEW)
    assert res.changed and res.added == [("x.a", "2026-03")]
    row = res.table[(res.table.date == "2026-03")].iloc[0]
    assert row.realtime_start == NEW and row.source_hash == "b" * 64
    assert res.superseded.empty and res.revised == []


def test_revised_value_replaces_row_and_supersedes_old(previous):
    fresh = previous.copy()
    fresh.loc[2, "value"] = 2.5
    fresh.loc[2, "source_hash"] = "c" * 64
    res = merge_vintages(previous, fresh, NEW)
    assert res.changed
    row = res.table[(res.table.date == "2026-02") & (res.table.series_id == "x.a")].iloc[0]
    assert (row.value, row.realtime_start, row.source_hash) == (2.5, NEW, "c" * 64)
    pd.testing.assert_frame_equal(res.superseded, previous.iloc[[2]].reset_index(drop=True))
    assert res.revised == [{"series_id": "x.a", "date": "2026-02", "old_value": 2.0, "old_flag": "P",
                            "new_value": 2.5, "new_flag": "P", "old_hash": "a" * 64, "new_hash": "c" * 64}]


def test_flag_change_alone_updates_the_row_in_place(previous):
    """A period leaving the provisional window changes its flag, not its value: no new vintage."""
    fresh = previous.copy()
    fresh.loc[2, "status_flag"] = "A"
    res = merge_vintages(previous, fresh, NEW)
    assert res.changed and res.revised == [] and res.added == [] and res.withdrawn == []
    assert res.flag_updated == [{"series_id": "x.a", "date": "2026-02", "old_flag": "P", "new_flag": "A"}]
    assert res.superseded.empty
    row = res.table[(res.table.date == "2026-02") & (res.table.series_id == "x.a")].iloc[0]
    assert (row.status_flag, row.realtime_start, row.value) == ("A", OLD, 2.0)
    # every other row is exactly as published
    others = res.table.drop(index=row.name).reset_index(drop=True)
    pd.testing.assert_frame_equal(others, previous.drop(index=2).reset_index(drop=True))


def test_flag_and_value_change_together_is_still_a_revision(previous):
    fresh = previous.copy()
    fresh.loc[2, ["value", "status_flag"]] = [2.5, "A"]
    fresh.loc[2, "source_hash"] = "c" * 64
    res = merge_vintages(previous, fresh, NEW)
    assert len(res.revised) == 1 and res.flag_updated == []
    assert len(res.superseded) == 1 and res.superseded.iloc[0]["status_flag"] == "P"


def test_flag_update_needs_no_later_vintage(previous):
    """An in-place flag update never touches the vintage, so the same-day rule cannot refuse it."""
    fresh = previous.copy()
    fresh.loc[2, "status_flag"] = "A"
    res = merge_vintages(previous, fresh, OLD)
    assert res.changed and len(res.flag_updated) == 1


def test_as_of_is_unchanged_by_an_in_place_flag_update(previous):
    fresh = previous.copy()
    fresh.loc[2, "status_flag"] = "A"
    res = merge_vintages(previous, fresh, NEW)
    assert as_of(res.table, None, OLD)[["date", "series_id", "value"]].equals(
        previous[["date", "series_id", "value"]])


def test_unit_change_is_a_revision(previous):
    fresh = previous.copy()
    fresh.loc[0, "unit"] = "PERCENT"
    res = merge_vintages(previous, fresh, NEW)
    assert len(res.revised) == 1


def test_unchanged_rows_keep_old_vintage_and_hash(previous):
    fresh = previous.copy()
    fresh["source_hash"] = "d" * 64
    fresh["realtime_start"] = NEW
    res = merge_vintages(previous, fresh, NEW)
    assert not res.changed and res.added == [] and res.revised == []
    pd.testing.assert_frame_equal(res.table, previous)


def test_nan_equals_nan(previous):
    res = merge_vintages(previous, previous.copy(), NEW)
    assert not res.changed


def test_missing_rows_are_kept_and_reported(previous):
    fresh = previous.iloc[:3].copy()
    res = merge_vintages(previous, fresh, NEW)
    assert not res.changed
    assert res.missing == [("x.b", "2026-02")]
    assert len(res.table) == 4


def test_missing_plus_added_keeps_missing_row(previous):
    fresh = pd.concat([previous.iloc[:3], frame([("2026-03", "x.a", 3.0, "P")])])
    res = merge_vintages(previous, fresh, NEW)
    assert res.changed and res.missing == [("x.b", "2026-02")]
    assert ((res.table.date == "2026-02") & (res.table.series_id == "x.b")).any()


def test_output_sorted_typed_and_valid(previous):
    fresh = pd.concat([frame([("2026-03", "x.b", 9.0, "P")]), previous], ignore_index=True)
    fresh.loc[1, "value"] = 1.5
    res = merge_vintages(previous, fresh, NEW)
    keys = list(zip(res.table.date, res.table.series_id))
    assert keys == sorted(keys)
    assert res.table["value"].dtype == "float64"
    assert validate_dataframe(res.table, dataset_name="merged") == []


def test_previous_none_adds_everything(previous):
    res = merge_vintages(None, previous, NEW)
    assert res.changed and len(res.added) == 4
    assert set(res.table.realtime_start) == {NEW}


def test_order_follows_previous_series_first_sort():
    prev = frame([("2026-01", "a", 1.0, "A"), ("2026-02", "a", 2.0, "A"),
                  ("2026-01", "b", 3.0, "A"), ("2026-02", "b", 4.0, "A")])
    fresh = pd.concat([prev, frame([("2026-03", "a", 5.0, "A")])])
    res = merge_vintages(prev, fresh, NEW)
    assert list(zip(res.table.series_id, res.table.date))[:3] == [("a", "2026-01"), ("a", "2026-02"), ("a", "2026-03")]


def test_stale_vintage_on_revision_is_refused(previous):
    fresh = previous.copy()
    fresh.loc[0, "value"] = 1.1
    with pytest.raises(ValueError, match="--vintage"):
        merge_vintages(previous, fresh, OLD)


def test_same_vintage_without_revision_is_allowed(previous):
    fresh = pd.concat([previous, frame([("2026-03", "x.a", 3.0, "P")])])
    res = merge_vintages(previous, fresh, OLD)
    assert res.added == [("x.a", "2026-03")]


def test_duplicate_fresh_keys_rejected(previous):
    with pytest.raises(ValueError, match="duplicate"):
        merge_vintages(previous, pd.concat([previous, previous.iloc[[0]]]), NEW)


# ---------------------------------------------------------------------- vintage history


def test_append_history_creates_file(tmp_path, previous):
    path = tmp_path / "history" / "t.parquet"
    append_history(path, previous.iloc[[0]])
    got = pd.read_parquet(path)
    assert len(got) == 1 and validate_dataframe(got, dataset_name="history") == []


def test_append_history_empty_does_nothing(tmp_path, previous):
    path = tmp_path / "t.parquet"
    append_history(path, previous.iloc[0:0])
    assert not path.exists()


def test_append_history_is_append_only(tmp_path, previous):
    path = tmp_path / "t.parquet"
    append_history(path, previous.iloc[[2, 0]])
    first = pd.read_parquet(path)
    later = previous.iloc[[1]].copy()
    append_history(path, later)
    second = pd.read_parquet(path)
    pd.testing.assert_frame_equal(second.iloc[: len(first)].reset_index(drop=True), first)
    assert not second.duplicated(["date", "series_id", "realtime_start"]).any()


def test_append_history_rejects_repeated_key(tmp_path, previous):
    path = tmp_path / "t.parquet"
    append_history(path, previous.iloc[[0]])
    with pytest.raises(ValueError, match="repeat"):
        append_history(path, previous.iloc[[0]])


def test_history_rows_are_older_than_published(tmp_path, previous):
    fresh = previous.copy()
    fresh.loc[[0, 3], "value"] = [1.25, 5.5]
    res = merge_vintages(previous, fresh, NEW)
    path = tmp_path / "t.parquet"
    append_history(path, res.superseded)
    hist = pd.read_parquet(path)
    pub = res.table.set_index(["date", "series_id"])
    for r in hist.itertuples():
        assert pub.at[(r.date, r.series_id), "realtime_start"] > r.realtime_start


# ---------------------------------------------------------------------- withdrawal, as-of


@pytest.fixture
def daily():
    return frame([
        ("2022-12-29", "s", 10.0, "A"),
        ("2023-01-04", "s", 11.0, "A"),
        ("2023-01-26", "s", 12.0, "A"),
        ("2023-02-01", "s", 13.0, "A"),
        ("2023-01-26", "t", 7.0, "A"),
    ])


def _fresh_without_jan26(daily):
    fresh = daily[~((daily.series_id == "s") & (daily.date == "2023-01-26"))].copy()
    fresh.loc[fresh.date == "2023-01-04", "value"] = 11.5
    return fresh


def test_complete_from_withdraws_missing_rows_in_scope(daily):
    res = merge_vintages(daily, _fresh_without_jan26(daily), NEW, complete_from={"s": "2023-01-01"})
    assert res.changed and res.withdrawn == [("s", "2023-01-26")]
    assert not ((res.table.series_id == "s") & (res.table.date == "2023-01-26")).any()
    old = res.superseded.set_index(["date", "series_id", "realtime_start"])
    assert old.at[("2023-01-26", "s", OLD), "value"] == 12.0
    assert old.at[("2023-01-04", "s", OLD), "value"] == 11.0  # the revision is superseded too
    marker = old.loc[("2023-01-26", "s", NEW)]  # the withdrawal itself, as a vintage
    assert np.isnan(marker["value"]) and marker["status_flag"] == "M" and marker["source_hash"] == "withdrawn"
    assert len(res.superseded) == 3 and res.missing == []
    assert validate_dataframe(res.superseded, "history") == []


def test_complete_from_keeps_rows_before_the_date_and_other_series(daily):
    fresh = daily[~(((daily.series_id == "s") & (daily.date == "2022-12-29")) | (daily.series_id == "t"))]
    res = merge_vintages(daily, fresh, NEW, complete_from={"s": "2023-01-01"})
    assert res.withdrawn == [] and not res.changed
    assert sorted(res.missing) == [("s", "2022-12-29"), ("t", "2023-01-26")]
    assert len(res.table) == len(daily)


def test_withdrawal_needs_a_later_vintage(daily):
    fresh = daily[~((daily.series_id == "s") & (daily.date == "2023-01-26"))]
    with pytest.raises(ValueError, match="--vintage"):
        merge_vintages(daily, fresh, OLD, complete_from={"s": "2023-01-01"})


def test_without_complete_from_nothing_is_withdrawn(daily):
    res = merge_vintages(daily, _fresh_without_jan26(daily), NEW)
    assert res.withdrawn == [] and res.missing == [("s", "2023-01-26")]
    assert ((res.table.series_id == "s") & (res.table.date == "2023-01-26")).any()


def test_as_of_rebuilds_an_earlier_vintage(daily, tmp_path):
    fresh = pd.concat([_fresh_without_jan26(daily), frame([("2023-02-02", "s", 14.0, "A")])])
    res = merge_vintages(daily, fresh, NEW, complete_from={"s": "2023-01-01"})
    path = tmp_path / "h.parquet"
    append_history(path, res.superseded)
    old = as_of(res.table, pd.read_parquet(path), OLD)
    pd.testing.assert_frame_equal(old, daily.reset_index(drop=True))  # daily is sorted series-first
    assert as_of(res.table, pd.read_parquet(path), NEW).equals(res.table)


def test_as_of_without_history_filters_by_vintage(daily):
    newer = frame([("2023-03-01", "s", 15.0, "A", "INDEX", NEW)])
    table = pd.concat([daily, newer], ignore_index=True)
    assert as_of(table, None, OLD).equals(daily.reset_index(drop=True))


# =====================================================================
# A hash-only change is a revision only under a provenance correction
# =====================================================================

OLD_HASH, NEW_HASH = "7621858f728e9ee2", "0637c3f3bc7a7516"
PC = [{"id": "PC9", "table": "oil_monthly", "series": ["x.a"], "from": "2026-01", "to": "2026-01",
       "published_hash": OLD_HASH, "corrected_hash": NEW_HASH, "applied": "revision"}]


def _hash_pair():
    previous = frame([("2026-01", "x.a", 1.0, "A", "INDEX", OLD, OLD_HASH),
                      ("2026-02", "x.a", 2.0, "A", "INDEX", OLD, OLD_HASH)])
    fresh = frame([("2026-01", "x.a", 1.0, "A", "INDEX", OLD, NEW_HASH),
                   ("2026-02", "x.a", 2.0, "A", "INDEX", OLD, NEW_HASH)])
    return previous, fresh


def test_hash_only_change_without_correction_keeps_published_hash():
    previous, fresh = _hash_pair()
    res = merge_vintages(previous, fresh, NEW, "oil_monthly")
    assert not res.changed and res.revised == []
    assert set(res.table["source_hash"]) == {OLD_HASH}


def test_hash_only_change_under_correction_is_a_revision():
    previous, fresh = _hash_pair()
    res = merge_vintages(previous, fresh, NEW, "oil_monthly", corrections=PC)
    assert [(r["series_id"], r["date"]) for r in res.revised] == [("x.a", "2026-01")]
    entry = res.revised[0]
    assert (entry["old_hash"], entry["new_hash"], entry["correction"]) == (OLD_HASH, NEW_HASH, "PC9")
    assert entry["old_value"] == entry["new_value"] and entry["old_flag"] == entry["new_flag"]
    row = res.table.set_index(["date", "series_id"]).loc[("2026-01", "x.a")]
    assert (row["source_hash"], row["realtime_start"]) == (NEW_HASH, NEW)
    # outside the correction's range the published hash is kept
    assert res.table.set_index(["date", "series_id"]).loc[("2026-02", "x.a"), "source_hash"] == OLD_HASH
    # the published row is in the superseded rows, so the earlier vintage is not overwritten
    assert res.superseded[["date", "source_hash", "realtime_start"]].values.tolist() == [["2026-01", OLD_HASH, OLD]]
    assert as_of(res.table, res.superseded, OLD).set_index("date").loc["2026-01", "source_hash"] == OLD_HASH


def test_correction_for_a_different_fresh_hash_does_not_apply():
    previous, fresh = _hash_pair()
    other = [dict(PC[0], corrected_hash="ffffffffffffffff")]
    assert merge_vintages(previous, fresh, NEW, "oil_monthly", corrections=other).revised == []


def test_correction_for_another_table_does_not_apply():
    previous, fresh = _hash_pair()
    assert merge_vintages(previous, fresh, NEW, "gdp_quarterly", corrections=PC).revised == []


def test_covered_row_with_a_flag_change_is_one_revision():
    previous, fresh = _hash_pair()
    fresh.loc[fresh.date == "2026-01", "status_flag"] = "U"
    res = merge_vintages(previous, fresh, NEW, "oil_monthly", corrections=PC)
    assert len(res.revised) == 1 and res.revised[0]["new_flag"] == "U"
    assert len(res.superseded) == 1
