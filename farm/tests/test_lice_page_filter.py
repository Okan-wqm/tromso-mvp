"""The sea-lice page's weekly table is the site's average (Vedlegg 1 point 6: the mean of every cage's average) and its
over-limit badge: a filter of the list below it, by unit or from a day inside a week, must not turn one cage's average
into the "site average" (audit F-082)."""
from datetime import timedelta
from decimal import Decimal

from django.urls import reverse

from ..health import services
from .test_health import HealthTestCase


class LicePageFilterTests(HealthTestCase):
    def setUp(self):
        super().setUp()
        self.stock(unit=self.t2)
        recent = self.day(3)
        self.monday = recent - timedelta(days=recent.weekday())
        self.count(self.t2, self.monday, females=12)                     # 0.6 per fish
        self.count(self.t1, self.monday + timedelta(days=1), females=4)  # 0.2 per fish

    def count(self, unit, day, females):
        services.record_lice_count(self.user, unit=unit, day=day, fish_counted=20, adult_females=females, mobile=0,
                                   attached=0)

    def week(self, **params):
        [week] = self.client.get(reverse('farm:lice_counts'), params).context['weeks']
        return week

    def test_the_site_average_is_the_sites_whatever_the_unit_filter(self):
        self.assertEqual(self.week().adult_females, Decimal('0.4'))
        filtered = self.week(unit=str(self.t1.pk))
        self.assertEqual((filtered.adult_females, [count.unit for count in filtered.counts]),
                         (Decimal('0.4'), [self.t1, self.t2]))

    def test_a_from_day_inside_a_week_keeps_the_whole_week(self):
        week = self.week(**{'from': (self.monday + timedelta(days=1)).isoformat()})
        self.assertEqual(week.adult_females, Decimal('0.4'))

    def test_the_list_below_is_still_filtered(self):
        page = self.client.get(reverse('farm:lice_counts'), {'unit': str(self.t1.pk)})
        self.assertEqual([row['count'].unit for row in page.context['rows']], [self.t1])
