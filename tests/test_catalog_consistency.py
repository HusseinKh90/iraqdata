"""
tests.test_catalog_consistency
==============================
The series catalog agrees with the data and exists once.
"""

import subprocess
import sys
import zipfile

import pandas as pd
import pytest

import catalog_check
from catalog_check import Discrepancy, check
from conftest import GARDEN_DIR, REPO_ROOT, make_rows, write_catalog

CATALOG = REPO_ROOT / "src" / "iraqdata" / "series_catalog.yaml"
HISTORY_DIR = REPO_ROOT / "pipeline" / "data" / "history"
OLD_PATH = "pipeline/metadata/series_catalog.yaml"


def _entry(sid="money.m2", start="2004-01", freq="monthly", unit="BILLION_IQD", origin=None, **extra):
    entry = {"series_id": sid, "frequency": freq, "unit": unit, "start_date": start,
             "origin": origin if origin is not None else [{"from": start, "to": "open", "class": "observed"}]}
    entry.update(extra)
    return entry


def _rules(found, sid="money.m2"):
    return sorted({d.rule for d in found if d.series_id == sid})


TABLE_OF = {"money.m2": "money", "fx.official": "fx", "gdp.real": "gdp", "aid.old": "aid"}


# =====================================================================
# One catalog
# =====================================================================

def _git(*args):
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8")


def test_single_catalog_file():
    tracked = _git("ls-files", "*series_catalog.yaml").stdout.split()
    assert tracked == ["src/iraqdata/series_catalog.yaml"]


def test_no_reference_to_old_catalog_path():
    """Nothing in the code, tests, docs or workflows may name the catalog's old location."""
    tracked = _git("ls-files", "pipeline", "src", "tests", "docs", ".github", "README.md").stdout.split()
    hits = []
    for name in tracked:
        path = REPO_ROOT / name
        if name == "tests/test_catalog_consistency.py" or path.suffix not in {".py", ".md", ".yml", ".yaml", ".toml", ".txt"}:
            continue
        if path.is_file() and OLD_PATH in path.read_text(encoding="utf-8", errors="replace"):
            hits.append(name)
    assert hits == []


def test_catalog_resolves_without_repo(monkeypatch, tmp_path):
    from iraqdata import catalog

    monkeypatch.delenv("IRAQDATA_CATALOG_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    assert catalog._resolve_catalog_path() == CATALOG


def test_env_override(monkeypatch, tmp_path):
    from iraqdata import catalog

    path = write_catalog(tmp_path / "c.yaml", [_entry()])
    monkeypatch.setenv("IRAQDATA_CATALOG_PATH", str(path))
    assert catalog._resolve_catalog_path() == path


def test_no_monorepo_fallback(monkeypatch):
    from iraqdata import catalog

    monkeypatch.delenv("IRAQDATA_CATALOG_PATH", raising=False)
    real_is_file = type(CATALOG).is_file
    monkeypatch.setattr(type(CATALOG), "is_file", lambda self: False if self.name == "series_catalog.yaml"
                        else real_is_file(self))
    with pytest.raises(FileNotFoundError):
        catalog._resolve_catalog_path()


@pytest.mark.slow
def test_wheel_contains_catalog(tmp_path):
    result = subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "-w", str(tmp_path), str(REPO_ROOT)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-2000:]
    wheel = next(tmp_path.glob("iraqdata-*.whl"))
    with zipfile.ZipFile(wheel) as z:
        assert z.read("iraqdata/series_catalog.yaml") == CATALOG.read_bytes()


# =====================================================================
# The rules, on fixtures
# =====================================================================

def test_clean_fixture_has_no_discrepancies():
    tables = {"money": make_rows("money.m2", ["2004-01", "2004-02"])}
    assert check([_entry()], tables, history={}, table_of=TABLE_OF) == []


def test_start_ignores_leading_missing_rows():
    tables = {"money": make_rows("money.m2", ["2003-12", "2004-01"], values=[None, 1.0])}
    assert check([_entry()], tables, history={}, table_of=TABLE_OF) == []
    found = check([_entry(start="2003-12")], tables, history={}, table_of=TABLE_OF)
    assert Discrepancy("start", "money.m2", "start_date", "2003-12", "2004-01",
                       "set `start_date: 2004-01` and origin[0].from") in found


