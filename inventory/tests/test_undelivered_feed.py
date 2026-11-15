"""A feed that was fed and never delivered is named in the store, with its shortfall (flow fault M-03). The store makes a
feed's item at its first delivery or reorder level, and the overview folded items only: a feed without one had no book,
so its feeding was compared with nothing and the Storage page showed neither it nor a shortfall. Such a feed is now
folded as an item without a line (read.undelivered), by the same fold that finds a stocked item's shortfall, and the
overview names it: how much was fed inside the correction window, since when, and that all of it is missing."""
from decimal import Decimal

from django.urls import reverse

from farm.feeding import services as feeding_services
from farm.models import Feed
from farm.stock.dates import shown_date
from farm.tests.helpers import correction_window, make_species, stock_fish
from farm.tests.test_stock import make_unit

from .. import read
from ..templatetags.inventory import quantity
from .helpers import StoreTestCase

D = Decimal


class UndeliveredFeedTests(StoreTestCase):
    def setUp(self):
        super().setUp()
        self.tank = make_unit('T-01', self.hall)
        stock_fish(self.user, self.tank, count=10000, weight='50', days_ago=20, species=make_species())

    def fed(self, kilos, days_ago, feed=None):
        return feeding_services.record_feeding(self.user, unit=self.tank, day=self.day(days_ago),
                                               feed=feed or self.feed, amount_kg=D(kilos))

    def undelivered(self):
        return [(row.site, row.feed, row.kilos, row.since) for row in read.overview().undelivered]

    def test_a_feed_fed_and_never_delivered_is_named_with_its_shortfall(self):
        self.fed('12', 3)
        self.fed('20', 2)
        self.assertEqual(self.undelivered(), [(self.bergen, self.feed, D(32), self.day(3))])
        page = self.client.get(reverse('inventory:storage'))
        self.assertContains(page, f'{quantity(D(32))} of {self.feed} fed at Bergen since {shown_date(self.day(3))}, and '
                                  f'none of it was ever delivered to the store: the store is {quantity(D(32))} short '
                                  'of it. Record its delivery, dated on or before that day.')
        self.assertContains(page, f'{reverse("farm:feeding_records")}?feed={self.feed.pk}')

    def test_each_feed_and_site_has_its_own_line_and_a_feed_never_fed_has_none(self):
        starter = Feed.objects.create(name='Starter 2', code='ST-2', feed_type='grower', pellet_size_mm=D(2))
        Feed.objects.create(name='Unused', code='UN-1', feed_type='grower', pellet_size_mm=D(6))
        self.fed('12', 3)
        self.fed('5', 1, feed=starter)
        self.assertEqual(self.undelivered(), [(self.bergen, self.feed, D(12), self.day(3)),
                                              (self.bergen, starter, D(5), self.day(1))])

    def test_once_it_is_delivered_the_store_has_its_book_and_says_what_is_still_uncovered(self):
        self.fed('12', 3)
        self.receive('3000', days_ago=1)                     # delivered after the feeding's day
        summary = read.overview()
        self.assertEqual(summary.undelivered, [])
        [record] = summary.site_items
        self.assertEqual((record.item.feed, record.uncovered, record.uncovered_since), (self.feed, D(12), self.day(3)))
        self.assertContains(self.client.get(reverse('inventory:storage')), 'beyond the recorded stock since')

    def test_a_delivery_dated_before_the_feeding_covers_it(self):
        self.receive('3000', days_ago=10)
        self.fed('12', 3)
        summary = read.overview()
        self.assertEqual((summary.undelivered, [record.uncovered for record in summary.site_items]), ([], [D(0)]))

    def test_only_the_feedings_inside_the_correction_window_are_counted(self):
        self.fed('12', 3)
        self.fed('20', 1)
        with correction_window(2):
            self.assertEqual(self.undelivered(), [(self.bergen, self.feed, D(20), self.day(1))])
