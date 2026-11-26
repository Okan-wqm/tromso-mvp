"""A worked-out water value is never fresher than its oldest input (the coordinator's decision of 2026-11-26): its
freshness is the earliest moment any of the values it was worked out with stops being fresh (farm/water/freshness.py
`derived_until`, the inputs each parameter declares in farm/water/parameters.py), never later than its own row's hours.
An NH₃ worked out from a 5-day-old pH was fresh for its own 168 h while the pH it came from was fresh for 72 h. Every
reader asks `read.Reading.fresh` / `fresh_until`, so the pages, the cards and the alarms say it the same way."""
from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.utils import timezone

from monitoring.cards import render
from sensors import bindings
from sensors.tests import make_channel, make_connection, make_device, make_format

from ..models import SamplingPoint, Tank, WaterFreshness
from ..water import evaluate, freshness, parameters, read
from ..water.evaluate import Status
from .helpers import may_record
from .test_water import WaterTestCase

D = Decimal
NH3, NH4 = 'nh3_n_mg_l', 'nh4_n_mg_l'
TAN, PH, TEMPERATURE, SALINITY = parameters.TAN, parameters.PH, parameters.TEMPERATURE, parameters.SALINITY
FULL = {'tan_mg_l': '1.000', 'ph': '7.50', 'temperature_c': '12.0', 'salinity_ppt': '0.0'}


class DeclaredInputsGuardTests(TestCase):
    """The guard: a worked-out parameter (one not measured) cannot exist without the inputs its freshness is taken from,
    so a value to come (the CO₂ worked out from the carbonate system) cannot skip the rule."""

    def derived(self):
        return [parameter for parameter in parameters.BY_CODE.values() if not parameter.measured]

    def test_every_worked_out_parameter_declares_its_inputs(self):
        self.assertTrue(self.derived())
        for parameter in self.derived():
            with self.subTest(parameter=parameter.code):
                self.assertTrue(parameter.inputs, f'{parameter.code} is worked out and declares no inputs')
                for code in parameter.inputs:
                    self.assertIn(code, parameters.BY_CODE)
                    self.assertTrue(parameters.get(code).measured, f'{code} is not a measured input')
                    self.assertTrue(WaterFreshness.objects.filter(parameter=code).exists(), code)
                self.assertTrue(WaterFreshness.objects.filter(parameter=parameter.code).exists())
        for parameter in parameters.BY_CODE.values():
            if parameter.measured:
                self.assertEqual(parameter.inputs, (), parameter.code)

    def test_the_ammonia_is_worked_out_from_the_tan_the_ph_the_temperature_and_the_salinity(self):
        for code in (NH3, NH4):
            self.assertEqual(set(parameters.get(code).inputs), {TAN, PH, TEMPERATURE, SALINITY})

    def test_the_derived_codes_are_the_declared_ones(self):
        self.assertEqual(set(read.DERIVED), {parameter.code for parameter in self.derived()})
        self.assertEqual(set(parameters.DERIVED), set(read.DERIVED))

    def test_a_worked_out_parameter_without_inputs_is_refused_where_it_is_made(self):
        with self.assertRaises(ValueError):
            parameters._parameter('co2_worked_mg_l', 'CO₂', 'CO₂', 1, 0, 200, measured=False)

    def test_each_input_running_out_ends_it(self):
        """For every worked-out parameter and every one of its inputs: that input alone stale makes it stale."""
        now = at = timezone.now()
        for parameter in self.derived():
            for code in parameter.inputs:
                with self.subTest(parameter=parameter.code, input=code):
                    ends = {each: now + timedelta(days=1) for each in parameter.inputs}
                    ends[code] = now - timedelta(seconds=1)
                    until = freshness.derived_until(parameter.code, at, ends)
                    self.assertFalse(evaluate.is_fresh(parameter, at, now, until=until))
                    ends[code] = now + timedelta(seconds=1)
                    self.assertTrue(evaluate.is_fresh(parameter, at, now,
                                                      until=freshness.derived_until(parameter.code, at, ends)))

    def test_an_input_left_out_or_one_not_declared_is_refused(self):
        now = timezone.now()
        inputs = parameters.get(NH3).inputs
        with self.assertRaises(ValueError):
            freshness.derived_until(NH3, now, {code: now for code in inputs[1:]})
        with self.assertRaises(ValueError):
            freshness.derived_until(NH3, now, {**{code: now for code in inputs}, 'nitrite_n_mg_l': now})
        with self.assertRaises(ValueError):
            freshness.derived_until(TAN, now, {})

    def test_a_worked_out_value_is_never_judged_fresh_by_its_own_hours_alone(self):
        """The one rule refuses a worked-out parameter without the end its inputs give (`until`): no reader can fall
        back on the NH₃ row's 168 h."""
        now = timezone.now()
        with self.assertRaises(ValueError):
            evaluate.is_fresh(parameters.get(NH3), now - timedelta(hours=1), now)

    def test_its_own_row_still_caps_it(self):
        now = timezone.now()
        far = {code: now + timedelta(days=60) for code in parameters.get(NH3).inputs}
        self.assertEqual(freshness.derived_until(NH3, now, far), now + freshness.fresh_for(NH3))


