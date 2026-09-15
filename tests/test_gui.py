"""Opt-in native window tests. Never opens Outlook or report viewers."""
from pathlib import Path
import os
import tempfile
import time
import unittest
from tests.helpers import pack, ready, AUDIT, BUSINESS

@unittest.skipUnless(os.environ.get('MAISON_GUI_TESTS') == '1', 'Native GUI smoke test is opt-in')
class GuiTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from night_reports.gui import Window
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = Window(self.root, Path(self.temp.name) / 'data')
        self.folder = pack(Path(self.temp.name) / 'input')
        self.app.folder.set(str(self.folder))
        self.app.audit.set(AUDIT.isoformat())
        self.app.business.set(BUSINESS.isoformat())
        self.app.confirmed.set(True)
        self.root.update()
    def tearDown(self):
        self.app.pool.shutdown(wait=True)
        self.root.destroy()
    def test_check_and_input_invalidation(self):
        self.app.start_check()
        deadline = time.monotonic() + 10
        while self.app.busy and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.02)
        self.assertFalse(self.app.busy)
        self.assertEqual(len(self.app.table.get_children()), 23)
        self.assertNotIn('disabled', self.app.draft_button.state())
        self.app.check = ready(self.folder)
        self.app.render()
        self.assertNotIn('disabled', self.app.draft_button.state())
        self.app.business.set('2026-09-12')
        self.assertIsNone(self.app.check)
        self.assertFalse(self.app.confirmed.get())
        self.assertIn('disabled', self.app.draft_button.state())
    def test_double_click_busy_guard(self):
        self.app.check = ready(self.folder)
        self.app.busy = True
        self.app.update_buttons()
        self.assertIn('disabled', self.app.draft_button.state())
        self.app.draft()
        self.assertFalse((self.app.data_root / 'runs').exists())
    def test_file_watcher_invalidates(self):
        self.app.check = ready(self.folder)
        self.app.stamp = self.app.folder_stamp()
        (self.folder / 'export-00.pdf').write_bytes(b'changed')
        self.app.watch()
        self.assertIsNone(self.app.check)

if __name__ == '__main__': unittest.main()
