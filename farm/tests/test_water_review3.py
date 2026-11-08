"""The third cross review of wip/fix-monitoring (REVIEW-CROSS-3-monitoring.md) and the coordinator's decisions on it:

1. every limited quantity, a column or a derived one (NH3-N), goes through the worst fresh value (A10.1): a fresh
   critical NH3 is never hidden by a newer OK TAN elsewhere (probes N1, N2);
2. a unit without an active middle point still gets its status from its other own-water points and its system (B5);
3. a value stamped ahead of the server's clock by more than CLOCK_SKEW, up to the ingest contract's 3600 s, takes part
   in the status with a note "device clock is ahead by N min", never shown as the newest (B2); beyond 3600 s it is a
   data error the card says ("timestamp in the future"), never silently OK;
4. a derived oxygen is not a second card reason beside the measurement it comes from;
5. A11: with every temperature stale, the ration takes the most recently entered one across all tiers (B7b);
7. a probe on the loop point is a "system sensor";
8. a point's own old critical stays in its point_status when another point's value is shown."""
from datetime import timedelta
from decimal import Decimal

from django.urls import reverse

from .. import withdrawal_gate
from ..feeding.temperature import temperature_for
from ..models import SamplingPoint
from ..water import parameters, read
from ..water.evaluate import Status
from .helpers import point_of
from .test_water_sources import SourcesCase

D = Decimal


class DerivedWorstFreshTests(SourcesCase):
    def setUp(self):
        super().setUp()
        self.stock()
        self.limit('nh3_n_mg_l', warning_high='0.01', critical_high='0.02')

    def test_n1_a_fresh_critical_manual_nh3_beside_a_newer_ok_sensor_tan(self):
        self.sample(hours=1, tan_mg_l='2.000', ph='8.0', temperature_c='15', salinity_ppt='0')   # NH3 critical
        self.on(self.mid1, self.value('tan_mg_l', 0.1, seconds=30, channel_no=1),
                self.value('ph', 7.0, seconds=30, channel_no=2),
                self.value('temperature_c', 10.0, seconds=30, channel_no=3))
        nh3 = self.latest().get('nh3_n_mg_l')
        self.assertEqual(nh3.origin, read.Origin.SENSOR)                     # shown: the newest, the sensor's
        self.assertEqual(nh3.status, Status.CRITICAL)                        # decided by the fresh manual NH3
        self.assertIn('reads 0.05', nh3.note)

    def test_n2_a_newer_ok_tan_at_the_outlet_never_hides_the_middles_critical_nh3(self):
        self.sample(hours=2, tan_mg_l='2.000', ph='8.0', temperature_c='15', salinity_ppt='0')
        outlet = point_of(self.t1, 'side_outlet')
        self.sample(point=outlet, hours=1, tan_mg_l='0.100', ph='7.0', temperature_c='10', salinity_ppt='0')
        water = self.latest()
        self.assertEqual(water.get('nh3_n_mg_l').status, Status.CRITICAL)
        self.assertEqual(water.point_status, Status.CRITICAL)                # measured at the middle itself

    def test_a_loops_fresh_critical_nh3_decides_beside_the_units_own_ok(self):
        self.sample(hours=1, tan_mg_l='0.100', ph='7.0', temperature_c='10', salinity_ppt='0')
        self.sample(point=self.loop, hours=2, tan_mg_l='2.000', ph='8.0', temperature_c='15', salinity_ppt='0')
        water = self.latest()
        self.assertEqual(water.get('nh3_n_mg_l').status, Status.CRITICAL)
        self.assertEqual(water.point_status, Status.OK)                      # nothing critical measured at the middle

    def test_every_limited_quantity_goes_through_the_worst_fresh_value(self):
        """Each parameter with a limit: an older fresh critical value at the middle is never hidden by a newer OK one
        at the outlet (the measured columns here; NH3-N, derived, above)."""
        outlet = point_of(self.t1, 'side_outlet')
        codes = {parameter.code for parameter in parameters.LIMITED}
        self.assertIn(parameters.NH3_N.code, codes)
        self.assertEqual(read.WORST_FRESH_CODES, frozenset(codes))
        from ..models import WaterMeasurement
        for parameter in parameters.LIMITED:
            if not parameter.measured:
                continue
            with self.subTest(code=parameter.code):
                with withdrawal_gate.opened('test fixture: each parameter on a clean slate'):
                    WaterMeasurement.objects.all().delete()
                middle = (parameter.low + parameter.high) / 2
                self.limit(parameter.code, critical_high=middle)
                self.sample(hours=2, **{parameter.code: parameter.high})
                self.sample(point=outlet, hours=1, **{parameter.code: parameter.low})
                self.assertEqual(self.latest().get(parameter.code).status, Status.CRITICAL)