class DerivedFreshnessTests(WaterTestCase):
    def context(self):
        return read.Context([self.mid1], self.now - read.WINDOW)

    def observation(self, hours, **values):
        return read.Observation(self.mid1, self.ago(hours=hours), read.Origin.MANUAL,
                                {code: D(value) for code, value in values.items()})

    def test_an_nh3_from_a_young_tan_and_an_old_ph_is_not_fresh(self):
        """The TAN 2 h old (fresh for 168 h), the pH 80 h old (fresh for 72 h): the NH₃ is not fresh."""
        ph = self.observation(80, ph='7.50')
        together = read.Observation.combined([self.observation(2, tan_mg_l='1.000'), ph,
                                              self.observation(1, temperature_c='12.0', salinity_ppt='0.0')])
        found = self.context().readings(together)
        for code in (NH3, NH4):
            with self.subTest(code=code):
                self.assertIsNotNone(found[code].value)
                self.assertEqual(found[code].fresh_until, ph.at + timedelta(hours=72))
                self.assertFalse(found[code].fresh(self.now))
        self.assertTrue(found[TAN].fresh(self.now))

    def test_young_inputs_give_a_fresh_nh3_that_ends_with_the_first_input(self):
        """One sample 1 h old: the NH₃ is fresh, and stale once its temperature (24 h) is, though its TAN (168 h) and its
        own row (168 h) are not."""
        self.sample(hours=1, **FULL)
        nh3 = self.unit_water().get(NH3)
        self.assertIsNotNone(nh3.value)
        self.assertTrue(nh3.fresh(self.now))
        self.assertEqual(nh3.status, Status.NO_LIMIT)
        ends = nh3.at + timedelta(hours=24)
        self.assertEqual(nh3.fresh_until, ends)
        self.assertTrue(nh3.fresh(ends))
        self.assertFalse(nh3.fresh(ends + timedelta(seconds=1)))
        tan = self.unit_water().get(TAN)
        self.assertTrue(tan.fresh(ends + timedelta(seconds=1)))

    def test_a_salinity_looked_up_from_an_earlier_sample_ends_it_first(self):
        """The salinity is not in the TAN sample: the point's salinity 160 h old stands in (fresh for 168 h, so 8 h
        more), and the NH₃ ends with it."""
        salinity = self.sample(hours=160, salinity_ppt='0.0')
        self.sample(hours=1, tan_mg_l='1.000', ph='7.50', temperature_c='12.0')
        nh3 = self.unit_water().get(NH3)
        self.assertIsNotNone(nh3.value)
        self.assertEqual(nh3.fresh_until, salinity.measured_at + timedelta(hours=168))
        self.assertTrue(nh3.fresh(self.now))
        self.assertFalse(nh3.fresh(self.now + timedelta(hours=8, seconds=1)))

    def test_a_changed_input_row_moves_it(self):
        """The inputs' freshness is the user's rows, read as every value's is."""
        self.sample(hours=30, **FULL)
        self.assertFalse(self.unit_water().get(NH3).fresh(self.now))
        WaterFreshness.objects.filter(parameter=TEMPERATURE).update(fresh_hours=48)
        freshness.forget()
        self.addCleanup(freshness.forget)
        self.assertTrue(self.unit_water().get(NH3).fresh(self.now))

    def test_the_page_and_the_card_show_it_stale(self):
        """A sample 30 h old: its TAN is fresh, its temperature is not, so its NH₃ is stale on the water's read API (the
        water page, the drawer, the overview) and on the monitoring card."""
        self.stock()
        self.limit(NH3, critical_high='0.025', warning_high='0.0125')
        self.sample(hours=30, **FULL)
        water = self.unit_water()
        nh3 = water.get(NH3)
        self.assertIsNotNone(nh3.value)
        self.assertEqual(nh3.status, Status.STALE)
        self.assertEqual(water.get(TAN).status, Status.NO_LIMIT)
        face = render.face(nh3, self.now)
        self.assertTrue(face.stale)
        self.assertEqual(face.status, Status.STALE)
        self.assertEqual(water.get(NH4).fresh(self.now), False)


