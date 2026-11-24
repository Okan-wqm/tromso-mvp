"""Company › Overview's figures (config.company.overview): each block read by its area's own function, split per site from
the same rows, so the split adds up to the area's own totals; a block only for a person who may read its area."""
import json
import re
from decimal import Decimal as D
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from alarms.models import Alarm, Source
from config.company import overview
from core.pagesays import unsaid
from farm.stock.views import overview_tiles
from farm.water.views import overview as water_overview
from sensors.models.alarm import Severity

from ..models import ProductionDepartment, Site
from .helpers import role
from .test_stock import make_unit
from .test_water import WaterTestCase


class CompanyFixture(WaterTestCase):
    """Bergen (two stocked units, a critical and a warning oxygen), Tromsø (one stocked cage), Alta (inactive, empty)."""

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


class CompanyOverviewTests(CompanyFixture):
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
        self.assertEqual(rows['AL']['water'], {'critical': 0, 'warning': 0, 'points': 0, 'measured': 0, 'worst': None,
                                              'stale_since': None})

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


MANIFEST = str(Path(__file__).resolve().parents[2] / 'core' / 'testdata' / 'islands-company-manifest.json')


def props_of(html, name):
    """The props block of the page's island `name` (json_script), as data."""
    found = re.search(r'<script id="island-' + name + r'-1" type="application/json">(.*?)</script>', html, re.S)
    return json.loads(found.group(1)) if found else None


@override_settings(ISLANDS_MANIFEST=MANIFEST)
class CompanyOverviewPageTests(CompanyFixture):
    """The page: the classic look as it was, and the new look (?ui=next) an island whose props say all the classic page
    said (core.pagesays) and the design's blocks besides."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def test_the_classic_page_is_the_classic_template_and_the_new_look_the_island(self):
        classic = self.client.get(reverse('home'), {'ui': 'classic'}).content.decode()
        self.assertNotIn('data-island="company"', classic)
        self.assertIn('class="tiles"', classic)
        page = self.client.get(reverse('home'), {'ui': 'next'}).content.decode()
        self.assertIn('data-island="company"', page)
        self.assertIsNotNone(props_of(page, 'company'))

    def test_the_new_look_says_everything_the_classic_page_says(self):
        for language in ('en', 'nb', 'tr'):
            with self.subTest(language=language):
                self.client.cookies['django_language'] = language
                old = self.client.get(reverse('home'), {'ui': 'classic'}).content.decode()
                new = self.client.get(reverse('home'), {'ui': 'next'}).content.decode()
                props = props_of(new, 'company')
                with translation.override(language):
                    # The classic page's line promising "the company's figures will appear here": the new page shows them.
                    placeholder = _('Welcome, %(name)s. The company’s figures will appear here.') % {'name': 'boss'}
                self.assertEqual(unsaid(old, props, ignore={placeholder}, new_html=new), [])

    def test_every_block_is_there_for_who_may_read_it(self):
        props = props_of(self.client.get(reverse('home'), {'ui': 'next'}).content.decode(), 'company')
        for name in ('sites', 'alarms', 'people', 'upcoming', 'feed', 'messages', 'activity', 'knowledge'):
            self.assertIsNotNone(props[name], name)
        rows = {row['code']: row for row in props['sites']['rows']}
        self.assertEqual((rows['BG']['units'], rows['BG']['water']['kind'], rows['AL']['units']), ('2', 'critical', '0'))
        person = get_user_model().objects.create_user('sites-only-page', 'sop@example.com')
        person.groups.add(role('Sites only page', 'view_site'))
        self.client.force_login(person)
        props = props_of(self.client.get(reverse('home'), {'ui': 'next'}).content.decode(), 'company')
        for name in ('alarms', 'people', 'upcoming', 'feed', 'messages', 'activity', 'knowledge'):
            self.assertIsNone(props[name], name)
        self.assertEqual([tile['key'] for tile in props['today']['tiles']], ['sites'])


class WaterChipTests(CompanyFixture):
    """The site's water chip says the worst value as the Water page judges it (PointWater.worst_alert), not a count."""

    def test_the_worst_value_is_said_critical_before_warning(self):
        from config.company_props import overview_props
        from farm.water import parameters
        props = overview_props(self.admin)
        chips = {row['code']: row['water'] for row in props['sites']['rows']}
        short = str(parameters.get('oxygen_mg_l').short)
        self.assertEqual(chips['BG']['kind'], 'critical')
        self.assertTrue(chips['BG']['text'].startswith(short), chips['BG'])
        self.assertIn('5', chips['BG']['text'])
        self.assertEqual(chips['AL'], {'kind': 'nodata', 'text': 'Not measured'})

    def test_a_point_without_an_alert_says_nothing_worse_than_its_judgement(self):
        from farm.water.evaluate import Status
        from farm.water.read import latest
        water = latest([self.mid2])[self.mid2.pk]
        reading, judged, old = water.worst_alert
        self.assertEqual((reading.code, judged, old), ('oxygen_mg_l', Status.WARNING, False))
        self.assertIsNone(latest([self.loop])[self.loop.pk].worst_alert)
