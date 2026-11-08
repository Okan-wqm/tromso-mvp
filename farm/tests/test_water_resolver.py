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
        self.sample(point=inlet, hours=1, temperature_c='14.0')                # the supply stream: never the unit's
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


class WorstFreshDecidesTests(SourcesCase):
    """Owner decision 2026-11-08 on the second cross review's P2: the value SHOWN stays A9's choice (the unit's own newest
    fresh value), but the STATUS (and so the alarm) is the worst of every fresh value the unit has: its own points' and
    its system's. When a worse fresh value decides it, the reading says so ("system sensor #1 reads 3.00 now ..."): danger
    is never hidden behind a newer or nearer OK. An inlet never counts (it is the supply stream)."""

    def setUp(self):
        super().setUp()
        self.stock()
        self.limit('oxygen_mg_l', critical_low=5, warning_low=7)

    def test_p2_a_critical_system_probe_is_never_hidden_by_the_units_own_older_ok(self):
        self.sample(hours=20, oxygen_mg_l='9', temperature_c='10', salinity_ppt='0')
        self.on(self.ras, self.value('oxygen_mg_l', 3.0, seconds=30))
        water = self.latest()
        reading = water.get('oxygen_mg_l')
        self.assertEqual((reading.value, reading.origin), (D('9.00'), read.Origin.MANUAL))     # shown: its own
        self.assertEqual((reading.status, reading.judged), (Status.CRITICAL, Status.CRITICAL))
        self.assertIn('system sensor #1 reads 3.00', reading.note)
        self.assertEqual(water.status, Status.CRITICAL)

    def test_the_card_and_the_water_page_say_it(self):
        self.sample(hours=20, oxygen_mg_l='9', temperature_c='10', salinity_ppt='0')
        self.on(self.ras, self.value('oxygen_mg_l', 3.0, seconds=30))
        from django.urls import reverse
        card = self.client.get(reverse('monitoring:monitor'), {'occupancy': 'all'}).content.decode()
        self.assertTrue('system sensor #1 reads 3.00' in card, 'the card says the worse fresh value')
        page = self.client.get(reverse('farm:water')).content.decode()
        self.assertTrue('system sensor #1 reads 3.00' in page, 'the water page says the worse fresh value')

    def test_a_worse_fresh_value_at_another_own_point_decides_the_status(self):
        drain = point_of(self.t1, 'bottom_drain')
        self.sample(point=drain, hours=2, oxygen_mg_l='4')
        self.sample(hours=1, oxygen_mg_l='9')
        reading = self.latest().get('oxygen_mg_l')
        self.assertEqual((reading.value, reading.point, reading.status), (D('9.00'), self.mid1, Status.CRITICAL))
        self.assertIn('reads 4.00', reading.note)

    def test_an_inlet_never_decides_the_units_status(self):
        inlet = point_of(self.t1, 'inlet')
        self.sample(point=inlet, hours=1, oxygen_mg_l='3')
        self.sample(hours=2, oxygen_mg_l='9')
        reading = self.latest().get('oxygen_mg_l')
        self.assertEqual((reading.value, reading.status, reading.note), (D('9.00'), Status.OK, ''))

    def test_a_stale_worse_value_does_not_decide_and_a_better_one_says_nothing(self):
        self.sample(point=self.loop, hours=30, oxygen_mg_l='3')            # stale: shown nowhere for the unit
        self.on(self.ras, self.value('oxygen_mg_l', 10.0, seconds=30))     # fresh and better
        self.sample(hours=1, oxygen_mg_l='8')
        reading = self.latest().get('oxygen_mg_l')
        self.assertEqual((reading.value, reading.status, reading.note), (D('8.00'), Status.OK, ''))

    def test_one_loop_value_is_judged_for_each_unit_on_its_own(self):
        """A loop sample standing in for two units is judged for each unit's fish: one unit's judgement never lands on
        the other's reading (each reading judged on its own copy)."""
        lumpfish = make_species(code='LUM', common_name='Lumpfish', scientific_name='Cyclopterus lumpus')
        self.stock(unit=self.t2, species=lumpfish)
        self.sample(point=self.loop, hours=1, oxygen_mg_l='5.5')
        water = read.latest([self.mid1, self.mid2], now=self.now)
        self.assertEqual(water[self.mid1.pk].get('oxygen_mg_l').status, Status.WARNING)
        self.assertEqual(water[self.mid2.pk].get('oxygen_mg_l').status, Status.NO_LIMIT)


