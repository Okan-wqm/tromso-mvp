from datetime import date, datetime, time, timezone as utc
from unittest import mock
from zoneinfo import ZoneInfo

from django.core.checks.registry import registry
from django.test import SimpleTestCase, TestCase, override_settings

from ..clocks import clocks
from ..models import Site
from ..models.site import zone_of
from ..stock.dates import local_today, site_today

UTC = utc.utc
NIGHT = datetime(2026, 1, 15, 23, 30, tzinfo=UTC)          # 00:30 on 16 January in Oslo


class ClockTests(TestCase):
    """The day on the clock of each time zone the sites use, and on the company's for a place without a site."""

    def test_one_clock_per_zone_and_one_for_places_without_a_site(self):
        auckland = Site.objects.create(name='Auckland', code='AK', timezone='Pacific/Auckland')    # UTC+13 in January
        oslo = Site.objects.create(name='Oslo', code='OS', timezone='Europe/Oslo')
        oslo2 = Site.objects.create(name='Bergen', code='BG', timezone='Europe/Oslo')
        london = Site.objects.create(name='London', code='LN', timezone='Europe/London')
        found = {(clock.zone.key, clock.sites is None): clock for clock in clocks(NIGHT)}
        self.assertEqual(set(found), {('Pacific/Auckland', False), ('Europe/Oslo', False), ('Europe/London', False),
                                      ('Europe/Oslo', True)})
        self.assertEqual((found['Pacific/Auckland', False].today.isoformat(), found['Pacific/Auckland', False].now),
                         ('2026-01-16', time(12, 30)))
        self.assertEqual(found['Europe/Oslo', False].today.isoformat(), '2026-01-16')
        self.assertEqual(found['Europe/London', False].today.isoformat(), '2026-01-15')
        self.assertEqual(set(found['Europe/Oslo', False].sites), {oslo.pk, oslo2.pk})
        self.assertEqual(found['Pacific/Auckland', False].sites, (auckland.pk,))
        self.assertEqual(found['Europe/London', False].sites, (london.pk,))
        self.assertEqual(found['Pacific/Auckland', False].start,
                         datetime(2026, 1, 16, tzinfo=found['Pacific/Auckland', False].zone))

    def test_on_selects_the_rows_of_the_sites_that_read_the_clock(self):
        site = Site.objects.create(name='Oslo', code='OS', timezone='Europe/Oslo')
        other = Site.objects.create(name='Bergen', code='BG', timezone='UTC')     # the server's clock
        clock = next(c for c in clocks() if c.zone.key == 'Europe/Oslo' and c.sites)
        self.assertEqual(set(Site.objects.filter(clock.on('pk'))), {site})
        none = next(c for c in clocks() if c.sites is None)
        self.assertEqual(Site.objects.filter(none.on('pk')).count(), 0)
        self.assertEqual(other.pk in next(c for c in clocks() if c.zone.key == 'UTC' and c.sites).sites, True)


class CompanyClockTests(TestCase):
    """A place without a site (an unposted person, a record with no site, a form over several sites' zones) reads the
    company's clock (settings.COMPANY_TIME_ZONE), never the server's UTC (settings.TIME_ZONE)."""

    def test_a_place_without_a_site_reads_the_companys_zone(self):
        self.assertEqual(zone_of(None), ZoneInfo('Europe/Oslo'))
        with override_settings(COMPANY_TIME_ZONE='Europe/Istanbul'):
            self.assertEqual(zone_of(None), ZoneInfo('Europe/Istanbul'))

    def test_the_companys_clock_says_the_companys_day(self):
        company = next(clock for clock in clocks(NIGHT) if clock.sites is None)
        self.assertEqual((company.zone.key, company.today, company.now), ('Europe/Oslo', date(2026, 1, 16), time(0, 30)))
        with mock.patch('django.utils.timezone.now', return_value=NIGHT):
            self.assertEqual((site_today(None), local_today()), (date(2026, 1, 16), date(2026, 1, 16)))


class CompanyZoneCheckTests(SimpleTestCase):
    """The server refuses to start on a company zone that is not a known zone or not one a site may be given: migration
    farm/0028 would write it into every zone-less site, and every read of the site's day would fail."""

    def errors(self):
        from .. import checks                                       # the module the farm app registers its checks from
        self.assertIn(checks.company_time_zone, registry.get_checks())
        return [message.id for message in checks.company_time_zone(None)]

    def test_a_known_zone_a_site_may_have_passes(self):
        self.assertEqual(self.errors(), [])

    def test_an_unknown_zone_or_one_no_site_may_have_is_an_error(self):
        for zone in ('Europe/Olso', '', 'Asia/Kolkata'):
            with self.subTest(zone=zone), override_settings(COMPANY_TIME_ZONE=zone):
                self.assertEqual(self.errors(), ['farm.E001'])
