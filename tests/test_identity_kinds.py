"""
Identity checks that cannot fail are not counted.

An identity period is definitional when one member's catalog origin is `derived` from the other
members. It is reported apart from the checked count, and derived series with no independent
check are listed. Tests whose name contains "production" read the production garden tables.
"""

import re

import pandas as pd

import flags
import validate
from conftest import GARDEN_DIR, run_validate, set_value, write_tmp_parquet

IDENTITY_INDEPENDENT = re.compile(r"^\[IDENTITY\] (.+) \(independent\): checked (\d+), skipped (\d+)(; .+)?$")
IDENTITY_DEFINITIONAL = re.compile(r"^\[IDENTITY\] (.+) \(definitional: (\S+)\): (\d+) period\(s\), not a check$")
DERIVED = re.compile(r"^\[DERIVED\] (\S+): no independent identity check$")


def _bis():
    return pd.read_parquet(GARDEN_DIR / "bis_lbs_quarterly.parquet")


def _rule(coverage, name):
    return next(c for c in coverage if c[0] == name)


def test_marking_a_member_derived_makes_its_rule_definitional():
    """Only the catalog changes."""
    df = _bis()
    catalog = {k: dict(v) for k, v in flags.load_catalog().items()}
    assert _rule(validate.identity_coverage(df, catalog), "BIS sector liabilities")[1] > 0
    entry = catalog["bis.lbs.liabilities_banks"]
    entry["origin"] = [{"from": "2004-Q1", "to": "open", "class": "derived",
                        "inputs": ["bis.lbs.liabilities_total", "bis.lbs.liabilities_nonbank"]}]
    assert _rule(validate.identity_coverage(df, catalog), "BIS sector liabilities")[1] == 0
    definitional = {(r, s) for r, s, n in validate.definitional_coverage(df, catalog) if n > 0}
    assert ("BIS sector liabilities", "bis.lbs.liabilities_banks") in definitional


def test_inputs_outside_the_group_do_not_make_it_definitional():
    df = _bis()
    catalog = {k: dict(v) for k, v in flags.load_catalog().items()}
    catalog["bis.lbs.liabilities_banks"]["origin"] = [
        {"from": "2004-Q1", "to": "open", "class": "derived", "inputs": ["money.m2"]}]
    assert _rule(validate.identity_coverage(df, catalog), "BIS sector liabilities")[1] > 0


def test_independent_identity_still_fails_on_a_break(tmp_path):
    """An independent identity still fails when a value is broken."""
    df = pd.read_parquet(GARDEN_DIR / "bop_trade_quarterly.parquet")
    date = sorted(df.loc[df["series_id"] == "bop.trade_balance", "date"])[5]
    broken = set_value(df, date, "bop.trade_balance", lambda v: v + 10_000.0)
    errors, _ = validate.validate_tier2_details(broken, "bop")
    assert any("trade" in e.lower() for e in errors)


def test_definitional_rules_on_production_data():
    """The three rules that hold by definition add nothing to the checked count."""
    seen = {}
    for path in sorted(GARDEN_DIR.glob("*.parquet")):
        df = pd.read_parquet(path)
        for rule, sid, n in validate.definitional_coverage(df):
            seen[rule] = sid
        for rule, checked, _ in validate.identity_coverage(df):
            assert rule != "OECD net ODA"
            if rule in ("Nominal GDP", "Real GDP", "BIS net position"):
                assert checked == 0, rule
    assert seen == {"Nominal GDP": "gdp.nominal_nonoil", "Real GDP": "gdp.real_nonoil",
                    "BIS net position": "bis.lbs.net_position"}


def test_uncovered_derived_series_on_production_data():
    """On the published data, the derived series with no independent identity are exactly these."""
    found = set()
    for path in sorted(GARDEN_DIR.glob("*.parquet")):
        found |= set(validate.uncovered_derived(pd.read_parquet(path)))
    assert sorted(found) == ["bis.lbs.net_position", "cpi_core", "cpi_headline",
                             "gdp.nominal_nonoil", "gdp.real_nonoil"]


def test_report_lines_match_the_contract(tmp_path):
    path = write_tmp_parquet(_bis(), tmp_path, "bis_lbs_quarterly")
    result = run_validate(path)
    assert result.returncode == 0, result.stdout + result.stderr
    lines = [line.strip() for line in result.stdout.splitlines()]
    identity = [line for line in lines if line.startswith("[IDENTITY]")]
    assert identity and all(IDENTITY_INDEPENDENT.match(x) or IDENTITY_DEFINITIONAL.match(x) for x in identity)
    assert any(IDENTITY_DEFINITIONAL.match(x) and "bis.lbs.net_position" in x for x in identity)
    assert [DERIVED.match(x).group(1) for x in lines if x.startswith("[DERIVED]")] == ["bis.lbs.net_position"]
