"""
tests.test_acknowledgement_expiry
=================================
Acknowledgements carry a review-by date and
are tied to the values they acknowledge.

- a missing review_by is a load error; review periods are at most 12 months, or 5 years for
  settled history;
- past review_by the warning is a notice again, [EXPIRED] is printed and --release fails;
- within 30 days of review_by: [DUE-FOR-REVIEW], and the acknowledgement still applies;
- a covered value that changes (compared at 10 significant figures): [CHANGED] with the old and
  new values, and the warning returns;
- one entry can cover several periods, each matched on its own.
"""

import pandas as pd
import pytest
import yaml

import validate
from conftest import GARDEN_DIR

SID = "cpi_core"  # in no identity, so the fixture has no [GAP] notices
AS_OF = pd.Timestamp("2026-10-26")


@pytest.fixture
def data(tmp_path):
    """Two years of real core CPI with the last month x1.5: one jump, at the last period."""
    df = pd.read_parquet(GARDEN_DIR / "prices_monthly.parquet")
    df = df[(df["series_id"] == SID) & (df["date"] >= "2019-01") & (df["date"] <= "2020-12")].copy()
    df = df.sort_values("date").reset_index(drop=True)
    df.loc[df.index[-1], "value"] *= 1.5
    path = tmp_path / "t.parquet"
    df.to_parquet(path, index=False)
    prev, last = df.iloc[-2], df.iloc[-1]
    return path, {str(prev["date"]): float(prev["value"]), str(last["date"]): float(last["value"])}


def ack(values, **extra):
    last = max(values)
    entry = {"series": SID, "check": "jump", "periods": [last], "values": dict(values),
             "reason": "Test event", "reviewer": "Test Reviewer", "date": "2026-10-26",
             "review_by": "2027-10-26"}
    entry.update(extra)
    return entry


def load(tmp_path, entries):
    path = tmp_path / "acks.yaml"
    path.write_text(yaml.safe_dump({"acknowledged": entries}, allow_unicode=True), encoding="utf-8")
    return validate.load_acknowledgements(path)


def gate(path, acks, capsys, as_of=AS_OF, release=True):
    code = validate.run_gatekeeper([path], acks, release=release, freshness=False, as_of=as_of, all_datasets=False)
    return code, capsys.readouterr().out


# =====================================================================
# Loading
# =====================================================================

def test_missing_review_by_is_a_load_error(tmp_path, data):
    entry = ack(data[1])
    del entry["review_by"]
    with pytest.raises(ValueError, match="review_by"):
        load(tmp_path, [entry])


@pytest.mark.parametrize("settled,review_by,ok", [
    (False, "2027-10-26", True),
    (False, "2027-10-27", False),
    (True, "2031-10-26", True),
    (True, "2031-10-27", False),
])
def test_review_period_limits(tmp_path, data, settled, review_by, ok):
    entry = ack(data[1], review_by=review_by, **({"settled": True} if settled else {}))
    if ok:
        assert load(tmp_path, [entry])
    else:
        with pytest.raises(ValueError, match="review_by"):
            load(tmp_path, [entry])


def test_values_must_cover_every_period(tmp_path, data):
    with pytest.raises(ValueError, match="values"):
        load(tmp_path, [ack({"2020-11": 1.0}, periods=["2020-12"])])


# =====================================================================
# States
# =====================================================================

def test_applies(tmp_path, data, capsys):
    path, values = data
    code, out = gate(path, load(tmp_path, [ack(values)]), capsys)
    assert code == 0
    assert "[ACKNOWLEDGED]" in out and "[NOTICE]" not in out


def test_expired_acknowledgement_no_longer_silences(tmp_path, data, capsys):
    path, values = data
    acks = load(tmp_path, [ack(values)])
    code, out = gate(path, acks, capsys, as_of=pd.Timestamp("2027-10-27"))
    assert code == 1
    assert "[EXPIRED]" in out and "2027-10-26" in out
    assert "[NOTICE]" in out and "[ACKNOWLEDGED]" not in out


def test_due_for_review_still_applies(tmp_path, data, capsys):
    path, values = data
    acks = load(tmp_path, [ack(values)])
    code, out = gate(path, acks, capsys, as_of=pd.Timestamp("2027-10-01"))
    assert code == 0
    assert "[DUE-FOR-REVIEW]" in out and "[ACKNOWLEDGED]" in out and "[NOTICE]" not in out
    _, out = gate(path, acks, capsys, as_of=pd.Timestamp("2027-09-25"))
    assert "[DUE-FOR-REVIEW]" not in out


def test_revised_value_is_reviewed_again(tmp_path, data, capsys):
    path, values = data
    last = max(values)
    stored = {**values, last: values[last] * (1 + 1e-6)}  # a revision in the 6th significant figure
    code, out = gate(path, load(tmp_path, [ack(stored)]), capsys)
    assert code == 1
    assert "[CHANGED]" in out and "[NOTICE]" in out
    assert f"{stored[last]:.10g}" in out and f"{values[last]:.10g}" in out


def test_revised_previous_value_is_reviewed_again(tmp_path, data, capsys):
    path, values = data
    first = min(values)
    stored = {**values, first: values[first] + 1.0}
    code, out = gate(path, load(tmp_path, [ack(stored)]), capsys)
    assert code == 1 and "[CHANGED]" in out


def test_floating_point_noise_is_not_a_revision(tmp_path, data, capsys):
    path, values = data
    stored = {p: v * (1 + 1e-13) for p, v in values.items()}
    code, out = gate(path, load(tmp_path, [ack(stored)]), capsys)
    assert code == 0 and "[CHANGED]" not in out


def test_one_entry_covers_several_periods(tmp_path, data, capsys):
    path, values = data
    df = pd.read_parquet(path)
    # a one-month spike six months before the end: a jump up into it and down out of it, plus
    # the original jump at the last period
    df.loc[df.index[-6], "value"] *= 1.5
    df.to_parquet(path, index=False)
    p6, p5, p7 = (str(df.at[df.index[i], "date"]) for i in (-6, -5, -7))
    events = {p7: float(df.at[df.index[-7], "value"]), p6: float(df.at[df.index[-6], "value"]),
              p5: float(df.at[df.index[-5], "value"]), "2099-01": 1.0, **values}
    entry = ack(events, periods=sorted([p6, p5, max(values), "2099-01"]))
    code, out = gate(path, load(tmp_path, [entry]), capsys)
    assert code == 0, out
    assert out.count("[ACKNOWLEDGED]") == 3
