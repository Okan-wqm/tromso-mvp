"""What Production › Overview and Production › Production units (the list and a unit's drawer) SAY today, read
whatever the markup (monitoring/tests/golden.py `page_says`), on a small farm in the states that matter: a critical and
a warning water value, a stocked unit with no water sample, an empty unit, and a person who may read everything and one
who may not read the water. The redesign behind `?ui=next` is held to it: the new page must say every item the old one
says (`says_missing` empty), and may add. A page that knows nothing of the water never says it is fine."""
from django.contrib.auth import get_user_model
from django.urls import reverse

from monitoring.tests.golden import page_says, squash

from .helpers import role
from .test_stock import make_unit
from .test_water import WaterTestCase

OVERVIEW, UNITS = reverse('production_home'), reverse('farm:production_units')


class ProductionFarm(WaterTestCase):
    """T-01 stocked with a critical CO₂ and a warm warning; T-02 stocked with no water sample; T-03 empty."""

    def setUp(self):
        super().setUp()
        self.t3 = make_unit('T-03', self.hall)
        self.stock()
        self.stock(self.t2)
        self.limit('co2_mg_l', warning_high=12, critical_high=15)
        self.limit('temperature_c', warning_high=15, critical_high=18)
        self.sample(self.t1, hours=1, co2_mg_l='15.6', temperature_c='16.0', oxygen_mg_l='9.10')
        self.everything = get_user_model().objects.create_superuser('admin', 'admin@example.com', 'x')

    def said(self, url, user=None, **query):
        self.client.force_login(user or self.everything)
        response = self.client.get(url, query)
        self.assertEqual(response.status_code, 200)
        return page_says(response.content.decode(), squash)

    def stock_reader(self):
        person = get_user_model().objects.create_user('stock', 'stock@example.com', 'x')
        person.groups.add(role('Stock reader', 'view_stockoperation', 'view_tank'))
        return person


def flat(found):
    return ' | '.join(found['headings'] + found['texts'] + [' · '.join(row) for row in found['pairs']])


class OverviewSaysTests(ProductionFarm):
    def test_the_critical_value_and_the_unsampled_unit_are_said(self):
        text = flat(self.said(OVERVIEW))
        self.assertIn('15.6', text)
        self.assertIn('1 stocked unit without a water sample', text)
        self.assertNotIn('Nothing needs attention', text)

    def test_a_person_who_may_not_read_the_water_is_never_told_it_is_fine(self):
        text = flat(self.said(OVERVIEW, self.stock_reader()))
        self.assertNotIn('15.6', text)
        self.assertNotIn('critical water', text.lower())


class UnitsSaysTests(ProductionFarm):
    def test_the_list_says_each_unit_with_its_water_and_the_empty_one_as_empty(self):
        found = self.said(UNITS)
        rows = {row[0].split(' ')[0]: row for row in found['pairs'] if row and row[0][:4] in ('T-01', 'T-02', 'T-03')}
        self.assertEqual(sorted(rows), ['T-01', 'T-02', 'T-03'])
        self.assertIn('16.0', ' '.join(rows['T-01']))
        self.assertIn('9.10', ' '.join(rows['T-01']))
        self.assertIn('Empty — ready to stock', ' '.join(rows['T-03']))
        # T-01's CO₂, and T-02: fish and no fresh oxygen (owner decision of 2026-11-23)
        self.assertIn('2 critical', flat(found))
        self.assertIn('Critical, no recent data', ' '.join(rows['T-02']))

    def test_the_list_hides_the_water_from_a_person_who_may_not_read_it(self):
        found = self.said(UNITS, self.stock_reader())
        self.assertNotIn('Temp. (°C)', flat(found))

    def test_the_drawer_says_the_units_water_with_its_status(self):
        found = self.said(UNITS, unit=str(self.t1.pk))
        text = flat(found)
        for fact in ('15.6', '16.0', 'Record water sample'):
            self.assertIn(fact, text)

    def test_the_drawer_of_a_unit_with_no_water_says_so(self):
        text = flat(self.said(UNITS, unit=str(self.t2.pk)))
        self.assertIn('No water sample in the last 30 days.', text)