@pytest.mark.parametrize("start, freq, dates", [
    (2004, "annual", ["2004", "2005"]),
    ("2004", "annual", ["2004"]),
    (pd.Timestamp("2004-01-06").date(), "daily", ["2004-01-06"]),
])
def test_date_forms_normalise(start, freq, dates):
    sid = {"annual": "gdp.real", "daily": "fx.official"}[freq]
    table = TABLE_OF[sid]
    tables = {table: make_rows(sid, dates, unit="X")}
    assert check([_entry(sid, start, freq, unit="X")], tables, history={}, table_of=TABLE_OF) == []


def test_daily_start_is_first_day_with_a_value():
    tables = {"fx": make_rows("fx.official", ["2004-01-06", "2004-01-07"], unit="IQD_PER_USD")}
    found = check([_entry("fx.official", "2004-01-01", "daily", "IQD_PER_USD")], tables, history={}, table_of=TABLE_OF)
    assert [(d.rule, d.data_value) for d in found] == [("start", "2004-01-06")]


def test_unit_mismatch_and_two_units():
    tables = {"money": make_rows("money.m2", ["2004-01"], unit="MILLION_IQD")}
    assert _rules(check([_entry()], tables, history={}, table_of=TABLE_OF)) == ["unit"]
    two = pd.concat([make_rows("money.m2", ["2004-01"]), make_rows("money.m2", ["2004-02"], unit="MILLION_IQD")])
    found = check([_entry()], {"money": two}, history={}, table_of=TABLE_OF)
    assert [d.hint for d in found if d.rule == "unit"] == ["the rows carry more than one unit"]


def test_frequency_mismatch():
    tables = {"money": make_rows("money.m2", ["2004-01", "2004-02"])}
    found = check([_entry(freq="quarterly")], tables, history={}, table_of=TABLE_OF)
    assert "frequency" in _rules(found)


def test_table_mismatch():
    tables = {"other": make_rows("money.m2", ["2004-01"])}
    assert _rules(check([_entry()], tables, history={}, table_of=TABLE_OF)) == ["table"]


def test_coverage_both_ways():
    tables = {"money": make_rows("money.m2", ["2004-01"]), "fx": make_rows("fx.official", ["2004-01-01"])}
    found = check([_entry(), _entry("gdp.real", "2004", "annual")], tables, history={}, table_of=TABLE_OF)
    assert ("coverage", "fx.official", "series_id") in [(d.rule, d.series_id, d.field) for d in found]
    assert ("coverage", "gdp.real", "rows") in [(d.rule, d.series_id, d.field) for d in found]


def _withdrawn(origin=None):
    origin = origin or [{"from": "2004", "to": "2005", "class": "observed"}]
    return _entry("aid.old", "2004", "annual", "MILLION_USD", status="withdrawn", withdrawn_in="data-2030-01",
                  origin=origin)


def test_withdrawn_with_rows_fails():
    tables = {"aid": make_rows("aid.old", ["2004", "2005"], unit="MILLION_USD")}
    assert "withdrawn" in _rules(check([_withdrawn()], tables, history={}, table_of=TABLE_OF), "aid.old")


def test_withdrawn_start_is_checked_against_history():
    history = {"aid": make_rows("aid.old", ["2005", "2006"], unit="MILLION_USD")}
    found = check([_withdrawn()], {"money": make_rows("money.m2", ["2004-01"])}, history=history,
                  table_of=TABLE_OF)
    # money.m2 has no entry here, which is a coverage finding; the withdrawn series is wrong too
    assert any(d.series_id == "aid.old" and d.rule == "start" and d.data_value == "2005" for d in found)
    clean = {"aid": make_rows("aid.old", ["2004", "2005"], unit="MILLION_USD")}
    assert _rules(check([_withdrawn(), _entry()], {"money": make_rows("money.m2", ["2004-01"])},
                        history=clean, table_of=TABLE_OF), "aid.old") == []


