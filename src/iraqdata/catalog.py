"""
Series metadata catalog and search engine for iraqdata.

Provides fast, in-memory discovery, filtering, and bilingual searching across
every series registered in the catalog (published ones, and any later withdrawn ones kept so older releases can be read).
Domestic series omit the publisher prefix (e.g. 'money.m2', 'fiscal.balance',
'gdp.nominal', 'cpi.headline_1993', 'bop.current_account') to reflect natural
macroeconomic concepts for researchers.
"""

from __future__ import annotations

import difflib
import os
import re
import warnings
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

# Static mapping from series_id to its canonical garden parquet table
SERIES_TO_TABLE: dict[str, str] = {
    # Family 1: Money & Banking (Monthly)
    "money.currency_outside_banks": "money_banking_monthly",
    "money.m0": "money_banking_monthly",
    "money.m1": "money_banking_monthly",
    "money.m2": "money_banking_monthly",
    "money.fx_deposits": "money_banking_monthly",
    "money.reserves_official": "money_banking_monthly",
    "money.policy_rate": "money_banking_monthly",
    "money.bank_deposit_rate": "money_banking_monthly",
    "money.bank_lending_rate": "money_banking_monthly",
    "money.required_reserves": "money_banking_monthly",

    # Family 2: Exchange Rates (Daily)
    "parallel_rate_iraq": "exchange_rates_daily",
    "fx.official": "exchange_rates_daily",

    # Family 3: Oil (Daily & Monthly)
    "oil_price_brent": "oil_daily",
    "crude_production_secondary": "oil_monthly",
    "crude_production_direct": "oil_monthly",
    "oil_price_basrah": "oil_monthly",

    # Family 4: Prices / CPI (Monthly)
    "cpi.headline_1993": "prices_monthly",
    "cpi.headline_2007": "prices_monthly",
    "cpi.headline_2012": "prices_monthly",
    "cpi.headline_2022": "prices_monthly",
    "cpi.core_1993": "prices_monthly",
    "cpi.core_2007": "prices_monthly",
    "cpi.core_2012": "prices_monthly",
    "cpi.core_2022": "prices_monthly",
    "cpi_headline": "prices_monthly",
    "cpi_core": "prices_monthly",

    # Family 5: Fiscal (Annual)
    "fiscal.revenue_total": "fiscal_annual",
    "fiscal.revenue_current": "fiscal_annual",
    "fiscal.revenue_investment": "fiscal_annual",
    "fiscal.expenditure_total": "fiscal_annual",
    "fiscal.expenditure_current": "fiscal_annual",
    "fiscal.expenditure_investment": "fiscal_annual",
    "fiscal.balance": "fiscal_annual",

    # Family 6: Balance of Payments & Trade (Quarterly)
    "bop.current_account": "bop_trade_quarterly",
    "bop.trade_balance": "bop_trade_quarterly",
    "bop.services_net": "bop_trade_quarterly",
    "bop.income_net": "bop_trade_quarterly",
    "bop.transfers_net": "bop_trade_quarterly",
    "bop.capital_account": "bop_trade_quarterly",
    "bop.financial_account": "bop_trade_quarterly",
    "bop.reserve_assets_change": "bop_trade_quarterly",
    "trade.exports_total": "bop_trade_quarterly",
    "trade.exports_crude_oil": "bop_trade_quarterly",
    "trade.exports_oil_products": "bop_trade_quarterly",
    "trade.exports_nonoil": "bop_trade_quarterly",
    "trade.imports_total": "bop_trade_quarterly",
    "trade.imports_government": "bop_trade_quarterly",
    "trade.imports_private": "bop_trade_quarterly",

    # Family 7: Output / GDP (Quarterly)
    "gdp.nominal": "gdp_quarterly",
    "gdp.nominal_nonoil": "gdp_quarterly",
    "gdp.nominal_oil": "gdp_quarterly",
    "gdp.real": "gdp_quarterly",
    "gdp.real_nonoil": "gdp_quarterly",
    "gdp.real_oil": "gdp_quarterly",

    # Family 8: External Mirrors / BIS LBS (Quarterly)
    "bis.lbs.claims_total": "bis_lbs_quarterly",
    "bis.lbs.liabilities_total": "bis_lbs_quarterly",
    "bis.lbs.liabilities_banks": "bis_lbs_quarterly",
    "bis.lbs.liabilities_nonbank": "bis_lbs_quarterly",
    "bis.lbs.claims_nonbank": "bis_lbs_quarterly",
    "bis.lbs.net_position": "bis_lbs_quarterly",

    # Family 9: Development Assistance / OECD DAC (Annual)
    "oecd.dac.oda_total_net": "oecd_dac_annual",
    "oecd.dac.grants_excl_tc": "oecd_dac_annual",
}

