"""
tests.test_update_foundation
============================
Foundation: dated raw-file resolution, period stepping and the update schedule.
"""

import copy

import pytest
import yaml

import downloads
import run_parsers
import validate
from conftest import METADATA_DIR

pytestmark = pytest.mark.usefixtures("no_network")


# ---------------------------------------------------------------------- dated files


def test_latest_version_without_siblings(tmp_path):
    base = tmp_path / "DCOILBRENTEU.csv"
    base.write_text("x")
    assert downloads.latest_version(base) == base
    assert downloads.latest_version(tmp_path / "missing.csv") == tmp_path / "missing.csv"


def test_latest_version_newest_dated_sibling_wins(tmp_path):
    base = tmp_path / "INTL.zip"
    base.write_text("x")
    for d in ("2026-11-02", "2027-01-05", "2026-12-01"):
        (tmp_path / f"INTL_{d}.zip").write_text(d)
    assert downloads.latest_version(base).name == "INTL_2027-01-05.zip"


def test_latest_version_ignores_malformed_dates(tmp_path):
    base = tmp_path / "wb_oda_net.json"
    base.write_text("x")
    for name in ("wb_oda_net_2026-13-01.json", "wb_oda_net_20261101.json", "wb_oda_net_2026-11-01.json.part",
                 "wb_oda_net_copy.json"):
        (tmp_path / name).write_text("y")
    assert downloads.latest_version(base) == base


def test_vintage_of():
    from pathlib import Path
    assert downloads.vintage_of(Path("a/DCOILBRENTEU_2026-11-02.csv")) == "2026-11-02"
    assert downloads.vintage_of(Path("a/cbi_bulletin_2026-11-02.xlsx")) == "2026-11-02"
    assert downloads.vintage_of(Path("a/DCOILBRENTEU.csv")) is None
    assert downloads.vintage_of(Path("a/x_2026-02-30.csv")) is None


def test_bop_inputs_group_by_base(tmp_path):
    import parse_cbi_bop

    for name in ("bop_2013_2016.xlsx", "bop_2025.xlsx", "bop_2026.xlsx", "bop_2026_2026-11-15.xlsx",
                 "bop_2027_2027-05-01.xlsx"):
        (tmp_path / name).write_text(name)
    got = {k: v.name for k, v in parse_cbi_bop.bop_inputs(tmp_path).items()}
    assert got == {
        "bop_2013_2016": "bop_2013_2016.xlsx",
        "bop_2025": "bop_2025.xlsx",
        "bop_2026": "bop_2026_2026-11-15.xlsx",
        "bop_2027": "bop_2027_2027-05-01.xlsx",
    }


# ---------------------------------------------------------------------- periods


@pytest.mark.parametrize("date, expected", [
    ("2026-10-20", "2026-10-21"),
    ("2026-12-31", "2027-01-01"),
    ("2026-09", "2026-10"),
    ("2026-12", "2027-01"),
    ("2026-Q1", "2026-Q2"),
    ("2026-Q4", "2027-Q1"),
    ("2025", "2026"),
])
def test_next_period(date, expected):
    assert validate.next_period(date) == expected


# ---------------------------------------------------------------------- update schedule


@pytest.fixture(scope="module")
def schedule_raw():
    return yaml.safe_load((METADATA_DIR / "update_schedule.yaml").read_text(encoding="utf-8"))


def test_real_schedule_loads():
    sched = validate.load_update_schedule()
    assert len(sched["sources"]) == 12
    assert len(sched["series"]) == 62  # gross ODA withdrawn; aid grants renamed, residual withdrawn


def test_exchange_rate_sources_are_automatic():
    """One automatic source per exchange-rate series."""
    sched = validate.load_update_schedule()
    sources = {s["id"]: s for s in sched["sources"]}
    assert sources["cbi_fx"]["fetch"] == "auto" and sources["github_fx"]["fetch"] == "auto"
    assert "reason" not in sources["cbi_fx"]
    assert (sched["series"]["fx.official"]["source"], sched["series"]["fx.official"]["lag_days"]) == ("cbi_fx", 14)
    assert (sched["series"]["parallel_rate_iraq"]["source"],
            sched["series"]["parallel_rate_iraq"]["lag_days"]) == ("github_fx", 7)


def test_schedule_covers_exactly_the_production_series(garden_tables):
    sched = validate.load_update_schedule()
    published = set()
    for df in garden_tables.values():
        published |= set(df["series_id"].unique())
    assert set(sched["series"]) == published
    assert len(published) == 62


