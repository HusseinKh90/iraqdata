"""
tests.test_oecd_ragged_edge
===========================
The two World Bank indicators behind the aid series are updated at different times. A year that only
one of them has is published for that series alone (the freshness check watches each series' own
latest year); a year missing inside a series' own range, a paginated response or a response without
any value still stops the run.
"""

import json

import pandas as pd
import pytest

from conftest import block_network
from fixtures import damage
from source_io import ParseError

NET, GRANTS = "oecd.dac.oda_total_net", "oecd.dac.grants_excl_tc"


def _build(tmp_path, edit=None):
    raw, seeds = damage.copy_inputs("oecd_dac", tmp_path)
    if edit is not None:
        edit(raw / "oecd")
    with block_network():
        out = damage.run_parser("oecd_dac", raw, seeds, tmp_path / "out")
    return pd.read_parquet(out / "oecd_dac_annual.parquet")


def _edit_json(path, change):
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def _set(data, year, value):
    for item in data[1]:
        if item["date"] == str(year):
            item["value"] = value


def test_year_only_one_indicator_has_is_published_for_that_series(tmp_path):
    df = _build(tmp_path, lambda oecd: _edit_json(oecd / "wb_oda_net.json", lambda d: _set(d, 2024, 3.5e9)))
    last = df.groupby("series_id")["date"].max()
    assert (last[NET], last[GRANTS]) == ("2024", "2023")
    assert df[(df.series_id == NET) & (df.date == "2024")]["value"].tolist() == [3500.0]


def test_other_way_round_is_published_too(tmp_path):
    df = _build(tmp_path, lambda oecd: _edit_json(oecd / "wb_oda_grants.json", lambda d: _set(d, 2024, 1e9)))
    last = df.groupby("series_id")["date"].max()
    assert (last[NET], last[GRANTS]) == ("2023", "2024")


def test_year_missing_inside_a_series_range_is_named(tmp_path):
    with pytest.raises(ParseError) as info:
        _build(tmp_path, lambda oecd: _edit_json(oecd / "wb_oda_grants.json", lambda d: _set(d, 2015, None)))
    msg = str(info.value)
    assert "wb_oda_grants.json" in msg and "2015" in msg and "2004" in msg and "2023" in msg


def test_response_without_a_value_is_refused(tmp_path):
    def edit(oecd):
        _edit_json(oecd / "wb_oda_net.json", lambda d: [_set(d, y, None) for y in range(2004, 2026)])
    with pytest.raises(ParseError) as info:
        _build(tmp_path, edit)
    assert "wb_oda_net.json" in str(info.value) and "no value" in str(info.value)


def test_paginated_response_is_refused(tmp_path):
    def edit(oecd):
        _edit_json(oecd / "wb_oda_net.json", lambda d: d[0].update({"pages": 2, "total": 130}))
    with pytest.raises(ParseError) as info:
        _build(tmp_path, edit)
    assert "wb_oda_net.json" in str(info.value) and "page" in str(info.value)


def test_unedited_inputs_give_the_published_table(tmp_path):
    df = _build(tmp_path)
    assert df.groupby("series_id")["date"].agg(["min", "max", "count"]).to_dict("index") == {
        NET: {"min": "2004", "max": "2023", "count": 20}, GRANTS: {"min": "2004", "max": "2023", "count": 20}}
