"""
tests.test_package_basics
=========================
Unit tests for the iraqdata library: the catalog and search, the storage layer and the client.
"""

import sys
from pathlib import Path
import pytest
import pandas as pd

# Add src to sys.path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "src"))

import iraqdata.catalog as cat
import iraqdata.storage as storage
import iraqdata.client as client
import iraqdata as id
from iraqdata.schema import CANONICAL_COLUMNS


def test_catalog_loads_all_62_series():
    """Verify that the catalog loads exactly 62 series across 9 families."""
    df = cat.list_series()
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 62, f"Expected 62 series, got {len(df)}"
    expected_cols = ["series_id", "name_en", "name_ar", "category", "frequency", "unit", "start_date", "table"]
    for col in expected_cols:
        assert col in df.columns, f"Missing column '{col}' in list_series() output"


def test_catalog_tables_and_categories():
    """Verify that all 10 garden tables and categories are present and populated."""
    tables = cat.list_tables()
    assert len(tables) == 10
    expected_tables = {
        "bis_lbs_quarterly",
        "bop_trade_quarterly",
        "exchange_rates_daily",
        "fiscal_annual",
        "gdp_quarterly",
        "money_banking_monthly",
        "oecd_dac_annual",
        "oil_daily",
        "oil_monthly",
        "prices_monthly",
    }
    assert set(tables) == expected_tables

    categories = cat.list_categories()
    assert "money_banking" in categories
    assert "fiscal" in categories
    assert "oil" in categories
    assert "prices" in categories


def test_series_info_valid_and_table_mapping():
    """Verify that get_series_info returns complete metadata and mapped table without provider prefix."""
    info = cat.get_series_info("money.m2")
    assert info["series_id"] == "money.m2"
    assert info["category"] == "money_banking"
    assert info["frequency"] == "monthly"
    assert info["table"] == "money_banking_monthly"
    assert cat.get_table_for_series("money.m2") == "money_banking_monthly"


def test_alias_resolution_and_legacy_support():
    """Verify alias shortcuts and backwards-compatible legacy prefix resolution."""
    # Aliases
    assert cat.resolve_series_id("m2") == "money.m2"
    assert cat.resolve_series_id("gdp") == "gdp.nominal"
    assert cat.resolve_series_id("fiscal_balance") == "fiscal.balance"
    assert cat.resolve_series_id("cpi") == "cpi_headline"
    assert cat.resolve_series_id("official_rate") == "fx.official"

    # Legacy prefix stripping
    assert cat.resolve_series_id("cbi.money.m2") == "money.m2"
    assert cat.resolve_series_id("cbi.fiscal.balance") == "fiscal.balance"
    assert cat.resolve_series_id("cosit.gdp_nominal") == "gdp.nominal"


def test_series_info_invalid_raises_with_hint():
    """Verify that querying an unknown series raises KeyError with close-match suggestions."""
    with pytest.raises(KeyError) as exc_info:
        cat.get_series_info("money.m2_typo")
    assert "Unknown series 'money.m2_typo'" in str(exc_info.value)
    assert "Did you mean:" in str(exc_info.value)


def test_list_series_filtering():
    """Verify category and frequency filters in list_series."""
    df_fiscal = cat.list_series(category="fiscal")
    assert len(df_fiscal) == 7
    assert all(df_fiscal["category"] == "fiscal")
    assert all(df_fiscal["frequency"] == "annual")
    assert "fiscal.balance" in df_fiscal["series_id"].values

    df_daily = cat.list_series(frequency="daily")
    assert len(df_daily) == 3  # parallel_rate_iraq, fx.official, oil_price_brent
    assert set(df_daily["series_id"]) == {"parallel_rate_iraq", "fx.official", "oil_price_brent"}


def test_search_bilingual():
    """Verify case-insensitive search in English and Arabic."""
    # English search
    df_cpi = cat.search("inflation")
    assert len(df_cpi) >= 8
    assert "cpi.headline_2022" in df_cpi["series_id"].values

    # Arabic search
    df_oil = cat.search("نفط")
    assert len(df_oil) >= 4
    assert any("oil" in sid for sid in df_oil["series_id"])


# =====================================================================
# Storage and Cache Engine Tests (storage.py)
# =====================================================================

def test_storage_cache_dir_resolution():
    """Verify that get_cache_dir returns an existing directory Path."""
    cdir = storage.get_cache_dir()
    assert isinstance(cdir, Path)
    assert cdir.is_dir()


def test_storage_resolve_all_10_garden_tables():
    """Verify that all 10 garden tables resolve to existing parquet files."""
    for table_name in cat.list_tables():
        p_path = storage.resolve_table_path(table_name)
        assert p_path.is_file(), f"Failed to resolve table '{table_name}' to a valid file."
        assert p_path.name == f"{table_name}.parquet"


def test_storage_load_table_schema_and_contents():
    """Verify that load_table returns canonical DataFrame matching expected columns."""
    df = storage.load_table("fiscal_annual")
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == CANONICAL_COLUMNS
    assert len(df) == 154  # 7 series x 22 years (2004-2025)
    assert "fiscal.balance" in df["series_id"].values