# Direct publication source where iraqdata retrieved the dataset (Option A)
SERIES_DIRECT_SOURCES: dict[str, str] = {
    # Family 1: Money & Banking (CBI)
    "money.currency_outside_banks": "Central Bank of Iraq (CBI)",
    "money.m0": "Central Bank of Iraq (CBI)",
    "money.m1": "Central Bank of Iraq (CBI)",
    "money.m2": "Central Bank of Iraq (CBI)",
    "money.fx_deposits": "Central Bank of Iraq (CBI)",
    "money.reserves_official": "Central Bank of Iraq (CBI)",
    "money.policy_rate": "Central Bank of Iraq (CBI)",
    "money.bank_deposit_rate": "Central Bank of Iraq (CBI)",
    "money.bank_lending_rate": "Central Bank of Iraq (CBI)",
    "money.required_reserves": "Central Bank of Iraq (CBI)",

    # Family 2: Exchange Rates
    "fx.official": "Central Bank of Iraq (CBI)",
    "parallel_rate_iraq": "Baghdad Currency Market (Consensus)",

    # Family 3: Oil
    "oil_price_brent": "U.S. EIA via FRED",
    "oil_price_basrah": "OPEC MOMR",
    "crude_production_secondary": "U.S. EIA",
    "crude_production_direct": "JODI-Oil / OPEC MOMR",

    # Family 4: Prices / CPI
    "cpi.headline_1993": "Central Bank of Iraq (CBI)",
    "cpi.headline_2007": "Central Bank of Iraq (CBI)",
    "cpi.headline_2012": "Central Bank of Iraq (CBI)",
    "cpi.headline_2022": "Central Bank of Iraq (CBI)",
    "cpi.core_1993": "Central Bank of Iraq (CBI)",
    "cpi.core_2007": "Central Bank of Iraq (CBI)",
    "cpi.core_2012": "Central Bank of Iraq (CBI)",
    "cpi.core_2022": "Central Bank of Iraq (CBI)",
    "cpi_headline": "iraqdata (Spliced from CBI Series)",
    "cpi_core": "iraqdata (Spliced from CBI Series)",

    # Family 5: Fiscal
    "fiscal.revenue_total": "Central Bank of Iraq (CBI) from 2024; 2004-2023 publisher unknown",
    "fiscal.revenue_current": "Central Bank of Iraq (CBI) from 2024; 2004-2023 publisher unknown",
    "fiscal.revenue_investment": "Central Bank of Iraq (CBI) from 2024; 2004-2023 publisher unknown",
    "fiscal.expenditure_total": "Central Bank of Iraq (CBI) from 2024; 2004-2023 publisher unknown",
    "fiscal.expenditure_current": "Central Bank of Iraq (CBI) from 2024; 2004-2023 publisher unknown",
    "fiscal.expenditure_investment": "Central Bank of Iraq (CBI) from 2024; 2004-2023 publisher unknown",
    "fiscal.balance": "Central Bank of Iraq (CBI) from 2024; 2004-2023 publisher unknown",

    # Family 6: Balance of Payments & Trade
    "bop.current_account": "Central Bank of Iraq (CBI)",
    "bop.trade_balance": "Central Bank of Iraq (CBI)",
    "bop.services_net": "Central Bank of Iraq (CBI)",
    "bop.income_net": "Central Bank of Iraq (CBI)",
    "bop.transfers_net": "Central Bank of Iraq (CBI)",
    "bop.capital_account": "Central Bank of Iraq (CBI)",
    "bop.financial_account": "Central Bank of Iraq (CBI)",
    "bop.reserve_assets_change": "Central Bank of Iraq (CBI)",
    "trade.exports_total": "Central Bank of Iraq (CBI)",
    "trade.exports_crude_oil": "Central Bank of Iraq (CBI)",
    "trade.exports_oil_products": "Central Bank of Iraq (CBI)",
    "trade.exports_nonoil": "Central Bank of Iraq (CBI)",
    "trade.imports_total": "Central Bank of Iraq (CBI)",
    "trade.imports_government": "Central Bank of Iraq (CBI)",
    "trade.imports_private": "Central Bank of Iraq (CBI)",

    # Family 7: Output / GDP
    "gdp.nominal": "Central Organization for Statistics (COSIT)",
    "gdp.nominal_nonoil": "Central Organization for Statistics (COSIT)",
    "gdp.nominal_oil": "Central Organization for Statistics (COSIT)",
    "gdp.real": "Central Organization for Statistics (COSIT)",
    "gdp.real_nonoil": "Central Organization for Statistics (COSIT)",
    "gdp.real_oil": "Central Organization for Statistics (COSIT)",

    # Family 8: External Mirrors / BIS LBS
    "bis.lbs.claims_total": "Bank for International Settlements (BIS)",
    "bis.lbs.liabilities_total": "Bank for International Settlements (BIS)",
    "bis.lbs.liabilities_banks": "Bank for International Settlements (BIS)",
    "bis.lbs.liabilities_nonbank": "Bank for International Settlements (BIS)",
    "bis.lbs.claims_nonbank": "Bank for International Settlements (BIS)",
    "bis.lbs.net_position": "Bank for International Settlements (BIS)",

    # Family 9: Development Assistance / OECD DAC
    "oecd.dac.oda_total_net": "World Bank WDI (compiled from OECD DAC data)",
    "oecd.dac.grants_excl_tc": "World Bank WDI (OECD DAC, DAC2A)",
}

