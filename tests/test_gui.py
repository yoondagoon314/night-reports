"""Native Windows UI tests; no Outlook access or real report sources."""
from pathlib import Path
import os
import tempfile
import time
import unittest
from unittest.mock import patch
from tests.helpers import pack, ready, AUDIT, BUSINESS

@unittest.skipUnless(os.environ.get('MAISON_GUI_TESTS')=='1','Native GUI smoke test is opt-in')
class GuiTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from night_reports.gui import Window
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=tk.Tk();self.root.withdraw();self.app=Window(self.root,Path(self.temp.name)/'data')
        self.folder=pack(Path(self.temp.name)/'input')
        self.app.folder.set(str(self.folder));self.app.audit.set(AUDIT.isoformat());self.app.business.set(BUSINESS.isoformat())
    def tearDown(self):
        self.app.pool.shutdown(wait=True);self.root.destroy()
    def test_source_and_prepared_views(self):
        check=ready(self.folder)
        rows=[dict(key=r.slot.key,report=r.slot.label,original=r.document.path.name,source=str(r.document.path),retrieved='07:01',created='07:01',modified='07:01',issue=str(BUSINESS),name=r.slot.filename,converted='No',status='PASS',reason='Matches') for r in check.rows]
        def discover(*args,**kwargs):
            kwargs['event']('sources',rows);return rows,{}, {},'23 reports found'
        with patch.object(self.app.automation,'discover',side_effect=discover):
            self.app.start_check();deadline=time.monotonic()+10
            while self.app.busy and time.monotonic()<deadline:self.root.update();time.sleep(.02)
        self.assertFalse(self.app.busy);self.assertEqual(len(self.app.source_table.get_children()),23)
        self.assertEqual(len(self.app.table.get_children()),0)
        self.app.events.put(('prepared',check));self.app.poll()
        self.assertEqual(len(self.app.table.get_children()),23)
        self.assertEqual(self.app.tabs.select(),str(self.app.prepared_page))
        self.assertNotIn('disabled',self.app.draft_button.state())
        self.app.business.set('2026-09-12');self.assertIsNone(self.app.check)
    def test_double_click_busy_guard(self):
        self.app.check=ready(self.folder);self.app.busy=True;self.app.update_buttons();self.app.draft()
        self.assertFalse((self.app.data_root/'runs').exists())
    def test_file_watcher_invalidates(self):
        self.app.check=ready(self.folder);self.app.stamp=self.app.folder_stamp()
        (self.folder/'export-00.pdf').write_bytes(b'changed');self.app.watch();self.assertIsNone(self.app.check)
    def test_log_and_progress(self):
        self.app.status.set('Test step complete');self.app.toggle_log();self.root.update()
        self.assertIn('Test step complete',self.app.log_text.get('1.0','end'))
        self.app.events.put(('progress',(65,'Verified')));self.app.poll()
        self.assertEqual(self.app.progress_value.get(),65)
    def test_settings_opens(self):
        self.app.edit_settings();self.root.update()
        self.assertTrue(any(w.winfo_class()=='Toplevel' for w in self.root.winfo_children()))
