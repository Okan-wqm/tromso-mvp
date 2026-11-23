"""Company › Overview's figures (config.company.overview): each block read by its area's own function, split per site from
the same rows, so the split adds up to the area's own totals; a block only for a person who may read its area."""
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.utils import timezone

from alarms.models import Alarm, Source
from config.company import overview
from farm.stock.views import overview_tiles
from farm.water.views import overview as water_overview
from sensors.models.alarm import Severity

from ..models import ProductionDepartment, Site
from .helpers import role
from .test_stock import make_unit
from .test_water import WaterTestCase


class CompanyOverviewTests(WaterTestCase):
    def setUp(self):
        super().setUp()
        self.admin = get_user_model().objects.create_superuser('boss', 'boss@example.com', 'x')
        self.tromso = Site.objects.create(name='Tromsø', code='TR', altitude=D(0), timezone='UTC')
        self.cages = ProductionDepartment.objects.create(site=self.tromso, name='Cages', code='CG')
        self.m1 = make_unit('M-01', self.cages)
        self.empty = Site.objects.create(name='Alta', code='AL', altitude=D(0), timezone='UTC',
                                         status=Site.Status.INACTIVE)
        self.stock()
        self.stock(self.t2)
        self.stock(self.m1)
        self.limit('oxygen_mg_l', critical_low=6, warning_low=7)
        self.sample(self.mid1, oxygen_mg_l='5', temperature_c='10')
        self.sample(self.mid2, oxygen_mg_l='6.5', temperature_c='10')

    def rows(self, found):
        return {row['site'].code: row for row in found['sites']['rows']}

    def test_the_split_per_site_adds_up_to_the_areas_own_totals(self):
        found = overview(self.admin)
        rows = self.rows(found)
        self.assertEqual((rows['BG']['units_stocked'], rows['TR']['units_stocked'], rows['AL']['units_stocked']), (2, 1, 0))
        tiles = {tile['key']: tile for tile in overview_tiles(self.admin)}
        self.assertEqual(sum(row['units_stocked'] for row in rows.values()), tiles['stocked']['count'])
        self.assertEqual(rows['AL']['biomass_kg'], 0)
        self.assertGreater(rows['BG']['biomass_kg'], rows['TR']['biomass_kg'])
        water = water_overview(self.admin)
        self.assertEqual(sum(row['water']['critical'] for row in rows.values()), water['critical'])
        self.assertEqual(sum(row['water']['warning'] for row in rows.values()), water['warning'])
        self.assertEqual((rows['BG']['water']['critical'], rows['BG']['water']['warning']), (1, 1))
        self.assertEqual(rows['AL']['water'], {'critical': 0, 'warning': 0, 'points': 0, 'measured': 0})

    def test_the_sites_are_counted_by_status_with_the_statuses_they_have(self):
        found = overview(self.admin)['sites']
        self.assertEqual(found['count'], 3)
        self.assertEqual([(str(label), count) for label, count in found['by_status']], [('Active', 2), ('Inactive', 1)])

    def test_an_open_alarm_is_counted_on_its_site_and_by_severity(self):
        Alarm.objects.create(source=Source.WATER_LIMIT, point=self.mid1, parameter='oxygen_mg_l',
                             severity=Severity.CRITICAL, site=self.bergen, opened_at=timezone.now(),
                             summary='Dissolved oxygen 5 mg/L, below 6')
        found = overview(self.admin)
        self.assertEqual((found['alarms']['count'], found['alarms']['critical'], found['alarms']['warning']), (1, 1, 0))
        self.assertEqual([row['open_alarms'] for row in found['sites']['rows']], [0, 1, 0])   # Alta, Bergen, Tromsø

    def test_a_person_gets_only_the_blocks_of_the_areas_they_may_read(self):
        person = get_user_model().objects.create_user('sites-only', 'so@example.com')
        person.groups.add(role('Sites only', 'view_site'))
        found = overview(person)
        for name in ('alarms', 'people', 'reports', 'messages', 'feed', 'activity', 'knowledge'):
            self.assertIsNone(found[name], name)
        for row in found['sites']['rows']:
            self.assertEqual((row['units_stocked'], row['biomass_kg'], row['water'], row['open_alarms']),
                             (None, None, None, None))
        nobody = get_user_model().objects.create_user('nobody', 'nb@example.com')
        self.assertIsNone(overview(nobody)['sites'])