# Renamed series ids: {old id: new id}. A renamed id stays a deprecated alias for at least one data
# release; resolving one warns and returns the new id. No series has been renamed yet.
DEPRECATED_IDS: dict[str, str] = {}

# Intuitive shortcut aliases mapping commonly requested names to canonical series_id
ALIASES: dict[str, str] = {
    # Monetary shortcuts
    "m0": "money.m0",
    "m1": "money.m1",
    "m2": "money.m2",
    "reserves": "money.reserves_official",
    "policy_rate": "money.policy_rate",
    "fx_deposits": "money.fx_deposits",
    "deposit_rate": "money.bank_deposit_rate",
    "lending_rate": "money.bank_lending_rate",
    "required_reserves": "money.required_reserves",
    "currency_outside_banks": "money.currency_outside_banks",

    # Exchange rate shortcuts
    "parallel_rate": "parallel_rate_iraq",
    "parallel": "parallel_rate_iraq",
    "official_rate": "fx.official",
    "official": "fx.official",

    # Inflation & Prices shortcuts
    "cpi": "cpi_headline",
    "inflation": "cpi_headline",
    "core_cpi": "cpi_core",

    # Fiscal shortcuts
    "fiscal_balance": "fiscal.balance",
    "budget_balance": "fiscal.balance",
    "revenue": "fiscal.revenue_total",
    "expenditure": "fiscal.expenditure_total",
    "spending": "fiscal.expenditure_total",

    # GDP shortcuts
    "gdp": "gdp.nominal",
    "gdp_nominal": "gdp.nominal",
    "gdp_real": "gdp.real",
    "real_gdp": "gdp.real",
    "gdp_oil": "gdp.nominal_oil",
    "gdp_nonoil": "gdp.nominal_nonoil",

    # Oil shortcuts
    "brent": "oil_price_brent",
    "oil_production": "crude_production_secondary",
    "production_secondary": "crude_production_secondary",
    "production_direct": "crude_production_direct",
    "basrah": "oil_price_basrah",
    "basrah_price": "oil_price_basrah",

    # BOP & Trade shortcuts
    "current_account": "bop.current_account",
    "trade_balance": "bop.trade_balance",
    "exports": "trade.exports_total",
    "imports": "trade.imports_total",
    "crude_exports": "trade.exports_crude_oil",
}


def _resolve_catalog_path() -> Path:
    """Find series_catalog.yaml: the IRAQDATA_CATALOG_PATH override, else the packaged file.

    The packaged file is the only catalog; the pipeline reads it too.
    """
    # 1. Explicit environment override
    env_path = os.environ.get("IRAQDATA_CATALOG_PATH")
    if env_path and Path(env_path).is_file():
        return Path(env_path)

    # 2. Package-bundled catalog (inside src/iraqdata)
    pkg_catalog = Path(__file__).parent / "series_catalog.yaml"
    if pkg_catalog.is_file():
        return pkg_catalog

    raise FileNotFoundError(
        f"Could not locate 'series_catalog.yaml' (looked for IRAQDATA_CATALOG_PATH and {pkg_catalog})."
    )


