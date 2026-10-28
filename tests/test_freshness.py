"""
tests.test_freshness
====================
Every run reports whether each series is still updating, and the release
check (`--release --freshness`) fails on unacknowledged overdue series.
"""

from pathlib import Path

import pandas as pd
import pytest
import yaml

import validate
from conftest import GATE_SUMMARY, run_validate, write_tmp_parquet

pytestmark = pytest.mark.usefixtures("no_network")

BASELINE_LINE = GATE_SUMMARY
# 62 series: 55 are still updating and 7 have ended (oil_price_basrah, whose only months are old transcribed ones, among them)
FRESHNESS_LINE = "[FRESHNESS] as of 2026-10-28: 55 current, 0 overdue, 0 acknowledged, 7 ended, 0 unchecked"


def run_gate(*args):
    """The gatekeeper CLI with options (conftest.run_validate passes any arguments through)."""
    return run_validate(*args)


def table(rows):
    return pd.DataFrame(rows, columns=["date", "series_id"])


SCHEDULE = {
    "series": {
        "m.a": {"source": "s", "lag_days": 30, "rationale": "x", "reviewed": "2026-10-24"},
        "m.ended": {"source": "s", "ended": "superseded", "reviewed": "2026-10-24"},
    }
}


# ---------------------------------------------------------------------- unit


def status(tables, as_of, acks=(), production=frozenset({"monthly"})):
    return {st.series_id: st for st in validate.freshness_status(tables, SCHEDULE, list(acks), as_of, set(production))}


def test_current_on_due_date_overdue_the_day_after():
    tables = {"monthly": table([("2026-08", "m.a"), ("2026-07", "m.a")])}
    # next period 2026-09 ends 2026-09-30; + 30 days = 2026-10-30
    on_due = status(tables, "2026-10-30")["m.a"]
    assert (on_due.state, on_due.due, on_due.days_overdue) == ("current", "2026-10-30", 0)
    late = status(tables, "2026-11-04")["m.a"]
    assert (late.state, late.days_overdue, late.latest) == ("overdue", 5, "2026-08")


def test_ended_and_unchecked():
    tables = {"monthly": table([("2009-12", "m.ended"), ("2026-01", "m.unknown")])}
    got = status(tables, "2026-10-24")
    assert got["m.ended"].state == "ended" and got["m.ended"].reason == "superseded"
    assert got["m.unknown"].state == "unchecked"


def test_acknowledged_needs_matching_latest_period():
    tables = {"monthly": table([("2026-01", "m.a")])}
    ack = {"series": "m.a", "check": "overdue", "periods": ["2026-01"], "reason": "r", "reviewer": "x",
           "date": "2026-10-24"}
    got = status(tables, "2026-10-24", acks=[ack])["m.a"]
    assert (got.state, got.ack_index, got.reason) == ("acknowledged", 0, "r")
    wrong = dict(ack, periods=["2025-12"])
    got = status(tables, "2026-10-24", acks=[wrong])["m.a"]
    assert (got.state, got.ack_index) == ("overdue", None)


def test_expired_overdue_acknowledgement_no_longer_applies():
    """Past review_by, an overdue series is overdue again."""
    tables = {"monthly": table([("2026-01", "m.a")])}
    ack = {"series": "m.a", "check": "overdue", "periods": ["2026-01"], "reason": "r", "reviewer": "x",
           "date": "2026-01-24", "review_by": "2026-10-23"}
    got = status(tables, "2026-10-24", acks=[ack])["m.a"]
    assert (got.state, got.ack_index) == ("overdue", 0)
    got = status(tables, "2026-10-23", acks=[ack])["m.a"]
    assert got.state == "acknowledged"


def test_ack_periods_parsed_as_dates_still_match():
    tables = {"daily": table([("2023-12-13", "m.a")])}
    ack = yaml.safe_load("series: m.a\ncheck: overdue\nperiods: [2023-12-13]\nreason: r\nreviewer: x\ndate: 2026-10-24")
    got = status(tables, "2026-10-24", acks=[ack], production={"daily"})["m.a"]
    assert got.state == "acknowledged"


def test_seed_snapshots_are_ignored():
    tables = {"monthly": table([("2026-01", "m.a")]), "monthly_seed": table([("2020-01", "m.a")])}
    got = validate.freshness_status(tables, SCHEDULE, [], "2026-10-24", {"monthly"})
    assert [st.dataset for st in got] == ["monthly"]


def test_deterministic():
    tables = {"monthly": table([("2026-01", "m.a"), ("2009-12", "m.ended")])}
    a = validate.freshness_status(tables, SCHEDULE, [], "2026-10-24", {"monthly"})
    b = validate.freshness_status(tables, SCHEDULE, [], "2026-10-24", {"monthly"})
    assert a == b


def test_real_data_counts(garden_tables):
    """Both exchange-rate series come from current sources, so nothing is overdue."""
    sched = validate.load_update_schedule()
    got = validate.freshness_status(garden_tables, sched, [], "2026-10-24", set(garden_tables))
    states = pd.Series([st.state for st in got]).value_counts().to_dict()
    assert states == {"current": 55, "ended": 7}


# ---------------------------------------------------------------------- command line


@pytest.fixture(scope="module")
def default_run():
    return run_gate("--as-of", "2026-10-28")


def test_cli_prints_freshness_and_keeps_baseline(default_run):
    out = default_run.stdout.splitlines()
    assert default_run.returncode == 0
    assert FRESHNESS_LINE in out
    assert not any(line.startswith("    [OVERDUE]") for line in out)
    assert sum(line.startswith("    [ENDED] prices_monthly/") for line in out) == 6
    assert out[-1] == BASELINE_LINE


