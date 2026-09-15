import unittest
import tempfile
from pathlib import Path
from datetime import datetime
from unittest.mock import patch
from night_reports.automation import DailyAutomation
from night_reports.storage import Settings
from night_reports.service import PackService
from night_reports.outlook import DraftRef
from tests.helpers import pack, ready, BUSINESS

class Adapter:
    def __init__(self): self.created = self.sent = 0
    def create(self, files, settings, run, saved):
        self.created += 1
        ref = DraftRef('entry', 'store'); saved(ref); return ref
    def send(self, *args): self.sent += 1
    def reopen(self, *args): raise AssertionError('Scheduled draft must stay hidden')

class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.check = ready(pack(self.root / 'pack'))
        self.adapter = Adapter()
        self.auto = DailyAutomation(self.root / 'data', PackService(self.root / 'data', self.adapter))
        self.settings = Settings(recipients=['test@example.com'], automation_enabled=True)
    def tearDown(self): self.tmp.cleanup()
    def at(self, hour, minute): return datetime.combine(BUSINESS, datetime.min.time()).replace(hour=hour, minute=minute)
    def test_timing_restart_no_duplicate(self):
        with patch('night_reports.automation.collect', return_value=self.check) as collector:
            self.auto.tick(self.settings, self.at(7,4)); collector.assert_not_called()
            self.auto.tick(self.settings, self.at(7,5))
            self.assertEqual((self.adapter.created,self.adapter.sent), (1,0))
            self.auto.tick(self.settings, self.at(7,9))
            self.auto.tick(self.settings, self.at(7,10))
            DailyAutomation(self.auto.root,self.auto.service).tick(self.settings,self.at(8,0))
            self.assertEqual((self.adapter.created,self.adapter.sent), (1,1))
    def test_uncertain_send_never_retried(self):
        with patch('night_reports.automation.collect', return_value=self.check):
            with patch.object(self.adapter,'send',side_effect=RuntimeError('lost')) as send:
                with self.assertRaises(RuntimeError): self.auto.tick(self.settings,self.at(7,10))
                with self.assertRaises(ValueError): self.auto.tick(self.settings,self.at(7,11))
                self.assertEqual(send.call_count,1)
    def test_changed_attachment_blocks(self):
        with patch('night_reports.automation.collect', return_value=self.check):
            self.auto.tick(self.settings,self.at(7,5))
            next((self.auto.root/'runs').rglob('Arrivals.pdf')).write_bytes(b'changed')
            with self.assertRaises(ValueError): self.auto.tick(self.settings,self.at(7,10))
            self.assertEqual(self.adapter.sent,0)
    def test_disabled(self):
        self.settings.automation_enabled=False
        self.auto.tick(self.settings,self.at(9,0)); self.assertEqual(self.adapter.created,0)
    def test_collect_renames_and_rejects_conflicting_exports(self):
        import os
        from night_reports.automation import collect, EOD
        from night_reports.manifest import manifest
        from tests.helpers import AUDIT, pdf, report_text
        source=self.root/'source'; source.mkdir()
        audit=source/'audit'/AUDIT.strftime('%d%m%y'); audit.mkdir(parents=True)
        prefixes=dict(zip(('arrivals','packages','birthdays','events','groups','yesterday','revenue','manager','noshow','complimentary','forecast'),('res_detail','pkgforecast','pr_birthday','rep_event_list_detailed','rep_rooms_f','resreserveyesterday','findeptcodes','manrepht','noshow','gihcomp','history_forecast')))
        for i,slot in enumerate(manifest(AUDIT,BUSINESS)):
            target=(audit if slot.rule.key in EOD else source)/f'{prefixes[slot.rule.key]}{i}.pdf'
            pdf(target,report_text(slot))
            os.utime(target,(self.at(7,1).timestamp(),)*2)
        result=collect(self.root,source,self.at(7,5),lambda *args:None)
        self.assertTrue(result.ready)
        self.assertTrue(all(r.document.path.name==r.slot.filename for r in result.rows))
        target=source/'res_detail999.pdf'
        pdf(target,report_text(manifest(AUDIT,BUSINESS)[0])+'\nDifferent content')
        os.utime(target,(self.at(7,1).timestamp(),)*2)
        with self.assertRaises(ValueError): collect(self.root,source,self.at(7,5),lambda *args:None)
