import unittest
import tempfile
import os
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch
from night_reports.automation import DailyAutomation
from night_reports.collection import Collector, EOD
from night_reports.storage import Settings
from night_reports.service import PackService
from night_reports.outlook import DraftRef
from night_reports.manifest import manifest, identify
from night_reports.engine import inspect_pdf, validate_period
from tests.helpers import BUSINESS, AUDIT, pdf, report_text, TITLES

PREFIXES=dict(zip(('arrivals','packages','birthdays','events','groups','yesterday','revenue','manager','noshow','complimentary','forecast'),('res_detail','pkgforecast','pr_birthday','rep_event_list_detailed','rep_rooms_f','resreserveyesterday','findeptcodes','manrepht','noshow','gihcomp','history_forecast')))
class Adapter:
    def __init__(self):self.created=self.sent=0
    def create(self,files,settings,run,saved):
        self.created+=1;ref=DraftRef('entry','store');saved(ref);return ref
    def send(self,*args):self.sent+=1
    def reopen(self,*args):raise AssertionError('Automatic draft must remain hidden')

class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.source=self.root/'source';self.source.mkdir()
        self.audit=self.source/'audit'/AUDIT.strftime('%d%m%y');self.audit.mkdir(parents=True)
        self.adapter=Adapter();self.auto=DailyAutomation(self.root/'data',PackService(self.root/'data',self.adapter))
        self.settings=Settings(recipients=['test@example.com'],automation_enabled=True,scheduler_folder=str(self.source),last_folder=str(self.root/'output'))
        self.paths=[]
        for i,slot in enumerate(manifest(AUDIT,BUSINESS)):
            text=report_text(slot)
            if slot.rule.key=='forecast':text=text.replace(TITLES['forecast'],'Past and Future Forecast RS MONTH'+(f' +{i-10:02}' if i>10 else ''))
            elif slot.rule.key=='packages':text=text.replace(TITLES['packages'],'Package forecast RS')
            elif slot.rule.key=='events':text=text.replace(TITLES['events'],'Event List Detailed RS')
            elif slot.rule.key=='revenue':text=text.replace(TITLES['revenue'],'FIN01127 Revenue by transaction code all')
            target=(self.audit if slot.rule.key in EOD else self.source)/f'{PREFIXES[slot.rule.key]}{i}.pdf'
            pdf(target,text);os.utime(target,(self.at(7,1).timestamp(),)*2);self.paths.append(target)
    def tearDown(self):self.tmp.cleanup()
    def at(self,h,m):return datetime.combine(BUSINESS,datetime.min.time()).replace(hour=h,minute=m)
    def test_timing_restart_no_duplicate(self):
        self.auto.tick(self.settings,self.at(6,59));self.assertEqual(self.adapter.created,0)
        self.auto.tick(self.settings,self.at(7,5));self.assertEqual((self.adapter.created,self.adapter.sent),(1,0))
        self.auto.tick(self.settings,self.at(7,10))
        DailyAutomation(self.auto.root,self.auto.service).tick(self.settings,self.at(8,0))
        self.assertEqual((self.adapter.created,self.adapter.sent),(1,1))
    def test_uncertain_send_never_retried(self):
        with patch.object(self.adapter,'send',side_effect=RuntimeError('lost')) as send:
            with self.assertRaises(RuntimeError):self.auto.tick(self.settings,self.at(7,10))
            with self.assertRaises(ValueError):self.auto.tick(self.settings,self.at(7,11))
            self.assertEqual(send.call_count,1)
    def test_changed_attachment_blocks(self):
        self.auto.tick(self.settings,self.at(7,5))
        next((self.auto.root/'runs').rglob('Arrivals.pdf')).write_bytes(b'changed')
        with self.assertRaises(ValueError):self.auto.tick(self.settings,self.at(7,10))
        self.assertEqual(self.adapter.sent,0)
    def test_disabled_and_cutoff(self):
        self.auto.tick(self.settings,self.at(9,0));self.assertEqual(self.adapter.created,0)
        self.settings.automation_enabled=False;self.auto.tick(self.settings,self.at(7,15));self.assertEqual(self.adapter.created,0)
    def test_partial_progress_late_arrival_and_output_replacement(self):
        late=self.paths[0];data=late.read_bytes();late.unlink()
        events=[];self.auto.tick(self.settings,self.at(7,5),event=lambda k,v:events.append((k,v)))
        rows=events[0][1];self.assertEqual(sum(r['status']=='PASS' for r in rows),22)
        self.assertFalse(Path(self.settings.last_folder).exists())
        out=Path(self.settings.last_folder);out.mkdir();(out/'Arrivals.pdf').write_bytes(b'old');(out/'unrelated.pdf').write_bytes(b'not part of pack')
        late.write_bytes(data);os.utime(late,(self.at(7,6).timestamp(),)*2)
        self.auto.tick(self.settings,self.at(7,7),event=lambda k,v:events.append((k,v)))
        self.assertEqual((out/'Arrivals.pdf').read_bytes(),data)
        self.assertTrue((out/'unrelated.pdf').exists())
        self.assertEqual(self.adapter.created,1)
        self.assertTrue(any(k=='prepared' and v.ready for k,v in events))
        self.assertTrue(all(r['converted']=='Yes' for r in self.auto.collector.last_rows))
    def test_stale_group_blocks_even_correct_months(self):
        p=self.paths[4];slot=manifest(AUDIT,BUSINESS)[4]
        pdf(p,report_text(slot,business=BUSINESS-timedelta(days=1)));os.utime(p,(self.at(7,1).timestamp(),)*2)
        rows,chosen,_,_=self.auto.discover(self.settings,self.at(7,5))
        self.assertNotIn('groups',chosen);self.assertEqual(rows[4]['status'],'WRONG')
    def test_stale_file_timestamp_excluded(self):
        os.utime(self.paths[4],(self.at(7,1).timestamp()-86400,)*2)
        rows,chosen,_,_=self.auto.discover(self.settings,self.at(7,5))
        self.assertNotIn('groups',chosen)
    def test_forecast_offset_conflict(self):
        slot=manifest(AUDIT,BUSINESS)[11]
        p=self.paths[11];pdf(p,report_text(slot).replace(TITLES['forecast'],'Past and Future Forecast RS MONTH +02'))
        self.assertEqual(validate_period(slot,inspect_pdf(p),AUDIT,BUSINESS)[0],'WRONG')
    def test_all_scheduler_month_spellings(self):
        for i in range(13):
            for suffix in ([str(i),f'{i:02}'] if i else ['']):
                title='Past and Future Forecast RS MONTH'+(' +'+suffix if suffix else '')
                self.assertEqual(identify(title),('forecast',))
    def test_conflicting_exports_and_replacement(self):
        extra=self.source/'res_detail999.pdf';pdf(extra,report_text(manifest(AUDIT,BUSINESS)[0])+'\nDifferent');os.utime(extra,(self.at(7,1).timestamp(),)*2)
        rows,chosen,_,_=self.auto.discover(self.settings,self.at(7,5));self.assertEqual(rows[0]['status'],'DUPLICATE')
        self.auto.collector.replacement(BUSINESS,'arrivals',self.paths[0])
        rows,chosen,_,_=self.auto.discover(self.settings,self.at(7,5));self.assertIn('arrivals',chosen)
    def test_reuses_unchanged_pdf_parses(self):
        self.auto.discover(self.settings,self.at(7,5))
        with patch('night_reports.collection.inspect_pdf',side_effect=AssertionError('Should use cache')):
            self.auto.discover(self.settings,self.at(7,6))
    def test_cutoff_keeps_ready_draft_unsent(self):
        self.auto.tick(self.settings,self.at(7,5));self.auto.tick(self.settings,self.at(9,0));self.assertEqual(self.adapter.sent,0)
