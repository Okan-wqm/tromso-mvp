"""A water the core refuses is never silent for the alarms (the verification of 2026-11-18, V-A). The verifier's water:
a fresh stocked unit whose fish have an NH₃-N limit of 0.025 (critical); 12.0 °C, S 0, alkalinity 80, pH 9.00, TAN
5.000. Without a conductivity its NH₃-N is 0.8924, 36 times the limit, and a warning and a critical alarm open. With a
conductivity of 40 000 µS/cm (stored: it is inside the parameter's range) the core refuses the water (its ionic
strength is past the Davies range), the NH₃ had no value, and a reading without a value raised nothing: no alarm, no
state. Now a judged value the core refuses is "cannot be evaluated" with the core's reason: the unit's state says so
on every page, and the alarm source raises a warning of the alarm system for the unit (the mechanism of a unit that
cannot be evaluated: a subject `system:unit:<id>:…`), which ends once the value can be worked out again. An alarm
already open is not cleared by it, and nothing falls back to another basis."""
from datetime import timedelta
from unittest import mock

from django.urls import reverse

from core.models import Profile
from farm.models import WaterLimit
from farm.tests.test_water import WaterTestCase
from farm.water import read as water_read

from .. import engine, read
from ..models import Alarm

WATER = {'ph': '9.00', 'temperature_c': '12.0', 'salinity_ppt': '0.0', 'alkalinity_mg_l': '80', 'tan_mg_l': '5.000'}
WHY = 'ionic strength above 0.5: outside the range of the Davies equation'
NH3 = 'nh3_n_mg_l'


class RefusedWaterCase(WaterTestCase):
    def setUp(self):
        super().setUp()
        self.stock()
        self.stock(self.t2)
        self.limit(NH3, critical_high='0.025', warning_high='0.0125')

    def run_pass(self, minutes=0):
        return engine.run_once(self.now + timedelta(minutes=minutes))

    def open_alarms(self, **filters):
        return Alarm.objects.filter(clearance__isnull=True, **filters).order_by('severity')

    def refuse(self, unit, hours=1):
        return self.sample(unit, hours=hours, **WATER, conductivity_25_us_cm='40000')


class ReadingTests(RefusedWaterCase):
    def test_the_same_water_without_the_conductivity_is_36_times_the_limit(self):
        self.sample(self.t2, **WATER)
        reading = self.unit_water(self.t2).get(NH3)
        self.assertEqual((str(reading.value), reading.status), ('0.8924', 'critical'))
        self.run_pass()
        self.assertEqual([(alarm.source, alarm.severity) for alarm in self.open_alarms()],
                         [('water_limit', 'critical'), ('water_limit', 'warning')])

    def test_a_refused_judged_value_cannot_be_evaluated_and_says_why(self):
        self.refuse(self.t2)
        water = self.unit_water(self.t2)
        reading = water.get(NH3)
        self.assertIsNone(reading.value)
        self.assertEqual((reading.status, reading.judged), ('unevaluated', 'unevaluated'))
        self.assertIn(WHY, reading.refused)
        self.assertIn(f'Cannot be worked out: {WHY}', str(reading.note))
        self.assertEqual(water.status, 'unevaluated')                # never OK behind a fine pH
        self.assertEqual([each.code for each in water.unevaluated], [NH3])

    def test_a_fine_value_beside_it_never_makes_the_unit_ok(self):
        self.limit('ph', critical_low=6, warning_low='6.5', warning_high='9.5', critical_high=10)
        self.refuse(self.t2)
        water = self.unit_water(self.t2)
        self.assertEqual((water.get('ph').status, water.status), ('ok', 'unevaluated'))

    def test_a_critical_value_beside_it_stays_the_units_status(self):
        self.limit('ph', critical_low=6, warning_low='6.5', warning_high='8.0', critical_high='8.5')
        self.refuse(self.t2)
        self.assertEqual(self.unit_water(self.t2).status, 'critical')

    def test_without_a_limit_or_without_fish_nothing_is_judged_so_nothing_is_said(self):
        self.refuse(self.t2)
        WaterLimit.objects.all().delete()
        water = self.unit_water(self.t2)
        self.assertEqual((water.get(NH3).status, water.unevaluated), ('not_measured', []))
        self.run_pass()
        self.assertFalse(Alarm.objects.exists())

    def test_the_history_row_says_it(self):
        sample = self.refuse(self.t2)
        row = water_read.history([sample])[0]
        self.assertEqual((row.readings[NH3].status, row.status), ('unevaluated', 'unevaluated'))