# Every measured parameter, at a plausible value of a sea tank (the drop-each-input guard).
EVERY = {'temperature_c': '12.0', 'oxygen_mg_l': '9.00', 'oxygen_saturation_pct': '95.0', 'ph': '7.80',
         'alkalinity_mg_l': '150', 'hardness_mg_l': '5000', 'co2_mg_l': '5.0', 'tan_mg_l': '1.000',
         'nitrite_n_mg_l': '0.100', 'nitrate_n_mg_l': '10.0', 'tgp_pct': '100.0', 'salinity_ppt': '30.0',
         'conductivity_25_us_cm': '45000', 'turbidity_ntu': '1.0', 'phosphate_p_mg_l': '0.10'}


class RecordedInputsTests(WaterTestCase):
    """The review of 2026-11-26, F2: the inputs a worked-out value records as used are the inputs its parameter
    declares, and the inputs it declares are the ones its derivation reads. A declaration that leaves one out (a CO₂
    declared from the pH and the alkalinity whose formula also reads the temperature) is caught here."""

    def setUp(self):
        super().setUp()
        Tank.objects.filter(pk=self.t1.pk).update(water_type='saltwater', water_origin='seawater')
        self.t1.refresh_from_db()

    def worked(self, values, hours=1):
        context = read.Context([self.mid1], self.now - read.WINDOW)
        observation = read.Observation(self.mid1, self.ago(hours=hours), read.Origin.MANUAL,
                                       {code: D(value) for code, value in values.items()})
        return context.readings(observation)

    def test_every_measured_parameter_is_covered_and_only_worked_out_ones_declare(self):
        self.assertEqual(set(EVERY), set(parameters.COLUMNS))
        for parameter in parameters.BY_CODE.values():
            if parameter.measured:
                self.assertEqual(parameter.uncounted, (), parameter.code)
        with self.assertRaises(ValueError):
            parameters._parameter('x_mg_l', 'X', 'X', 1, 0, 1, uncounted=('ph',))

    def test_dropping_each_measured_value_in_turn(self):
        """Dropping a declared input changes the worked-out value or empties it; dropping any other measured value
        leaves it as it was, except the ones the parameter declares it reads without counting (`uncounted`)."""
        for parameter in (parameters.get(code) for code in parameters.DERIVED):
            full = self.worked(EVERY)[parameter.code]
            self.assertIsNotNone(full.value, parameter.code)
            self.assertEqual(set(full.inputs_until), set(parameter.inputs))
            for code in parameters.COLUMNS:
                with self.subTest(parameter=parameter.code, dropped=code):
                    found = self.worked({key: value for key, value in EVERY.items() if key != code}).get(parameter.code)
                    value = None if found is None else found.exact
                    if code in parameter.inputs:
                        self.assertNotEqual(value, full.exact, f'{code} is declared and not read')
                    elif code not in parameter.uncounted:
                        self.assertEqual(value, full.exact, f'{code} is read and not declared')

    def test_an_input_looked_up_from_the_point_is_recorded(self):
        """The salinity dropped from the sample, the point's earlier salinity stands in: the value is the same, and the
        input recorded is that salinity, with its own end (a missing stamp would read None)."""
        earlier = self.sample(hours=20, salinity_ppt='30.0')
        full = self.worked(EVERY)[NH3]
        found = self.worked({key: value for key, value in EVERY.items() if key != SALINITY})[NH3]
        self.assertEqual(found.exact, full.exact)
        self.assertEqual(found.inputs_until[SALINITY], earlier.measured_at + timedelta(hours=168))
        self.assertEqual(full.inputs_until[SALINITY], self.ago(hours=1) + timedelta(hours=168))

    def test_a_record_unlike_the_declaration_is_refused(self):
        nh3 = self.worked(EVERY)[NH3]
        for inputs in ({key: value for key, value in nh3.inputs_until.items() if key != PH},
                       {**nh3.inputs_until, 'alkalinity_mg_l': self.now}):
            with self.subTest(inputs=sorted(inputs)):
                nh3.inputs_until = inputs
                with self.assertRaises(ValueError):
                    nh3.fresh(self.now)


