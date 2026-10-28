# Transcription records

Some published values are not read from a file by a parser: they were typed in from a document (the
COSIT quarterly GDP figures; OPEC's Monthly Oil Market Report for the oil months JODI does not cover). Each
such value lives in a **transcription record**, an archived CSV under `pipeline/raw/transcribed/`. No typed
number appears in parser code, and every published row carries the hash of the record it came from.

## File

- Name: `<kind>_YYYY-MM-DD.csv`, for example `cosit_gdp_quarterly_2026-10-28.csv`. The date is when the record
  was written; it is also the vintage the merge stamps on the values it adds or revises.
- UTF-8, LF line endings, no byte-order mark, header exactly
  `series_id,period,value,unit,source_document,page_or_table,transcriber,transcribed_on,notes`.
- Rows sorted by `series_id`, then `period`; one row per series and period (a repeat is an error).
- A record is **never edited**. A correction is a new file with a later date; the parser reads the newest
  record of its kind. It is registered in the raw manifest (`python pipeline/raw_audit.py manifest add <file>`)
  and named in the `record:` entries of the series catalog (`src/iraqdata/series_catalog.yaml`, then
  `python pipeline/docs_origin.py`). The parser refuses a newest record the catalog does not name, so a
  deleted record never falls back to an older one silently.

## Columns

| Column | Meaning |
|---|---|
| `series_id`, `period` | The catalog series and its period (`2025-Q1`, `2024-04`). |
| `value`, `unit` | A number, and the catalog's unit for the series (a different unit is an error). |
| `source_document` | The archived document the value is read from, as a path under `pipeline/raw/` (`cosit/alarm/1-2025.pdf`), or, if the document is not archived, a description of the publication. |
| `page_or_table` | Where in it. `sheet '<name>' cell <ref>` for a workbook, `page <n>, table 1, column <c> (<period>), row '<label>'` for a PDF, `unknown` when the document is not archived. |
| `transcriber`, `transcribed_on` | Who typed or extracted it and when (`YYYY-MM-DD`, or `unknown` for values that predate the record). |
| `notes` | For a row that cites an archived document: `printed=<the number as printed>` or `computed=<a> - <b>` (a value that is the difference of two printed numbers, such as oil GDP from total and non-oil GDP). Otherwise free text. |

## Status flags

A value whose record row cites an archived document, so that it can be read back from it, is an observed value
(flag `A`, or `P` inside its revision window). A value whose document is not archived keeps flag `U`
(unverified). The catalog's `origin` segments say which periods are which (`class: observed` or
`transcribed`), because a flag is decided by the catalog and `pipeline/metadata/flag_policy.yaml`, never by a
parser.

## Checking a record

`python pipeline/check_cosit_record.py` reads every citation of the COSIT record back from its document: a
workbook cell must hold the value and be the line the series means (the GDP line, not the total by activities;
the crude-oil line); each printed number must be on the cited PDF page; a computed value must be the
difference it names. A number on a scanned page is accepted when another archived document prints it. Rows
whose document is not archived are counted, not checked. `tests/test_cosit_record.py` runs it.

## Adding a record

1. Archive the source document under `pipeline/raw/<provider>/` (never overwrite) and add it to the manifest.
2. Write the new dated record with one row per value, citing the document as above.
3. Register the record, update the `record:` entries in the catalog, run `python pipeline/docs_origin.py`.
4. `python pipeline/check_cosit_record.py`, then `python pipeline/run_parsers.py` (the merge keeps the earlier
   values in the vintage history), then the gate, as in `docs/collecting_data_doc.md`, section 5.
5. To lift a value from `U` to `A`, archive its document, cite it in the new record, and mark the catalog
   segment `observed`.
