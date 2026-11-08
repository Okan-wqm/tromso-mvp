"""The second cross review of the water's one resolver (farm/water/read.py, owner rule A9) and what an oxygen value is
worked out with. Each case is a probe of the review (P1-P8) turned round: it asserts what the water must say.

- A device clock ahead of ours: a value stamped more than evaluate.CLOCK_SKEW in the future is neither fresh nor the
  newest (P7)."""
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

from django.test import SimpleTestCase

from ..water import read
from ..water.evaluate import Status
from .helpers import make_species, point_of

from ..water import evaluate
from ..water.evaluate import is_fresh
from ..water.parameters import get
from .test_water_sources import SourcesCase

D = Decimal


class ClockSkewTests(SimpleTestCase):
    def test_a_value_from_further_ahead_than_the_skew_is_not_fresh(self):
        now = datetime(2026, 11, 8, 12, tzinfo=dt_timezone.utc)
        ph = get('ph')
        CLOCK_SKEW = getattr(evaluate, 'CLOCK_SKEW', timedelta(minutes=5))
        self.assertEqual(getattr(evaluate, 'CLOCK_SKEW', None), timedelta(minutes=5))
        self.assertTrue(is_fresh(ph, now + CLOCK_SKEW, now))
        self.assertFalse(is_fresh(ph, now + CLOCK_SKEW + timedelta(seconds=1), now))
        self.assertFalse(is_fresh(ph, now + timedelta(minutes=50), now, fresh_for=3600))


class FutureValueTests(SourcesCase):
    def test_p7_a_value_stamped_50_minutes_ahead_is_not_the_newest(self):
        self.sample(hours=0, ph='6.0')
        self.on(self.mid1, self.value('ph', 7.5, seconds=-3000))      # 50 min ahead (the contract allows 3600 s)
        reading = self.latest().get('ph')
        self.assertEqual(reading.value, D('6.00'))
        self.on(self.mid1, self.value('ph', 7.2, seconds=-60, channel_no=2))   # a minute ahead: an ordinary clock
        self.assertEqual(self.latest().get('ph').value, D('7.20'))

    def test_a_value_only_from_the_future_is_shown_but_never_fresh(self):
        self.on(self.mid1, self.value('ph', 7.5, seconds=-3000))
        reading = self.latest().get('ph')
        self.assertEqual(reading.value, D('7.50'))
        self.assertFalse(reading.fresh(self.now))


