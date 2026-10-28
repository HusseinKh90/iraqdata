"""
Release gate.

The release export runs the CI gate (validate --release) before writing anything; the gatekeeper
fails in release mode when it has no tables to check; jumps at B-flagged observations stay
informational. Every export goes to tmp_path, never to release/ or pipeline/data/.
"""

import shutil
import subprocess
import sys

import pandas as pd
import pytest

import export_release
import validate
from conftest import GARDEN_DIR, REPO_ROOT

AS_OF = pd.Timestamp("2026-10-24")


def _garden_copy(tmp_path, change=None):
    garden = tmp_path / "garden"
    shutil.copytree(GARDEN_DIR, garden)
    if change is not None:
        name, fn = change
        df = pd.read_parquet(garden / f"{name}.parquet")
        fn(df).to_parquet(garden / f"{name}.parquet", index=False)
    return garden


def _duplicate_row(df):
    return pd.concat([df, df.head(1)], ignore_index=True)


def _scale_m2(df):
    i = df.index[df["series_id"] == "money.m2"][-1]
    df.loc[i, "value"] = df.loc[i, "value"] * 1000
    return df


@pytest.fixture
def no_reference_copy(monkeypatch):
    """Record (never perform) copies made by the export, so a failing test cannot touch pipeline/data/."""
    calls = []
    monkeypatch.setattr(export_release.shutil, "copy2", lambda *a, **k: calls.append(a))
    return calls


@pytest.mark.parametrize("change", [("bop_trade_quarterly", _duplicate_row), ("money_banking_monthly", _scale_m2)],
                         ids=["tier1_duplicate_key", "unacknowledged_warning"])
def test_export_refuses_tables_that_fail_the_gate(change, tmp_path, no_reference_copy):
    garden = _garden_copy(tmp_path, change)
    out = tmp_path / "release"
    with pytest.raises(RuntimeError, match="Release gate failed"):
        export_release.export_release(tag="test", output_dir=out, garden_dir=garden,
                                      history_dir=tmp_path / "no_history", reference_copy=True)
    assert not out.exists()
    assert no_reference_copy == []


def test_export_refuses_catalog_mismatch(tmp_path, monkeypatch, no_reference_copy):
    """Series metadata that disagrees with the tables stops the export."""
    from iraqdata import catalog as cat

    bad = tmp_path / "catalog.yaml"
    source = (REPO_ROOT / "src" / "iraqdata" / "series_catalog.yaml").read_text(encoding="utf-8")
    bad.write_text(source.replace("start_date: 2013-Q1", "start_date: 2004-Q1", 1), encoding="utf-8")
    monkeypatch.setenv("IRAQDATA_CATALOG_PATH", str(bad))
    cat.get_catalog.cache_clear()
    out = tmp_path / "release"
    try:
        with pytest.raises(export_release.ReleaseGateError, match="bop.current_account start"):
            export_release.export_release(tag="test", output_dir=out, history_dir=tmp_path / "none",
                                          reference_copy=True)
    finally:
        monkeypatch.delenv("IRAQDATA_CATALOG_PATH")
        cat.get_catalog.cache_clear()
    assert not out.exists()
    assert no_reference_copy == []


def test_exported_series_carry_status(tmp_path):
    """Each series entry says whether it is active or withdrawn."""
    dp = export_release.export_release(tag="test", output_dir=tmp_path / "rel", history_dir=tmp_path / "none",
                                       reference_copy=False)
    status = {s["series_id"]: s["status"] for s in dp["seriesCatalog"]["series"]}
    assert set(status.values()) == {"active"} and status["money.m2"] == "active"

    # Terms of reuse and the scope of the licence travel with the release
    import yaml
    records = yaml.safe_load((REPO_ROOT / "pipeline" / "metadata" / "sources.yaml").read_text(encoding="utf-8"))
    ids = [s["id"] for s in dp["sources"]]
    assert ids == [r["id"] for r in records["sources"]]
    assert "Compiled and derived data" in dp["licenses"][0]["scope"]
    assert "publisher's terms" in dp["description"]
    series = {s["series_id"]: s for s in dp["seriesCatalog"]["series"]}
    for s in series.values():
        assert s["sources"] and set(s["sources"]) <= set(ids), s["series_id"]
    assert series["crude_production_secondary"]["sources"] == ["eia_intl"]
    assert series["gdp.real_nonoil"]["sources"] == ["cosit_national_accounts"]  # derived: from its inputs


def _files(folder):
    """Every file's bytes; exports are deterministic, so no field is ignored."""
    return {p.name: p.read_bytes() for p in sorted(folder.iterdir())}


