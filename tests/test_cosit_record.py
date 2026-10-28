"""
tests.test_cosit_record
=======================
The COSIT GDP record cites the archived documents its numbers come from, and
pipeline/check_cosit_record.py reads every citation back from the document: a workbook cell or a
number on a PDF page. These tests run that check on the real record and show that it notices a
wrong value, a wrong cell, a wrong line, a number that is not on the page and a wrong subtraction.
"""

import csv

import pytest

import check_cosit_record as check
from conftest import REPO_ROOT

RECORD = check.newest_record()

HEADER = ["series_id", "period", "value", "unit", "source_document", "page_or_table", "transcriber",
          "transcribed_on", "notes"]
WORKBOOK = "cosit/التقديرات_الأولية_الفصلية_والإجمالية_للناتج_المحلي_الإجمالي_لسنة_2020.xls"
PDF = "cosit/alarm/1-2025.pdf"
SCAN = "cosit/alarm/2-2025.pdf"


def _row(series, period, value, document, where, notes):
    return dict(series_id=series, period=period, value=value, unit="MILLION_IQD", source_document=document,
                page_or_table=where, transcriber="t", transcribed_on="2026-10-28", notes=notes)


def _check(tmp_path, *rows):
    path = tmp_path / "cosit_gdp_quarterly_2026-10-28.csv"
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, HEADER, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return check.check_record(path)


GDP_Q1_2020 = _row("gdp.nominal", "2020-Q1", "53145283.3", WORKBOOK, "sheet 'جاري' cell E23", "printed=53145283.3")
OIL_Q1_2020 = _row("gdp.nominal_oil", "2020-Q1", "20548529.1", WORKBOOK, "sheet 'جاري' cell E8", "printed=20548529.1")
GDP_Q1_2025 = _row("gdp.nominal", "2025-Q1", "82974731.0", PDF, "page 7, table 1, column 3 (2025-Q1), row 'GDP at current prices'",
                   "printed=82,974,731")
OIL_Q1_2025 = _row("gdp.nominal_oil", "2025-Q1", "30663490.0", PDF,
                   "page 7, table 1, column 3 (2025-Q1), rows 'GDP at current prices' and 'non-oil GDP at current prices'",
                   "computed=82,974,731 - 52,311,241")


# ---------------------------------------------------------------------------- the real record


@pytest.fixture(scope="module")
def result():
    return check.check_record(RECORD)


def test_every_citation_agrees_with_its_document(result):
    counts, problems = result
    assert problems == []
    assert counts.get("unchecked", 0) == 0          # no scanned number stands without another document printing it
    assert counts["cell"] >= 32 and counts["page"] >= 47 and counts["corroborated"] >= 4


