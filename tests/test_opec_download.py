import copy
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from lxml import html

pytestmark = pytest.mark.usefixtures("no_network")

import downloads
import opec_momr as o
import fetchers as f

FIX=Path(__file__).parent/'fixtures'/'opec'
TODAY=date(2026,11,3)


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.raw=Path(self.temp.name)/'raw';self.raw.mkdir()
        manifest=json.loads((FIX/'routes.json').read_text())
        self.responses={url:(FIX/r['file']).read_bytes() for url,r in manifest.items()}
        self.calls=[]
        self.mock=patch.object(f,'_get',side_effect=self.get);self.mock.start();self.addCleanup(self.mock.stop)

    def get(self,url,**kwargs):
        self.calls.append(url);value=self.responses[url]
        if isinstance(value,Exception):raise value
        return value

    def run_fetch(self):
        return f.fetch_opec_momr(self.raw,TODAY,self.raw/'manifest.yaml')

    def historical(self):
        directory=self.raw/'transcribed';directory.mkdir()
        (directory/'opec_momr_crude_direct_2026-10-25.csv').write_text('series_id,period,value\ncrude_production_direct,2026-06,3915\n')

    def revised(self):
        report=o.discover(self.responses[o.INDEX],today=TODAY)[0]
        doc=o.document(self.responses[report.chapter_url])
        caption=next(n for n in doc.xpath('//h6') if 'direct communication' in n.text_content().lower())
        table=caption.xpath('following::table[1]')[0]
        row=next(r for r in table.xpath('.//tr') if o.normalize(r.xpath('./td')[0].text_content())=='Iraq')
        cell=row.xpath('./td')[-2];cell.clear();cell.text='4,400'
        self.responses[report.chapter_url]=html.tostring(doc,encoding='utf-8')

    def test_latest_capture_roundtrip_and_repeat(self):
        saved=self.run_fetch();self.assertEqual(len(saved),1)
        meta,report,obs=o.read_capture(saved[0].read_bytes())
        self.assertEqual(report.period,'2026-10');self.assertEqual(obs[-1]['value'],'4399')
        self.assertEqual(meta['html'].encode(),self.responses[report.chapter_url])
        self.assertEqual(downloads.vintage_of(saved[0]),'2026-11-03')
        before={p.name:p.read_bytes() for p in (self.raw/'opec').glob('*')}
        self.assertIsNone(self.run_fetch())
        self.assertEqual(before,{p.name:p.read_bytes() for p in (self.raw/'opec').glob('*')})

    def test_catch_up_from_historical_record(self):
        self.historical();saved=self.run_fetch()
        self.assertEqual([o.read_capture(p.read_bytes())[1].period for p in saved],['2026-08','2026-09','2026-10'])
        self.assertIsNone(self.run_fetch())

    def test_same_day_revision_does_not_overwrite_previous_capture(self):
        first=self.run_fetch()[0];original=first.read_bytes()
        self.revised();second=self.run_fetch()[0]
        self.assertNotEqual(first,second);self.assertEqual(first.read_bytes(),original)
        self.assertEqual(o.read_capture(second.read_bytes())[2][-1]['value'],'4400')
        self.assertIsNone(self.run_fetch())

    def test_unrelated_html_change_does_not_make_new_capture(self):
        self.run_fetch();report=o.discover(self.responses[o.INDEX],today=TODAY)[0]
        self.responses[report.chapter_url]=self.responses[report.chapter_url].replace(b'</body>',b'<p>New footer</p></body>')
        self.assertIsNone(self.run_fetch())

    def test_one_failed_catch_up_report_saves_nothing(self):
        self.historical();url='https://publications.opec.org/momr/archive/chapter/161/3019'
        self.responses[url]=TimeoutError('simulated outage')
        with self.assertRaises(TimeoutError):self.run_fetch()
        self.assertFalse((self.raw/'opec').exists())

    def test_failure_preserves_existing_capture(self):
        saved=self.run_fetch()[0];before=saved.read_bytes()
        report=o.discover(self.responses[o.INDEX],today=TODAY)[0]
        self.responses[report.chapter_url]=b'<html>Maintenance</html>'
        with self.assertRaises(o.CollectionError):self.run_fetch()
        self.assertEqual(saved.read_bytes(),before)

    def test_corrupt_capture_is_rejected(self):
        saved=self.run_fetch()[0];meta=json.loads(saved.read_text());meta['html']+='tampered'
        saved.write_text(json.dumps(meta))
        with self.assertRaises(o.CollectionError):self.run_fetch()

    def test_capture_timezone_is_required(self):
        saved=self.run_fetch()[0];meta=json.loads(saved.read_text());meta['retrieved_at']='2026-11-03T12:00:00'
        with self.assertRaises(o.CollectionError):o.read_capture(json.dumps(meta).encode())

    def test_source_identity_is_required(self):
        saved=self.run_fetch()[0];meta=json.loads(saved.read_text());meta['source_url']='https://example.com/momr/chapter/162/3037'
        with self.assertRaises(o.CollectionError):o.read_capture(json.dumps(meta).encode())

    def test_numeric_formatting_does_not_count_as_revision(self):
        self.assertEqual(o.observation_signature([{'date':'2026-09','value':'4399','unit':'TB_PER_D'}]),
                         o.observation_signature([{'date':'2026-09','value':'4399.0','unit':'TB_PER_D'}]))


if __name__=='__main__':unittest.main()