class OneResolverTests(SourcesCase):
    """A9 lives in ONE function (read.choose): the latest values (read.latest), a value at a moment (Series.latest) and
    the ration's temperature (feeding TemperatureBook.at) all pick through it, from the same places in the same tiers:
    the unit's own (every active point of the unit: its sensors and its samples), then its system's (the system's
    sensors, the sensors on the loop point and the loop's samples), and break a tie at one measurement time the same way
    (a sensor before a sample, the primary channel before the backup)."""

    def both(self, unit=None):
        """(the unit's water temperature, the ration's) as (value, point, fresh) each."""
        from ..feeding.temperature import temperature_for
        unit = unit or self.t1
        water = read.unit_water([unit], now=self.now)[unit.pk].get('temperature_c')
        ration = temperature_for([unit], self.now)[unit.pk]
        return ((water.value, water.point, water.fresh(self.now)) if water else None,
                (ration.value_c, getattr(ration, 'sampling_point', 'no sampling_point'), ration.fresh) if ration else None)

    def test_one_function_picks_for_every_reader(self):
        from unittest import mock

        from ..feeding.temperature import temperature_for
        self.sample(hours=1, temperature_c='9.0')
        self.assertTrue(hasattr(read, 'choose'), 'read.choose: the one place of A9')
        with mock.patch.object(read, 'choose', wraps=read.choose) as chosen:
            read.latest([self.mid1], now=self.now)
            self.assertTrue(chosen.called, 'read.latest')
            chosen.reset_mock()
            read.Series([self.mid1], 'temperature_c', self.ago(days=2), self.now).latest(self.mid1.pk, self.now,
                                                                                          timedelta(days=7))
            self.assertTrue(chosen.called, 'Series.latest')
            chosen.reset_mock()
            temperature_for([self.t1], self.now)
            self.assertTrue(chosen.called, 'TemperatureBook.at')

    def test_p1_a_probe_on_the_loop_point_stands_in_for_the_unit_on_every_page(self):
        self.on(self.loop, self.value('temperature_c', 12.0, seconds=30))
        water, ration = self.both()
        self.assertEqual(water, (D('12.0'), self.loop, True))
        self.assertEqual(ration, water)
        reading = self.latest().get('temperature_c')
        self.assertEqual(read.origin_text(reading), 'system sensor #1')

    def test_every_point_of_the_units_own_water_is_its_own_and_the_newest_fresh_wins(self):
        """A9.1 (owner, 2026-11-08): the unit's OWN sampling points (plural) are those measuring its own water (the
        middle, a depth point, an outlet, a drain): a fresh value at its drain, newer than the middle's, wins. An inlet
        measures the supply stream, not the unit's water: it never counts for the unit."""
        drain = point_of(self.t1, 'bottom_drain')
        inlet = point_of(self.t1, 'inlet')
        self.sample(hours=3, temperature_c='9.0')
        self.sample(point=drain, hours=1, temperature_c='9.4')
        self.sample(point=inlet, hours=0, temperature_c='14.0')                # the supply stream: never the unit's
        self.on(inlet, self.value('temperature_c', 14.2, seconds=5))
        self.on(self.ras, self.value('temperature_c', 11.0, seconds=30))      # the system's never stands in for it
        water, ration = self.both()
        self.assertEqual(water, (D('9.4'), drain, True))
        self.assertEqual(ration, water)
        self.on(drain, self.value('temperature_c', 9.6, seconds=60))
        self.assertEqual(self.both()[0], (D('9.6'), drain, True))
        self.assertEqual(self.both()[1], self.both()[0])
        # the drain's and the inlet's own water are their own alone: the middle's samples are not theirs
        self.assertEqual(read.latest([drain], now=self.now)[drain.pk].get('temperature_c').point, drain)
        self.assertEqual(read.latest([inlet], now=self.now)[inlet.pk].get('temperature_c').value, D('14.2'))

    def test_a_tie_at_one_measurement_time_goes_the_same_way_everywhere(self):
        """A sensor value and a sample measured at the same second: the sensor, on the water page and for the ration,
        fresh or stale."""
        for hours, fresh in ((1, True), (30, False)):
            with self.subTest(hours=hours):
                from ..models import WaterMeasurement
                WaterMeasurement.objects.all().delete()
                self.provider.now_values.clear()
                self.provider.history.clear()
                self.sample(hours=hours, temperature_c='9.0')
                self.on(self.mid1, self.value('temperature_c', 9.9, seconds=hours * 3600, fresh_for=3 * 86400 if fresh
                                              else 180))
                water, ration = self.both()
                self.assertEqual(water, (D('9.9'), self.mid1, fresh))
                self.assertEqual(ration, water)

    def test_with_nothing_fresh_the_units_own_stale_value_is_shown_before_the_systems(self):
        self.sample(hours=30, temperature_c='8.0')
        self.sample(point=self.loop, hours=26, temperature_c='10.0')
        water, ration = self.both()
        self.assertEqual(water, (D('8.0'), self.mid1, False))
        self.assertEqual(ration, water)

    def test_a_value_exactly_at_its_freshness_is_fresh_on_every_reader(self):
        self.sample(hours=24, temperature_c='8.0')                          # temperature is fresh for 24 h
        self.sample(point=self.loop, hours=1, temperature_c='10.0')
        water, ration = self.both()
        self.assertEqual(water, (D('8.0'), self.mid1, True))
        self.assertEqual(ration, water)

    def test_a_loop_value_standing_in_is_judged_for_the_units_fish_only(self):
        """The system's value standing in for a unit is judged for that unit's fish, as its own would be, whether it
        is a sensor's or a sample of the loop."""
        lumpfish = make_species(code='LUM', common_name='Lumpfish', scientific_name='Cyclopterus lumpus')
        self.stock()
        self.stock(unit=self.t2, species=lumpfish)                         # no limit row for the lumpfish
        self.limit('oxygen_mg_l', critical_low=6)
        self.sample(point=self.loop, hours=1, oxygen_mg_l='5')
        reading = self.latest().get('oxygen_mg_l')
        self.assertEqual((reading.point, reading.judged, reading.uncovered), (self.loop, Status.CRITICAL, ()))
        self.provider.now_values.clear()
        from ..models import WaterMeasurement
        WaterMeasurement.objects.all().delete()
        self.on(self.ras, self.value('oxygen_mg_l', 5.0))
        reading = self.latest().get('oxygen_mg_l')
        self.assertEqual((reading.judged, reading.uncovered), (Status.CRITICAL, ()))
        # the loop's own water is judged for every unit of the loop
        loop = self.latest(self.loop).get('oxygen_mg_l')
        self.assertEqual(loop.uncovered, (lumpfish.pk,))
