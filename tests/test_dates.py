import unittest
from datetime import date
from night_reports.dates import read_day
class DateTests(unittest.TestCase):
    def test_calendar_and_partial_year(self):
        self.assertEqual(read_day('19.05.'+str(date.today().year)[:3]),date(date.today().year,5,19))
        self.assertEqual(read_day('19.05'),date(date.today().year,5,19))
        self.assertEqual(read_day('19.05.26'),date(2026,5,19))
        self.assertEqual(read_day('2026-05-19'),date(2026,5,19))
    def test_invalid_dates_not_guessed(self):
        for value in ('31.02.2026','19.05.123','garbage'):
            with self.assertRaises(ValueError):read_day(value)