def test_withdrawn_without_history_values_fails():
    history = {"aid": make_rows("aid.other", ["2004"], unit="MILLION_USD")}  # the table's history, not this series
    found = check([_withdrawn()], {}, history=history, table_of=TABLE_OF)
    assert [(d.rule, d.field) for d in found] == [("withdrawn", "history")]


def test_withdrawn_is_skipped_when_its_table_has_no_history():
    info = []
    assert check([_withdrawn()], {}, history={}, table_of=TABLE_OF, info=info) == []
    assert any("aid.old" in line for line in info)


def test_missing_history_skips_withdrawn_start_with_info():
    info = []
    found = check([_withdrawn()], {}, history=None, table_of=TABLE_OF, info=info)
    assert found == []
    assert any("history" in line for line in info)


@pytest.mark.parametrize("origin, field", [
    ([{"from": "2004-01", "to": "2004-03"}, {"from": "2004-05", "to": "open"}], "origin[1].from"),   # gap
    ([{"from": "2004-01", "to": "2004-03"}, {"from": "2004-03", "to": "open"}], "origin[1].from"),   # overlap
    ([{"from": "2004-01", "to": "open"}, {"from": "2004-02", "to": "open"}], "origin[0].to"),        # open, not last
    ([{"from": "2004-02", "to": "open"}], "origin[0].from"),                                         # wrong start
    ([{"from": "2004-01", "to": "2004-01"}], "origin[0].to"),                                        # ends too early
])
def test_origin_rules(origin, field):
    tables = {"money": make_rows("money.m2", ["2004-01", "2004-02"])}
    found = check([_entry(origin=origin)], tables, history={}, table_of=TABLE_OF)
    assert field in [d.field for d in found if d.rule == "origin"]


def test_withdrawn_last_segment_must_be_closed():
    history = {"aid": make_rows("aid.old", ["2004"], unit="MILLION_USD")}
    entry = _withdrawn(origin=[{"from": "2004", "to": "open", "class": "observed"}])
    found = check([entry], {}, history=history, table_of=TABLE_OF)
    assert [d.field for d in found if d.rule == "origin"] == ["origin[0].to"]


def test_output_is_sorted():
    tables = {"money": make_rows("money.m2", ["2004-01"], unit="Y"), "fx": make_rows("fx.official", ["x"], unit="Y")}
    entries = [_entry("fx.official", "2004-01-01", "daily", "Z"), _entry(unit="Z")]
    found = check(entries, tables, history={}, table_of=TABLE_OF)
    assert found == sorted(found, key=lambda d: (d.series_id, d.rule, d.field))


# =====================================================================
# The source rule
# =====================================================================

H_EIA, H_OPEC = "a" * 64, "b" * 64
MANIFEST = {"files": [{"path": "pipeline/raw/eia/INTL.zip", "sha256": H_EIA, "source_ref": "eia_intl"},
                      {"path": "pipeline/raw/opec/m.csv", "sha256": H_OPEC, "source_ref": "opec_momr"}],
            "input_groups": [{"id": "c" * 16, "name": "both", "members": ["pipeline/raw/eia/INTL.zip"]}]}


def _sourced(ref, cls="observed", **extra):
    return _entry(origin=[{"from": "2004-01", "to": "open", "class": cls, "source_ref": ref, **extra}])


def test_source_rule_on_fixtures():
    tables = {"money": make_rows("money.m2", ["2004-01", "2004-02"], source_hash=H_EIA)}
    assert check([_sourced("eia_intl")], tables, history={}, table_of=TABLE_OF, manifest=MANIFEST) == []
    found = check([_sourced("opec_momr")], tables, history={}, table_of=TABLE_OF, manifest=MANIFEST)
    assert [(d.rule, d.catalog_value, d.data_value) for d in found] == [("source", "opec_momr", "eia_intl")]
    # an input group resolves to its members' sources
    grouped = {"money": make_rows("money.m2", ["2004-01"], source_hash="c" * 16)}
    assert check([_sourced("eia_intl")], grouped, history={}, table_of=TABLE_OF, manifest=MANIFEST) == []


