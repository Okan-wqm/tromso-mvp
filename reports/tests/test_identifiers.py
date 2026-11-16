"""Identifiers are printed as they are written (flow fault M-13). A report's page and its print list every figure of the
content through one registry (reports.labels.outline), which wrote any number, and any text made of digits, the way the
language writes a number: "Organisation number 987,654,321", "Lokalitetsnummer 12,345", "Year class 2,026". A leaf that
names something (an identifier, a code, a year: labels.names) is now printed as written; what counts (fish, kilos) keeps
the language's number."""
from django.test import SimpleTestCase
from django.utils import translation

from .. import labels, services

CONTENT = {
    'kind': 'planned_slaughter',
    'facility': {'name': 'Fjord Slakteri', 'approval_number': '1234', 'organisation_number': '987654321'},
    'filer': {'organisation_number': '912345678', 'name': 'Fjord AS'},
    'localities': {'site-1': {
        'site': 'Kvaløya', 'lokalitetsnummer': 12345, 'organisation_number': '987654321', 'site_code': '10432',
        'species': {'SAL': {'monday': 12500, 'tuesday': None}}}},
    'stock': [{'species': 'SAL', 'year_class': 2026, 'fish': 12500, 'kg': '1234.5'}],
    'units': [{'number': '1001', 'fish': 2000}],
    'week': 47, 'year': 2026, 'reference': '20261115',
}


def values(content):
    return [value for _label, value in labels.outline(content)]


class NamingLeavesTests(SimpleTestCase):
    def test_which_leaves_name(self):
        naming = [['facility', 'approval_number'], ['localities', 'x', 'lokalitetsnummer'], ['filer', 'organisation_number'],
                  ['stock', '0', 'year_class'], ['units', '3', 'number'], ['week'], ['year'], ['reference'],
                  ['localities', 'x', 'site_code'], ['delivery', 'destination_site_number'], ['identity', 'anything'],
                  ['facility', 'name']]
        counting = [['stock', '0', 'fish'], ['stock', '0', 'kg'], ['localities', 'x', 'species', 'SAL', 'monday'],
                    ['units', '3', 'fish'], ['week', 'monday'], []]
        for parts in naming:
            self.assertTrue(labels.names(parts), parts)
        for parts in counting:
            self.assertFalse(labels.names(parts), parts)
        for leaf in services.IDENTITY_LEAVES:                      # what is "identity" for a change is naming for the page
            if leaf not in ('/species', '/site'):                  # names in words already
                self.assertTrue(labels.names(['units', '0', leaf.strip('/')]), leaf)

    def test_an_identifier_is_printed_as_written_and_a_count_as_a_number(self):
        shown = values(CONTENT)
        for written in ('987654321', '912345678', '12345', '10432', '1234', '2026', '1001', '47', '20261115'):
            self.assertIn(written, shown, written)
        for grouped in ('987,654,321', '912,345,678', '12,345', '10,432', '1,234', '2,026', '1,001', '20,261,115'):
            self.assertNotIn(grouped, shown, grouped)
        self.assertEqual(shown.count('12,500'), 2)                 # the fish and the planned kilos are still numbers
        self.assertIn('1234.5', shown)                              # a decimal was never grouped
        self.assertIn('2,000', shown)

    def test_in_norwegian_too(self):
        with translation.override('nb'):
            shown = values(CONTENT)
        self.assertIn('987654321', shown)
        self.assertIn('2026', shown)
        self.assertFalse([value for value in shown if value.replace('\xa0', ' ') in ('987 654 321', '2 026', '12 345')])

    def test_the_value_filter_is_unchanged_for_what_counts(self):
        self.assertEqual(labels.shown(12500), '12,500')
        self.assertEqual(labels.shown('1234.5'), '1234.5')
        self.assertEqual(labels.shown(12500, naming=True), '12500')
        self.assertEqual(labels.shown('987654321', naming=True), '987654321')
        self.assertEqual(labels.shown(None, naming=True), '–')
