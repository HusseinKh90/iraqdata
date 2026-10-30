# iraqdata

**Iraq's economic statistics: clean, consistent and in one place.**

[![Code licence: MIT](https://img.shields.io/badge/code-MIT-blue.svg)](https://github.com/husseinkh90/iraqdata/blob/main/LICENSE)
[![Data licence: CC BY 4.0](https://img.shields.io/badge/data-CC%20BY%204.0-lightgrey.svg)](https://github.com/husseinkh90/iraqdata/blob/main/LICENSE-DATA)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)

`iraqdata` project provides key economic time series for Iraq, covering money, prices, exchange rates, oil, public finance, GDP, trade, and more, in ready-to-use tables, accessible via lines of code or a simple download.

## Why this project matters

Anyone studying Iraq’s economy faces the same set of challenges:

- **Data is fragmented.** Iraq's data is scattered across the websites of the Central Bank of Iraq, the Central Organization for Statistics (COSIT), the Ministry of Finance, the Ministry of Oil, OPEC, and various international organizations. Web pages are frequently moved or altered without notice.
- **Files are difficult to work with.** Much of the data comes as complex, multilingual (Arabic) spreadsheets or PDF documents, rather than tables ready for immediate analysis.
- **Time series contain breaks.** Price indices have been rebased multiple times (in 1993, 2007, 2012, and 2022), and accounting standards have also evolved over time. Merging these datasets correctly requires careful, precise work.
- **Redundant effort.** Researchers often spend the majority of their time collecting and cleaning data, long before the actual analysis can begin.

`iraqdata` carries out this work in a thorough and transparent manner, offering it as a one-time service:

- Each figure specifies its source and the methodology used for measurement. 91% of the observations come directly from official archival documents; the rest are calculated from these publications. The series are listed in 
  [docs/series.md](https://github.com/husseinkh90/iraqdata/blob/main/docs/series.md#data-not-observed-from-an-archived-official-file) and flagged.
- Breaks between series are marked rather than hidden.
- The data are checked before each release.

This project delivers a shared, free starting point. Researchers can study the Iraqi economy faster and replicate and verify results more easily.

## Who it is for

- **Researchers and students:**
- **Journalists and the public:**
- **Banks, businesses and investors:**
- **Policymakers and analysts:**

## What data is included

Each *series* is one indicator measured over time, such as broad money (M2) month by month.
There are 62 series in 9 areas:

| Area | Examples | Original publisher |
|---|---|---|
| Money and banking | broad money `money.m2`, policy rate `money.policy_rate`, official reserves `money.reserves_official` | Central Bank of Iraq |
| Exchange rates | official rate `fx.official`, Baghdad parallel-market rate `parallel_rate_iraq` | Central Bank of Iraq; Iraq-parallel-exchange-rate project |
| Prices and inflation | consumer prices `cpi_headline` and `cpi_core` | COSIT, via the Central Bank of Iraq |
| Oil | Brent price `oil_price_brent`, Basrah price `oil_price_basrah`, crude production `crude_production_direct` | Ministry of Oil and SOMO, OPEC and JODI, U.S. EIA |
| Public finance | revenue `fiscal.revenue_total`, spending `fiscal.expenditure_total`, balance `fiscal.balance` | Ministry of Finance, via the Central Bank of Iraq |
| GDP | nominal GDP `gdp.nominal`, real GDP `gdp.real`, non-oil GDP `gdp.nominal_nonoil` | COSIT |
| Balance of payments and trade | current account `bop.current_account`, exports `trade.exports_total`, imports `trade.imports_total` | Central Bank of Iraq |
| Cross-border banking | claims `bis.lbs.claims_total`, liabilities `bis.lbs.liabilities_total` | Bank for International Settlements |
| Development aid | net aid received `oecd.dac.oda_total_net` | OECD / World Bank |

See the [full list of all 62 series](https://github.com/husseinkh90/iraqdata/blob/main/docs/series.md).

## Install

```bash
pip install iraqdata
```

You need Python 3.10 or newer. To try the latest development version, run
`pip install git+https://github.com/husseinkh90/iraqdata` instead.
The test suite runs on Python 3.10–3.13.

## How to use

Check out this user guide. The [user guide](https://github.com/husseinkh90/iraqdata/blob/main/docs/user_guide.md) explains each option step by step: finding series, loading and renaming them, status indicators, the origin of each figure, saving data, pinning a data version, offline use, and the meaning of the various error messages.

Import the library:

```python
import iraqdata as id
```

Get one series as a table indexed by date:

```python
df = id.get_series("money.m2")
print(df.tail())
```

You could display different series at the same time. Series of different frequencies (monthly, daily) come back as one
table per frequency, so nothing is mixed or averaged:

```python
tables = id.get_series(["money.m2", "fx.official"])
print(tables["monthly"].tail())
print(tables["daily"].tail())
```

Choose a date range and your own column names:

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

The data downloads the first time you request it and then stores it on your computer, so future requests can be handled offline.

### Status flags

Every value has a status flag: `A` normal, `P` provisional, `B` break (for example, a rebased
index), `E` estimated, `M` missing, `U` low reliability. Display them next to the values with
`flags=True`:

```python
df = id.get_series(["cpi", "m2"], flags=True)
print(df[df["cpi_flag"].isin(["B", "P"])])
```

Without `flags=True`, a `FlagWarning` tells you when a table contains breaks or provisional
values. To hide it: `warnings.filterwarnings("ignore", category=id.FlagWarning)`.

### Values as published on a past date

Values are revised over time. `as_of` returns them as they were published on a given date, from
the vintage history that ships with a release. A release has a `history/` folder once a published
value has been revised or withdrawn. The first release, `data-2026-10`, has none, because every
value in it was first published on 2026-10-28; asking it for `as_of` raises
`NoVintageHistoryError`. From the first release that has a history:

<!-- not run: needs a release with a history folder -->
```python
then = id.get_series("cpi", wide=False, as_of="2026-10-28")
print(then[["date", "value", "realtime_start"]].tail())
```

### Which data release you are using

By default, you receive the most recently released data version. This is retrieved the first time you use the library and is then stored until you request a newer version via `id.refresh_latest()`; this ensures your results remain consistent. To make results reproducible, you can pin a specific version (associated with a date). Such a pinned version will always be used, even within a copy of this repository:

```python
id.set_release("data-2026-10")    # or set the environment variable IRAQDATA_RELEASE
print(id.get_data_source())       # release data-2026-10 (pinned with set_release) from husseinkh90/iraqdata
```

`id.set_release()` takes precedence over `IRAQDATA_RELEASE`; `id.set_release(None)` removes the
pin. Downloads are kept in `~/.cache/iraqdata/` (or `IRAQDATA_CACHE_DIR`), one folder per release.
`id.clear_cache()` deletes only the files iraqdata downloaded there; anything else in that folder is
left alone. Data are downloaded from the GitHub releases of `husseinkh90/iraqdata`; set
`IRAQDATA_REPO` to use another repository.

## Without Python

The [guide for R and Stata](https://github.com/husseinkh90/iraqdata/blob/main/docs/r_and_stata.md)
This demonstrates how to load a series, convert the dates into date format, use the flags, and reshape the table. In short, every table is available as a CSV file on the
[latest release page](https://github.com/husseinkh90/iraqdata/releases/latest), one file per
subject area (for example `money_banking_monthly.csv`).

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
  version = {1.0.0},
  url     = {https://github.com/husseinkh90/iraqdata}
}
```

I will add a DOI once the release is archived on Zenodo.

Please cite both the package and the original publishers of the series you use (each series'
sources are in `datapackage.json`, and their terms in
[`pipeline/metadata/sources.yaml`](https://github.com/husseinkh90/iraqdata/blob/main/pipeline/metadata/sources.yaml)):
- the Central Bank of Iraq;
- the Central Organization for Statistics and Information Technology (COSIT);
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