@lru_cache(maxsize=1)
def get_catalog() -> dict[str, Any]:
    """Load and cache the raw series catalog dictionary from YAML."""
    path = _resolve_catalog_path()
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=1)
def _get_series_dict() -> dict[str, dict[str, Any]]:
    """Return dictionary of series metadata keyed by series_id."""
    catalog = get_catalog()
    series_list = catalog.get("series", [])
    return {s["series_id"]: s for s in series_list}


def resolve_series_id(series_name_or_alias: str) -> str:
    """
    Resolve a user-provided series name or shortcut alias to its canonical series_id.

    Supports:
    - Exact canonical ID (e.g. 'money.m2')
    - Friendly alias (e.g. 'm2' -> 'money.m2', 'cpi' -> 'cpi_headline')
    - Legacy / historical provider prefixed IDs (e.g. 'cbi.money.m2' -> 'money.m2')
    - Renamed IDs in DEPRECATED_IDS, with a FutureWarning ('old.id' -> 'new.id')
    """
    name = series_name_or_alias.strip()

    # 0. Renamed ids: warn and use the new id
    if name in DEPRECATED_IDS:
        warnings.warn(
            f"'{name}' is deprecated; use '{DEPRECATED_IDS[name]}'", FutureWarning, stacklevel=2
        )
        return DEPRECATED_IDS[name]

    # 1. Direct canonical match
    if name in SERIES_TO_TABLE:
        return name

    # 2. Friendly alias lookup
    name_lower = name.lower()
    if name_lower in ALIASES:
        return ALIASES[name_lower]

    # 3. Strip legacy 'cbi.' or 'cosit.' prefixes for backwards compatibility
    if name_lower.startswith("cbi."):
        candidate = name_lower[4:]
        if candidate in SERIES_TO_TABLE:
            return candidate
    elif name_lower.startswith("cosit."):
        candidate = name_lower[6:]
        if candidate in SERIES_TO_TABLE:
            return candidate
        # e.g. cosit.gdp_nominal -> gdp.nominal
        if candidate.startswith("gdp_"):
            gdp_candidate = "gdp." + candidate[4:]
            if gdp_candidate in SERIES_TO_TABLE:
                return gdp_candidate

    # If not matched to any alias or legacy prefix, return original name
    return name


def get_source_for_series(series_id_or_alias: str) -> str:
    """Return the direct publication source where iraqdata retrieved the dataset."""
    # Stored ids (including ones renamed since, in older releases) are looked up without a warning
    if series_id_or_alias in SERIES_DIRECT_SOURCES:
        return SERIES_DIRECT_SOURCES[series_id_or_alias]
    canonical_id = resolve_series_id(series_id_or_alias)
    return SERIES_DIRECT_SOURCES.get(canonical_id, "Official Publication")


def source_for_observation(series_id: str, date: str) -> str:
    """
    The source of one stored observation: the series' direct source, except in a period whose
    catalog origin is `unknown` (e.g. the 2004-2023 fiscal seed), where no publisher is claimed.
    """
    entry = _get_series_dict().get(series_id) or {}
    for seg in entry.get("origin") or []:
        to = str(seg["to"])
        if seg.get("class") == "unknown" and str(seg["from"]) <= date and (to == "open" or date <= to):
            return f"Unknown publisher (see get_origin('{series_id}'))"
    return get_source_for_series(series_id)


def get_series_info(series_id_or_alias: str) -> dict[str, Any]:
    """
    Retrieve metadata for a specific series or alias.

    Raises KeyError if series is not found, with suggestions for closest match.
    """
    # Try resolving alias first
    try:
        canonical_id = resolve_series_id(series_id_or_alias)
    except KeyError:
        canonical_id = series_id_or_alias

    series_dict = _get_series_dict()
    if canonical_id in series_dict:
        info = dict(series_dict[canonical_id])
        info["table"] = SERIES_TO_TABLE.get(canonical_id)
        info["source"] = get_source_for_series(canonical_id)
        return info

    # Find closest match across canonical IDs and aliases
    candidates = list(series_dict.keys()) + list(ALIASES.keys())
    matches = difflib.get_close_matches(series_id_or_alias, candidates, n=3, cutoff=0.5)
    hint = f" Did you mean: {', '.join(matches)}?" if matches else ""
    raise KeyError(f"Unknown series '{series_id_or_alias}'.{hint}")


