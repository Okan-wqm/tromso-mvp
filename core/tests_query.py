"""What a page reads from its address follows one rule (F-006, F-176, F-120): a value that is not well formed, or lies
outside what the page can show, is taken as not given (None). Days are core.dates' (read_day, cross review F8); this
module holds the numbers and the years, on the same calendar."""
from django.test import SimpleTestCase

from . import dates, query


class ParserTests(SimpleTestCase):
    def test_days_are_read_in_one_place(self):
        self.assertFalse(hasattr(query, 'day'))

    def test_a_number_is_ascii_digits_within_its_bounds(self):
        self.assertEqual(query.number('42'), 42)
        self.assertEqual(query.number('7', least=1, most=10), 7)
        for value in ('²', '٣', '-1', '1e3', ' 4', '', None, '99999999999999999999'):
            self.assertIsNone(query.number(value), value)
        self.assertIsNone(query.number('11', most=10))
        self.assertIsNone(query.number('0', least=1))

    def test_a_year_lies_in_the_calendar_the_dates_read(self):
        self.assertEqual(query.year('2026'), 2026)
        self.assertEqual((query.year(str(dates.FIRST.year)), query.year(str(dates.LAST.year))),
                         (dates.FIRST.year, dates.LAST.year))
        for value in ('²', '0', str(dates.FIRST.year - 1), str(dates.LAST.year + 1), '99999', '-2026', ''):
            self.assertIsNone(query.year(value), value)
