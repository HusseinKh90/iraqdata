"""OPEC HTML reader regression tests against ten frozen official publications."""
import copy
import hashlib
import csv
import json
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from lxml import html
import opec_momr as c
FIXTURES = Path(__file__).parent / "fixtures" / "opec"
TODAY = date(2026, 11, 3)

class MemoryClient:
    def __init__(self):
        manifest = json.loads((FIXTURES / 'routes.json').read_text())
        self.bodies = {url: (FIXTURES / entry['file']).read_bytes() for url, entry in manifest.items()}
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        value = self.bodies[url]
        if isinstance(value, Exception):
            raise value
        return value


def latest(client=None):
    client = client or MemoryClient()
    return c.discover(client.get(c.INDEX), today=TODAY)[0]


def mutation(body, edit):
    doc = c.document(body)
    caption = next(n for n in doc.xpath('//h6') if 'direct communication' in n.text_content().lower())
    table = caption.xpath('following::table[1]')[0]
    rows = table.xpath('.//tr')
    header = next(r for r in rows if c.normalize(r.xpath('./td|./th')[0].text_content()) == 'Direct communication')
    row = next(r for r in rows if c.normalize(r.xpath('./td|./th')[0].text_content()) == 'Iraq')
    edit(doc, caption, table, header, row)
    return html.tostring(doc, encoding='utf-8')


