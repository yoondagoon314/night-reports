from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from night_reports.outlook import OutlookAdapter, OutlookError, DraftRef
from night_reports.storage import Settings

class Attachments:
    def __init__(self):
        self.items = []
        self.fail_at = None
        self.corrupt = False
    @property
    def Count(self): return len(self.items)
    def Add(self, name, mode):
        if self.fail_at == len(self.items): raise RuntimeError('attachment failure')
        self.items.append((Path(name).name, Path(name).read_bytes()))
    def Item(self, index):
        name, data = self.items[index - 1]
        return SimpleNamespace(FileName=name, SaveAsFile=lambda p: Path(p).write_bytes(b'bad' if self.corrupt else data))

class Recipients:
    def __init__(self):
        self.items = []
        self.resolve = True
    @property
    def Count(self): return len(self.items)
    def Add(self, address):
        item = SimpleNamespace(Address=address, Type=None)
        self.items.append(item)
        return item
    def Remove(self, i): del self.items[i - 1]
    def ResolveAll(self): return self.resolve

class Properties:
    def __init__(self): self.props = {}
    def Add(self, key, kind):
        prop = SimpleNamespace(Value=None)
        self.props[key] = prop
        return prop
    def Find(self, key): return self.props.get(key)

class Mail:
    def __init__(self):
        self.Attachments = Attachments()
        self.Recipients = Recipients()
        self.UserProperties = Properties()
        self.EntryID = 'entry'
        self.Parent = SimpleNamespace(StoreID='store')
        self.Sent = False
        self.displayed = False
        self.saves = 0
    def Save(self): self.saves += 1
    def Display(self, modal): self.displayed = True
    def Send(self): raise AssertionError('Sending is forbidden')

class OutlookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.files = []
        for n in range(23):
            p = Path(self.temp.name) / f'report-{n:02}.pdf'
            p.write_bytes(f'Test attachment {n}'.encode())
            self.files.append(p)
        self.mail = Mail()
        self.app = SimpleNamespace(CreateItem=lambda kind: self.mail,
            Session=SimpleNamespace(GetItemFromID=lambda entry, store: self.mail))
        self.adapter = OutlookAdapter()
        self.saved = []
        self.settings = Settings(recipients=[f'test{n}@example.org' for n in range(17)])
    def create(self):
        return self.adapter._create(self.app, self.files, self.settings, 'run', self.saved.append)
    def test_exact_mail_and_attachment_order_no_send(self):
        ref = self.create()
        self.assertEqual(ref, DraftRef('entry', 'store'))
        self.assertEqual(self.saved, [ref])
        self.assertEqual(self.mail.Subject, self.settings.subject)
        self.assertEqual(self.mail.Body, self.settings.body)
        self.assertEqual([r.Address for r in self.mail.Recipients.items], self.settings.recipients)
        self.assertEqual([name for name, data in self.mail.Attachments.items], [p.name for p in self.files])
        self.assertFalse(self.mail.displayed)
        self.assertFalse(self.mail.Sent)
    def test_attachment_failure_saves_id_and_clears_recipients(self):
        self.mail.Attachments.fail_at = 4
        with self.assertRaises(OutlookError): self.create()
        self.assertEqual(len(self.saved), 1)
        self.assertEqual(self.mail.Recipients.Count, 0)
        self.assertIn('INCOMPLETE', self.mail.Subject)
    def test_attachment_bytes_verified(self):
        self.mail.Attachments.corrupt = True
        with self.assertRaises(OutlookError): self.create()
        self.assertEqual(self.mail.Recipients.Count, 0)
    def test_unresolved_recipient_blocks_and_clears_all(self):
        self.mail.Recipients.resolve = False
        with self.assertRaises(OutlookError): self.create()
        self.assertEqual(self.mail.Recipients.Count, 0)
        self.assertIn('INCOMPLETE', self.mail.Subject)
    def test_id_persistence_failure_prevents_distribution(self):
        def fail(ref): raise OSError('disk full')
        with self.assertRaises(OutlookError):
            self.adapter._create(self.app, self.files, self.settings, 'run', fail)
        self.assertEqual(self.mail.Recipients.Count, 0)
        self.assertEqual(self.mail.Attachments.Count, 0)
    def test_reopen_validates_then_displays(self):
        ref = self.create()
        @contextmanager
        def app(): yield self.app
        with patch('night_reports.outlook.outlook_application', app):
            self.adapter.reopen(ref, self.files, 'run')
        self.assertTrue(self.mail.displayed)
    def test_already_sent_blocks_reopen(self):
        ref = self.create()
        self.mail.Sent = True
        @contextmanager
        def app(): yield self.app
        with patch('night_reports.outlook.outlook_application', app), self.assertRaises(OutlookError):
            self.adapter.reopen(ref, self.files, 'run')
        self.assertFalse(self.mail.displayed)
    def test_wrong_run_blocks_reopen(self):
        ref = self.create()
        @contextmanager
        def app(): yield self.app
        with patch('night_reports.outlook.outlook_application', app), self.assertRaises(OutlookError):
            self.adapter.reopen(ref, self.files, 'wrong')
    def test_send_checks_recipients_and_attachments(self):
        ref = self.create()
        for recipient in self.mail.Recipients.items:
            recipient.AddressEntry = SimpleNamespace(Type='SMTP', Address=recipient.Address)
        self.mail.Recipients.Item = lambda i: self.mail.Recipients.items[i-1]
        calls = []
        self.mail.Send = lambda: calls.append('submitted')
        @contextmanager
        def app(): yield self.app
        with patch('night_reports.outlook.outlook_application', app):
            self.adapter.send(ref, self.files, 'run', self.settings)
            self.assertEqual(calls, ['submitted'])
            self.mail.Recipients.items[0].AddressEntry.Address = 'other@example.org'
            with self.assertRaises(OutlookError):
                self.adapter.send(ref, self.files, 'run', self.settings)
            self.assertEqual(calls, ['submitted'])

    def test_non_windows_compatibility_explains_requirement(self):
        with patch('night_reports.outlook.sys.platform', 'darwin'), self.assertRaisesRegex(OutlookError, 'classic Outlook on Windows'):
            self.adapter.compatibility()

if __name__ == '__main__': unittest.main()
