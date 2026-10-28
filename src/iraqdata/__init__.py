"""
iraqdata
========
Open, documented, and reproducible macroeconomic data package for Iraq.

Quickstart:
    import iraqdata as id

    # 1. Discover indicators
    id.search("inflation")
    id.list_series(category="money_banking")

    # 2. Retrieve time-series data
    df = id.get_series("m2")
    df_fx = id.get_series(["official_rate", "parallel_rate"], start="2020-01-01")

    # 3. Retrieve entire tables
    df_fiscal = id.get_table("fiscal_annual")

    # 4. Reproducibility: pin a release and see which data are in use
    id.set_release("data-2026-10")
    print(id.get_data_source())

    # 5. Status flags next to values, and values as published on a past date
    #    (as_of needs a release that carries vintage history)
    df_cpi = id.get_series("cpi", flags=True)
    df_then = id.get_series("cpi", as_of="2026-10-28")
"""

from iraqdata.catalog import (
    get_catalog,
    get_origin,
    get_series_info,
    list_categories,
    list_series,
    list_tables,
    resolve_series_id,
    search,
)
from iraqdata.client import get_series, get_table
from iraqdata.errors import (
    ChecksumMismatchError,
    FileNotInReleaseError,
    FlagWarning,
    IraqdataError,
    NoVintageHistoryError,
    ReleaseNotFoundError,
    RepositoryNotFoundError,
    UnverifiableFileError,
)
from iraqdata.schema import CANONICAL_COLUMNS, Observation, validate_dataframe
from iraqdata.storage import (
    DataSource,
    clear_cache,
    get_active_release,
    get_cache_dir,
    get_data_source,
    load_table,
    refresh_latest,
    resolve_table_path,
    set_release,
)

__version__ = "1.0.0"

__all__ = [
    # Primary user API
    "get_series",
    "get_table",
    "list_series",
    "search",
    "get_series_info",
    "get_origin",
    "list_categories",
    "list_tables",
    "get_catalog",
    "resolve_series_id",
    # Storage & cache management
    "set_release",
    "get_active_release",
    "get_data_source",
    "refresh_latest",
    "DataSource",
    "clear_cache",
    "get_cache_dir",
    "load_table",
    "resolve_table_path",
    # Errors and warnings
    "IraqdataError",
    "RepositoryNotFoundError",
    "ReleaseNotFoundError",
    "FileNotInReleaseError",
    "ChecksumMismatchError",
    "UnverifiableFileError",
    "NoVintageHistoryError",
    "FlagWarning",
    # Schema contract
    "CANONICAL_COLUMNS",
    "Observation",
    "validate_dataframe",
    "__version__",
]