class SensorTemperatureTests(WaterTestCase):
    """The coordinator's decision of 2026-11-26 on the temperature of a sample's NH₃, where the place has a temperature
    probe: (a) a TAN sample without a temperature takes the place's sensor temperature at its time, and records it as
    the input used; (b) the temperature input stays fresh while the place's live temperature stays within
    the platform owner's band (freshness.temperature_band, 1.0 °C until set) of it, and ends the moment it moves further or goes stale. A probe on T-01's
    middle point, a value every 10 min, fresh for 30 min."""

    def setUp(self):
        super().setUp()
        device = make_device(make_connection(), make_format(), self.bergen, code='PROBE-T')
        self.channel = make_channel(device, 'temperature_c', code='TEMP', heartbeat_s=600)
        may_record(self.user, 'add_binding')            # binds the probe: the binding service asks (L-6)
        bindings.move(self.user, self.channel, point=self.mid1, at=self.ago(hours=60))

    def send(self, value, start, end):
        """The probe's value every 10 min from `start` to `end` hours ago."""
        with connection.cursor() as cursor:
            cursor.execute('INSERT INTO sensors_reading (channel_no, ts, value) SELECT %s, g, %s FROM '
                           "generate_series(%s::timestamptz, %s::timestamptz, interval '10 minutes') g",
                           [self.channel.channel_no, value, self.ago(hours=start), self.ago(hours=end)])

    def test_the_channel_is_fresh_for_30_minutes(self):
        self.channel.refresh_from_db()
        self.assertEqual(self.channel.fresh_s, 1800)
        self.assertEqual(freshness.temperature_band(), 1.0)

    def test_a_sample_without_a_temperature_takes_the_probes(self):
        """(a) TAN and pH 30 h ago, no temperature: worked out with the probe's 12.0 °C of that time, said beside the
        value, the same NH₃ as a sample that typed 12.0 °C; fresh while the probe goes on at 12.0 °C."""
        self.send(12.0, 50, 0)
        self.sample(hours=30, tan_mg_l='1.000', ph='7.50', salinity_ppt='0.0')
        nh3 = self.unit_water().get(NH3)
        self.assertIsNotNone(nh3.value)
        self.assertIn('Worked out with the temperature 12.0 °C of', nh3.provenance)
        self.assertTrue(nh3.fresh(self.now))
        self.assertGreaterEqual(nh3.inputs_until[TEMPERATURE], self.now)
        typed = read.Context([self.mid1], self.now - read.WINDOW).readings(read.Observation(
            self.mid1, self.ago(hours=30), read.Origin.MANUAL, {code: D(value) for code, value in FULL.items()}))
        self.assertEqual(nh3.exact, typed[NH3].exact)

    def test_without_a_probe_value_at_its_time_nothing_is_worked_out(self):
        self.send(12.0, 20, 0)                  # the probe began 10 h after the sample
        self.sample(hours=30, tan_mg_l='1.000', ph='7.50', salinity_ppt='0.0')
        nh3 = self.unit_water().get(NH3)
        self.assertIsNone(nh3.value)
        self.assertEqual(nh3.note, 'Needs the pH and the temperature of the same sample.')

    def test_a_typed_temperature_the_probe_confirms_stays_fresh(self):
        """(b) The sample's own 12.0 °C, 30 h old (its own 24 h are over): the probe within 1.0 °C all along keeps it."""
        self.send(12.4, 50, 0)
        self.sample(hours=30, **FULL)
        nh3 = self.unit_water().get(NH3)
        self.assertTrue(nh3.fresh(self.now))
        self.assertEqual(nh3.status, Status.NO_LIMIT)

    def test_the_probe_moving_ends_it_then(self):
        """(b) The probe goes from 12.4 to 13.5 °C 10 h ago: the temperature input ends at that value, the NH₃ is stale
        since then."""
        self.send(12.4, 50, 10.5)
        self.send(13.5, 10, 0)
        self.sample(hours=30, **FULL)
        nh3 = self.unit_water().get(NH3)
        self.assertEqual(nh3.inputs_until[TEMPERATURE], self.ago(hours=10))
        self.assertEqual(nh3.fresh_until, self.ago(hours=10))
        self.assertEqual(nh3.status, Status.STALE)

    def test_the_probe_going_silent_ends_it_at_its_freshness(self):
        """(b) The probe's last value 5 h ago: the input ends 30 min after it."""
        self.send(12.0, 50, 5)
        self.sample(hours=30, **FULL)
        nh3 = self.unit_water().get(NH3)
        self.assertEqual(nh3.fresh_until, self.ago(hours=5) + timedelta(minutes=30))
        self.assertFalse(nh3.fresh(self.now))

    def test_a_probe_further_off_at_the_samples_time_confirms_nothing(self):
        """(b) The probe reads 14.0 °C when the sample says 12.0 °C: the temperature does not describe the water, the
        input ends at once."""
        self.send(14.0, 50, 0)
        self.sample(hours=3, **FULL)
        nh3 = self.unit_water().get(NH3)
        self.assertLessEqual(nh3.fresh_until, self.ago(hours=3))
        self.assertEqual(nh3.status, Status.STALE)

    def test_the_outlet_reads_the_places_probe(self):
        """The probe on the middle point stands for the unit's water: a sample at another own point (the outlet) takes it
        too (A9's own tier)."""
        outlet = SamplingPoint.objects.create(unit=self.t1, name='Outlet', kind='outlet')
        self.send(12.0, 50, 0)
        self.sample(outlet, hours=30, tan_mg_l='1.000', ph='7.50', salinity_ppt='0.0')
        nh3 = self.unit_water().get(NH3)
        self.assertIsNotNone(nh3.value)
        self.assertEqual(nh3.point, outlet)
        self.assertTrue(nh3.fresh(self.now))

    def test_the_band_is_the_platform_owners_and_a_changed_band_changes_the_verdict(self):
        """The band is reference data (Platform settings › Water freshness, 1.0 °C until set): the probe 0.4 °C off the
        sample's 12.0 °C confirms it at 1.0 °C and ends it at once at 0.3 °C."""
        from core.models import PlatformSettings
        self.assertEqual(PlatformSettings.get().temperature_band_c, D('1.0'))
        self.assertEqual(freshness.temperature_band(), 1.0)
        self.send(12.4, 50, 0)
        self.sample(hours=30, **FULL)
        self.assertTrue(self.unit_water().get(NH3).fresh(self.now))
        row = PlatformSettings.get()
        self.addCleanup(freshness.forget)           # the band read in this test's transaction goes with it
        row.temperature_band_c = D('0.3')
        row.save()
        nh3 = self.unit_water().get(NH3)
        self.assertFalse(nh3.fresh(self.now))
        self.assertLessEqual(nh3.fresh_until, self.ago(hours=30))

    def test_the_database_refuses_a_band_out_of_range(self):
        from django.db import IntegrityError, transaction

        from core.models import PlatformSettings
        for band in ('0.0', '5.1'):
            with self.subTest(band=band), self.assertRaises(IntegrityError), transaction.atomic():
                PlatformSettings.objects.update(temperature_band_c=D(band))

    def test_the_platform_settings_form_has_the_band(self):
        from core.forms import PlatformSettingsForm
        from core.models import PlatformSettings
        form = PlatformSettingsForm(instance=PlatformSettings.get())
        self.assertIn('temperature_band_c', form.fields)
        data = {name: form.initial.get(name) for name in form.fields}
        for band, ok in (('0.1', True), ('5.0', True), ('0.05', False), ('5.5', False)):
            with self.subTest(band=band):
                self.assertEqual(PlatformSettingsForm({**{key: value for key, value in data.items() if value is not None},
                                                       'temperature_band_c': band},
                                                      instance=PlatformSettings.get()).is_valid(), ok)