def test_every_parser_belongs_to_a_source():
    sched = validate.load_update_schedule()
    covered = {p for s in sched["sources"] for p in s["parsers"]}
    assert covered == set(run_parsers.BY_NAME)


def _write(tmp_path, data):
    path = tmp_path / "update_schedule.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def _break(schedule_raw, fn):
    data = copy.deepcopy(schedule_raw)
    fn(data)
    return data


BROKEN = {
    "missing publisher": lambda d: d["sources"][0].pop("publisher"),
    "bad fetch": lambda d: d["sources"][0].update(fetch="sometimes"),
    "manual without reason": lambda d: next(s for s in d["sources"] if s["fetch"] == "manual").pop("reason"),
    "auto with reason": lambda d: next(s for s in d["sources"] if s["fetch"] == "auto").update(reason="x"),
    "duplicate id": lambda d: d["sources"].append(dict(d["sources"][0])),
    "unknown parser": lambda d: d["sources"][0]["parsers"].append("no_such_parser"),
    "parser not covered": lambda d: d["sources"].remove(next(s for s in d["sources"] if s["id"] == "cosit")),
    "series unknown source": lambda d: d["series"]["money.m2"].update(source="nowhere"),
    "series lag and ended": lambda d: d["series"]["money.m2"].update(ended="x"),
    "series neither": lambda d: d["series"]["money.m2"].pop("lag_days"),
    "lag zero": lambda d: d["series"]["money.m2"].update(lag_days=0),
    "lag without rationale": lambda d: d["series"]["money.m2"].pop("rationale"),
    "bad reviewed": lambda d: d["series"]["money.m2"].update(reviewed="24/10/2026"),
    # notify and fetch settings
    "no notify": lambda d: d.pop("notify"),
    "empty notify handle": lambda d: d.update(notify={"github": " "}),
    "auto without kind": lambda d: next(s for s in d["sources"] if s["fetch"] == "auto").pop("kind"),
    "unknown kind": lambda d: next(s for s in d["sources"] if s["fetch"] == "auto").update(kind="pdf"),
    "threshold zero": lambda d: d["sources"][0].update(failure_threshold=0),
    "threshold not int": lambda d: d["sources"][0].update(failure_threshold="2"),
}


def test_schedule_kinds_thresholds_and_maintainer():
    """Every auto source has a kind; thresholds default to 2; the maintainer is named."""
    sched = validate.load_update_schedule()
    auto = {s["id"]: s for s in sched["sources"] if s["fetch"] == "auto"}
    assert {k for k, s in auto.items() if s["kind"] == "spreadsheet"} == {"cbi_bop", "cbi_kfi", "cbi_bulletin", "cbi_fx"}
    assert {k for k, s in auto.items() if s["kind"] == "api"} == {"bis_lbs", "wb_oda", "fred_brent", "eia_intl", "github_fx"}
    assert {s["id"]: s["failure_threshold"] for s in sched["sources"] if s["failure_threshold"] == 1} ==         {"fred_brent": 1, "github_fx": 1, "cbi_fx": 1}
    assert all(s["failure_threshold"] == 2 for s in sched["sources"] if s["id"] not in {"fred_brent", "github_fx", "cbi_fx"})
    assert sched["notify"]["github"] == "HusseinKh90"


@pytest.mark.parametrize("case", sorted(BROKEN))
def test_schedule_rule_violations_raise(case, schedule_raw, tmp_path):
    path = _write(tmp_path, _break(schedule_raw, BROKEN[case]))
    with pytest.raises(ValueError):
        validate.load_update_schedule(path)


def test_every_auto_source_has_a_fetcher():
    import fetchers

    sched = validate.load_update_schedule()
    auto = {s["id"] for s in sched["sources"] if s["fetch"] == "auto"}
    assert auto == set(fetchers.FETCHERS)


def test_auto_source_without_fetcher_raises(schedule_raw, tmp_path):
    data = _break(schedule_raw, lambda d: next(s for s in d["sources"] if s["id"] == "cosit").update(
        fetch="auto", kind="spreadsheet", reason=None))
    data["sources"] = [{k: v for k, v in s.items() if v is not None} for s in data["sources"]]
    with pytest.raises(ValueError, match="fetcher"):
        validate.load_update_schedule(_write(tmp_path, data))
