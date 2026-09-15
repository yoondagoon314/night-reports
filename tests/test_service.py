from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
from night_reports.engine import file_digest
from night_reports.outlook import DraftRef, OutlookError
from night_reports.service import PackService
from night_reports.storage import FileLock, Settings
from tests.helpers import pack, ready


class FakeAdapter:
    def __init__(self):
        self.creates, self.opens = 0, 0
        self.fail_create = self.fail_open = False
        self.files = []

    def create(self, files, settings, run_id, on_saved):
        self.creates += 1
        self.files = files
        ref = DraftRef(f'entry-{self.creates}', 'store')
        on_saved(ref)
        if self.fail_create:
            raise OutlookError('Simulated attachment failure')
        return ref

    def reopen(self, ref, files, run_id):
        self.opens += 1
        if self.fail_open:
            raise OutlookError('Simulated unavailable Outlook')


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.check = ready(pack(self.root / 'input'))
        self.adapter = FakeAdapter()
        self.service = PackService(self.root / 'data', self.adapter)
        self.settings = Settings(recipients=[f'test{n}@example.org' for n in range(17)])

    def test_preparation_preserves_originals_order_names_and_confirmation(self):
        before = self.check.snapshot
        self.assertIn('Draft ready', self.service.prepare(self.check, self.settings))
        self.assertEqual(before, {str(p.resolve()): file_digest(p) for p in (self.root / 'input').iterdir()})
        self.assertEqual([p.name for p in self.adapter.files], [r.slot.filename for r in self.check.rows])
        record = self.service.existing(self.check)
        self.assertEqual(record['state'], 'ready')
        self.assertEqual(record['check']['reports'][3]['status'], 'PASS')
        self.assertIsNone(record['check']['reports'][3]['confirmation'])
        self.assertEqual(record['email']['recipient_count'], 17)
        self.assertEqual(len(record['files']), 23)

    def test_repeat_and_restart_reopen_same_draft(self):
        self.service.prepare(self.check, self.settings)
        restarted = PackService(self.root / 'data', self.adapter)
        self.assertIn('Existing', restarted.prepare(self.check, self.settings))
        self.assertEqual(self.adapter.creates, 1)
        self.assertEqual(self.adapter.opens, 2)

    def test_settings_change_requires_explicit_replacement(self):
        self.service.prepare(self.check, self.settings)
        self.settings.subject = 'Changed subject'
        with self.assertRaisesRegex(ValueError, 'settings changed'):
            self.service.prepare(self.check, self.settings)
        self.assertEqual(self.adapter.creates, 1)

    def test_copy_change_during_outlook_prevents_ready_display(self):
        create = self.adapter.create
        def changed(files, settings, attempt, callback):
            ref = create(files, settings, attempt, callback)
            files[0].write_bytes(b'changed after attachment')
            return ref
        with patch.object(self.adapter, 'create', side_effect=changed), self.assertRaises(ValueError):
            self.service.prepare(self.check, self.settings)
        self.assertEqual(self.adapter.opens, 0)
        self.assertEqual(self.service.existing(self.check)['state'], 'uncertain')

    def test_explicit_another_creates_and_archives_record(self):
        self.service.prepare(self.check, self.settings)
        self.service.prepare(self.check, self.settings, another=True)
        self.assertEqual(self.adapter.creates, 2)
        self.assertEqual(len(list(self.service.run_folder(self.check).glob('previous-*.json'))), 1)

    def test_attachment_failure_is_uncertain_and_blocks_retry(self):
        self.adapter.fail_create = True
        with self.assertRaises(OutlookError):
            self.service.prepare(self.check, self.settings)
        record = self.service.existing(self.check)
        self.assertEqual(record['state'], 'uncertain')
        self.assertIsNotNone(record['draft'])
        self.adapter.fail_create = False
        with self.assertRaises(ValueError):
            self.service.prepare(self.check, self.settings)
        self.assertEqual(self.adapter.creates, 1)

    def test_display_failure_does_not_create_duplicate(self):
        self.adapter.fail_open = True
        with self.assertRaises(OutlookError):
            self.service.prepare(self.check, self.settings)
        self.assertEqual(self.service.existing(self.check)['state'], 'ready')
        self.adapter.fail_open = False
        self.service.prepare(self.check, self.settings)
        self.assertEqual(self.adapter.creates, 1)

    def test_source_change_during_preparation_blocks_outlook(self):
        original_copy = self.service._copy_pack
        def changed(check, directory):
            files = original_copy(check, directory)
            check.rows[0].document.path.write_bytes(b'changed')
            return files
        with patch.object(self.service, '_copy_pack', side_effect=changed):
            with self.assertRaises(ValueError):
                self.service.prepare(self.check, self.settings)
        self.assertEqual(self.adapter.creates, 0)
        self.assertEqual(self.service.existing(self.check)['state'], 'failed')

    def test_source_changes_during_copy_are_detected(self):
        from night_reports import service as module
        original = module.inspect_pdf
        def altered(path):
            path.write_bytes(path.read_bytes() + b'CORRUPTION')
            return original(path)
        with patch.object(module, 'inspect_pdf', side_effect=altered):
            with self.assertRaises(ValueError):
                self.service.prepare(self.check, self.settings)
        self.assertEqual(self.adapter.creates, 0)

    def test_saved_copy_change_blocks_reopen(self):
        self.service.prepare(self.check, self.settings)
        self.adapter.files[0].write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.service.prepare(self.check, self.settings)
        self.assertEqual(self.adapter.creates, 1)

    def test_run_lock_prevents_concurrent_draft(self):
        with FileLock(self.root / 'data' / 'draft.lock'):
            with self.assertRaises(ValueError):
                self.service.prepare(self.check, self.settings)
        self.assertEqual(self.adapter.creates, 0)
        self.service.prepare(self.check, self.settings)

    def test_settings_roundtrip_and_exact_defaults(self):
        self.settings.save(self.root / 'data')
        loaded = Settings.load(self.root / 'data')
        self.assertEqual(loaded, self.settings)
        self.assertEqual(loaded.subject, 'RE: Night reports')
        self.assertEqual(len(loaded.recipients), 17)
        self.assertTrue(loaded.body.endswith('Front Office'))
        self.assertIn('test0@example.org', loaded.recipients)
        self.assertIn('test1@example.org', loaded.recipients)

    def test_corrupt_settings_not_silently_reset(self):
        (self.root / 'settings.json').write_text('{')
        with self.assertRaises(ValueError):
            Settings.load(self.root)

    def test_invalid_settings_block_outlook(self):
        self.settings.recipients = ['not an email']
        with self.assertRaises(ValueError):
            self.service.prepare(self.check, self.settings)
        self.assertEqual(self.adapter.creates, 0)

    def test_corrupt_run_record_blocks_duplicates(self):
        self.service.prepare(self.check, self.settings)
        (self.service.run_folder(self.check) / 'run.json').write_text('{')
        with self.assertRaises(ValueError):
            self.service.prepare(self.check, self.settings)
        self.assertEqual(self.adapter.creates, 1)


if __name__ == '__main__':
    unittest.main()

class CloudSettingsTests(unittest.TestCase):
    def test_cloud_defaults_have_no_distribution(self):
        settings = Settings()
        self.assertEqual(settings.recipients, [])
        with self.assertRaises(ValueError):
            settings.validate()

    def test_blank_mail_settings_can_be_stored_for_check_only_use(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            Settings().save(root)
            self.assertEqual(Settings.load(root).recipients, [])
