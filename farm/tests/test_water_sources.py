"""The water's other sources (farm/water/sources.py): live values from a provider (the sensors app registers one; these
tests a fake), resolved per parameter, each on its own, in ONE place (farm/water/read.py `latest`), in the owner's order
(owner amendment A1):

1. a fresh value bound to the point itself, the primary channel before the backup;
2. else, for the middle point of a unit or of a system, a fresh value bound to the system (the unit's `system`);
3. else the latest manual or lab value, when it is fresh;
4. else the newest of what there is, shown stale.

Every value says where it comes from and how old it is, on the water page, the monitoring card and the Deffeyes window.
Derived values (NH3, the other oxygen unit) need all their inputs from one kind of source: a sensor TAN with sensor pH and
temperature (the oldest input's time), a manual TAN with its own sample's pH and temperature, never a mix. A provider that
fails leaves the manual values and says so."""
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from django.test import SimpleTestCase
from django.urls import reverse

from ..models import SamplingPoint
from ..water import calculation, read, sources
from ..water.evaluate import Status, is_fresh
from ..water.parameters import get
from .helpers import point_of
from .test_water import WaterTestCase

D = Decimal
PRIMARY, BACKUP = sources.PRIMARY, sources.BACKUP


@dataclass
class FakeProvider:
    """Values per target, as the sensors app would give them: {(kind, pk): {code: [SensorValue]}}; `history` for
    value_at: {(kind, pk): {code: [SensorValue]}} of every stored value."""
    now_values: dict = field(default_factory=dict)
    history: dict = field(default_factory=dict)
    broken: bool = False
    asked: list = field(default_factory=list)

    def latest(self, targets, now):
        self.asked.append(('latest', tuple(sorted(targets, key=str))))
        if self.broken:
            raise RuntimeError('the sensors database is not reachable')
        return {target: self.now_values[target] for target in targets if target in self.now_values}

    def value_at(self, targets, code, moment):
        if self.broken:
            raise RuntimeError('the sensors database is not reachable')
        found = {}
        for target in targets:
            values = [value for value in self.history.get(target, {}).get(code, []) if value.at <= moment]
            if values:
                newest = {}
                for value in sorted(values, key=lambda item: item.at):
                    newest[value.channel_no] = value
                found[target] = list(newest.values())
        return found


class SourcesCase(WaterTestCase):
    def setUp(self):
        super().setUp()
        self.provider = FakeProvider()
        sources.register(self.provider)
        self.addCleanup(sources.unregister, self.provider)

    def value(self, code, value, seconds=10, fresh_for=180, role=PRIMARY, channel_no=1):
        return sources.SensorValue(code=code, value=value, at=self.now - timedelta(seconds=seconds),
                                   fresh_for=fresh_for, role=role, channel_no=channel_no)

    def on(self, target, *values):
        kind = sources.SYSTEM if target is self.ras else sources.POINT
        key = (kind, target.pk)
        for item in values:
            self.provider.now_values.setdefault(key, {}).setdefault(item.code, []).append(item)
            self.provider.history.setdefault(key, {}).setdefault(item.code, []).append(item)

    def latest(self, point=None):
        point = point or self.mid1
        return read.latest([point], now=self.now)[point.pk]


