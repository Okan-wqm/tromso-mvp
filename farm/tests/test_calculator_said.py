"""What the water calculator SAYS today (its page, its live parts and its printed report), read whatever the markup
(monitoring/tests/golden.py `page_says`), for the cases the calculator's own tests use: the defaults, a filled water,
a dose with the simulator, a water that cannot be, a wrong value. The redesign behind `?ui=next` is held to it: the
new page must say every item the old one says, value for value (`says_missing` empty), and may add. Only the
presentation changes; the chemistry (chemcore, farm/water/calculation.py) is the same call for both.

The characterisation is live, not a recording: both looks are rendered from the same code in the same test, so it
never ages and needs no recording run. The new look is the same GET form, the same live parts and the same report,
drawn with the new look's classes (core/ui.py: the `ui` cookie that `?ui=next` sets; the cookie, not the parameter, so
the report's address, which carries the form's query, is the same in both looks)."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core import ui
from monitoring.tests.golden import page_says, says_missing, squash

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

    def said(self, url, query, scope='', look=ui.CLASSIC):
        if look == ui.NEXT:
            self.client.cookies[ui.COOKIE] = ui.NEXT
        else:
            self.client.cookies.pop(ui.COOKIE, None)
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
        self.assertRegex(ammonia[1], r'^\d+\.\d{4} mg/L')                  # the value and its unit
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

    def test_the_new_look_says_everything_the_classic_look_says_on_every_view(self):
        """Every case, on the page, its live parts and the report: nothing the classic look says is missing from the new
        one, value for value (it may add: the plates' titles "Values" and "Results")."""
        for name, query in CASES.items():
            for url in (PAGE, PARTS, REPORT):
                with self.subTest(case=name, url=url):
                    old, new = self.said(url, query), self.said(url, query, look=ui.NEXT)
                    self.assertEqual(says_missing(old, new), {})

    def test_the_new_look_is_drawn_in_the_new_look(self):
        """The new look's marks are there (the plates' titles, data-ui on the report's own page), and the classic look has
        none of them: the same templates, the look decided by the request alone."""
        for look, expected in ((ui.NEXT, True), (ui.CLASSIC, False)):
            with self.subTest(look=look):
                if look == ui.NEXT:
                    self.client.cookies[ui.COOKIE] = ui.NEXT
                else:
                    self.client.cookies.pop(ui.COOKIE, None)
                page = self.client.get(PAGE, CASES['filled']).content.decode()
                parts = self.client.get(PARTS, CASES['filled']).content.decode()
                report = self.client.get(REPORT, CASES['filled']).content.decode()
                self.assertEqual('class="calc-plate-title">Values<' in page, expected)
                self.assertEqual('class="calc-plate-title">Results<' in parts, expected)
                self.assertEqual('data-ui="next"' in report, expected)
                self.assertEqual('data-ui="next"' in page, expected)