def test_the_quarters_without_an_archived_document_are_the_ones_the_catalog_names():
    """The catalog says 2015-2019 and a few later quarters come from documents that are not archived."""
    with open(RECORD, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    unarchived = {(r["series_id"], r["period"]) for r in rows if r["page_or_table"] == "unknown"}
    quarters = {p for _, p in unarchived}
    assert quarters == ({f"{y}-Q{q}" for y in range(2015, 2020) for q in range(1, 5)}
                        | {"2021-Q3", "2021-Q4", "2022-Q2", "2022-Q3", "2023-Q3"})
    assert ("gdp.nominal", "2023-Q3") not in unarchived   # only the oil value of 2023-Q3 is kept from the earlier record
    cited = [r for r in rows if r["page_or_table"] != "unknown"]
    assert all(r["transcriber"].startswith("Claude Code") and "not yet reviewed by the maintainer" in r["transcriber"]
               for r in cited)


def test_the_implausible_printed_value_is_documented_not_used():
    with open(RECORD, encoding="utf-8", newline="") as f:
        row = next(r for r in csv.DictReader(f) if (r["series_id"], r["period"]) == ("gdp.nominal_oil", "2023-Q3"))
    assert "80,625,844" in row["notes"] and "not used" in row["notes"]
    assert float(row["value"]) > 30_000_000       # not the 3,993,620 the printed non-oil figure would leave


def test_every_row_of_the_record_is_in_the_published_table():
    import pandas as pd
    garden = pd.read_parquet(REPO_ROOT / "pipeline" / "data" / "garden" / "gdp_quarterly.parquet")
    with open(RECORD, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    published = garden.set_index(["series_id", "date"])["value"]
    assert all(published[(r["series_id"], r["period"])] == float(r["value"]) for r in rows)


# ---------------------------------------------------------------------------- the check notices damage


def test_good_rows_pass(tmp_path):
    counts, problems = _check(tmp_path, GDP_Q1_2020, OIL_Q1_2020, GDP_Q1_2025, OIL_Q1_2025)
    assert problems == [] and counts == {"cell": 2, "page": 2}


def test_a_value_that_is_not_in_the_cell_is_named(tmp_path):
    bad = dict(GDP_Q1_2020, value="53145283.4", notes="printed=53145283.4")
    _, problems = _check(tmp_path, bad)
    assert len(problems) == 1 and "gdp.nominal 2020-Q1" in problems[0] and "holds 53145283.3" in problems[0]


def test_a_value_that_differs_from_its_printed_text_is_named(tmp_path):
    _, problems = _check(tmp_path, dict(GDP_Q1_2020, value="53145283.0"))
    assert len(problems) == 1 and "not the cell's" in problems[0]


def test_a_missing_sheet_or_cell_is_named(tmp_path):
    _, problems = _check(tmp_path, dict(GDP_Q1_2020, page_or_table="sheet 'nowhere' cell E23"))
    assert len(problems) == 1 and "nowhere" in problems[0]


def test_the_total_by_activities_is_not_gdp(tmp_path):
    """The line above GDP (before the imputed bank service charge) holds a different number: row 21, not 23."""
    bad = dict(GDP_Q1_2020, value="53806962.9", page_or_table="sheet 'جاري' cell E21", notes="printed=53806962.9")
    _, problems = _check(tmp_path, bad)
    assert len(problems) == 1 and "not the one for gdp.nominal" in problems[0]


def test_the_wrong_line_for_oil_is_named(tmp_path):
    bad = dict(OIL_Q1_2020, value="53145283.3", page_or_table="sheet 'جاري' cell E23", notes="printed=53145283.3")
    _, problems = _check(tmp_path, bad)
    assert len(problems) == 1 and "not the one for gdp.nominal_oil" in problems[0]


def test_a_number_that_is_not_on_the_cited_page_is_named(tmp_path):
    bad = dict(GDP_Q1_2025, value="82974732.0", notes="printed=82,974,732")
    _, problems = _check(tmp_path, bad)
    assert len(problems) == 1 and "82,974,732 is not on" in problems[0] and "page 7" in problems[0]


def test_a_page_number_is_taken_from_the_row(tmp_path):
    _, problems = _check(tmp_path, dict(GDP_Q1_2025, page_or_table=GDP_Q1_2025["page_or_table"].replace("page 7", "page 6")))
    assert len(problems) == 1 and "is not on" in problems[0]


def test_a_wrong_subtraction_is_named(tmp_path):
    bad = dict(OIL_Q1_2025, value="30663500.0")
    _, problems = _check(tmp_path, bad)
    assert len(problems) == 1 and "is not 30663500.0" in problems[0]


def test_notes_that_say_nothing_checkable_are_refused(tmp_path):
    counts, problems = _check(tmp_path, dict(GDP_Q1_2025, notes="typed by hand"))
    assert counts == {"unchecked": 1} and "printed=" in problems[0]


def test_a_document_that_is_not_in_the_archive_is_named(tmp_path):
    _, problems = _check(tmp_path, dict(GDP_Q1_2025, source_document="cosit/alarm/missing.pdf"))
    assert len(problems) == 1 and "not in the archive" in problems[0]


def test_rows_without_an_archived_source_are_counted_not_checked(tmp_path):
    row = _row("gdp.nominal", "2015-Q1", "43100000.0", "COSIT Directorate of National Accounts", "unknown",
               "not found in any archived COSIT document")
    counts, problems = _check(tmp_path, row)
    assert counts == {"not-archived": 1} and problems == []


def test_a_number_on_a_scanned_page_needs_another_document_to_print_it(tmp_path):
    scanned = _row("gdp.nominal", "2024-Q2", "96391305.0", SCAN,
                   "page 7, table 1, column 1 (2024-Q2), row 'GDP at current prices'", "printed=96,391,305")
    other = _row("gdp.nominal", "2024-Q2", "96391305.0", "cosit/alarm/ف2_2024_نهائي.pdf",
                 "page 7, table 1, column 3 (2024-Q2), row 'GDP at current prices'", "printed=96,391,305")
    counts, problems = _check(tmp_path, scanned, other)
    assert counts == {"corroborated": 1, "page": 1} and problems == []
    # the same number cited alone: no cited page prints it
    counts, _ = _check(tmp_path, scanned)
    assert counts == {"unchecked": 1}


def test_the_command_line_reports_ok(capsys):
    assert check.main(["--record", str(RECORD)]) == 0
    assert capsys.readouterr().out.strip().endswith("COSIT record: OK")