class OrderTests(SourcesCase):
    def test_a_fresh_sensor_on_the_point_beats_a_fresh_manual_value(self):
        self.sample(hours=1, ph='7.10')
        self.on(self.mid1, self.value('ph', 7.4111))
        reading = self.latest().get('ph')
        self.assertEqual(reading.value, D('7.41'))                     # quantized as a manual pH is
        self.assertEqual(reading.sample.origin, read.Origin.SENSOR)
        self.assertEqual(reading.sample.channel_no, 1)
        self.assertEqual(reading.at, self.now - timedelta(seconds=10))

    def test_the_backup_when_the_primary_is_stale_and_the_primary_when_both_are_fresh(self):
        self.on(self.mid1, self.value('ph', 7.0, seconds=600, channel_no=1),
                self.value('ph', 7.2, seconds=5, role=BACKUP, channel_no=2))
        self.assertEqual(self.latest().get('ph').sample.channel_no, 2)
        self.on(self.mid1, self.value('ph', 7.3, seconds=20, channel_no=3))
        self.assertEqual(self.latest().get('ph').sample.channel_no, 3)

    def test_the_system_sensor_when_the_unit_has_no_fresh_sensor_of_its_own(self):
        self.on(self.ras, self.value('temperature_c', 9.54))
        reading = self.latest().get('temperature_c')
        self.assertEqual((reading.value, reading.sample.origin), (D('9.5'), read.Origin.SYSTEM_SENSOR))
        self.on(self.mid1, self.value('temperature_c', 10.0, seconds=400, fresh_for=180))      # its own, stale
        self.assertEqual(self.latest().get('temperature_c').sample.origin, read.Origin.SYSTEM_SENSOR)
        self.on(self.mid1, self.value('temperature_c', 10.2, seconds=30, channel_no=5))
        self.assertEqual(self.latest().get('temperature_c').sample.origin, read.Origin.SENSOR)

    def test_the_system_tier_is_for_the_middle_point_only(self):
        inlet = point_of(self.t1, 'inlet')
        self.on(self.ras, self.value('temperature_c', 9.5))
        self.assertIsNone(read.latest([inlet], now=self.now)[inlet.pk].get('temperature_c'))
        # the system's own middle point (its loop) has the system's sensors as its own
        self.assertEqual(self.latest(self.loop).get('temperature_c').sample.origin, read.Origin.SYSTEM_SENSOR)

    def test_a_fresh_manual_value_beats_stale_sensors(self):
        self.sample(hours=2, ph='7.00')
        self.on(self.mid1, self.value('ph', 7.4, seconds=3600, fresh_for=900))
        reading = self.latest().get('ph')
        self.assertEqual((reading.value, reading.sample.origin), (D('7.00'), read.Origin.MANUAL))

    def test_with_nothing_fresh_the_newest_value_is_shown_stale(self):
        self.stock()
        self.limit('temperature_c', warning_high=14)
        self.sample(hours=30, temperature_c='8.0')                          # stale after 24 h
        self.on(self.mid1, self.value('temperature_c', 9.0, seconds=7200, fresh_for=180))
        reading = self.latest().get('temperature_c')
        self.assertEqual((reading.value, reading.status, reading.sample.origin),
                         (D('9.0'), Status.STALE, read.Origin.SENSOR))
        self.on(self.mid1, self.value('temperature_c', 9.1, seconds=40 * 3600, fresh_for=180, channel_no=9))
        self.provider.now_values[(sources.POINT, self.mid1.pk)]['temperature_c'] = [
            self.value('temperature_c', 9.1, seconds=40 * 3600, fresh_for=180)]
        reading = self.latest().get('temperature_c')
        self.assertEqual((reading.value, reading.sample.origin), (D('8.0'), read.Origin.MANUAL))   # newer than it

    def test_each_parameter_is_resolved_on_its_own(self):
        self.sample(hours=3, alkalinity_mg_l='90', salinity_ppt='0', ph='6.9', temperature_c='8')
        self.on(self.mid1, self.value('ph', 7.4))
        self.on(self.ras, self.value('temperature_c', 9.5))
        water = self.latest()
        origins = {code: water.get(code).sample.origin for code in ('ph', 'temperature_c', 'alkalinity_mg_l',
                                                                    'salinity_ppt')}
        self.assertEqual(origins, {'ph': read.Origin.SENSOR, 'temperature_c': read.Origin.SYSTEM_SENSOR,
                                   'alkalinity_mg_l': read.Origin.MANUAL, 'salinity_ppt': read.Origin.MANUAL})

    def test_a_lab_value_says_so(self):
        self.sample(hours=1, source='lab', alkalinity_mg_l='80')
        self.assertEqual(self.latest().get('alkalinity_mg_l').sample.origin, read.Origin.LAB)

    def test_a_failing_provider_leaves_the_manual_values_and_says_so(self):
        self.sample(hours=1, ph='7.00')
        self.provider.broken = True
        water = self.latest()
        self.assertEqual(water.get('ph').value, D('7.00'))
        self.assertTrue(water.sensors_failed)
        self.provider.broken = False
        self.assertFalse(self.latest().sensors_failed)

    def test_one_call_to_the_provider_for_all_points(self):
        read.latest([self.mid1, self.mid2, self.loop], now=self.now)
        self.assertEqual(len([ask for ask in self.provider.asked if ask[0] == 'latest']), 1)


class DerivedTests(SourcesCase):
    def test_sensor_tan_with_sensor_ph_and_temperature_gives_nh3_at_the_oldest_input(self):
        self.on(self.mid1, self.value('tan_mg_l', 1.0, seconds=30, channel_no=1),
                self.value('ph', 7.5, seconds=90, channel_no=2), self.value('temperature_c', 10.0, seconds=10, channel_no=3))
        water = self.latest()
        nh3 = water.get('nh3_n_mg_l')
        self.assertIsNotNone(nh3.value)
        self.assertEqual(nh3.at, self.now - timedelta(seconds=90))
        self.assertTrue(nh3.derived)
        self.assertEqual(nh3.sample.origin, read.Origin.SENSOR)

    def test_a_manual_tan_is_never_mixed_with_a_sensor_ph(self):
        self.sample(hours=1, tan_mg_l='1.000')                  # no pH or temperature in the sample
        self.on(self.mid1, self.value('ph', 7.5), self.value('temperature_c', 10.0, channel_no=2))
        nh3 = self.latest().get('nh3_n_mg_l')
        self.assertIsNone(nh3.value)
        self.assertEqual(nh3.note, 'Needs the pH and the temperature of the same sample.')

    def test_a_sensor_tan_without_fresh_sensor_ph_is_not_worked_out(self):
        self.sample(hours=1, ph='7.5', temperature_c='10')
        self.on(self.mid1, self.value('tan_mg_l', 1.0))
        nh3 = self.latest().get('nh3_n_mg_l')
        self.assertIsNone(nh3.value)

    def test_sensor_oxygen_with_sensor_temperature_gives_the_saturation(self):
        self.sample(hours=1, salinity_ppt='0')
        self.on(self.mid1, self.value('oxygen_mg_l', 10.0, seconds=20), self.value('temperature_c', 10.0, seconds=50,
                                                                                  channel_no=2))
        water = self.latest()
        saturation = water.get('oxygen_saturation_pct')
        self.assertTrue(saturation.derived)
        self.assertEqual(saturation.at, self.now - timedelta(seconds=50))
        self.assertAlmostEqual(float(saturation.value), 100 * 10 / 11.288, delta=0.2)

    def test_the_sensor_value_is_judged_as_a_manual_one(self):
        self.stock()
        self.limit('oxygen_mg_l', critical_low=6, warning_low=7)
        self.on(self.mid1, self.value('oxygen_mg_l', 5.996))
        reading = self.latest().get('oxygen_mg_l')
        self.assertEqual((reading.value, reading.status), (D('6.00'), Status.WARNING))