def test_storage_column_subset_reading():
    """Verify that load_table with columns parameter only reads requested subset."""
    cols = ["date", "series_id", "value"]
    df = storage.load_table("oil_daily", columns=cols, use_memory_cache=False)
    assert list(df.columns) == cols
    assert len(df) == 5685


def test_storage_invalid_table_raises_value_error():
    """Verify that attempting to resolve an unknown table raises ValueError."""
    with pytest.raises(ValueError) as exc_info:
        storage.resolve_table_path("non_existent_table")
    assert "Unknown table 'non_existent_table'" in str(exc_info.value)


def test_storage_release_configuration():
    """Verify setting and getting active release tag."""
    original = storage.get_active_release()
    try:
        storage.set_release("data-2026-10")
        assert storage.get_active_release() == "data-2026-10"
    finally:
        storage.set_release(original)


# =====================================================================
# Client Query Engine Tests (client.py)
# =====================================================================

def test_client_get_series_single_wide():
    """Verify single series fetch with default wide format."""
    df = client.get_series("m2", start="2024-01", end="2024-03")
    assert isinstance(df, pd.DataFrame)
    assert df.index.name == "date"
    assert list(df.columns) == ["m2"]
    assert len(df) == 3
    assert df.loc["2024-01", "m2"] == 177251.0


def test_client_get_series_multi_wide_alignment():
    """Verify multi-series retrieval with aligned date index."""
    df = client.get_series(["official_rate", "parallel_rate"], start="2023-01-04", end="2023-01-05")
    assert list(df.columns) == ["official_rate", "parallel_rate"]
    assert len(df) == 2
    assert df.loc["2023-01-04", "official_rate"] == 1450.0
    # From 2023 the parallel rate is the Baghdad close of daily_fx.csv (the seed had 1565.702)
    assert abs(df.loc["2023-01-04", "parallel_rate"] - 1564.5) < 0.001


def test_client_get_series_dict_aliasing():
    """Verify custom column names when passing a dictionary."""
    df = client.get_series({"Narrow Money": "m1", "Broad Money": "m2"}, start="2024-01", end="2024-02")
    assert list(df.columns) == ["Narrow Money", "Broad Money"]
    assert len(df) == 2
    assert df.loc["2024-01", "Narrow Money"] == 156675.0
    assert df.loc["2024-01", "Broad Money"] == 177251.0


def test_client_get_series_canonical_tidy():
    """Verify wide=False returns clean long format with direct source, and audit=True includes hash."""
    df = client.get_series("cpi", start="2024-01", end="2024-03", wide=False)
    assert list(df.columns) == ["date", "series_id", "value", "unit", "status_flag", "source"]
    assert len(df) == 3
    assert (df["series_id"] == "cpi_headline").all()
    # 2024-01 is the 2012 -> 2022 splice month, flagged B
    assert df["status_flag"].tolist() == ["B", "A", "A"]
    assert (df["source"] == "iraqdata (Spliced from CBI Series)").all()

    # Test audit=True
    df_audit = client.get_series("m2", start="2024-01", end="2024-01", wide=False, audit=True)
    assert "source_hash" in df_audit.columns
    assert "realtime_start" in df_audit.columns
    assert df_audit.loc[0, "source"] == "Central Bank of Iraq (CBI)"


def test_client_get_series_cross_table_join():
    """Verify multi-series fetch across different parquet tables (money & cpi)."""
    df = client.get_series(["m2", "cpi"], start="2024-01", end="2024-03")
    assert list(df.columns) == ["m2", "cpi"]
    assert len(df) == 3
    assert not df["m2"].isna().any()
    assert not df["cpi"].isna().any()


def test_client_get_table_full():
    """Verify get_table loads table with direct source column and date filtering."""
    df = client.get_table("fiscal_annual", start="2020", end="2022")
    assert list(df.columns) == ["date", "series_id", "value", "unit", "status_flag", "source"]
    # 7 series x 3 years = 21 rows
    assert len(df) == 21
    assert set(df["date"].unique()) == {"2020", "2021", "2022"}
    # Origin: the 2004-2023 fiscal seed has no known publisher, so no row claims the CBI
    assert (df["source"] == "Unknown publisher (see get_origin('" + df["series_id"] + "'))").all()
    later = client.get_table("fiscal_annual", start="2024", end="2024")
    assert (later["source"] == "Central Bank of Iraq (CBI) from 2024; 2004-2023 publisher unknown").all()


def test_toplevel_package_api_exports():
    """Verify that all core functions are directly exported by top-level iraqdata module."""
    assert hasattr(id, "get_series")
    assert hasattr(id, "get_table")
    assert hasattr(id, "list_series")
    assert hasattr(id, "search")
    assert hasattr(id, "get_series_info")
    assert hasattr(id, "list_categories")
    assert hasattr(id, "list_tables")
    assert hasattr(id, "set_release")
    assert hasattr(id, "clear_cache")

    df = id.get_series("m2", start="2024-01", end="2024-01")
    assert df.loc["2024-01", "m2"] == 177251.0