class ParsingTests(unittest.TestCase):
    def setUp(self):
        self.client = MemoryClient()
        self.report = latest(self.client)
        self.body = self.client.get(self.report.chapter_url)

    def test_fixture_bytes_match_recorded_fingerprints(self):
        routes = json.loads((FIXTURES / "routes.json").read_text())
        for url, record in routes.items():
            with self.subTest(url=url):
                self.assertEqual(hashlib.sha256((FIXTURES / record["file"]).read_bytes()).hexdigest(),
                                 record["sha256"])

    def test_discover_all_ten_published_reports(self):
        reports = c.discover(self.client.get(c.INDEX), year=2026, today=TODAY)
        self.assertEqual([r.period for r in reports], [f'2026-{m:02d}' for m in range(1, 11)])
        self.assertEqual(reports[-1].chapter_url, 'https://publications.opec.org/momr/chapter/162/3037')

    def test_archive_resolution_excludes_current_navigation(self):
        report = c.discover(self.client.get(c.INDEX), year=2026, today=TODAY)[0]
        resolved = c.resolve_archive(report, self.client.get(report.archive_url))
        self.assertEqual(resolved.publication_id, '150')
        self.assertEqual(resolved.chapter_url, 'https://publications.opec.org/momr/archive/chapter/150/2769')

    def test_all_30_observations_match_independently_verified_csv(self):
        with (FIXTURES / 'expected-observations.csv').open() as f:
            expected = {(r['report_month'], r['observation_month']): Decimal(r['value']) for r in csv.DictReader(f)}
        got = {}
        for report in c.discover(self.client.get(c.INDEX), year=2026, today=TODAY):
            if report.archive_url:
                report = c.resolve_archive(report, self.client.get(report.archive_url))
            for obs in c.extract(report, self.client.get(report.chapter_url)):
                month = c.MONTHS[int(report.period[5:]) - 1] + ' ' + report.period[:4]
                got[month, obs['date']] = Decimal(obs['value'])
                self.assertEqual(obs['unit'], 'TB_PER_D')
                self.assertEqual(obs['series_id'], 'crude_production_direct')
        self.assertEqual(len(got), 30)
        self.assertEqual(got, expected)

    def test_all_nine_pdf_crosschecks_match(self):
        for record in json.loads((FIXTURES / 'pdf-crosschecks.json').read_text()):
            with self.subTest(report=record['report_date']):
                month = c.MONTHS.index(record['report_date'].split()[1]) + 1
                report = c.discover(self.client.get(c.INDEX), year=2026, today=TODAY)[month - 1]
                report = c.resolve_archive(report, self.client.get(report.archive_url))
                got = c.extract(report, self.client.get(report.chapter_url))
                self.assertEqual([(o['date'], Decimal(o['value'])) for o in got],
                                 [(o['period'], Decimal(str(o['value']))) for o in record['observations']])

    def test_changed_page_position_and_table_number_are_supported(self):
        def edit(doc, caption, table, header, row):
            caption.xpath('preceding::h4[1]')[0].text = 'Table 5 - 9'
            doc.insert(0, html.fromstring('<div>Additional introductory material</div>'))
        got = c.extract(self.report, mutation(self.body, edit))
        self.assertEqual(got[-1]['value'], '4399')
        self.assertEqual(got[-1]['table'], 'Table 5 - 9')

    def test_year_rollover_and_change_column_are_not_observations(self):
        report = c.discover(self.client.get(c.INDEX), year=2026, today=TODAY)[0]
        report = c.resolve_archive(report, self.client.get(report.archive_url))
        got = c.extract(report, self.client.get(report.chapter_url))
        self.assertEqual([o['date'] for o in got], ['2025-10', '2025-11', '2025-12'])
        self.assertEqual(len(got), 3)

    def test_wrong_units_and_wrong_source_definition_are_rejected(self):
        for title in ['OPEC crude oil production based on direct communication, mb/d',
                      'OPEC crude oil production based on secondary sources, tb/d']:
            with self.subTest(title=title):
                body = mutation(self.body, lambda d, caption, *args: setattr(caption, 'text', title))
                with self.assertRaises(c.CollectionError):
                    c.extract(self.report, body)

    def test_duplicate_and_missing_iraq_are_rejected(self):
        for duplicate in [True, False]:
            def edit(doc, caption, table, header, row):
                if duplicate:
                    row.getparent().append(copy.deepcopy(row))
                else:
                    row.getparent().remove(row)
            with self.subTest(duplicate=duplicate), self.assertRaises(c.CollectionError):
                c.extract(self.report, mutation(self.body, edit))

    def test_missing_footnoted_or_malformed_values_require_review(self):
        for value in ['..', '', '4,39', '4,399*', '-1', 'NaN', '1e3']:
            def edit(doc, caption, table, header, row):
                cell = row.xpath('./td|./th')[-2]
                cell.clear(); cell.text = value
            with self.subTest(value=value), self.assertRaises(c.CollectionError):
                c.extract(self.report, mutation(self.body, edit))

    def test_wrong_month_and_merged_cells_are_rejected(self):
        def month(doc, caption, table, header, row):
            cell = header.xpath('./td|./th')[-2]; cell.clear(); cell.text = 'Oct 26'
        def merged(doc, caption, table, header, row):
            row.xpath('./td|./th')[1].set('colspan', '2')
        for edit in [month, merged]:
            with self.subTest(case=edit.__name__), self.assertRaises(c.CollectionError):
                c.extract(self.report, mutation(self.body, edit))

    def test_wrong_publication_month_or_id_is_rejected(self):
        for r in [c.Report('2026-09', '162', chapter_url=self.report.chapter_url),
                  c.Report('2026-10', '999', chapter_url=self.report.chapter_url)]:
            with self.subTest(report=r), self.assertRaises(c.CollectionError):
                c.extract(r, self.body)

    def test_missing_month_in_index_is_not_silently_ignored(self):
        doc = c.document(self.client.get(c.INDEX))
        for anchor in doc.xpath('//a[@href]'):
            if anchor.get('href').rstrip('/') == '/momr/archive/150':
                anchor.getparent().remove(anchor)
        with self.assertRaises(c.CollectionError):
            c.discover(html.tostring(doc, encoding='utf-8'), year=2026, today=TODAY)

    def test_future_publication_is_rejected(self):
        with self.assertRaises(c.CollectionError):
            c.discover(self.client.get(c.INDEX), today=date(2026, 9, 1))


