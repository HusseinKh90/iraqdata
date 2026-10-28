"""
tests.test_rule_derivation
==========================
Every plausibility rule is statistical
(reproducible from the published data up to its derived_through date) or reviewed (hand-set,
with a rationale). history×3 is gone, and new data never changes a rule.
"""

import shutil

import numpy as np
import pandas as pd
import pytest

import derive_rules
import validate
from conftest import GARDEN_DIR

RULES = derive_rules.load()["series"]


def test_no_rule_is_history_x3_and_every_rule_has_a_basis():
    assert derive_rules.problems({"series": RULES}) == []
    for sid, rule in RULES.items():
        assert rule["basis"] in ("statistical", "reviewed"), sid
        assert "history" not in str(rule["basis"]), sid


def test_reviewed_rules_have_a_rationale():
    reviewed = {sid: r for sid, r in RULES.items() if r["basis"] == "reviewed"}
    assert set(reviewed) == {"money.policy_rate", "oil_price_basrah", "oecd.dac.grants_excl_tc",
                             "oecd.dac.oda_total_net"}
    for sid, rule in reviewed.items():
        assert len(rule["rationale"]) > 40, sid


def test_statistical_rules_equal_a_rederivation():
    assert derive_rules.main(["--check"]) == 0


def test_measure_is_scaled_exactly_for_series_with_values_not_above_zero(garden_tables):
    values = pd.concat(garden_tables.values()).dropna(subset=["value"])
    non_positive = set(values.loc[values["value"] <= 0, "series_id"])
    statistical = {sid for sid, r in RULES.items() if r["basis"] == "statistical"}
    scaled = {sid for sid in statistical if RULES[sid]["jump"]["measure"] == "scaled"}
    assert scaled == non_positive & statistical
    assert len(scaled) == 10


def test_statistical_threshold_is_k_times_typical():
    for sid, rule in RULES.items():
        if rule["basis"] == "statistical":
            jump = rule["jump"]
            assert jump["k"] == 10
            assert jump["threshold"] == pytest.approx(10 * jump["typical"], rel=1e-5), sid


def test_too_little_history_cannot_be_statistical():
    with pytest.raises(ValueError, match="at least 20"):
        derive_rules.derive(np.arange(1.0, 20.0), "positive")
    rules = {"defaults": {}, "series": {"x": {"unit": "U", "sign": "positive", "basis": "statistical",
                                              "derived_through": "2026-10-26"}}}
    with pytest.raises(ValueError, match="x: .*reviewed"):
        derive_rules.rederive(rules, lambda date: {"x": np.arange(1.0, 11.0)})


def test_rederivation_never_touches_a_reviewed_rule():
    reviewed = {"unit": "PERCENT", "basis": "reviewed", "rationale": "hand-set", "min": 0, "max": 40,
                "jump": {"measure": "log", "threshold": 0.35}, "reviewed": "2026-10-26"}
    out = derive_rules.rederive({"defaults": {}, "series": {"r": reviewed}}, lambda d: {"r": np.ones(3)}, "2030-01-01")
    assert out["series"]["r"] is reviewed


def test_history_x3_is_refused_at_load(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text("series:\n  s:\n    unit: U\n    basis: history×3\n", encoding="utf-8")
    with pytest.raises(ValueError, match="basis"):
        validate.load_rules(path)


def test_new_data_does_not_change_the_rules_but_the_gate_warns(tmp_path):
    """Rules are frozen at derived_through: a later value outside the range leaves --check green."""
    garden = tmp_path / "garden"
    shutil.copytree(GARDEN_DIR, garden)
    path = garden / "prices_monthly.parquet"
    df = pd.read_parquet(path)
    last = df[df["series_id"] == "cpi_headline"].sort_values("date").iloc[[-1]].copy()
    last["date"] = "2099-01"
    last["value"] = RULES["cpi_headline"]["max"] * 3
    last["realtime_start"] = "2099-02-01"
    pd.concat([df, last], ignore_index=True).to_parquet(path, index=False)

    assert derive_rules.main(["--check", "--garden", str(garden), "--history", str(tmp_path / "history")]) == 0  # no history
    _, warnings = validate.validate_tier2_details(pd.read_parquet(path), "prices_monthly")
    assert any(w.series == "cpi_headline" and w.check == "envelope" and "2099-01" in w.periods for w in warnings)