class NoMiddlePointTests(SourcesCase):
    @withdrawal_gate.opened('test fixture: the middle point made inactive straight in the database')
    def test_b5_a_unit_without_a_middle_point_is_judged_from_its_outlet_and_its_system(self):
        self.stock()
        self.limit('oxygen_mg_l', critical_low=5, warning_low=7)
        outlet = point_of(self.t1, 'side_outlet')
        self.sample(point=outlet, hours=1, oxygen_mg_l='3', temperature_c='10', salinity_ppt='0')
        SamplingPoint.objects.filter(pk=self.mid1.pk).update(is_active=False)
        water = read.unit_water([self.t1])[self.t1.pk]
        self.assertTrue(water.for_unit)
        self.assertEqual(water.status, Status.CRITICAL)
        card = self.client.get(reverse('monitoring:monitor'), {'occupancy': 'all'}).content.decode()
        self.assertIn('Dissolved oxygen (mg/L O₂) (T-01 › Side outlet): Critical', card)
        from ..models import WaterMeasurement
        WaterMeasurement.objects.all().delete()
        self.on(self.ras, self.value('oxygen_mg_l', 8.0, seconds=30))      # nothing of its own: the system's
        self.assertEqual(read.unit_water([self.t1])[self.t1.pk].status, Status.OK)


class ClockAheadTests(SourcesCase):
    def setUp(self):
        super().setUp()
        self.stock()
        self.limit('oxygen_mg_l', critical_low=5, warning_low=7)
        self.sample(hours=1, oxygen_mg_l='9', temperature_c='10', salinity_ppt='0')

    def test_b2_a_critical_value_ten_minutes_ahead_decides_the_status_and_says_the_clock_is_ahead(self):
        self.on(self.mid1, self.value('oxygen_mg_l', 3.0, seconds=-600))
        reading = self.latest().get('oxygen_mg_l')
        self.assertEqual(reading.value, D('9.00'))                           # never shown as the newest
        self.assertEqual(reading.status, Status.CRITICAL)
        self.assertIn('device clock is ahead by 10 min', reading.note)

    def test_a_value_more_than_an_hour_ahead_is_a_data_error_the_card_says(self):
        self.on(self.mid1, self.value('oxygen_mg_l', 9.5, seconds=-2 * 3600))
        water = self.latest()
        self.assertEqual(water.get('oxygen_mg_l').value, D('9.00'))
        self.assertEqual([reading.code for reading in water.future], ['oxygen_mg_l'])
        card = self.client.get(reverse('monitoring:monitor'), {'occupancy': 'all'}).content.decode()
        self.assertIn('Dissolved oxygen (mg/L O₂): timestamp in the future', card)


class ReasonsTests(SourcesCase):
    def test_a_derived_saturation_is_not_a_second_reason_beside_its_measurement(self):
        from monitoring import read as monitoring_read
        self.stock()
        self.limit('oxygen_mg_l', critical_low=5)
        self.limit('oxygen_saturation_pct', critical_low=60)
        self.sample(hours=1, oxygen_mg_l='4', temperature_c='10', salinity_ppt='0')     # the % is worked out from it
        water = self.latest()
        self.assertEqual(water.get('oxygen_saturation_pct').status, Status.CRITICAL)
        critical, _warning, _old = monitoring_read._alerts(water, self.now)
        self.assertEqual(critical, ['Dissolved oxygen (mg/L O₂): Critical'])


class A11Tests(SourcesCase):
    def test_b7b_with_everything_stale_the_ration_takes_the_most_recently_entered_temperature(self):
        self.sample(hours=24 * 8, temperature_c='9.0')
        loop = self.sample(point=self.loop, hours=24 * 2, temperature_c='14.0')
        found = temperature_for([self.t1], self.now)[self.t1.pk]
        self.assertEqual((found.value_c, found.via, found.fresh), (D('14.0'), read.SYSTEM, False))
        self.assertIn('(2 days old)', found.warning)
        del loop


class LoopProbeTests(SourcesCase):
    def test_a_probe_on_the_loop_point_is_a_system_sensor(self):
        self.on(self.loop, self.value('temperature_c', 12.0, seconds=30))
        reading = self.latest().get('temperature_c')
        self.assertEqual((reading.origin, read.origin_text(reading)), (read.Origin.SYSTEM_SENSOR, 'system sensor #1'))


class MeasuredHereTests(SourcesCase):
    def test_a_middles_own_old_critical_stays_in_its_point_status_when_another_points_value_is_shown(self):
        self.stock()
        self.limit('co2_mg_l', critical_high=15)
        self.sample(hours=80, co2_mg_l='15.6')                               # the middle's own, older than 72 h
        side = point_of(self.t1, 'side_outlet')
        self.sample(point=side, hours=75, co2_mg_l='8')                      # newer, also stale: shown for the unit
        water = self.latest()
        self.assertEqual(water.get('co2_mg_l').point, side)
        self.assertEqual(water.point_status, Status.CRITICAL)                # "critical, no recent data" at the middle
