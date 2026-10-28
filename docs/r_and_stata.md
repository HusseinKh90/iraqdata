# Using the data in R and Stata

You do not need Python. Every table of every data release is a CSV file on the repository's GitHub
releases page, and R and Stata can read it straight from the web address. This page shows how to
load a series, turn its dates into dates, look at the status flags and reshape the table.

- [1. The files and what is in them](#1-the-files-and-what-is-in-them)
- [2. R](#2-r)
- [3. Stata](#3-stata)
- [4. Reproducible work: pin a release](#4-reproducible-work-pin-a-release)
- [5. Excel](#5-excel)

## 1. The files and what is in them

The latest data release is at
<https://github.com/husseinkh90/iraqdata/releases/latest>. Each subject table is one CSV file (and
one Parquet file with the same content):

| File | Series in it | Dates (as text) |
|---|---|---|
| `money_banking_monthly.csv` | money, reserves, bank rates | year-month, `2024-08` |
| `prices_monthly.csv` | consumer prices (`cpi_headline`, `cpi_core` and their bases) | year-month, `2024-08` |
| `oil_monthly.csv` | crude production, Basrah price | year-month, `2024-08` |
| `exchange_rates_daily.csv` | official and parallel exchange rates | day, `2024-08-15` |
| `oil_daily.csv` | Brent price | day, `2024-08-15` |
| `gdp_quarterly.csv` | GDP, nominal and real, oil and non-oil | quarter, `2024-Q3` |
| `bop_trade_quarterly.csv` | balance of payments and trade | quarter, `2024-Q3` |
| `bis_lbs_quarterly.csv` | cross-border banking | quarter, `2024-Q3` |
| `fiscal_annual.csv` | revenue, spending, balance | year, `2024` |
| `oecd_dac_annual.csv` | development aid | year, `2023` |

[series.md](https://github.com/husseinkh90/iraqdata/blob/main/docs/series.md) lists every series
with its table, unit and start date. Every file has the same seven columns, one row per
observation:

| Column | Meaning |
|---|---|
| `date` | The period, as text (see the table above). |
| `series_id` | The series, such as `money.m2` or `cpi_headline`. |
| `value` | The number. Empty where the source has no value. |
| `unit` | The unit, such as `BILLION_IQD`, `INDEX` or `IQD_PER_USD`. Check it before comparing series. |
| `status_flag` | `A` normal, `P` provisional, `B` break, `E` estimated, `M` missing, `U` low reliability. See the [user guide](https://github.com/husseinkh90/iraqdata/blob/main/docs/user_guide.md#5-status-flags-how-far-to-trust-a-value). |
| `realtime_start` | The date the value was first published in this dataset. |
| `source_hash` | An internal fingerprint of the source file; ignore it. |

## 2. R

Base R is enough. Set the address once; every example below uses it.

```r
base <- "https://github.com/husseinkh90/iraqdata/releases/latest/download/"
```

### Load a table and pick a series

```r
money <- read.csv(paste0(base, "money_banking_monthly.csv"), stringsAsFactors = FALSE)
str(money)                       # 7 columns
unique(money$series_id)          # the series in this table

m2 <- subset(money, series_id == "money.m2")
m2$month <- as.Date(paste0(m2$date, "-01"))     # "2026-08" -> 2026-08-01
tail(m2[, c("month", "value", "unit", "status_flag")])
```

```r
plot(m2$month, m2$value, type = "l", xlab = "", ylab = "Billion IQD", main = "Broad money (M2)")
```

### Dates of each frequency

```r
# daily: the text is already a date
fx <- read.csv(paste0(base, "exchange_rates_daily.csv"), stringsAsFactors = FALSE)
official <- subset(fx, series_id == "fx.official")
official$day <- as.Date(official$date)

# quarterly: "2026-Q1" -> first day of the quarter
gdp <- read.csv(paste0(base, "gdp_quarterly.csv"), stringsAsFactors = FALSE)
gdp$year    <- as.integer(substr(gdp$date, 1, 4))
gdp$quarter <- as.integer(substr(gdp$date, 7, 7))
gdp$qstart  <- as.Date(sprintf("%d-%02d-01", gdp$year, 3 * gdp$quarter - 2))

# annual: "2025" -> 2025
fiscal <- read.csv(paste0(base, "fiscal_annual.csv"), stringsAsFactors = FALSE)
fiscal$year <- as.integer(fiscal$date)

tail(subset(gdp, series_id == "gdp.nominal")[, c("date", "qstart", "value", "status_flag")], 3)
```

### Status flags

```r
table(subset(gdp, series_id == "gdp.nominal")$status_flag)     # how many of each flag
nominal <- subset(gdp, series_id == "gdp.nominal" & status_flag != "U")   # leave out low-reliability values

prices <- read.csv(paste0(base, "prices_monthly.csv"), stringsAsFactors = FALSE)
cpi <- subset(prices, series_id == "cpi_headline")
cpi[cpi$status_flag == "B", c("date", "value")]                 # the months where the base changes
```

A flag `B` marks a change of basis, so a change across that date is not a real movement. Leave
those months out of growth rates, or look at them separately.

### One column per series (wide)

```r
two <- subset(money, series_id %in% c("money.m1", "money.m2"))
wide <- reshape(two[, c("date", "series_id", "value")], idvar = "date",
                timevar = "series_id", direction = "wide")
names(wide) <- sub("^value\\.", "", names(wide))
tail(wide, 3)
```

With the tidyverse the same step is
`tidyr::pivot_wider(two[, c("date", "series_id", "value")], names_from = series_id, values_from = value)`.

### Parquet instead of CSV (optional)

Parquet files are smaller and keep the types. They need the `arrow` package:

<!-- not run: needs the arrow package and a download -->
```r
install.packages("arrow")
download.file(paste0(base, "money_banking_monthly.parquet"), "money_banking_monthly.parquet", mode = "wb")
money <- arrow::read_parquet("money_banking_monthly.parquet")
```

### Save your result

```r
write.csv(wide, "money_wide.csv", row.names = FALSE)
```

## 3. Stata

Stata 14 or newer reads a CSV from a web address. Run the commands in a do-file (**File**, **New**,
**Do-file**): the `///` at the end of a line continues the command on the next line, which works in
a do-file but not in the Command window. Two things to know: Stata variable names cannot
contain a dot, so a series such as `money.m2` is a **value** of the column `series_id`, not a
variable name; and the column `date` is read as text on purpose (`stringcols(1)`), so that the
annual tables are not read as numbers.

### Load a table and pick a series

```stata
import delimited "https://github.com/husseinkh90/iraqdata/releases/latest/download/money_banking_monthly.csv", ///
    clear varnames(1) stringcols(1)
rename date period
describe
tab series_id                              // the series in this table

keep if series_id == "money.m2"
gen month = monthly(period, "YM")           // "2026-08" -> a Stata monthly date
format month %tm
tsset month
list month value unit status_flag in -5/l
tsline value, title("Broad money (M2)")
```

### Dates of each frequency

After `rename date period`, use the line for the table you loaded:

```stata
* monthly tables (money_banking, prices, oil_monthly):  "2026-08"
gen month = monthly(period, "YM")
format month %tm

* daily tables (exchange_rates_daily, oil_daily):  "2026-10-20"
gen day = date(period, "YMD")
format day %td

* quarterly tables (gdp, bop_trade, bis_lbs):  "2026-Q1"
gen quarter = yq(real(substr(period, 1, 4)), real(substr(period, 7, 1)))
format quarter %tq

* annual tables (fiscal, oecd_dac):  "2025"
gen year = real(period)
```

Then declare the time variable once, for one series at a time: `tsset month` (or `day`, `quarter`,
`year`). A daily series has gaps at weekends and holidays; its lags (`L.value`) refer to calendar
days, so such a day is missing.

### Status flags

```stata
tab status_flag                             // how many values of each flag
drop if status_flag == "U"                  // leave out low-reliability values
list month value if status_flag == "B"      // the months where an index changes base
```

A flag `B` marks a change of basis, so a change across that date is not a real movement.

### One column per series (wide)

Rename `value` first, so that the new variable names stay under Stata's 32-character limit, and
replace the dot in each series name:

```stata
import delimited "https://github.com/husseinkh90/iraqdata/releases/latest/download/money_banking_monthly.csv", ///
    clear varnames(1) stringcols(1)
rename date period
keep if inlist(series_id, "money.m1", "money.m2")
replace series_id = subinstr(series_id, ".", "_", .)
keep period series_id value
rename value v
reshape wide v, i(period) j(series_id) string
rename v* *
list in -3/l
```

You now have the variables `money_m1` and `money_m2`, one row per month.

### Save your result

```stata
save "money_wide.dta", replace
export delimited "money_wide.csv", replace
```

## 4. Reproducible work: pin a release

The address with `latest` always gives the newest data release, so a script run next year may give
different numbers. For a paper or a report, point to one dated release instead. Replace
`releases/latest/download/` by `releases/download/<release>/`:

<!-- not run: the pinned address replaces the one the other examples use -->
```r
base <- "https://github.com/husseinkh90/iraqdata/releases/download/data-2026-10/"
```

```stata
import delimited "https://github.com/husseinkh90/iraqdata/releases/download/data-2026-10/money_banking_monthly.csv", ///
    clear varnames(1) stringcols(1)
```

A published release is never changed, so the same address always gives the same bytes. Say which
release you used (`data-2026-10`) in your methods section, next to the citation in the README.

To check that a file is what the release published, compare its SHA-256 fingerprint with the line
for it in `checksums.sha256`, which is among the release's files. In R, the `digest` package does
this: `digest::digest(file = "money_banking_monthly.csv", algo = "sha256")`.

## 5. Excel

In Excel: **Data**, **Get Data**, **From Web**, paste the address of a CSV file (for example
`https://github.com/husseinkh90/iraqdata/releases/latest/download/money_banking_monthly.csv`) and
choose **Load**. If the `date` column is turned into dates, set it back to text, because quarters
such as `2026-Q1` are not dates. Use the filter on `series_id` to keep one series, and a
PivotTable (rows `date`, columns `series_id`, values `value`) for one column per series.