def get_table_for_series(series_id_or_alias: str) -> str:
    """Return the parquet table name where the series observations are stored."""
    canonical_id = resolve_series_id(series_id_or_alias)
    if canonical_id in SERIES_TO_TABLE:
        return SERIES_TO_TABLE[canonical_id]
    get_series_info(canonical_id)
    raise KeyError(f"No table mapping registered for series '{series_id_or_alias}'.")


def list_series(
    category: str | None = None,
    frequency: str | None = None,
) -> pd.DataFrame:
    """
    List registered macroeconomic series as a pandas DataFrame.

    Parameters
    ----------
    category : str, optional
        Filter by macroeconomic category (e.g. 'money_banking', 'fiscal', 'oil',
        'prices', 'bop', 'trade', 'gdp', 'bis', 'oecd').
    frequency : str, optional
        Filter by frequency ('daily', 'monthly', 'quarterly', 'annual').

    Returns
    -------
    pd.DataFrame
        DataFrame with columns ['series_id', 'name_en', 'name_ar', 'category',
        'frequency', 'unit', 'start_date', 'table', 'source', 'origin', 'official', 'status'].
        `origin` summarises how each period was produced (see `get_origin`); `official` is True
        only when every period is observed or derived from an official publisher. `status` is
        'withdrawn' for a series no longer published (kept so older releases can be read), else
        'active'.
    """
    series_list = get_catalog().get("series", [])
    records: list[dict[str, Any]] = []

    cat_norm = category.lower().strip() if category else None
    freq_norm = frequency.lower().strip() if frequency else None

    for s in series_list:
        s_cat = s.get("category", "")
        s_freq = s.get("frequency", "")

        if cat_norm and s_cat.lower() != cat_norm:
            continue
        if freq_norm and s_freq.lower() != freq_norm:
            continue

        records.append({
            "series_id": s["series_id"],
            "name_en": s.get("name_en", ""),
            "name_ar": s.get("name_ar", ""),
            "category": s_cat,
            "frequency": s_freq,
            "unit": s.get("unit", ""),
            "start_date": s.get("start_date", ""),
            "table": SERIES_TO_TABLE.get(s["series_id"], ""),
            "source": SERIES_DIRECT_SOURCES.get(s["series_id"], ""),
            "origin": origin_summary(s.get("origin", [])),
            "official": is_official(s.get("origin", [])),
            "status": s.get("status", "active"),
        })

    df = pd.DataFrame(records)
    if not df.empty:
        df = df.sort_values(by=["category", "series_id"]).reset_index(drop=True)
    return df


SEARCH_RESULT_COLUMNS = [
    "series_id", "name_en", "name_ar", "category", "frequency", "unit", "start_date", "table", "source",
    "origin", "official", "status",
]

ORIGIN_COLUMNS = ["from", "to", "class", "official", "method", "source", "record"]


def origin_summary(segments: list[dict[str, Any]]) -> str:
    """One line per series, e.g. 'observed 2007-01..2024-03; transcribed 2024-04..open'."""
    parts = []
    for seg in segments:
        unofficial = "" if seg.get("official", True) else " (unofficial)"
        parts.append(f"{seg['class']}{unofficial} {seg['from']}..{seg['to']}")
    return "; ".join(parts)


def is_official(segments: list[dict[str, Any]], _seen: frozenset = frozenset()) -> bool:
    """
    True only if every period is observed from an official publisher, or derived from series that
    are themselves official (a series derived from transcribed values is not).
    """
    if not segments:
        return False
    series = _get_series_dict()
    for seg in segments:
        if not seg.get("official", False) or seg["class"] not in ("observed", "derived"):
            return False
        if seg["class"] == "derived":
            for sid in seg.get("inputs", []):
                if sid in _seen or sid not in series:
                    return False
                if not is_official(series[sid].get("origin", []), _seen | {sid}):
                    return False
    return True


