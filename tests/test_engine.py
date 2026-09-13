from datetime import date
from pathlib import Path
import json
import tempfile
import unittest
from pypdf import PdfReader, PdfWriter
from night_reports.engine import scan, inspect_pdf, extract_period
from night_reports.manifest import manifest
from tests.helpers import AUDIT, BUSINESS, TITLES, pack, pdf, ready, report_text


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = pack(Path(self.temp.name) / 'input')
        self.slots = manifest(AUDIT, BUSINESS)

    def check(self):
        return scan(self.folder, AUDIT, BUSINESS)

    def test_complete_pack_needs_documented_reviews(self):
        c = self.check()
        self.assertEqual([r.slot.key for r in c.rows if r.status == 'REVIEW'], ['events', 'groups'])
        self.assertFalse(c.ready)
        self.assertTrue(ready(self.folder).ready)

    def test_missing_fixed(self):
        (self.folder / 'export-00.pdf').unlink()
        self.assertEqual(self.check().rows[0].status, 'MISSING')

    def test_missing_forecast(self):
        (self.folder / 'export-11.pdf').unlink()
        c = self.check()
        self.assertEqual(c.rows[11].status, 'MISSING')
        self.assertIn('October', c.rows[11].message)

    def test_filename_does_not_determine_identity(self):
        (self.folder / 'export-00.pdf').rename(self.folder / 'Manager flash.pdf')
        c = ready(self.folder)
        self.assertEqual(c.rows[0].document.path.name, 'Manager flash.pdf')
        self.assertEqual(c.rows[0].slot.filename, 'Arrivals.pdf')

    def test_corrupt_pdf_blocks(self):
        (self.folder / 'export-00.pdf').write_bytes(b'%PDF-1.4 invalid %%EOF')
        c = self.check()
        self.assertFalse(c.ready)
        self.assertTrue(any(block for _, _, block in c.extras))

    def test_corrupt_extra_blocks(self):
        (self.folder / 'extra.pdf').write_bytes(b'broken')
        c = self.check()
        self.assertTrue(c.extras[0][2])

    def test_valid_empty_report(self):
        self.assertEqual(self.check().rows[8].status, 'PASS')

    def test_wrong_date_cannot_be_overridden(self):
        pdf(self.folder / 'export-07.pdf', report_text(self.slots[7]).replace('10.09.26', '09.09.26'))
        c = self.check()
        self.assertEqual(c.rows[7].status, 'WRONG')
        c.mark_opened(c.rows[7].document.path)
        with self.assertRaises(ValueError):
            c.confirm_date('manager', 'TEST', 'not allowed')

    def test_unreadable_date_requires_open_and_record(self):
        pdf(self.folder / 'export-00.pdf', report_text(self.slots[0], missing_date=True))
        c = self.check()
        self.assertEqual(c.rows[0].status, 'REVIEW')
        with self.assertRaises(ValueError):
            c.confirm_date('arrivals', 'TEST', 'checked')
        c.mark_opened(c.rows[0].document.path)
        with self.assertRaises(ValueError):
            c.confirm_date('arrivals', '', '')
        c.confirm_date('arrivals', 'YD', '11.09.2026 checked')
        self.assertEqual(c.rows[0].status, 'CONFIRMED')
        self.assertEqual(c.record()['reports'][0]['confirmation']['reviewer'], 'YD')

    def test_duplicate_blocks(self):
        (self.folder / 'copy.pdf').write_bytes((self.folder / 'export-00.pdf').read_bytes())
        self.assertEqual(self.check().rows[0].status, 'DUPLICATE')

    def test_unrelated_extra_excluded(self):
        pdf(self.folder / 'extra.pdf', 'Unrelated housekeeping document')
        c = ready(self.folder)
        self.assertEqual(len(c.extras), 1)
        self.assertFalse(c.extras[0][2])

    def test_unknown_forecast_never_guesses_month(self):
        pdf(self.folder / 'export-11.pdf', report_text(self.slots[11], missing_date=True))
        c = self.check()
        self.assertEqual(c.rows[11].status, 'MISSING')
        doc = c.extras[0][0]
        with self.assertRaises(ValueError):
            c.assign_forecast(doc.path, self.slots[11].key)
        c.mark_opened(doc.path)
        c.assign_forecast(doc.path, self.slots[11].key)
        self.assertEqual(c.rows[11].status, 'REVIEW')
        c.confirm_date(self.slots[11].key, 'YD', 'October 2026, generated 11.09.2026')
        self.assertEqual(c.rows[11].status, 'CONFIRMED')

    def test_stale_forecast_blocks_even_without_period(self):
        pdf(self.folder / 'export-11.pdf', report_text(self.slots[11], date(2026, 9, 10), missing_date=True))
        c = self.check()
        d = c.extras[0][0]
        c.mark_opened(d.path)
        c.assign_forecast(d.path, self.slots[11].key)
        self.assertEqual(c.rows[11].status, 'WRONG')

    def test_stale_forecast_with_period(self):
        pdf(self.folder / 'export-10.pdf', report_text(self.slots[10], date(2026, 9, 10)))
        self.assertEqual(self.check().rows[10].status, 'WRONG')

    def test_forecast_missing_issue_requires_review(self):
        pdf(self.folder / 'export-10.pdf', report_text(self.slots[10], issue=False))
        self.assertEqual(self.check().rows[10].status, 'REVIEW')

    def test_partial_month_wrong(self):
        pdf(self.folder / 'export-10.pdf', report_text(self.slots[10]).replace('30.09.26', '29.09.26'))
        self.assertEqual(self.check().rows[10].status, 'WRONG')

    def test_readable_wrong_start_with_unreadable_end_blocks(self):
        pdf(self.folder / 'export-00.pdf', report_text(self.slots[0]).replace('From Date 11.09.26 To Date 11.09.26', 'From Date 10.09.26 To Date unreadable'))
        self.assertEqual(self.check().rows[0].status, 'WRONG')

    def test_readable_wrong_end_with_unreadable_start_blocks(self):
        pdf(self.folder / 'export-00.pdf', report_text(self.slots[0]).replace('From Date 11.09.26 To Date 11.09.26', 'From Date unreadable To Date 10.09.26'))
        self.assertEqual(self.check().rows[0].status, 'WRONG')

    def test_readable_correct_start_with_unreadable_end_reviews(self):
        pdf(self.folder / 'export-00.pdf', report_text(self.slots[0]).replace('To Date 11.09.26', 'To Date unreadable'))
        self.assertEqual(self.check().rows[0].status, 'REVIEW')

    def test_year_rollover_and_filenames(self):
        slots = manifest(date(2026, 12, 31), date(2027, 1, 1))
        self.assertEqual(slots[10].filename, 'HF January EUR.pdf')
        self.assertEqual(slots[22].filename, 'HF January 2028 EUR.pdf')
        self.assertEqual(slots[22].start, date(2028, 1, 1))
        dec = manifest(date(2026, 12, 1), date(2026, 12, 2))
        self.assertEqual(dec[11].filename, 'HF January 2027 EUR.pdf')

    def test_leap_february(self):
        slots = manifest(date(2028, 1, 31), date(2028, 2, 1))
        self.assertEqual(slots[10].end, date(2028, 2, 29))
        self.assertEqual(slots[22].end, date(2029, 2, 28))
        ready(pack(Path(self.temp.name) / 'leap', date(2028, 1, 31), date(2028, 2, 1)), date(2028, 1, 31), date(2028, 2, 1))

    def test_files_changed_after_check(self):
        c = ready(self.folder)
        pdf(self.folder / 'extra.pdf', 'extra')
        with self.assertRaises(ValueError):
            c.assert_unchanged()

    def test_guest_dates_ignored(self):
        p = extract_period('11.09.26\nRES01145 Reservations - made Yesterday', ('Guest arrival 10.09.26 departure 12.09.26',), 'yesterday')
        self.assertIsNone(p.start)
        self.assertEqual(p.issue, BUSINESS)

    def test_conflicting_pages_block(self):
        pdf(self.folder / 'export-00.pdf', report_text(self.slots[0]), report_text(self.slots[0]).replace('11.09.26', '12.09.26'))
        self.assertEqual(self.check().rows[0].status, 'WRONG')

    def test_combined_report_types_block(self):
        p = pdf(self.folder / 'export-00.pdf', report_text(self.slots[0]), report_text(self.slots[1]))
        self.assertIn('Multiple', inspect_pdf(p).error)

    def test_truncated_pdf_blocks(self):
        p = self.folder / 'export-00.pdf'
        p.write_bytes(p.read_bytes()[:-20])
        self.assertTrue(inspect_pdf(p).error)

    def test_encrypted_pdf_blocks(self):
        p = self.folder / 'export-00.pdf'
        w = PdfWriter()
        w.append(PdfReader(p))
        w.encrypt('secret')
        w.write(p)
        self.assertIn('Encrypted', inspect_pdf(p).error)

    def test_wrong_breakfast_filter(self):
        pdf(self.folder / 'export-01.pdf', report_text(self.slots[1]).replace('BKF', 'DINNER'))
        self.assertEqual(self.check().rows[1].status, 'WRONG')

    def test_missing_breakfast_filter_needs_review(self):
        pdf(self.folder / 'export-01.pdf', report_text(self.slots[1]).replace('Pkg. Forecast Group BKF', ''))
        self.assertEqual(self.check().rows[1].status, 'REVIEW')

    def test_wrong_forecast_filter_blocks(self):
        pdf(self.folder / 'export-10.pdf', report_text(self.slots[10]).replace('Non-Deduct N', 'Non-Deduct Y'))
        self.assertEqual(self.check().rows[10].status, 'WRONG')

    def test_missing_forecast_filter_needs_review(self):
        pdf(self.folder / 'export-10.pdf', report_text(self.slots[10]).replace('Room Revenue Net Distributed Y', ''))
        self.assertEqual(self.check().rows[10].status, 'REVIEW')

    def test_forecast_body_revenue_is_not_a_parameter(self):
        pdf(self.folder / 'export-10.pdf', report_text(self.slots[10]) + '\nhistory_forecast\nRoom Revenue 714')
        self.assertEqual(self.check().rows[10].status, 'PASS')

    def test_known_wrong_period_beats_unreadable_filter(self):
        pdf(self.folder / 'export-10.pdf', report_text(self.slots[10]).replace('Room Revenue Net Distributed Y', '').replace('30.09.26', '29.09.26'))
        self.assertEqual(self.check().rows[10].status, 'WRONG')

    def test_financial_calendar_period(self):
        for kind in ['manager', 'revenue']:
            text = '11.09.26\n' + TITLES[kind] + '\nCalendar/ Month to Date (Date 10.09.26)'
            self.assertEqual(extract_period(text, (text,), kind).start, AUDIT)

    def test_yesterday_wrong_issue(self):
        pdf(self.folder / 'export-05.pdf', report_text(self.slots[5], date(2026, 9, 10)))
        self.assertEqual(self.check().rows[5].status, 'WRONG')

    def test_invalid_business_day(self):
        with self.assertRaises(ValueError):
            manifest(BUSINESS, AUDIT)

    def test_records_do_not_contain_extracted_text(self):
        pdf(self.folder / 'export-00.pdf', report_text(self.slots[0]) + '\nPRIVATE_GUEST_MARKER')
        self.assertNotIn('PRIVATE_GUEST_MARKER', json.dumps(self.check().record()))


if __name__ == '__main__':
    unittest.main()