class AlarmTests(RefusedWaterCase):
    def test_a_refused_water_raises_a_warning_of_the_alarm_system_for_the_unit(self):
        self.refuse(self.t2)
        summary = self.run_pass()
        self.assertEqual(summary.failed_steps, [])
        alarm = self.open_alarms().get()
        self.assertEqual((alarm.source, alarm.severity, alarm.parameter, alarm.site, alarm.production_department),
                         ('system', 'warning', NH3, self.bergen, self.hall))
        self.assertTrue(alarm.summary.startswith(
            f'T-02: Un-ionised ammonia (mg/L NH₃ as N) cannot be evaluated: {WHY}'), alarm.summary)
        self.assertLessEqual(len(alarm.summary), 300)
        self.run_pass(minutes=1)                                        # the same pass again: one alarm, not two
        self.assertEqual(self.open_alarms().count(), 1)

    def test_it_ends_once_the_value_can_be_worked_out_and_the_limit_then_alarms(self):
        self.refuse(self.t2, hours=2)
        self.run_pass()
        alarm = self.open_alarms().get()
        self.sample(self.t2, hours=1, **WATER, conductivity_25_us_cm='500')
        for minutes in (1, 2, 60):
            self.run_pass(minutes=minutes)
        self.assertFalse(read.is_open(alarm))
        self.assertEqual(alarm.clearance.cause, 'restored')
        self.assertEqual([(each.source, each.severity) for each in self.open_alarms()],
                         [('water_limit', 'critical'), ('water_limit', 'warning')])

    def test_an_alarm_already_open_is_not_cleared_by_the_refusal(self):
        self.sample(self.t1, hours=3, **WATER)
        self.run_pass()
        self.assertEqual(self.open_alarms(source='water_limit').count(), 2)
        self.refuse(self.t1, hours=1)
        for minutes in (0, 1, 2, 60, 600):
            self.run_pass(minutes=minutes)
        self.assertEqual([each.severity for each in self.open_alarms(source='water_limit')], ['critical', 'warning'])
        self.assertIn('T-01', self.open_alarms(source='system').get().summary)

    def test_a_30_hour_old_conductivity_of_the_point_refuses_a_new_sample_and_the_unit_alarms(self):
        """The looked-up case: the new sample has no conductivity; the point's own of 30 hours ago is fresh for days."""
        self.sample(self.t2, hours=30, conductivity_25_us_cm='45000')
        self.sample(self.t2, hours=1, **WATER)
        reading = self.unit_water(self.t2).get(NH3)
        self.assertEqual((reading.value, reading.status), (None, 'unevaluated'))
        self.run_pass()
        alarm = self.open_alarms().get()
        self.assertEqual((alarm.source, alarm.severity, alarm.parameter), ('system', 'warning', NH3))
        self.assertIn(f'T-02: Un-ionised ammonia (mg/L NH₃ as N) cannot be evaluated: {WHY}', alarm.summary)

    def test_a_unit_that_cannot_be_read_does_not_end_it_blind(self):
        self.refuse(self.t2)
        self.run_pass()
        alarm = self.open_alarms().get()
        real = water_read.unit_water

        def unit_water(units, now=None):
            if any(unit.pk == self.t2.pk for unit in units):
                raise ValueError('a bad row of T-02')
            return real(units, now)
        with mock.patch.object(water_read, 'unit_water', side_effect=unit_water), \
                self.assertLogs('alarms.sources', level='ERROR'):
            for minutes in (1, 2, 60):
                self.run_pass(minutes=minutes)
        self.assertTrue(read.is_open(alarm))

    def test_the_fish_gone_ends_it(self):
        self.refuse(self.t2)
        self.run_pass()
        alarm = self.open_alarms().get()
        WaterLimit.objects.all().delete()                           # nothing judges the value any more
        for minutes in (1, 2, 60):
            self.run_pass(minutes=minutes)
        self.assertFalse(read.is_open(alarm))


class PageTests(RefusedWaterCase):
    SAID = f'Un-ionised ammonia (mg/L NH₃ as N) cannot be evaluated: {WHY}'

    def test_the_water_page_says_the_units_state_and_the_reason(self):
        self.refuse(self.t2)
        page = self.client.get(reverse('farm:water'))
        row = next(row for row in page.context['rows'] if row['owner'] == self.t2)
        self.assertEqual(row['water'].status, 'unevaluated')
        body = page.content.decode()
        self.assertIn('wq-unevaluated', body)
        self.assertIn('<span>Cannot be evaluated</span>', body)
        self.assertIn(self.SAID, body)

    def test_in_norwegian_and_turkish(self):
        self.refuse(self.t2)
        for language, said in (('nb', 'Kan ikke vurderes'), ('tr', 'Değerlendirilemiyor')):
            with self.subTest(language=language):
                Profile.objects.update_or_create(user=self.user, defaults={'language': language})
                self.assertContains(self.client.get(reverse('farm:water')), said)
