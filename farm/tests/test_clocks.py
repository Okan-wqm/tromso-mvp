from datetime import datetime, time, timezone as utc

from django.test import TestCase

from ..clocks import clocks
from ..models import Site


class ClockTests(TestCase):
    """The day on the clock of each time zone the sites use, and on the company's for a place without a site."""

    def test_one_clock_per_zone_and_one_for_places_without_a_site(self):
        auckland = Site.objects.create(name='Auckland', code='AK', timezone='Pacific/Auckland')    # UTC+13 in January
        oslo = Site.objects.create(name='Oslo', code='OS', timezone='Europe/Oslo')
        oslo2 = Site.objects.create(name='Bergen', code='BG', timezone='Europe/Oslo')
        found = {clock.zone.key: clock for clock in clocks(datetime(2026, 1, 15, 23, 30, tzinfo=utc.utc))}
        self.assertEqual(set(found), {'Pacific/Auckland', 'Europe/Oslo', 'UTC'})
        self.assertEqual((found['Pacific/Auckland'].today.isoformat(), found['Pacific/Auckland'].now),
                         ('2026-01-16', time(12, 30)))
        self.assertEqual(found['Europe/Oslo'].today.isoformat(), '2026-01-16')
        self.assertEqual(found['UTC'].today.isoformat(), '2026-01-15')
        self.assertEqual(set(found['Europe/Oslo'].sites), {oslo.pk, oslo2.pk})
        self.assertEqual(found['Pacific/Auckland'].sites, (auckland.pk,))
        self.assertIsNone(found['UTC'].sites)
        self.assertEqual(found['Pacific/Auckland'].start, datetime(2026, 1, 16, tzinfo=found['Pacific/Auckland'].zone))

    def test_on_selects_the_rows_of_the_sites_that_read_the_clock(self):
        site = Site.objects.create(name='Oslo', code='OS', timezone='Europe/Oslo')
        other = Site.objects.create(name='Bergen', code='BG')    # company zone (UTC)
        clock = next(c for c in clocks() if c.zone.key == 'Europe/Oslo')
        self.assertEqual(set(Site.objects.filter(clock.on('pk'))), {site})
        none = next(c for c in clocks() if c.sites is None)
        self.assertEqual(Site.objects.filter(none.on('pk')).count(), 0)
        self.assertEqual(other.pk in next(c for c in clocks() if c.zone.key == 'UTC' and c.sites).sites, True)
