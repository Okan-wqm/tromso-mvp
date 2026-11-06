"""What a page reads from its address follows one rule (core.query, F-006, F-176, F-120): a value that is not well
formed, or lies outside what the page can show, is taken as not given (None)."""
from datetime import date

from django.test import SimpleTestCase

from . import query


class ParserTests(SimpleTestCase):
    def test_a_day_is_written_yyyy_mm_dd_and_lies_in_the_calendar_the_pages_show(self):
        self.assertEqual(query.day('2026-11-06'), date(2026, 11, 6))
        for value in ('2026-13-45', '2026-02-30', '20261106', '2026-W45-1', '06.11.2026', '２０２６-11-06',
                      '0001-01-01', '9999-12-31', '', ' 2026-11-06', None, 'x'):
            self.assertIsNone(query.day(value), value)

    def test_a_number_is_ascii_digits_within_its_bounds(self):
        self.assertEqual(query.number('42'), 42)
        self.assertEqual(query.number('7', least=1, most=10), 7)
        for value in ('²', '٣', '-1', '1e3', ' 4', '', None, '99999999999999999999'):
            self.assertIsNone(query.number(value), value)
        self.assertIsNone(query.number('11', most=10))
        self.assertIsNone(query.number('0', least=1))

    def test_a_year_lies_in_the_calendar_the_pages_show(self):
        self.assertEqual(query.year('2026'), 2026)
        for value in ('²', '0', '99999', '-2026', ''):
            self.assertIsNone(query.year(value), value)
