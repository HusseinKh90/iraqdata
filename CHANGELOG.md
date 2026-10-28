# Changelog

All notable changes to `iraqdata` are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the code uses
[Semantic Versioning](https://semver.org/). Data releases are dated separately
(e.g. `data-2026-10`) and record the code version that built them.

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
  `pipeline/raw/transcribed/` (`docs/transcription_records.md`), never in code.
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
- Documentation: `docs/collecting_data_doc.md` (how each source is collected and checked),
  `docs/source_inventory.md` (sources and terms of reuse), `docs/series.md`,
  `docs/transcription_records.md` and `docs/linked_inflation_method.md`.
