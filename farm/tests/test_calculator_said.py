"""What the water calculator SAYS today (its page, its live parts and its printed report), read whatever the markup
(monitoring/tests/golden.py `page_says`), for the cases the calculator's own tests use: the defaults, a filled water,
a dose with the simulator, a water that cannot be, a wrong value. The redesign behind `?ui=next` is held to it: the
new page must say every item the old one says, value for value (`says_missing` empty), and may add. Only the
presentation changes; the chemistry (chemcore, farm/water/calculation.py) is the same call for both.

The characterisation is live, not a recording: both pages are rendered from the same code in the same test, so it
never ages and needs no recording run. Until the new page exists the tests pin what today's page says."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from monitoring.tests.golden import page_says, squash

from .helpers import role
from . import test_calculator

PAGE, PARTS, REPORT = (reverse(name) for name in ('farm:water_calculator', 'farm:water_calculator_results',
                                                   'farm:water_calculator_report'))
FILLED = test_calculator.CalculatorPageTests.values
CASES = {
    'defaults': {},
    'filled': FILLED,
    'dosed': {**FILLED, 'dose_nahco3': '50', 'ph': '7.2'},
    'impossible': {**FILLED, 'temperature_c': '10', 'salinity_ppt': '0.2', 'ph': '11', 'alkalinity_mg_l': '3'},
    'wrong': {**FILLED, 'ph': '25'},
}
# The rows of the report's two tables a filled water always has (their values are the chemistry's, compared by the
# comparison with the new page, not here).
WORKED_ROWS = ('Un-ionised ammonia (NH₃-N)', 'H₂S (as H₂S)', 'Carbon dioxide (CO₂)', 'Dissolved inorganic carbon (DIC)',
               'Oxygen saturation', 'Target DIC', 'Target CO₂')


def same(text):
    return squash(text)


class CalculatorSaysTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('ali', 'ali@example.com', 'eski-sifre-123')
        self.user.groups.add(role('Water reader', 'view_watermeasurement'))
        self.client.force_login(self.user)

    def said(self, url, query, scope=''):
        response = self.client.get(url, query)
        self.assertEqual(response.status_code, 200)
        return page_says(response.content.decode(), same, scope)

    def test_every_case_says_something_on_every_view(self):
        for name, query in CASES.items():
            for url in (PAGE, PARTS, REPORT):
                with self.subTest(case=name, url=url):
                    found = self.said(url, query)
                    self.assertTrue(found['pairs'] or found['texts'])

    def test_the_report_of_a_filled_water_names_every_value_and_every_worked_out_row(self):
        found = self.said(REPORT, CASES['filled'])
        labels = {row[0] for row in found['pairs']}
        for label in WORKED_ROWS + ('Reagents to dose with', 'Temperature (°C)'):
            self.assertIn(label, labels)
        ammonia = next(row for row in found['pairs'] if row[0] == 'Un-ionised ammonia (NH₃-N)')
        self.assertRegex(ammonia[1], r'^\d+\.\d{4} mg/L · \S')         # the value, its unit and its status
        self.assertIn('Water chemistry report', found['headings'])

    def test_a_water_that_cannot_be_says_why_on_every_view(self):
        for url in (PAGE, PARTS, REPORT):
            with self.subTest(url=url):
                found = self.said(url, CASES['impossible'])
                self.assertTrue(any('At this pH the alkalinity is above' in text
                                    for text in found['texts'] + [cell for row in found['pairs'] for cell in row]))

    def test_the_dose_brings_the_simulator_and_the_recipes(self):
        found = self.said(PAGE, CASES['dosed'])
        everything = ' '.join(found['headings'] + found['texts'])
        for text in ('Dosing simulator', 'Dosing recipes'):
            self.assertIn(text, everything)