def test_source_rule_skips_derived_and_counts_unresolved():
    tables = {"money": make_rows("money.m2", ["2004-01"], source_hash=H_OPEC)}
    derived = _entry(origin=[{"from": "2004-01", "to": "open", "class": "derived", "inputs": ["x"]}])
    assert check([derived], tables, history={}, table_of=TABLE_OF, manifest=MANIFEST) == []
    info = []
    unknown = {"money": make_rows("money.m2", ["2004-01"], source_hash="f" * 64)}
    assert check([_sourced("eia_intl")], unknown, history={}, table_of=TABLE_OF, manifest=MANIFEST, info=info) == []
    assert any("unresolved" in line for line in info)


def test_secondary_production_is_checked_against_its_raw_file(real):
    """The catalog names the EIA bulk file, not OPEC MOMR, as the source of the EIA rows."""
    entry, tables, history = _alone(real, "crude_production_secondary")
    manifest, corrections = catalog_check.load_provenance()
    assert check([entry], tables, history, manifest=manifest, corrections=corrections) == []
    entry["origin"] = [dict(entry["origin"][0], source_ref="opec_momr")]
    found = check([entry], tables, history, manifest=manifest, corrections=corrections)
    assert [(d.rule, d.data_value) for d in found] == [("source", "eia_intl")]


# =====================================================================
# The real catalog and data
# =====================================================================

@pytest.fixture(scope="module")
def real():
    catalog = catalog_check.load_catalog()
    history = catalog_check.load_tables(HISTORY_DIR) if HISTORY_DIR.is_dir() else {}
    return catalog, catalog_check.load_tables(GARDEN_DIR), history


def test_real_catalog_matches_garden(real):
    catalog, tables, history = real
    manifest, corrections = catalog_check.load_provenance()
    found = check(catalog, tables, history, manifest=manifest, corrections=corrections)
    assert [catalog_check.format_line(d) for d in found] == []


def _alone(real, sid):
    """The catalog entry for `sid` and only that series' rows, so one injection is checked quickly."""
    catalog, tables, history = real
    entry = dict(next(e for e in catalog if e["series_id"] == sid))
    only = {t: df[df["series_id"] == sid] for t, df in tables.items()}
    past = {t: df[df["series_id"] == sid] for t, df in history.items()}
    return entry, {t: df for t, df in only.items() if len(df)}, {t: df for t, df in past.items() if len(df)}


SERIES = [e["series_id"] for e in catalog_check.load_catalog()]
OTHER_FREQ = {"daily": "monthly", "monthly": "quarterly", "quarterly": "annual", "annual": "daily"}


@pytest.mark.parametrize("field", ["start_date", "unit", "frequency"])
@pytest.mark.parametrize("sid", SERIES)
def test_injected_errors_are_caught(real, sid, field):
    entry, tables, history = _alone(real, sid)
    freq = entry["frequency"]
    if field == "start_date":
        entry["start_date"] = catalog_check.next_period(catalog_check.normalize_period(entry["start_date"], freq), freq)
        rule = "start"
    elif field == "unit":
        entry["unit"] = "WRONG_UNIT"
        rule = "unit"
    else:
        entry["frequency"] = OTHER_FREQ[freq]
        rule = "frequency"
    found = check([entry], tables, history)
    assert rule in _rules(found, sid), [catalog_check.format_line(d) for d in found]


def _run_cli(*args):
    return subprocess.run([sys.executable, "pipeline/catalog_check.py", *map(str, args)], cwd=REPO_ROOT,
                          capture_output=True, text=True, encoding="utf-8")


def test_cli_clean_and_exit_codes(tmp_path):
    clean = _run_cli()
    assert clean.returncode == 0, clean.stdout[-3000:]
    assert clean.stdout.strip().splitlines()[-1].startswith("Catalog check: 0 discrepancies in ")

    text = CATALOG.read_text(encoding="utf-8").replace("start_date: 2013-Q1", "start_date: 2004-Q1", 1)
    bad = tmp_path / "catalog.yaml"
    bad.write_text(text, encoding="utf-8")
    dirty = _run_cli("--catalog", bad)
    assert dirty.returncode == 1
    assert any(line.startswith("[CATALOG] ") and " start: " in line for line in dirty.stdout.splitlines())

    assert _run_cli("--tables", tmp_path / "no_such_dir").returncode == 2