class StaleNeverCalculatesTests(SourcesCase):
    """PLAN A9.3: a stale value never enters a calculation. A conversion uses the temperature and the salinity fresh AT
    the value's own time (at or before it, no older than their freshness, or measured within evaluate.CLOCK_SKEW after
    it); else the result is not worked out and says why (second cross review, finding 3 and P8)."""

    def saltwater(self):
        from ..models import Tank
        Tank.objects.filter(pk=self.t1.pk).update(water_type='saltwater')

    def test_a_salinity_older_than_its_freshness_is_not_used(self):
        self.saltwater()
        self.sample(hours=10 * 24, salinity_ppt='33')                       # 10 days: salinity is fresh for 7
        self.sample(hours=1, oxygen_mg_l='8', temperature_c='9')
        percent = self.latest().get('oxygen_saturation_pct')
        self.assertIsNone(percent.value)
        self.assertEqual(percent.note, 'Needs the salinity: none was measured here in the 7 days before.')
        self.sample(hours=5 * 24, salinity_ppt='33')
        self.assertIsNotNone(self.latest().get('oxygen_saturation_pct').value)

    def test_p8_a_stale_saturation_is_never_judged_with_todays_temperature(self):
        self.stock()
        self.limit('oxygen_mg_l', critical_low=5, warning_low=7)
        self.on(self.mid1, self.value('oxygen_saturation_pct', 60.0, seconds=3 * 86400, fresh_for=180))
        judged = []
        for today in ('4.0', '20.0'):
            from ..models import WaterMeasurement
            WaterMeasurement.objects.all().delete()
            self.sample(hours=1, temperature_c=today, salinity_ppt='0')
            judged.append(self.latest().get('oxygen_saturation_pct').judged)
        self.assertEqual(judged, [Status.NO_LIMIT, Status.NO_LIMIT])

    def test_a_fresh_saturation_is_judged_with_a_temperature_from_its_own_moment(self):
        self.stock()
        self.limit('oxygen_mg_l', critical_low=5, warning_low=7)
        self.sample(hours=2, temperature_c='9', salinity_ppt='0')           # before the value, fresh at its time
        self.on(self.mid1, self.value('oxygen_saturation_pct', 35.0, seconds=10))
        self.assertEqual(self.latest().get('oxygen_saturation_pct').judged, Status.CRITICAL)

    def test_a_stale_sensor_tan_gives_no_nh3_and_says_it_is_old(self):
        self.on(self.mid1, self.value('tan_mg_l', 1.0, seconds=3600, fresh_for=180),
                self.value('ph', 7.5, seconds=10, channel_no=2), self.value('temperature_c', 10.0, seconds=10,
                                                                             channel_no=3))
        nh3 = self.latest().get('nh3_n_mg_l')
        self.assertIsNone(nh3.value)
        self.assertEqual(nh3.note, 'Not worked out: the TAN is no longer fresh.')


class JudgedThroughTheOtherUnitTests(SourcesCase):
    """A % judged against an mg/L limit (or the reverse) through the solubility says so: the value it was judged as,
    what that was worked out from and the limit used (second cross review, finding 5)."""

    def test_the_saturation_judged_against_the_mg_l_row_says_how(self):
        self.stock()
        self.limit('oxygen_mg_l', critical_low=6)
        self.sample(hours=1, temperature_c='9', salinity_ppt='0')
        self.on(self.mid1, self.value('oxygen_saturation_pct', 35))
        reading = self.latest().get('oxygen_saturation_pct')
        self.assertEqual(reading.judged, Status.CRITICAL)
        self.assertIsNotNone(getattr(reading, 'through', None), 'the converted reading is kept')
        self.assertEqual((reading.through.code, [row.parameter for row in reading.through.limits]),
                         ('oxygen_mg_l', ['oxygen_mg_l']))
        self.assertRegex(reading.note, r'Judged as \d+\.\d\d mg/L\. Worked out from 9\.0 °C, 0\.0 ‰ and 1\.000 atm')
        self.assertIn('Atlantic salmon: critical below 6.00', reading.note)
        from django.urls import reverse
        card = self.client.get(reverse('monitoring:monitor'), {'occupancy': 'all'}).content.decode()
        self.assertTrue('Judged as ' in card, 'the card says how the % was judged')