def test_export_of_passing_tables_is_unchanged(tmp_path, monkeypatch):
    gated = tmp_path / "gated"
    export_release.export_release(tag="test", output_dir=gated, history_dir=tmp_path / "none",
                                  reference_copy=False)
    monkeypatch.setattr(validate, "run_gatekeeper", lambda *a, **k: 0)
    free = tmp_path / "free"
    export_release.export_release(tag="test", output_dir=free, history_dir=tmp_path / "none",
                                  reference_copy=False)
    assert _files(gated) == _files(free)


def test_empty_release_run_fails():
    acks = validate.load_acknowledgements()
    assert validate.run_gatekeeper([], acks, release=True, freshness=False, as_of=AS_OF, all_datasets=True) == 1
    assert validate.run_gatekeeper([], acks, release=False, freshness=False, as_of=AS_OF, all_datasets=True) == 0


def test_missing_file_still_fails(tmp_path, capsys):
    acks = validate.load_acknowledgements()
    code = validate.run_gatekeeper([tmp_path / "missing.parquet"], acks, release=True, freshness=False,
                                   as_of=AS_OF, all_datasets=False)
    assert code == 1
    assert "Failed to read file" in capsys.readouterr().out


def test_break_at_b_flag_stays_informational(tmp_path, capsys):
    """A jump at a B-flagged value is a [BREAK] line, never a failure."""
    df = pd.read_parquet(GARDEN_DIR / "prices_monthly.parquet")
    i = df.index[(df["series_id"] == "cpi_core") & (df["status_flag"] == "B")][0]
    df.loc[i, "value"] = df.loc[i, "value"] * 1.5  # a large jump, inside the envelope
    path = tmp_path / "prices_monthly.parquet"
    df.to_parquet(path, index=False)
    code = validate.run_gatekeeper([path], validate.load_acknowledgements(), release=True, freshness=False,
                                   as_of=AS_OF, all_datasets=False)
    out = capsys.readouterr().out
    assert "[BREAK] cpi_core 2010-01" in out  # first splice month
    assert code == 0


def test_cli_exits_1_when_the_gate_fails(tmp_path):
    out = tmp_path / "release"
    # shutil.copy2 is disabled in the child too, so even a broken gate cannot write the reference
    # copy to pipeline/data/datapackage.json
    script = (
        "import sys, runpy, shutil; shutil.copy2 = lambda *a, **k: None; "
        f"sys.path[:0] = [{str(REPO_ROOT / 'pipeline')!r}, {str(REPO_ROOT / 'src')!r}]; "
        "import validate; validate.run_gatekeeper = lambda *a, **k: 1; "
        f"sys.argv = ['export_release.py', '--tag', 'data-2026-11', '--output-dir', {str(out)!r}]; "
        f"runpy.run_path({str(REPO_ROOT / 'pipeline' / 'export_release.py')!r}, run_name='__main__')"
    )
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, cwd=REPO_ROOT)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "Release gate failed" in proc.stdout + proc.stderr
    assert not out.exists()


# ---------------------------------------------------------------------- a release is never rewritten


def test_export_refuses_a_folder_that_already_holds_files(tmp_path, no_reference_copy):
    out = tmp_path / "release"
    out.mkdir()
    (out / "datapackage.json").write_text("published", encoding="utf-8")
    with pytest.raises(export_release.ReleaseExistsError, match="never rewritten"):
        export_release.export_release(tag="data-2026-11", output_dir=out, history_dir=tmp_path / "none",
                                      reference_copy=True)
    assert [p.name for p in out.iterdir()] == ["datapackage.json"]
    assert (out / "datapackage.json").read_text(encoding="utf-8") == "published"
    assert no_reference_copy == []


def test_export_accepts_an_empty_folder(tmp_path):
    out = tmp_path / "release"
    out.mkdir()
    export_release.export_release(tag="data-2026-11", output_dir=out, history_dir=tmp_path / "none",
                                  reference_copy=False)
    assert (out / "datapackage.json").exists()


def test_the_command_line_requires_a_well_formed_tag():
    import subprocess
    import sys
    script = str(REPO_ROOT / "pipeline" / "export_release.py")
    missing = subprocess.run([sys.executable, script], capture_output=True, text=True)
    assert missing.returncode == 2 and "--tag" in missing.stderr
    wrong = subprocess.run([sys.executable, script, "--tag", "2026-11"], capture_output=True, text=True)
    assert wrong.returncode == 2 and "data-YYYY-MM" in wrong.stderr
    assert export_release.release_tag("data-2026-11") == "data-2026-11"
    with pytest.raises(Exception):
        export_release.release_tag("data-2026-13")


def test_the_published_release_cannot_be_overwritten_by_default(tmp_path):
    published = REPO_ROOT / "release" / "data-2026-10"
    if not published.is_dir():
        pytest.skip("no published release folder in this checkout")
    before = sorted(p.name for p in published.iterdir())
    with pytest.raises(export_release.ReleaseExistsError):
        export_release.export_release(tag="data-2026-10", history_dir=tmp_path / "none", reference_copy=False)
    assert sorted(p.name for p in published.iterdir()) == before