def test_cli_is_deterministic(default_run):
    assert run_gate("--as-of", "2026-10-28").stdout == default_run.stdout


def test_ci_gate_ignores_freshness():
    assert run_gate("--release", "--as-of", "2026-10-28").returncode == 0


def test_release_check_passes_on_current_data():
    assert run_gate("--release", "--freshness", "--as-of", "2026-10-28").returncode == 0


# The overdue scenarios use the published data with two exchange-rate feeds cut short, as if they
# had stopped updating: fx.official after 2023-12-13 and parallel_rate_iraq after 2023-08-03.
# Every other table is unchanged.
STALE_FEED_BASELINE_LINE = (
    "ALL CHECKS PASSED: 14 dataset(s) verified (22,992 total observations, 0 review notice(s))."
)
LAST_DAY = {"fx.official": "2023-12-13", "parallel_rate_iraq": "2023-08-03"}


@pytest.fixture(scope="module")
def stale_feed_files(tmp_path_factory):
    import shutil

    from conftest import GARDEN_DIR, SEEDS_DIR

    folder = tmp_path_factory.mktemp("stale_feed")
    for path in GARDEN_DIR.glob("*.parquet"):
        shutil.copy2(path, folder / path.name)
    exchange = pd.read_parquet(GARDEN_DIR / "exchange_rates_daily.parquet")
    last = exchange["series_id"].map(LAST_DAY)
    exchange[last.isna() | (exchange["date"] <= last)].to_parquet(folder / "exchange_rates_daily.parquet", index=False)
    return sorted(folder.glob("*.parquet")) + sorted(SEEDS_DIR.glob("*.parquet"))


def _vintage_acks(files):
    """
    Acknowledgements are tied to values, and the cut-short exchange table differs from the published
    one, so the committed ones do not cover it. Draft its own, as a maintainer would.
    """
    drafts = validate.propose_acknowledgements(validate.collect_warnings(list(files)), [],
                                               pd.Timestamp("2026-10-28"))
    for d in drafts:
        d.update(reason="stale feed scenario", reviewer="tester", date="2026-10-24", review_by="2027-10-24")
    return drafts


def _write_acks(folder, entries):
    path = Path(folder) / "acks.yaml"
    path.write_text(yaml.safe_dump({"acknowledged": entries}), encoding="utf-8")
    return path


def gate_stale_feed(files, capsys, acks_path=None):
    if acks_path is None:
        import tempfile
        acks_path = _write_acks(tempfile.mkdtemp(), _vintage_acks(files))
    acks = validate.load_acknowledgements(acks_path)
    code = validate.run_gatekeeper(files, acks, release=True, freshness=True,
                                   as_of=pd.Timestamp("2026-10-28"), all_datasets=True)
    return code, capsys.readouterr().out


def test_release_check_fails_on_overdue(stale_feed_files, capsys):
    code, out = gate_stale_feed(stale_feed_files, capsys)
    assert code == 1
    lines = out.splitlines()
    assert ("    [OVERDUE] exchange_rates_daily/fx.official: latest 2023-12-13, next due 2023-12-28, "
            "1035 days overdue") in lines
    assert ("    [OVERDUE] exchange_rates_daily/parallel_rate_iraq: latest 2023-08-03, next due 2023-08-11, "
            "1174 days overdue") in lines
    assert lines[-1] == STALE_FEED_BASELINE_LINE


def _acks(tmp_path, files, fx_period="2023-12-13"):
    entries = _vintage_acks(files) + [
        {"dataset": "exchange_rates_daily", "series": "fx.official", "check": "overdue", "periods": [fx_period],
         "reason": "test reason fx", "reviewer": "tester", "date": "2026-10-24", "review_by": "2027-10-24"},
        {"series": "parallel_rate_iraq", "check": "overdue", "periods": ["2023-08-03"],
         "reason": "test reason parallel", "reviewer": "tester", "date": "2026-10-24", "review_by": "2027-10-24"},
    ]
    return _write_acks(tmp_path, entries)


def test_acknowledged_overdue_passes_release_check(stale_feed_files, tmp_path, capsys):
    code, out = gate_stale_feed(stale_feed_files, capsys, _acks(tmp_path, stale_feed_files))
    assert code == 0, out[-2000:]
    lines = [l for l in out.splitlines() if l.startswith("    [ACKNOWLEDGED] exchange_rates_daily/")]
    assert len(lines) == 2 and "test reason fx" in "".join(lines)
    assert "[FRESHNESS] as of 2026-10-28: 53 current, 0 overdue, 2 acknowledged, 7 ended, 0 unchecked" in out


def test_stale_overdue_ack_fails(stale_feed_files, tmp_path, capsys):
    code, out = gate_stale_feed(stale_feed_files, capsys, _acks(tmp_path, stale_feed_files, fx_period="2023-12-12"))
    assert code == 1
    assert "[STALE] fx.official (2023-12-12)" in out


def test_invalid_as_of_is_a_usage_error():
    proc = run_gate("--as-of", "2026-13-01")
    assert proc.returncode == 2


def test_file_run_judges_only_production_tables(tmp_path, garden_tables):
    path = write_tmp_parquet(garden_tables["money_banking_monthly"], tmp_path, "money_banking_monthly")
    proc = run_gate(path, "--as-of", "2026-10-28")
    assert proc.returncode == 0
    assert "[FRESHNESS] as of 2026-10-28: 10 current, 0 overdue, 0 acknowledged, 0 ended, 0 unchecked" in proc.stdout
    seed = write_tmp_parquet(garden_tables["oil_monthly"], tmp_path, "opec_momr_historical")
    assert "[FRESHNESS]" not in run_gate(seed, "--as-of", "2026-10-28").stdout
