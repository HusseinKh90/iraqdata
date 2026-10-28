# User guide

How to find, load and use the data in `iraqdata`, step by step. Every Python example on this page
is run by the test suite against the published data.

- [1. Install and first use](#1-install-and-first-use)
- [2. Find the series you need](#2-find-the-series-you-need)
- [3. Load data](#3-load-data)
- [4. Dates, units and missing values](#4-dates-units-and-missing-values)
- [5. Status flags: how far to trust a value](#5-status-flags-how-far-to-trust-a-value)
- [6. Where a number comes from](#6-where-a-number-comes-from)
- [7. Save the data or use it in another program](#7-save-the-data-or-use-it-in-another-program)
- [8. Reproducible results: data releases, offline use and the cache](#8-reproducible-results-data-releases-offline-use-and-the-cache)
- [9. Values as published on a past date](#9-values-as-published-on-a-past-date)
- [10. Errors and warnings](#10-errors-and-warnings)
- [11. Quick reference](#11-quick-reference)
- [12. Citing, licences and problems](#12-citing-licences-and-problems)

## 1. Install and first use

You need Python 3.10 or newer. Install the package from a normal command window (Command Prompt or
PowerShell on Windows, a terminal on macOS and Linux), **not** from inside Python:

```
python -m pip install iraqdata
```

Then start Python (`python`) and load a series:

```python
import iraqdata as id

m2 = id.get_series("m2")
print(m2.tail())
```

The first time, the library downloads the data from the project's GitHub releases (this needs an
internet connection once) and keeps a copy on your computer. After that it works offline. Every
downloaded file is checked against a checksum list published with the release, and a file that does
not match is never used.

In the examples `id` is short for `iraqdata`. If you prefer, write `import iraqdata` and call
`iraqdata.get_series(...)`.

## 2. Find the series you need

There are 62 series in ten subject tables. Three ways to find one:

**Search** in English or Arabic. It looks in ids, short names, names in both languages and
descriptions, ignores capital letters and Arabic spelling variants, and returns the best matches
first:

```python
print(id.search("inflation")[["series_id", "name_en", "frequency"]])
print(id.search("دينار")[["series_id", "name_ar"]])
```

**List** all series, or only one subject or frequency. The subjects (`category`) are `bis`, `bop`,
`exchange_rates`, `fiscal`, `gdp`, `money_banking`, `oecd`, `oil`, `prices` and `trade`; the
frequencies are `daily`, `monthly`, `quarterly` and `annual`:

```python
print(id.list_categories())
oil = id.list_series(category="oil", frequency="monthly")
print(oil[["series_id", "name_en", "unit", "start_date"]])
```

Each row also says the table the series is stored in, who published it (`source`), how it was
produced (`origin`) and whether every period comes from an official publisher (`official`).

**Read the full list** in [series.md](https://github.com/husseinkh90/iraqdata/blob/main/docs/series.md):
one row per series with its frequency, unit, start date and a short description.

### Names of series

Every series has an id such as `money.m2` or `fiscal.balance`. For the common ones there is also a
short name, and you can use either:

| Short name | Series | Short name | Series |
|---|---|---|---|
| `m0`, `m1`, `m2` | `money.m0`, `money.m1`, `money.m2` | `gdp`, `gdp_nominal` | `gdp.nominal` |
| `reserves` | `money.reserves_official` | `real_gdp`, `gdp_real` | `gdp.real` |
| `policy_rate` | `money.policy_rate` | `gdp_oil`, `gdp_nonoil` | `gdp.nominal_oil`, `gdp.nominal_nonoil` |
| `deposit_rate`, `lending_rate` | the bank rates | `revenue`, `spending`, `expenditure` | fiscal totals |
| `official`, `official_rate` | `fx.official` | `fiscal_balance`, `budget_balance` | `fiscal.balance` |
| `parallel`, `parallel_rate` | `parallel_rate_iraq` | `exports`, `imports`, `trade_balance` | trade totals |
| `cpi`, `inflation` | `cpi_headline` | `current_account` | `bop.current_account` |
| `core_cpi` | `cpi_core` | `brent`, `basrah` | oil prices |
| `oil_production` | `crude_production_secondary` | `production_direct` | `crude_production_direct` |

A name that does not exist gives an error with the closest matches:

```python
try:
    id.get_series("m3")
except KeyError as error:
    print(error)
```

## 3. Load data

### One series, several series

```python
m2 = id.get_series("m2")                       # one series: a table indexed by date
money = id.get_series(["m0", "m1", "m2"])      # several of the same frequency: one table
print(money.tail(3))
```

Series of different frequencies are never mixed or averaged. Ask for a monthly and a daily series
together and you get a dictionary with one table per frequency:

```python
tables = id.get_series(["m2", "official_rate"])
print(list(tables))                            # ['daily', 'monthly']
print(tables["monthly"].tail(2))
print(tables["daily"].tail(2))
```

### Choose the period

`start` and `end` take a year, a month, a quarter or a day, and both ends are included:

```python
fx = id.get_series("official_rate", start="2020-01-01", end="2020-12-31")
gdp = id.get_series("gdp", start="2015-Q1", end="2019")
money = id.get_series(["m1", "m2"], start="2020", end="2024-06")
print(len(fx), gdp.index.min(), gdp.index.max())
```

(`start_date` and `end_date` are accepted as other spellings of the same two options. Give only one
of each pair.)

### Name the columns yourself

```python
df = id.get_series({"Broad money": "m2", "Narrow money": "m1"}, start="2024-01", end="2024-03")
print(df)

df = id.get_series(["m1", "m2"], aliases={"m1": "Narrow", "m2": "Broad"}, start="2024-01", end="2024-03")
print(df.columns.tolist())
```

### One long table instead of columns

`wide=False` returns one row per observation, with the unit, the status flag and the publisher in
each row. This is the form to use when you mix series of different frequencies or want to filter by
flag:

```python
long = id.get_series(["cpi", "m2"], wide=False)
print(long.columns.tolist())      # date, series_id, value, unit, status_flag, source
print(long.tail(3))
```

### A whole table

Each subject table holds all its series in long form. The tables are `bis_lbs_quarterly`,
`bop_trade_quarterly`, `exchange_rates_daily`, `fiscal_annual`, `gdp_quarterly`,
`money_banking_monthly`, `oecd_dac_annual`, `oil_daily`, `oil_monthly` and `prices_monthly`:

```python
fiscal = id.get_table("fiscal_annual")
print(fiscal["series_id"].unique())
print(id.get_table("gdp_quarterly", start="2024").tail(3))
```

## 4. Dates, units and missing values

- **Dates** are text that sorts correctly: daily `2026-10-20`, monthly `2026-08`, quarterly
  `2026-Q1`, annual `2025`. The table's index is called `date`.
- **Units** are in the `unit` column of the long form and of `list_series()`. The units used are
  `BILLION_IQD`, `MILLION_IQD`, `MILLION_USD`, `INDEX` (a price index), `PERCENT`, `IQD_PER_USD`,
  `USD_PER_BBL` (dollars per barrel) and `TB_PER_D` (thousand barrels per day). Always check the unit
  before you compare two series.
- **Missing values** appear as empty cells (`NaN`). A series is never filled in or interpolated, so a
  date with no observation is simply empty. The wide form has one row per date that any requested
  series has.
- **Start dates** differ by series; `list_series()` shows each series' first period.

## 5. Status flags: how far to trust a value

Every value has a one-letter status flag:

| Flag | Meaning |
|---|---|
| `A` | Normal. |
| `P` | Provisional: the publisher may still revise it. |
| `B` | Break: the series changes basis here (for example a new base year of an index), so a change across this date is not a real movement. |
| `E` | Estimated. |
| `M` | Missing at the source. |
| `U` | Low reliability: the origin is unknown, or the value was typed in from a publication that is not archived. Use with care. |

Ask for the flags next to the values with `flags=True`; each value column is followed by a
`<name>_flag` column:

```python
cpi = id.get_series("cpi", flags=True)
print(cpi.tail(3))
print(cpi[cpi["cpi_flag"] == "B"])           # the base changes in the linked CPI
```

Without `flags=True`, a `FlagWarning` tells you when the result contains breaks or provisional values.
To hide that warning:

```python
import warnings
warnings.filterwarnings("ignore", category=id.FlagWarning)
```

In the long form the flag is the `status_flag` column:

```python
long = id.get_series("gdp", wide=False)
print(long["status_flag"].value_counts())    # many quarters before 2020 are U
```

Which series carry `U` values, and why, is listed at the end of
[series.md](https://github.com/husseinkh90/iraqdata/blob/main/docs/series.md#data-not-observed-from-an-archived-official-file).
The main cases are the GDP quarters before 2020, the 2004–2023 fiscal values and the typed-in Basrah
prices. Read the method note for the linked price indices
([linked_inflation_method.md](https://github.com/husseinkh90/iraqdata/blob/main/docs/linked_inflation_method.md)):
`cpi_core` before 2010 does not measure the same thing as after.

## 6. Where a number comes from

Three levels of detail.

**The publisher of each value** is in the `source` column of the long form.

**How each period of a series was produced** is in `get_origin`: one row per stretch of dates, with
its class (`observed` is read from an archived official file, `derived` is computed from other
series, `transcribed` is typed in from a publication, `unknown` is of unknown origin), whether it is
official, and the method and source:

```python
print(id.get_origin("fiscal.revenue_total")[["from", "to", "class", "official", "source"]])
```

**Everything about a series** (name in both languages, unit, start date, description, table, source)
is in `get_series_info`:

```python
info = id.get_series_info("m2")
print(info["name_en"], "|", info["name_ar"], "|", info["unit"], "|", info["table"])
```

Each publisher's terms of reuse, and the credit to give, are in
[sources.yaml](https://github.com/husseinkh90/iraqdata/blob/main/pipeline/metadata/sources.yaml) and in the `sources` of every release's `datapackage.json`.

## 7. Save the data or use it in another program

The results are ordinary pandas tables:

```python
m2 = id.get_series("m2", start="2020")
m2.to_csv("m2.csv")                   # opens in Excel, R, Stata and the like
```

<!-- not run: needs the openpyxl package (python -m pip install openpyxl) -->
```python
m2.to_excel("m2.xlsx")
```

Without Python, every table is also a CSV file on the repository's
[latest release page](https://github.com/husseinkh90/iraqdata/releases/latest), one file per table
(`money_banking_monthly.csv`, `prices_monthly.csv` and so on), with the same columns as the long
form. The [guide for R and Stata](https://github.com/husseinkh90/iraqdata/blob/main/docs/r_and_stata.md)
shows how to read them in those programs (and in Excel).

## 8. Reproducible results: data releases, offline use and the cache

Data is published in dated releases (`data-2026-10`, `data-2026-11`, ...). By default you get the
newest one. It is looked up the first time you use the library and then kept, so your results do not
change on their own. See which data you are using:

```python
print(id.get_data_source())
```

**To get the same numbers again next year**, pin the release at the top of your script:

```python
id.set_release("data-2026-10")        # or set the environment variable IRAQDATA_RELEASE
print(id.get_data_source())
```

A pinned release is always used. `id.set_release(None)` removes the pin.

**To move to newer data**, ask for it on purpose; older releases stay on your computer:

<!-- not run: asks GitHub for the newest release -->
```python
id.refresh_latest()
```

**Offline use.** Once a release has been downloaded, loading works without a connection. If you are
offline and nothing has been downloaded yet, you get a `ConnectionError` that says what to do.

**The cache** is a folder on your computer, one subfolder per release. Show where it is, or remove
what the library downloaded (nothing else in that folder is touched):

```python
print(id.get_cache_dir())
```

<!-- not run: deletes the downloaded data -->
```python
id.clear_cache()                      # everything; id.clear_cache("data-2026-10") for one release
```

**Settings by environment variable** (set them before starting Python):

| Variable | Effect |
|---|---|
| `IRAQDATA_RELEASE` | Pins a data release, like `set_release`. `set_release` wins if both are set. |
| `IRAQDATA_CACHE_DIR` | Keeps the downloads in this folder instead of the default (`~/.cache/iraqdata`). |
| `IRAQDATA_LOCAL_DIR` | Reads the tables from a folder you already have (the files of a release) instead of downloading. |
| `IRAQDATA_REPO` | Downloads from another GitHub repository, as `owner/name`. |

## 9. Values as published on a past date

Values are revised over time, and the library can return them as they were published on a given
date, so that a result can be reproduced exactly:

<!-- not run: needs a release with a vintage history, and the first release has none -->
```python
then = id.get_series("cpi", wide=False, as_of="2027-01-15")
print(then[["date", "value", "realtime_start"]].tail())
```

`as_of` needs a release that ships a `history/` folder, which a release has once some published
value has been revised or withdrawn. The first release (`data-2026-10`) has none, because every value
in it was first published on 2026-10-28, and raises `NoVintageHistoryError`. A series that did not
exist on the date gives an empty result and a warning.

## 10. Errors and warnings

| What you see | Meaning and what to do |
|---|---|
| `KeyError: Unknown series ...` | The name is wrong. The message suggests close matches; `id.search("...")` finds others. |
| `ValueError` about a window | `start` is after `end`, or a date is not a year, month, quarter or day. |
| `ValueError: ... Column label ... is assigned to both ...` | Two series would get the same column name; rename one. |
| `TypeError: Pass either 'start' or 'start_date'` | Both spellings were given; keep one. |
| `FlagWarning` | The wide result contains breaks or provisional values. Use `flags=True` to see them. |
| `ConnectionError: Cannot find the latest data release ...` | Nothing has been downloaded and GitHub cannot be reached. Connect once, or pin a release you have. |
| `ReleaseNotFoundError` | The release you pinned does not exist in the repository. Check the name (`data-YYYY-MM`). |
| `RepositoryNotFoundError` | The repository named by `IRAQDATA_REPO` (or the default) was not found or is private. |
| `FileNotInReleaseError` | A release is missing a file the library needs, so it is incomplete. Use another release. |
| `ChecksumMismatchError` | A downloaded file does not match the release's checksum list and was discarded. Try again; if it repeats, report it. |
| `UnverifiableFileError` | The release has no checksum for a file, so the library will not use it. |
| `NoVintageHistoryError` | `as_of` was used with a release that has no revision history (section 9). |

All errors and warnings of the library are in `iraqdata.errors`, and `id.IraqdataError` is the base
class of its own errors. `help(id.get_series)` shows the full description of any function.

## 11. Quick reference

| Function | What it does |
|---|---|
| `get_series(series, start, end, wide, flags, aliases, as_of)` | Load one or more series. |
| `get_table(table_name, start, end, as_of)` | Load a whole subject table (long form). |
| `search(text)` | Find series by words, in English or Arabic. |
| `list_series(category, frequency)` | List series with unit, start date, source and origin. |
| `list_categories()`, `list_tables()` | The subjects and the tables. |
| `get_series_info(series)` | All details of one series. |
| `get_origin(series)` | How each period of a series was produced. |
| `get_data_source()`, `set_release(tag)`, `refresh_latest()` | Which data release is in use, and choosing it. |
| `get_cache_dir()`, `clear_cache(tag)` | Where downloads are kept, and removing them. |

## 12. Citing, licences and problems

- **Cite** the package, and the original publishers of the series you use; the README gives a
  ready-made reference.
- **Licences:** the code is MIT. The compiled and derived data are CC BY 4.0; the source data keep
  their publishers' own terms, which are listed in
  [sources.yaml](https://github.com/husseinkh90/iraqdata/blob/main/pipeline/metadata/sources.yaml).
- **A wrong number, an unclear message, a missing series?** Open an issue at
  <https://github.com/husseinkh90/iraqdata/issues> and say the series, the dates and the data release
  (`print(id.get_data_source())`).
