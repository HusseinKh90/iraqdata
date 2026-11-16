# iraqdata

[العربية](https://github.com/husseinkh90/iraqdata/blob/main/README.ar.md)

**Iraq's economic statistics: clean, consistent and in one place.**

[![Code licence: MIT](https://img.shields.io/badge/code-MIT-blue.svg)](https://github.com/husseinkh90/iraqdata/blob/main/LICENSE)
[![Data licence: CC BY 4.0](https://img.shields.io/badge/data-CC%20BY%204.0-lightgrey.svg)](https://github.com/husseinkh90/iraqdata/blob/main/LICENSE-DATA)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)

The `iraqdata` project provides Iraq's main economic time series (money and banking, prices, exchange rates, oil, public finance, GDP, the balance of payments, and more) as ready-to-use tables, available in Python or as plain CSV downloads.

## Why `iraqdata`?

Analysing Iraq's macroeconomic data currently requires massive ETL (Extract, Transform, Load) overhead. `iraqdata` removes this friction, letting researchers and analysts focus entirely on modelling. This library solves four structural data challenges:

- **Centralised Access:** Iraqi economic data is spread across the Central Bank of Iraq, the Commission of Statistics and GIS (CSGIS), Ministries of Finance and Oil, OPEC, and international organisations. `iraqdata` brings these sources together in a single Python library.
- **Analysis-Ready Formats:** Eliminates the need to scrape PDFs or parse complex, bilingual (Arabic/English) spreadsheets. `iraqdata` delivers clean, fully typed DataFrames.
- **Continuous Time Series:** Links the four CPI base years (1993, 2007, 2012, 2022) into continuous headline and core indices (`cpi_headline`, `cpi_core`), while keeping each original base available as a separate series. The linked indices are an `iraqdata` construction, documented in [docs/linked_inflation_method.md](https://github.com/husseinkh90/iraqdata/blob/main/docs/linked_inflation_method.md).
- **Streamlined Workflow:** Data collection, translation, and cleaning typically consume the majority of a research project. `iraqdata` minimises this preparation phase, allowing researchers to proceed directly to analysis.

Every value records its source and method. <!-- share:begin -->90%<!-- share:end --> of observations come directly from archived official publications; the exceptions are listed in [docs/series.md](https://github.com/husseinkh90/iraqdata/blob/main/docs/series.md#data-not-observed-from-an-archived-official-file).

By providing a free, open-source foundation, `iraqdata` lets researchers study the Iraqi economy more efficiently while making it easier to replicate and verify results.

## Target Audience

- **Researchers and students:** Fully documented series with clear provenance, prepared for econometric modelling and replication.
- **Journalists and the public:** Easily accessible official figures, ensuring every number can be verified against the primary publisher.
- **Banks, businesses, and investors:** Track monetary, exchange-rate, oil, and fiscal indicators presented in consistent units and frequencies.
- **Policymakers and analysts:** Consistent, long-term time series for reliable economic monitoring and assessment.

## Dataset Overview

Data is structured as individual time series, with each representing a single economic indicator (e.g., monthly Broad Money, M2). 
The library currently provides access to 82 distinct series across 9 core macroeconomic categories:


| Area | Examples | Original publisher |
|---|---|---|
| Money and banking | broad money `money.m2`, policy rate `money.policy_rate`, official reserves `money.reserves_official`, commercial bank credit to the private sector `credit.private_total`, net claims of the banking system on government `govt.system_net_claims` | Central Bank of Iraq |
| Exchange rates | official rate `fx.official`, Baghdad parallel-market rate `parallel_rate_iraq`, CBI foreign currency sales `fx.auction_total` | Central Bank of Iraq; Iraq-parallel-exchange-rate project |
| Prices and inflation | consumer prices `cpi_headline` and `cpi_core` | CSGIS, via the Central Bank of Iraq |
| Oil | Brent price `oil_price_brent`, Basrah price `oil_price_basrah`, crude production `crude_production_direct` | Ministry of Oil and SOMO, OPEC and JODI, U.S. EIA |
| Public finance | revenue `fiscal.revenue_total`, spending `fiscal.expenditure_total`, balance `fiscal.balance` | Ministry of Finance, via the Central Bank of Iraq |
| GDP | nominal GDP `gdp.nominal`, real GDP `gdp.real`, non-oil GDP `gdp.nominal_nonoil` | CSGIS |
| Balance of payments and trade | current account `bop.current_account`, exports `trade.exports_total`, imports `trade.imports_total` | Central Bank of Iraq |
| Cross-border banking | claims `bis.lbs.claims_total`, liabilities `bis.lbs.liabilities_total` | Bank for International Settlements |
| Development aid | net aid received `oecd.dac.oda_total_net` | OECD / World Bank |

See the [full list of all 82 series](https://github.com/husseinkh90/iraqdata/blob/main/docs/series.md).

## Install

```bash
pip install iraqdata
```

`iraqdata` requires Python 3.10+ (tested across Python 3.10–3.13).
To install the latest development version directly from GitHub:

```bash
pip install git+https://github.com/husseinkh90/iraqdata
```


## Documentation

The [user guide](https://github.com/husseinkh90/iraqdata/blob/main/docs/user_guide.md) explains the library in detail. It covers finding, loading, and renaming series; understanding status flags and each value's origin; saving data; pinning data releases; offline use; and interpreting error messages.

Import the library:

```python
import iraqdata as id
```

Retrieve a single series as a table indexed by date:

```python
df = id.get_series("money.m2")
print(df.tail())
```

Retrieve multiple series simultaneously. To prevent implicit aggregation, series with different frequencies (e.g., monthly vs. daily) are returned as distinct DataFrames grouped by frequency:

```python
tables = id.get_series(["money.m2", "fx.official"])
print(tables["monthly"].tail())
print(tables["daily"].tail())
```

Choose a date range and column names:

```python
df = id.get_series({"Broad money": "m2", "Narrow money": "m1"}, start="2020-01", end="2024-12")
print(df.head())
```

Use short names for common indicators, such as `m2`, `cpi`, `official_rate`, `parallel_rate`,
`brent` and `gdp`:

```python
df = id.get_series(["m2", "cpi"])
print(df.tail())
```

Search in English or Arabic, or load a whole subject table:

```python
print(id.search("inflation"))
print(id.search("دينار"))
money = id.get_table("money_banking_monthly")
print(money.head())
```

The data downloads on the first request and caches locally, so subsequent requests run offline.

## Status Flags
Every data point includes a status flag indicating its quality or condition. You can display these flags alongside the values by passing `flags=True`.

The available flags are: `A` normal, `P` provisional, `B` break in series (e.g., a rebased index), `E` estimated, `M` missing, `U` low reliability.

```python
df = id.get_series(["cpi", "m2"], flags=True)
print(df[df["cpi_flag"].isin(["B", "P"])])
```

Without `flags=True`, a `FlagWarning` tells you when a table contains breaks or provisional values. To hide it:

```python
import warnings
warnings.filterwarnings("ignore", category=id.FlagWarning)
```

## Point-in-Time Querying (`as_of`)

Macroeconomic data is frequently revised. To ensure reproducibility, the `as_of` parameter lets you retrieve values exactly as they were published on a specific past date.

<!-- not run: needs a release with a history folder -->
```python
then = id.get_series("cpi", wide=False, as_of="2026-10-28")
print(then[["date", "value", "realtime_start"]].tail())
```

## Pinning a Data Release
Data is published in dated releases (e.g., `data-2026-10`, `data-2026-11`). By default, the library automatically fetches the newest available release upon first use and caches it. It will continue to use this cached version to prevent unexpected changes to your results, until you explicitly run `id.refresh_latest()`.

For absolute reproducibility across environments or users, pin a specific release. Once pinned, that exact release is always used:

```python
id.set_release("data-2026-11")    # or set the environment variable IRAQDATA_RELEASE
print(id.get_data_source())       # release data-2026-11 (pinned with set_release) from husseinkh90/iraqdata
```

`id.set_release()` takes precedence over `IRAQDATA_RELEASE`; `id.set_release(None)` removes the
pin. Downloads are kept in `~/.cache/iraqdata/` (or `IRAQDATA_CACHE_DIR`), one folder per release.
`id.clear_cache()` deletes only the files iraqdata downloaded there; anything else in that folder is
left alone. Data are downloaded from the GitHub releases of `husseinkh90/iraqdata`; set
`IRAQDATA_REPO` to use another repository.

## Without Python

Every table is available as a CSV file on the
[latest release page](https://github.com/husseinkh90/iraqdata/releases/latest), one file per
table (for example `money_banking_monthly.csv`). The
[guide for R and Stata](https://github.com/husseinkh90/iraqdata/blob/main/docs/r_and_stata.md)
shows how to load a series, convert the dates, use the status flags and reshape a table.

- **Excel:** Data → From Web, then paste
  `https://github.com/husseinkh90/iraqdata/releases/latest/download/money_banking_monthly.csv`.
- **Stata:**

  ```stata
  import delimited "https://github.com/husseinkh90/iraqdata/releases/latest/download/money_banking_monthly.csv", clear
  ```

- **R:**

  ```r
  money <- read.csv("https://github.com/husseinkh90/iraqdata/releases/latest/download/money_banking_monthly.csv")
  ```

## How to cite

If you use `iraqdata`, please cite it:

```bibtex
@software{khalid2026iraqdata,
  author  = {Khalid, Hussein},
  title   = {iraqdata: Open, Documented, and Reproducible Iraqi Macroeconomic Data Package},
  year    = {2026},
  version = {1.1.0},
  url     = {https://github.com/husseinkh90/iraqdata}
}
```

A DOI will be added once the release is archived on Zenodo.

Please cite both the package and the original publishers of the series you use (each series'
sources are in `datapackage.json`, and their terms in
[`pipeline/metadata/sources.yaml`](https://github.com/husseinkh90/iraqdata/blob/main/pipeline/metadata/sources.yaml)):
- the Central Bank of Iraq;
- the Commission of Statistics and GIS (CSGIS);
- the Ministry of Finance;
- the Ministry of Oil and SOMO;
- OPEC and JODI;
- the U.S. Energy Information Administration and FRED;
- the Bank for International Settlements;
- the World Bank;
- the Iraq-parallel-exchange-rate project (parallel exchange rate from 2023).

## Licence

- **Code:** [MIT](https://github.com/husseinkh90/iraqdata/blob/main/LICENSE).
- **Data:** the compiled and derived data are [CC BY 4.0](https://github.com/husseinkh90/iraqdata/blob/main/LICENSE-DATA). The source data keep
  their publishers' own terms, some of which state no licence; see
  [`pipeline/metadata/sources.yaml`](https://github.com/husseinkh90/iraqdata/blob/main/pipeline/metadata/sources.yaml).

## Contributing

A wrong number, an unclear message or a missing series: please open an issue at
<https://github.com/husseinkh90/iraqdata/issues> and say the series, the dates and the data release
(`print(id.get_data_source())`). The documents in
[`docs/`](https://github.com/husseinkh90/iraqdata/tree/main/docs) describe the series, the linked price
indices and how to use the data.
