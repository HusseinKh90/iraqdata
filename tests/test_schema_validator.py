"""
tests.test_schema_validator
===========================
Unit tests for the canonical observation schema validator and quality gatekeeper.

Can be run directly via:
    python tests/test_schema_validator.py
Or via pytest:
    pytest tests/
"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np

# Add src and pipeline directories to sys.path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "src"))
sys.path.insert(0, str(repo_root / "pipeline"))

from iraqdata.schema import CANONICAL_COLUMNS, Observation, validate_dataframe
from validate import validate_tier2_domain


def test_valid_observation():
    """Confirms that a clean observation passes validation with zero errors."""
    obs = Observation(
        date="2024-07",
        series_id="cbi.money.m2",
        value=171404.0,
        unit="BILLION_IQD",
        status_flag="A",
        realtime_start="2024-09-15",
        source_hash="a1b2c3d4"
    )
    errors = obs.validate()
    assert len(errors) == 0, f"Expected 0 errors, got: {errors}"


def test_invalid_date_format():
    """Confirms that non-ISO date formats are caught and rejected."""
    obs = Observation(
        date="July 2024",  # Illegal text month format
        series_id="cbi.money.m2",
        value=171404.0,
        unit="BILLION_IQD",
    )
    errors = obs.validate()
    assert len(errors) > 0
    assert any("Invalid date format" in err for err in errors)


def test_invalid_series_id_format():
    """Confirms that uppercase or space-containing series IDs are rejected."""
    obs = Observation(
        date="2024-07",
        series_id="CBI Money M2",  # Illegal uppercase and spaces
        value=171404.0,
        unit="BILLION_IQD",
    )
    errors = obs.validate()
    assert len(errors) > 0
    assert any("Invalid series_id" in err for err in errors)


def test_validate_dataframe_clean():
    """Confirms that a clean table passes Tier-1 validation."""
    data = {
        "date": ["2024-01", "2024-02", "2024-03"],
        "series_id": ["cbi.money.m1", "cbi.money.m1", "cbi.money.m1"],
        "value": [110000.0, 112000.0, 115000.0],
        "unit": ["BILLION_IQD", "BILLION_IQD", "BILLION_IQD"],
        "status_flag": ["A", "A", "P"],
        "realtime_start": ["2024-04-01", "2024-04-01", "2024-04-01"],
        "source_hash": ["hash1", "hash1", "hash1"],
    }
    df = pd.DataFrame(data)
    errors = validate_dataframe(df)
    assert len(errors) == 0, f"Expected 0 errors, got: {errors}"


def test_validate_dataframe_catches_duplicates():
    """Confirms that duplicate (date, series_id) observations are detected."""
    data = {
        "date": ["2024-01", "2024-01"],  # Duplicate date for the same series
        "series_id": ["cbi.money.m1", "cbi.money.m1"],
        "value": [110000.0, 111000.0],
        "unit": ["BILLION_IQD", "BILLION_IQD"],
        "status_flag": ["A", "A"],
        "realtime_start": ["2024-04-01", "2024-04-01"],
        "source_hash": ["hash1", "hash1"],
    }
    df = pd.DataFrame(data)
    errors = validate_dataframe(df)
    assert any("duplicate" in err.lower() for err in errors)


def test_validate_dataframe_catches_missing_columns():
    """Confirms that missing canonical columns are detected."""
    data = {
        "date": ["2024-01"],
        "series_id": ["cbi.money.m1"],
        "value": [110000.0],
        # Missing unit, status_flag, realtime_start, source_hash
    }
    df = pd.DataFrame(data)
    errors = validate_dataframe(df)
    assert any("Column layout mismatch" in err for err in errors)


def test_tier2_catches_budget_column_swap():
    """Confirms that Tier-2 catches budget discrepancies (Current + Investment != Total)."""
    data = {
        "date": ["2012", "2012", "2012"],
        "series_id": [
            "cbi_bulletin.budget_revenue_total",
            "cbi_bulletin.budget_revenue_current",
            "cbi_bulletin.budget_revenue_investment"
        ],
        "value": [119466403.0, 100.0, 200.0],  # 100 + 200 != 119466403
        "unit": ["MILLION_IQD", "MILLION_IQD", "MILLION_IQD"],
        "status_flag": ["A", "A", "A"],
        "realtime_start": ["2024-01-01", "2024-01-01", "2024-01-01"],
        "source_hash": ["hash1", "hash1", "hash1"],
    }
    df = pd.DataFrame(data)
    errors, warnings = validate_tier2_domain(df)
    assert any("Budget Accounting Discrepancy" in err for err in errors)


def test_tier2_catches_gdp_identity():
    """Confirms that Tier-2 catches GDP discrepancies (Real Oil + Real Non-Oil != Headline Real)."""
    data = {
        "date": ["2024-Q1", "2024-Q1", "2024-Q1"],
        "series_id": [
            "cosit.gdp_real",
            "cosit.gdp_real_oil",
            "cosit.gdp_real_nonoil"
        ],
        "value": [50000000.0, 30000000.0, 15000000.0],  # 30M + 15M = 45M != 50M
        "unit": ["MILLION_IQD", "MILLION_IQD", "MILLION_IQD"],
        "status_flag": ["A", "A", "A"],
        "realtime_start": ["2024-06-01", "2024-06-01", "2024-06-01"],
        "source_hash": ["hash1", "hash1", "hash1"],
    }
    df = pd.DataFrame(data)
    errors, warnings = validate_tier2_domain(df)
    assert any("GDP Accounting Discrepancy" in err for err in errors)


def test_tier2_plausibility_warning_notice():
    """Confirms that values outside default bounds emit non-fatal review notices."""
    data = {
        "date": ["2024-05-15"],
        "series_id": ["oil_price_brent"],
        "value": [310.0],  # Exceeds $250 default envelope
        "unit": ["USD_PER_BBL"],
        "status_flag": ["A"],
        "realtime_start": ["2024-05-16"],
        "source_hash": ["hash1"],
    }
    df = pd.DataFrame(data)
    errors, warnings = validate_tier2_domain(df)
    assert len(errors) == 0  # Does NOT trigger fatal error
    assert any("Plausibility Notice" in w for w in warnings)  # Emits review notice


def test_tier2_catches_bis_identity():
    """Confirms that BIS net position discrepancy is detected."""
    data = {
        "date": ["2024-Q1", "2024-Q1", "2024-Q1"],
        "series_id": ["bis.lbs.liabilities_total", "bis.lbs.claims_total", "bis.lbs.net_position"],
        "value": [25000.0, 3000.0, 20000.0],  # Should be 22000, not 20000
        "unit": ["MILLION_USD"] * 3,
        "status_flag": ["A"] * 3,
        "realtime_start": ["2026-10-22"] * 3,
        "source_hash": ["hash"] * 3,
    }
    df = pd.DataFrame(data)
    errors, warnings = validate_tier2_domain(df)
    assert len(errors) > 0
    assert any("BIS Net Position Discrepancy" in err for err in errors)


def test_tier2_catches_bis_sector_identity():
    """Confirms that an independent identity (BIS banks + non-banks <= total) is detected.
    """
    data = {
        "date": ["2024-Q1"] * 5,
        "series_id": ["bis.lbs.liabilities_total", "bis.lbs.claims_total", "bis.lbs.net_position",
                      "bis.lbs.liabilities_banks", "bis.lbs.liabilities_nonbank"],
        "value": [20000.0, 3000.0, 17000.0, 15000.0, 9000.0],  # 15000 + 9000 = 24000 > 20000
        "unit": ["MILLION_USD"] * 5,
        "status_flag": ["A"] * 5,
        "realtime_start": ["2026-10-22"] * 5,
        "source_hash": ["hash"] * 5,
    }
    df = pd.DataFrame(data)
    errors, warnings = validate_tier2_domain(df)
    assert len(errors) > 0
    assert any("BIS Sector Liability Discrepancy" in err for err in errors)


if __name__ == "__main__":
    print("=" * 60)
    print("Running iraqdata Schema & Quality Gatekeeper Test Suite")
    print("=" * 60)
    
    test_valid_observation()
    print("  [PASS] test_valid_observation")
    
    test_invalid_date_format()
    print("  [PASS] test_invalid_date_format")
    
    test_invalid_series_id_format()
    print("  [PASS] test_invalid_series_id_format")
    
    test_validate_dataframe_clean()
    print("  [PASS] test_validate_dataframe_clean")
    
    test_validate_dataframe_catches_duplicates()
    print("  [PASS] test_validate_dataframe_catches_duplicates")
    
    test_validate_dataframe_catches_missing_columns()
    print("  [PASS] test_validate_dataframe_catches_missing_columns")
    
    test_tier2_catches_budget_column_swap()
    print("  [PASS] test_tier2_catches_budget_column_swap")
    
    test_tier2_catches_gdp_identity()
    print("  [PASS] test_tier2_catches_gdp_identity")
    
    test_tier2_plausibility_warning_notice()
    print("  [PASS] test_tier2_plausibility_warning_notice")

    test_tier2_catches_bis_identity()
    print("  [PASS] test_tier2_catches_bis_identity")

    test_tier2_catches_bis_sector_identity()
    print("  [PASS] test_tier2_catches_bis_sector_identity")
    
    print("=" * 60)
    print("ALL 11 UNIT TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)