class FreshnessTests(SimpleTestCase):
    def test_fresh_for_seconds_overrides_the_parameters_hours(self):
        from datetime import datetime, timezone
        now = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)
        temperature = get('temperature_c')
        self.assertTrue(is_fresh(temperature, now - timedelta(hours=23), now))
        self.assertFalse(is_fresh(temperature, now - timedelta(seconds=181), now, fresh_for=180))
        self.assertTrue(is_fresh(temperature, now - timedelta(seconds=180), now, fresh_for=180))


class SeriesTests(SourcesCase):
    def test_a_unit_s_temperature_at_a_moment_takes_a_fresh_sensor_value(self):
        from ..feeding.temperature import temperature_for
        self.sample(hours=5, temperature_c='8.0')
        self.on(self.mid1, self.value('temperature_c', 9.73, seconds=60))
        found = temperature_for([self.t1], self.now)[self.t1.pk]
        self.assertEqual((found.value_c, found.via, found.fresh), (D('9.7'), read.UNIT, True))

    def test_a_stale_sensor_value_gives_way_to_a_fresh_manual_one(self):
        from ..feeding.temperature import temperature_for
        self.sample(hours=5, temperature_c='8.0')
        self.on(self.mid1, self.value('temperature_c', 9.7, seconds=3600, fresh_for=180))
        found = temperature_for([self.t1], self.now)[self.t1.pk]
        self.assertEqual(found.value_c, D('8.0'))

    def test_the_system_sensor_reaches_the_loop_point(self):
        from ..feeding.temperature import temperature_for
        self.on(self.ras, self.value('temperature_c', 11.04, seconds=30))
        found = temperature_for([self.t1], self.now)[self.t1.pk]
        self.assertEqual((found.value_c, found.via), (D('11.0'), read.SYSTEM))

    def test_no_value_from_after_the_moment(self):
        from ..feeding.temperature import temperature_for
        self.on(self.mid1, self.value('temperature_c', 9.7, seconds=-60))       # a minute after the moment asked
        self.assertIsNone(temperature_for([self.t1], self.now)[self.t1.pk])


class ShownTests(SourcesCase):
    def setUp(self):
        super().setUp()
        self.sample(hours=26, alkalinity_mg_l='90', salinity_ppt='0', ph='7.0', temperature_c='8')
        self.on(self.mid1, self.value('ph', 7.41, seconds=12))
        self.on(self.ras, self.value('temperature_c', 9.5, seconds=40))

    def test_the_deffeyes_window_names_each_inputs_origin_and_age(self):
        chart = calculation.chart_of(self.t1, now=self.now)
        origins = {item.field: item.reading.sample.origin for item in chart.inputs if item.reading}
        self.assertEqual(origins, {'ph': read.Origin.SENSOR, 'temperature_c': read.Origin.SYSTEM_SENSOR,
                                   'alkalinity_mg_l': read.Origin.MANUAL, 'salinity_ppt': read.Origin.MANUAL})
        html = self.client.get(reverse('farm:water_unit_chart', args=[self.t1.pk])).content.decode()
        self.assertRegex(html, r'unit sensor #\d+ · 1[2-9] s ago')
        self.assertRegex(html, r'system sensor #\d+ · 4[0-9] s ago')
        self.assertRegex(html, r'manual · 1.day ago')

    def test_the_water_page_and_the_card_name_the_origin(self):
        self.stock()                                              # an empty unit's card shows no water
        page = self.client.get(reverse('farm:water')).content.decode()
        self.assertRegex(page, r'unit sensor #\d+ · 1[2-9] s ago')
        card = self.client.get(reverse('monitoring:monitor'), {'occupancy': 'all'}).content.decode()
        self.assertRegex(card, r'unit sensor #\d+ · 1[2-9] s ago')
        self.assertRegex(card, r'system sensor #\d+ · 4[0-9] s ago')