def get_origin(series_id_or_alias: str) -> pd.DataFrame:
    """
    How each period of a series was produced: one row per origin segment, in period
    order, with columns ['from', 'to', 'class', 'official', 'method', 'source', 'record'].

    `class` is one of observed, derived, modelled, transcribed (typed in by hand from a document)
    or unknown; `record` names the archived transcription record where there is one.
    """
    info = get_series_info(series_id_or_alias)
    rows = [{**{k: None for k in ORIGIN_COLUMNS},
             **{k: (str(v) if k in ("from", "to") else v) for k, v in seg.items() if k in ORIGIN_COLUMNS}}
            for seg in info.get("origin", [])]
    return pd.DataFrame(rows, columns=ORIGIN_COLUMNS)

# Arabic diacritics (harakat, Quranic marks) and tatweel, removed before matching
_ARABIC_MARKS = re.compile("[ؐ-ًؚ-ٰٟۖ-ۭـ]")
# Spelling variants folded to one form: alef forms -> bare alef, taa marbuta -> haa, alef maqsura -> yaa
_ARABIC_FOLD = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ة": "ه", "ى": "ي"})
_TOKEN_SPLIT = re.compile(r"[^\w]+")


def _normalize_text(text: Any) -> str:
    """Lowercase and fold Arabic spelling variants so equivalent spellings match."""
    return _ARABIC_MARKS.sub("", str(text or "").lower()).translate(_ARABIC_FOLD)


def _tokens(text: Any) -> set[str]:
    """Whole words of a normalised field; '.', '_' and spaces all separate words."""
    return {t for t in _TOKEN_SPLIT.split(_normalize_text(text)) if t}


def _match_tier(query: str, entry: dict[str, Any], aliases: list[str]) -> int | None:
    """
    Rank how strongly a catalog entry matches a normalised query (lower is stronger):
    1 exact series ID or alias; 2 whole word in ID, alias or title;
    3 partial match in ID, alias or title; 4 description or other metadata only.
    """
    ids = [entry["series_id"], *aliases]
    titles = [entry.get("name_en", ""), entry.get("name_ar", "")]
    other = [entry.get(k, "") for k in ("description", "category", "source_row_label", "cross_check")]

    if any(_normalize_text(x) == query for x in ids):
        return 1
    if any(query in _tokens(x) for x in ids + titles):
        return 2
    if any(query in _normalize_text(x) for x in ids + titles):
        return 3
    if any(query in _normalize_text(x) for x in other):
        return 4
    return None


def search(query: str) -> pd.DataFrame:
    """
    Search registered series across English & Arabic names, descriptions, and labels.

    Matching is case-insensitive and ignores Arabic diacritics and spelling variants.
    Results are ranked strongest first: exact ID/alias, whole word in ID/alias/title,
    partial match in ID/alias/title, then description-only matches; ties keep catalog order.

    Parameters
    ----------
    query : str
        Keyword string to search for. An empty query lists every series.

    Returns
    -------
    pd.DataFrame
        DataFrame of matching series (empty, with the standard columns, if none match).
    """
    q = _normalize_text(query).strip()
    if not q:
        return list_series()

    aliases_by_series: dict[str, list[str]] = {}
    for alias, sid in ALIASES.items():
        aliases_by_series.setdefault(sid, []).append(alias)

    ranked: list[tuple[int, int, dict[str, Any]]] = []
    for index, s in enumerate(get_catalog().get("series", [])):
        tier = _match_tier(q, s, aliases_by_series.get(s["series_id"], []))
        if tier is None:
            continue
        ranked.append((tier, index, {
            "series_id": s["series_id"],
            "name_en": s.get("name_en", ""),
            "name_ar": s.get("name_ar", ""),
            "category": s.get("category", ""),
            "frequency": s.get("frequency", ""),
            "unit": s.get("unit", ""),
            "start_date": s.get("start_date", ""),
            "table": SERIES_TO_TABLE.get(s["series_id"], ""),
            "source": SERIES_DIRECT_SOURCES.get(s["series_id"], ""),
            "origin": origin_summary(s.get("origin", [])),
            "official": is_official(s.get("origin", [])),
            "status": s.get("status", "active"),
        }))

    ranked.sort(key=lambda item: (item[0], item[1]))
    return pd.DataFrame([record for _, _, record in ranked], columns=SEARCH_RESULT_COLUMNS)


def list_categories() -> list[str]:
    """Return sorted list of all unique macroeconomic categories."""
    df = list_series()
    if df.empty:
        return []
    return sorted(df["category"].unique().tolist())


def list_tables() -> list[str]:
    """Return sorted list of all unique garden parquet table names."""
    return sorted(set(SERIES_TO_TABLE.values()))
