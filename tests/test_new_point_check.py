"""
tests.test_new_point_check
==========================
The new-point volatility check compares each of a series' latest periods with the moves just before
it, so an error that the series-wide jump rule lets through (a 40-50% misread in a volatile series)
is a review notice. It is off until pipeline/metadata/new_point_check.yaml says `enabled: true`;
the calibration recorded in that file's header is pinned here.
"""

import numpy as np
import pandas as pd
import pytest
import yaml

import validate
from conftest import METADATA_DIR

CONFIG = {"enabled": True, "k": 15, "latest": 3, "windows": {"monthly": 36, "quarterly": 12}}


def _monthly(values, start="2010-01", sid="s", flags=None):
    dates = [str(p) for p in pd.period_range(start, periods=len(values), freq="M")]
    return pd.DataFrame({"date": dates, "series_id": sid, "value": values, "unit": "X",
                         "status_flag": flags or ["A"] * len(values), "realtime_start": "2026-10-22",
                         "source_hash": "0" * 16})


def _noisy(n=60, seed=1):
    rng = np.random.default_rng(seed)
    return list(100 * np.exp(np.cumsum(rng.normal(0.0, 0.01, n))))


def test_the_check_is_off_in_the_repository():
    assert validate.load_new_point_check()["enabled"] is False


def test_a_spike_in_the_latest_period_is_a_notice_with_both_values():
    values = _noisy()
    values[-1] *= 1.45
    (w,) = validate.new_point_warnings(_monthly(values), "t", CONFIG)
    assert (w.series, w.check, w.periods) == ("s", "new_point", ["2014-12"])
    assert "New Point Notice: s 2014-12 moved ×1.4" in w.message and "limit 15" in w.message
    assert set(w.values) == {"2014-11", "2014-12"}
    assert validate.VALUE_CHECKS >= {"new_point"} and "new_point" in validate.VALID_CHECKS


def test_a_spike_before_the_latest_periods_is_not_reported():
    values = _noisy()
    values[-10] *= 1.45                 # the next change back is large too, but both are outside the latest 3
    values[-9:] = [v * 1.45 for v in values[-9:]]
    assert validate.new_point_warnings(_monthly(values), "t", CONFIG) == []


def test_ordinary_moves_pass():
    assert validate.new_point_warnings(_monthly(_noisy()), "t", CONFIG) == []


def test_a_known_break_explains_the_move():
    values = _noisy()
    values[-1] *= 1.45
    flags = ["A"] * (len(values) - 1) + ["B"]
    assert validate.new_point_warnings(_monthly(values, flags=flags), "t", CONFIG) == []


def test_k_and_latest_decide():
    values = _noisy()
    values[-3] *= 1.45                  # a spike is two big moves: up at the third latest period, back down at the second
    df = _monthly(values)
    assert validate.new_point_warnings(df, "t", {**CONFIG, "k": 1000}) == []
    assert validate.new_point_warnings(df, "t", {**CONFIG, "latest": 1}) == []
    assert len(validate.new_point_warnings(df, "t", {**CONFIG, "latest": 2})) == 1
    assert len(validate.new_point_warnings(df, "t", {**CONFIG, "latest": 3})) == 2


def test_a_series_that_can_be_negative_is_scaled_by_its_level():
    rng = np.random.default_rng(2)
    values = list(rng.normal(0, 1.0, 60))
    values[-1] += 40
    (w,) = validate.new_point_warnings(_monthly(values), "t", CONFIG)
    assert "median level" in w.message


def test_a_flat_history_does_not_make_every_move_infinite():
    values = [5.0] * 59 + [5.1]
    scores = validate.new_point_scores(np.array(values), 36)
    assert all(np.isfinite(z) for _, z, _ in scores)


def test_a_short_series_is_not_checked():
    assert validate.new_point_warnings(_monthly(_noisy(40)), "t", CONFIG) == []          # window 36 + 10 needed


def test_the_gate_runs_it_only_when_enabled(monkeypatch):
    values = _noisy()
    values[-1] *= 1.45
    df = _monthly(values)
    assert not [w for w in validate.validate_tier2_details(df, "t")[1] if w.check == "new_point"]
    monkeypatch.setattr(validate, "load_new_point_check", lambda *a, **k: CONFIG)
    assert [w.check for w in validate.validate_tier2_details(df, "t")[1] if w.check == "new_point"] == ["new_point"]


@pytest.mark.parametrize("change", [{"k": 0}, {"latest": 0}, {"windows": {"monthly": 36}}, {"windows": {"monthly": 3, "quarterly": 12}},
                                    {"enabled": "yes"}])
def test_a_malformed_setting_is_refused(tmp_path, change):
    path = tmp_path / "check.yaml"
    path.write_text(yaml.safe_dump({**{k: v for k, v in CONFIG.items()}, **change}), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid check.yaml"):
        validate.load_new_point_check(path)


def test_the_calibration_in_the_settings_file_is_what_the_data_gives(garden_tables):
    """Every point of every monthly and quarterly series with enough history is tested as if it were the latest."""
    tested, z_by_age = 0, []
    series = 0
    for df in garden_tables.values():
        for _, group in df.dropna(subset=["value"]).groupby("series_id"):
            group = group.assign(date=group["date"].astype(str)).sort_values("date")
            dates = group["date"].tolist()
            shape = next((n for n, rx in validate._PERIOD_SHAPES if rx.match(dates[0])), None)
            window = CONFIG["windows"].get(shape)
            if window is None or len(group) < window + 10:
                continue
            series += 1
            for index, z, _ in validate.new_point_scores(group["value"].to_numpy(dtype=float), window):
                tested += 1
                z_by_age.append((z, len(group) - 1 - index))
    z = np.array([a for a, _ in z_by_age])
    age = np.array([b for _, b in z_by_age])
    assert (series, tested) == (47, 4778)
    assert {k: int((z > k).sum()) for k in (8, 12, 15, 20, 30)} == {8: 68, 12: 42, 15: 26, 20: 17, 30: 6}
    assert int(((z > 15) & (age < 3)).sum()) == 1
    header = (METADATA_DIR / "new_point_check.yaml").read_text(encoding="utf-8")
    assert "47 such series, 4,778 points" in header and "k = 15: 26 (0.54%)" in header
