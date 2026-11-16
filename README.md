# iraqdata

[العربية](README.ar.md)

**Iraq's economic statistics: clean, consistent and in one place.**

[![Code licence: MIT](https://img.shields.io/badge/code-MIT-blue.svg)](https://github.com/husseinkh90/iraqdata/blob/main/LICENSE)
[![Data licence: CC BY 4.0](https://img.shields.io/badge/data-CC%20BY%204.0-lightgrey.svg)](https://github.com/husseinkh90/iraqdata/blob/main/LICENSE-DATA)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)

The `iraqdata` project provides the main economic time series for Iraq (money and banking, prices, exchange rates, oil, public finance, GDP, the balance of payments and more) as ready-to-use tables, available from Python or as plain CSV downloads.

## Why this project matters

Anyone studying Iraq’s economy faces the same set of challenges:

- **Data is fragmented.** Iraq's data is scattered across the websites of the Central Bank of Iraq, the Central Organization for Statistics and Information Technology (COSIT), the Ministry of Finance, the Ministry of Oil, OPEC, and various international organizations. Web pages are frequently moved or altered without notice.
- **Files are difficult to work with.** Much of the data comes as complex Arabic or bilingual spreadsheets and PDF documents, rather than tables ready for analysis.
- **Time series contain breaks.** The consumer price index has been published on four base years (1993, 2007, 2012 and 2022), and the Central Bank of Iraq has revised its monetary statistics to the IMF methodology back to 2012. Joining these series correctly requires careful work.
- **Redundant effort.** Researchers often spend the majority of their time collecting and cleaning data, long before the actual analysis can begin.

`iraqdata` does this work once, thoroughly and transparently, so that users do not have to repeat it:

- Every value records its source and how it was obtained. <!-- share:begin -->90%<!-- share:end --> of the observations are read directly from archived official publications. The rest are computed from other series, read from a non-official source, typed in from publications or of unknown origin; each such period is listed in
  [docs/series.md](https://github.com/husseinkh90/iraqdata/blob/main/docs/series.md#data-not-observed-from-an-archived-official-file), and values typed in or of unknown origin carry the status flag `U`.
- Breaks in a series, such as a change of base year, are flagged rather than hidden.
- The data pass automated quality checks before each release.

This project delivers a shared, free starting point. Researchers can study the Iraqi economy faster and replicate and verify results more easily.

## Who it is for

- **Researchers and students:** documented series with their sources, ready for estimation and replication.
- **Journalists and the public:** official figures in one place, each traceable to its publisher.
- **Banks, businesses and investors:** monetary, exchange-rate, oil and fiscal indicators with stated units and frequencies.
- **Policymakers and analysts:** consistent long series for monitoring and assessment.

## What data is included

Each *series* is one indicator measured over time, such as broad money (M2) month by month.
There are 82 series in 9 areas:

| Area | Examples | Original publisher |
|---|---|---|
| Money and banking | broad money `money.m2`, policy rate `money.policy_rate`, official reserves `money.reserves_official`, commercial bank credit to the private sector `credit.private_total`, net claims of the banking system on government `govt.system_net_claims` | Central Bank of Iraq |
| Exchange rates | official rate `fx.official`, Baghdad parallel-market rate `parallel_rate_iraq`, CBI foreign currency sales `fx.auction_total` | Central Bank of Iraq; Iraq-parallel-exchange-rate project |
| Prices and inflation | consumer prices `cpi_headline` and `cpi_core` | COSIT, via the Central Bank of Iraq |
| Oil | Brent price `oil_price_brent`, Basrah price `oil_price_basrah`, crude production `crude_production_direct` | Ministry of Oil and SOMO, OPEC and JODI, U.S. EIA |
| Public finance | revenue `fiscal.revenue_total`, spending `fiscal.expenditure_total`, balance `fiscal.balance` | Ministry of Finance, via the Central Bank of Iraq |
| GDP | nominal GDP `gdp.nominal`, real GDP `gdp.real`, non-oil GDP `gdp.nominal_nonoil` | COSIT |
| Balance of payments and trade | current account `bop.current_account`, exports `trade.exports_total`, imports `trade.imports_total` | Central Bank of Iraq |
| Cross-border banking | claims `bis.lbs.claims_total`, liabilities `bis.lbs.liabilities_total` | Bank for International Settlements |
| Development aid | net aid received `oecd.dac.oda_total_net` | OECD / World Bank |

See the [full list of all 82 series](https://github.com/husseinkh90/iraqdata/blob/main/docs/series.md).

## Install

```bash
pip install iraqdata
```

You need Python 3.10 or newer. To try the latest development version, run
`pip install git+https://github.com/husseinkh90/iraqdata` instead.
The test suite runs on Python 3.10–3.13.

## How to use

The [user guide](https://github.com/husseinkh90/iraqdata/blob/main/docs/user_guide.md) explains each step in detail: finding series, loading and renaming them, status flags, the origin of each value, saving data, pinning a data release, offline use and the meaning of each error message.

Import the library:

```python
import iraqdata as id
```

Get one series as a table indexed by date:

```python
df = id.get_series("money.m2")
print(df.tail())
```

Request several series at once. Series of different frequencies (monthly, daily) come back as one
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

The data are downloaded the first time you request them and kept on your computer, so later requests work offline.

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
value has been revised or withdrawn. The releases so far, `data-2026-10` and `data-2026-11`, have
none, because no published value has yet been revised; asking them for `as_of` raises
`NoVintageHistoryError`. From the first release that has a history:

<!-- not run: needs a release with a history folder -->
```python
then = id.get_series("cpi", wide=False, as_of="2026-10-28")
print(then[["date", "value", "realtime_start"]].tail())
```

### Which data release you are using

Data are published in dated releases (`data-2026-10`, `data-2026-11`, ...). By default you receive the newest release. It is looked up the first time you use the library and then kept until you ask for a newer one with `id.refresh_latest()`, so your results do not change on their own. To make results reproducible, pin a release. A pinned release is always used, even within a copy of this repository:

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
