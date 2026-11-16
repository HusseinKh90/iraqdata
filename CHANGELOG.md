# Changelog

All notable changes to `iraqdata` are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the code uses
[Semantic Versioning](https://semver.org/). Data releases are dated separately
(e.g. `data-2026-10`) and record the code version that built them.

## [Unreleased]

### Data

- Data release `data-2026-12`: 2025 GDP at current prices from the CSGIS 2025 preliminary quarterly
  estimates (`pipeline/raw/cosit/`, record `cosit_gdp_quarterly_2026-11-16.csv`). GDP 2025-Q2 is revised
  from 82,673,353 to 82,102,269.6 million IQD and oil GDP 2025-Q1 from 30,663,390 to 30,663,490; the
  other changes are rounding. Constant-price values are unchanged. The superseded values ship in the
  release's `history/` folder, so `as_of` returns them.

### Changed

- `pipeline/check_cosit_record.py` finds a number that a PDF's text splits with stray spaces, and counts
  a value the PDF draws only as an image (marked "read from the page image") apart, never as checked.

## [1.1.0] - 2026-11-16

### Data

Data release `data-2026-11` (82 series in 13 tables, 25,386 observations) adds the following.

- Three new monthly series of CBI foreign currency sales (the dollar auction), in million USD, from
  2020-01, in the new table `fx_auction_monthly`: `fx.auction_cash`, `fx.auction_transfers` (every
  non-cash sale) and `fx.auction_total`. 2020-2023 come from monthly data the maintainer obtained
  from the CBI (`pipeline/seeds/cbi_fx_auction_monthly_seed.xlsx`), checked against the annual
  totals of the CBI Monthly Statistical Bulletin; from 2024-01 they are read from sheet 3-a of that
  bulletin, which the monthly update check already downloads, so new months arrive automatically.
- Six new monthly series of commercial bank direct cash credit by sector, in million IQD, from
  2015-01, in the new table `credit_monthly`: `credit.private_total` (credit to the private
  sector), split into `credit.private_state_banks` and `credit.private_private_banks`, plus
  `credit.central_gov`, `credit.public_institutions` and the grand total `credit.total`.
  2015-2023 come from monthly data the maintainer obtained from the CBI
  (`pipeline/seeds/cbi_credit_monthly_seed.xlsx`), checked against the bulletin's year-end rows;
  from 2024-01 they are read from sheets 8-a to 8-c of the bulletin. The gate checks that the
  bank types add up to private credit and the sectors add up to the total.
- Eleven monthly series of the banking system's claims on, and deposits of, the government, in
  million IQD, from 2018-01, in the new table `govt_claims_monthly`. Read: the CBI's government
  securities `govt.cbi_tbills`, loans `govt.cbi_loans`, gross claims `govt.cbi_claims_total` and
  government deposits `govt.cbi_deposits` (bulletin sheet 4); commercial banks' claims on
  government `govt.bank_claims` and government deposits `govt.bank_deposits` (sheet 5). Computed:
  `govt.cbi_net_claims`, `govt.bank_net_claims`, `govt.system_debt_holdings` (CBI securities plus
  bank claims), `govt.system_deposits` and `govt.system_net_claims` (CBI net plus bank net claims).
  2018-2023 come from monthly data the maintainer obtained from the CBI
  (`pipeline/seeds/cbi_govt_claims_monthly_seed.csv`; its 2015-2017 rows predate the CBI's
  revision to the IMF methodology and are not used), checked against the bulletin's year-ends.

### Changed

- The update check (`.github/workflows/update_check.yml`) runs monthly, on the 20th, instead of
  weekly. A failed download is reported at the first failed run, and a downloaded release that has
  not been applied by the next run is raised as an anomaly.

### Documentation

- An Arabic README, `README.ar.md`, with the same content as the English one.

## [1.0.0] - 2026-10-28

First release, with the data release `data-2026-10`.

### Data

- 62 series in 9 areas (money and banking, exchange rates, prices and inflation, oil, public
  finance, GDP, balance of payments and trade, cross-border banking, development aid), in 10
  single-frequency tables with 23,139 observations. Each table is released as a CSV and a Parquet
  file, with `checksums.sha256`, a Frictionless `datapackage.json` and `release-assets.txt` (the
  GitHub upload name of every file).
- Every value has a status flag (`A` normal, `P` provisional, `B` break, `E` estimated, `M`
  missing, `U` low reliability), decided in one place (`pipeline/flags.py`) from each series'
  origin and the flag policy.
- Every series says how each period was produced: read from an archived official file, computed
  from other series, typed in from a publication, or from a source of unknown publisher. The list of
  everything that was not read from an archived official file is in `docs/series.md`.
- `cpi_headline` and `cpi_core` link the official CPI bases into continuous series, with a break
  flag at each base change (method and sensitivity in `docs/linked_inflation_method.md`).
  `cpi_core` before 2010 does not measure the same thing as after; read the warning there.
- Every value in this release was first published on 2026-10-28, so the release has no vintage
  history.
- Known limits: GDP quarters before 2020 and a few later ones are typed in from documents that are
  not archived (flag `U`); the 2004–2023 fiscal values come from a seed of unknown publisher
  (flag `U`); the Basrah crude price has ten typed-in months only.

### Python client

- `get_series` and `get_table` return one series or table with its date index; several
  frequencies come back as one table per frequency, never mixed. Options: `start`, `end`, `aliases`,
  `wide`, `flags` (a `<label>_flag` column after each value column) and `as_of` (values as
  published on a past date, from a release's vintage history).
- `search` and `list_series` work in English and Arabic; `get_origin` and `get_series_info` describe
  a series; `list_categories`, `list_tables` and `get_catalog` list what exists.
- `set_release`, `get_data_source` and `refresh_latest` say and control which data release is read.
  "Latest" is the newest `data-YYYY-MM` release, looked up once and kept until refreshed. A pin is
  always honoured.
- Every downloaded file is checked against the release's `checksums.sha256` when it is downloaded
  and before every read from the cache; a file that does not match is never used. `clear_cache`
  removes only files iraqdata created.
- Errors in `iraqdata.errors` say what went wrong and what to do; wide output warns
  (`FlagWarning`) about hidden breaks and provisional values.

### Pipeline

- Eleven parsers read the archived raw files and stop, naming the file and the sheet, cell or row,
  rather than guess, skip or drop a value. Typed-in values live in transcription records under
  `pipeline/raw/transcribed/`, never in code.
- The quality gate (`pipeline/validate.py`) checks schema, plausibility limits derived from each
  series' own data, jumps, accounting identities, cross-source sanity, continuity and freshness.
  `--release` fails on any review notice that has not been acknowledged by a named reviewer.
- A merge into the published tables keeps every revised or withdrawn value in a vintage history,
  writes all files as one recoverable transaction, and refuses to drop published rows silently.
- A weekly, report-only update check fetches every automatically fetchable source into a scratch
  folder, rebuilds and gatekeeps there, and keeps one GitHub issue per open problem. Downloads are
  https-only, limited to each source's own hosts, size-capped and content-checked before they are
  saved. A dead-man's switch reports a check that stopped running.
- `pipeline/export_release.py` runs the gate and the catalog check first and never overwrites an
  existing release; its output is byte-for-byte reproducible.
- Documentation: `docs/user_guide.md` (how to use the library, step by step),
  `docs/r_and_stata.md` (the same data in R, Stata and Excel without Python), `docs/series.md`
  (every series) and `docs/linked_inflation_method.md`. Each source's terms of reuse are in
  `pipeline/metadata/sources.yaml`.
