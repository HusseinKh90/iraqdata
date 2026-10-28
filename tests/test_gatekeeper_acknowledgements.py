"""
tests.test_gatekeeper_acknowledgements
======================================
Tests for warning acknowledgements, --release mode,
stale acknowledgement detection, and --list-acknowledged.

Entries carry review_by and, for value checks, the acknowledged values. A test that
passes its own acknowledgements file keeps the committed entries in it, so the real events they
acknowledge stay acknowledged.
"""

import yaml
import pytest

import validate
from conftest import (
    GATE_SUMMARY,
    METADATA_DIR,
    run_validate,
    set_value,
    write_tmp_parquet,
)


SID = "crude_production_secondary"


def committed():
    data = yaml.safe_load((METADATA_DIR / "acknowledged_warnings.yaml").read_text(encoding="utf-8")) or {}
    return list(data.get("acknowledged") or [])


def write_acks(tmp_path, entries, name="acks.yaml"):
    path = tmp_path / name
    path.write_text(yaml.safe_dump({"acknowledged": committed() + entries}, allow_unicode=True), encoding="utf-8")
    return path


def entry(series, check, periods, values, reason, **extra):
    return {"series": series, "check": check, "periods": periods, "values": values, "reason": reason,
            "reviewer": "Test Reviewer", "date": "2026-10-24", "review_by": "2027-10-24", **extra}


def test_acknowledged_warning_is_reported_as_such(garden_tables, tmp_path):
    """An acknowledged jump warning is reported as [ACKNOWLEDGED], not [NOTICE], and notice count is 0."""
    df = garden_tables["oil_monthly"].copy()
    target_date = "2020-04"
    faulty_df = set_value(df, target_date, SID, lambda v: v * 0.28)
    tmp_data = write_tmp_parquet(faulty_df, tmp_path, "oil_monthly")

    # acknowledge every new warning the injection causes, with the values the gate sees
    _, before = validate.validate_tier2_details(df, "oil_monthly.parquet")
    _, after = validate.validate_tier2_details(faulty_df, "oil_monthly.parquet")
    new = [w for w in after if w.series == SID and w not in before]
    assert new and any(target_date in w.periods for w in new)
    ack_file = write_acks(tmp_path, [entry(SID, w.check, w.periods, w.values, "Test acknowledgement")
                                     for w in new])

    proc = run_validate(tmp_data, "--acknowledgements", str(ack_file))
    assert proc.returncode == 0
    assert "[ACKNOWLEDGED]" in proc.stdout
    assert "Test acknowledgement" in proc.stdout
    assert SID in proc.stdout
    assert "[NOTICE]" not in proc.stdout
    assert "0 review notice(s)" in proc.stdout


def test_unacknowledged_warning_fails_release(garden_tables, tmp_path):
    """An unacknowledged warning fails when run with --release."""
    df = garden_tables["oil_monthly"].copy()
    target_date = "2020-04"
    faulty_df = set_value(df, target_date, SID, lambda v: v * 0.28)
    tmp_data = write_tmp_parquet(faulty_df, tmp_path, "oil_monthly")

    proc = run_validate(tmp_data, "--release")
    assert proc.returncode == 1
    assert "[NOTICE]" in proc.stdout
    assert SID in proc.stdout


STALE = entry("oil_price_brent", "jump", ["1999-01"], {"1999-01": 10.0}, "Ancient non-existent jump")


def test_stale_acknowledgement_fails_release(tmp_path):
    """A stale acknowledgement fails --release when scanning all 14 datasets."""
    ack_file = write_acks(tmp_path, [STALE], "stale_acks.yaml")

    proc = run_validate("--release", "--acknowledgements", str(ack_file))
    assert proc.returncode == 1
    assert "[STALE]" in proc.stdout
    assert "Ancient non-existent jump" in proc.stdout


def test_stale_detection_only_on_all_datasets(garden_tables, tmp_path):
    """Stale checks are disabled when scanning single file arguments."""
    ack_file = write_acks(tmp_path, [STALE], "stale_acks.yaml")

    single_file = "pipeline/data/garden/oil_monthly.parquet"
    proc = run_validate(single_file, "--release", "--acknowledgements", str(ack_file))
    assert proc.returncode == 0
    assert "[STALE]" not in proc.stdout


def test_list_acknowledged_prints_markdown(tmp_path):
    """The --list-acknowledged flag prints entries as markdown bullets and exits 0."""
    ack_file = tmp_path / "acks.yaml"
    ack_file.write_text(yaml.dump({"acknowledged": [
        entry("oil_price_brent", "jump", ["2020-04"], {"2020-03": 30.0, "2020-04": 20.0}, "Test reason")]}),
        encoding="utf-8")

    proc = run_validate("--list-acknowledged", "--acknowledgements", str(ack_file))
    assert proc.returncode == 0
    assert ("- **oil_price_brent** (2020-04): Test reason (reviewed by Test Reviewer on 2026-10-24; "
            "review by 2027-10-24)") in proc.stdout


def test_committed_acknowledgements_pass_release_on_real_data():
    """Default --release run on committed data with the committed acknowledgements passes."""
    proc = run_validate("--release")
    assert proc.returncode == 0
    assert GATE_SUMMARY in proc.stdout


@pytest.mark.parametrize("bad", [
    {"check": "invalid_check_name"},
    {"reason": ""},
    {"review_by": None},
    {"values": None},
])
def test_malformed_acknowledgements_fails(tmp_path, bad):
    """A malformed acknowledgement (bad check, no reason, no review_by, no values) fails with exit 1."""
    ack = {**entry("oil_price_brent", "jump", ["2020-04"], {"2020-03": 30.0, "2020-04": 20.0}, "r"), **bad}
    ack = {k: v for k, v in ack.items() if v is not None}
    ack_file = tmp_path / "bad_acks.yaml"
    ack_file.write_text(yaml.dump({"acknowledged": [ack]}), encoding="utf-8")

    proc = run_validate("--acknowledgements", str(ack_file))
    assert proc.returncode == 1
    assert "Invalid acknowledgement" in proc.stdout
