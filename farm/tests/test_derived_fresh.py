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

    def test_the_band_is_compared_exactly(self):
        """Review 3, L1: 12.4 °C against 12.0 °C is 0.4 °C away, within a band of 0.4 °C (the help says "within"),
        never 0.40000000000000036 by a float."""
        from core.models import PlatformSettings
        self.addCleanup(freshness.forget)
        PlatformSettings.objects.update(temperature_band_c=D('0.4'))
        freshness.forget()
        self.send(12.4, 50, 0)
        self.sample(hours=30, **FULL)
        self.assertTrue(self.unit_water().get(NH3).fresh(self.now))

    def test_a_probe_value_just_after_the_sample_confirms_or_ends_it(self):
        """Review 3, L2: the probe's first value 60 s after the sample (within the clock tolerance), 14.0 °C against the
        sample's 12.0 °C: the same tolerance as the look-up, so it ends the input at once."""
        with connection.cursor() as cursor:
            cursor.execute('INSERT INTO sensors_reading (channel_no, ts, value) SELECT %s, g, 14.0 FROM '
                           "generate_series(%s::timestamptz, %s::timestamptz, interval '10 minutes') g",
                           [self.channel.channel_no, self.ago(hours=3) + timedelta(seconds=60), self.now])
        self.sample(hours=3, **FULL)
        nh3 = self.unit_water().get(NH3)
        self.assertLessEqual(nh3.fresh_until, self.ago(hours=3) + timedelta(seconds=60))
        self.assertEqual(nh3.status, Status.STALE)

    def test_a_failing_sensor_source_is_said_in_the_nh3(self):
        """Review 3, L3: a source that fails is not a missing temperature: the NH₃ says the live values could not be
        read."""
        from ..water import sources
        from .test_water_sources import FakeProvider
        broken = FakeProvider(broken=True)
        sources.register(broken)
        self.addCleanup(sources.unregister, broken)
        self.sample(hours=3, tan_mg_l='1.000', ph='7.50', salinity_ppt='0.0')
        nh3 = self.unit_water().get(NH3)
        self.assertIsNone(nh3.value)
        self.assertEqual(nh3.note, 'Needs a temperature: the sample has none, and the live sensor values could not be '
                                   'read.')

    def test_the_probe_is_asked_only_up_to_the_moment_the_nh3_is_stale_anyway(self):
        """Review 3, H2: a sample whose pH has run out (80 h old, 72 h) has a stale NH₃ whatever the probe says: its
        temperature's band is not asked; one whose inputs are fresh (30 h) is asked up to now, no further."""
        from unittest import mock

        from ..water import sources
        outlet = SamplingPoint.objects.create(unit=self.t1, name='Outlet', kind='outlet')
        self.send(12.0, 59, 0)
        self.sample(hours=80, **FULL)
        self.sample(outlet, hours=30, **FULL)
        with mock.patch.object(sources, 'steady_until', wraps=sources.steady_until) as steady:
            moment = timezone.now()
            read.latest([self.mid1, outlet], now=moment)
        asks = [ask for call in steady.call_args_list for ask in call.args[3]]
        self.assertEqual([start for _targets, start, _value, _until in asks], [self.ago(hours=30)])
        self.assertEqual([until for _targets, _start, _value, until in asks], [moment])

    def test_one_rule_for_the_oxygen_the_nh3_and_the_history(self):
        """Review 3, M2: a sample with a TAN, a pH and an oxygen but no temperature. Its oxygen's temperature is stored
        with it (the place's probe then, 12.0 °C); its NH₃ takes the same, says where from, and the history works out the
        same NH₃ as the latest read."""
        self.send(12.0, 50, 0)
        sample = self.sample(hours=3, tan_mg_l='1.000', ph='7.50', salinity_ppt='0.0', oxygen_mg_l='9.00')
        sample.refresh_from_db()
        self.assertEqual(sample.oxygen_basis_temperature_c, D('12.0'))
        latest = self.unit_water()
        nh3 = latest.get(NH3)
        self.assertIsNotNone(nh3.value)
        self.assertIn('Worked out with the temperature 12.0 °C of', nh3.provenance)
        history = {row.sample.pk: row for row in read.history([sample])}[sample.pk]
        self.assertEqual(history.readings[NH3].exact, nh3.exact)
        self.assertEqual(history.readings['oxygen_saturation_pct'].exact, latest.get('oxygen_saturation_pct').exact)

    def test_the_ph_scale_conversion_temperature_is_recorded(self):
        """Review 3, L4: a sensor pH put on the NBS scale with a temperature that stops being fresh before the pH: the NH₃
        worked out from that pH ends with that temperature."""
        conversion_ends = self.ago(hours=0.5)
        observation = read.Observation(
            self.mid1, self.ago(hours=1), read.Origin.SENSOR,
            {TAN: D('1.000'), PH: D('7.50'), TEMPERATURE: D('12.0'), SALINITY: D('0.0')}, fresh_for=7200,
            ph=read.SensorPh('total', D('7.40'), formula=4, temperature=D('12.0'), temperature_until=conversion_ends))
        nh3 = read.Context([self.mid1], self.now - read.WINDOW).readings(observation)[NH3]
        self.assertEqual(nh3.inputs_until[PH], conversion_ends)
        self.assertEqual(nh3.fresh_until, conversion_ends)

    # ---- review 4 -------------------------------------------------------------------------------------------------
    def test_a_voided_basis_temperature_never_reaches_an_nh3(self):
        """Review 4, H3: the middle's temperature keyed 5.0 °C by mistake, an outlet sample (TAN, pH, oxygen, no
        temperature) written meanwhile stores it as its oxygen's basis, the 5.0 °C sample voided. No probe: the NH₃
        takes the sample's own temperature or the probe, never a basis, so it has none."""
        from ..water import services
        wrong = self.sample(hours=2, temperature_c='5.0')
        sample = self.sample(hours=1, tan_mg_l='1.000', ph='7.50', salinity_ppt='0.0', oxygen_mg_l='9.00')
        sample.refresh_from_db()
        self.assertEqual(sample.oxygen_basis_temperature_c, D('5.0'))
        services.void(self.user, wrong, 'typed 5 for 15')
        nh3 = self.unit_water().get(NH3)
        self.assertIsNone(nh3.value)
        self.assertEqual(nh3.note, 'Needs the pH and the temperature of the same sample.')

    def test_with_and_without_an_oxygen_the_nh3_takes_the_same_temperature(self):
        """Review 4, H3: two samples at the same point and minute, one with an oxygen (its basis the probe's) and one
        without: the same NH₃ temperature, the probe's at their time."""
        self.send(12.0, 50, 0)
        context = read.Context([self.mid1], self.now - read.WINDOW)
        context.know(read._places([self.mid1]), self.now)
        with_oxygen = read.Observation(self.mid1, self.ago(hours=3), read.Origin.MANUAL,
                                       {TAN: D('1.000'), PH: D('7.50'), SALINITY: D('0.0'), 'oxygen_mg_l': D('9.00')},
                                       basis={TEMPERATURE: read.Basis(D('15.0'), 'manual', None, self.ago(hours=4))})
        without = read.Observation(self.mid1, self.ago(hours=3), read.Origin.MANUAL,
                                   {TAN: D('1.000'), PH: D('7.50'), SALINITY: D('0.0')})
        first, second = context.readings(with_oxygen)[NH3], context.readings(without)[NH3]
        self.assertEqual(first.exact, second.exact)
        self.assertEqual(first.inputs_until[TEMPERATURE], second.inputs_until[TEMPERATURE])

    def test_no_probe_and_a_manual_basis_elsewhere_gives_no_nh3(self):
        """Review 4, H3: a temperature typed in one sample, a later sample with an oxygen and no temperature (its basis
        that one), no probe: no NH₃, never another sample's temperature."""
        self.sample(hours=2, temperature_c='12.0')
        sample = self.sample(hours=1, tan_mg_l='1.000', ph='7.50', salinity_ppt='0.0', oxygen_mg_l='9.00')
        sample.refresh_from_db()
        self.assertEqual(sample.oxygen_basis_temperature_c, D('12.0'))
        self.assertIsNone(self.unit_water().get(NH3).value)

    def test_a_probe_temperature_ends_at_its_channels_freshness_when_the_band_fails(self):
        """Review 4, M1 and M3: a sample without a temperature takes the probe's; the band check alone fails. The input
        ends at once, never 24 h later, the NH₃ says the sensors could not be read, and so does the place."""
        from ..water import sources

        class BandFails:
            def latest(self, targets, now):
                return {}

            def bound(self, targets, code, since, until):
                return set()

            def value_at(self, targets, code, moment):
                return {}

            def steady_until(self, code, band, tolerance, asks):
                raise RuntimeError('the band check timed out')

        failing = BandFails()
        sources.register(failing)
        self.addCleanup(sources.unregister, failing)
        self.send(12.0, 50, 0)
        self.sample(hours=3, tan_mg_l='1.000', ph='7.50', salinity_ppt='0.0')
        water = self.unit_water()
        nh3 = water.get(NH3)
        self.assertIsNotNone(nh3.value)
        self.assertFalse(nh3.fresh(self.now))
        self.assertLessEqual(nh3.inputs_until[TEMPERATURE], self.ago(hours=3) + timedelta(minutes=30))
        self.assertIn('the live sensor values could not be read', nh3.note)
        self.assertTrue(water.sensors_failed)

    def test_the_history_of_an_outlet_alone_takes_the_units_probe(self):
        """Review 4, M2: the history page of the outlet alone (no middle sample on it) works out the outlet sample's NH₃
        with the unit's probe, as the latest read does."""
        outlet = SamplingPoint.objects.create(unit=self.t1, name='Outlet', kind='outlet')
        self.send(12.0, 50, 0)
        sample = self.sample(outlet, hours=3, tan_mg_l='1.000', ph='7.50', salinity_ppt='0.0')
        row = read.history([sample])[0]
        self.assertIsNotNone(row.readings[NH3].value)
        self.assertEqual(row.readings[NH3].exact, read.latest([outlet])[outlet.pk].get(NH3).exact)

    def test_the_band_check_reads_only_new_rows_on_the_next_read(self):
        """Review 4, M4: the band check keeps what it has confirmed; the next read reads only the rows after it, not the
        whole history again (rows read, not statements)."""
        from sensors import provider
        self.send(12.0, 30, 0)
        self.sample(hours=20, **FULL)
        before = provider.ROWS_READ[0]
        self.unit_water()
        first = provider.ROWS_READ[0] - before
        self.assertGreater(first, 100)                                # 20 h of a value every 10 min
        before = provider.ROWS_READ[0]
        self.unit_water()
        self.assertLessEqual(provider.ROWS_READ[0] - before, 2)

    def test_why_an_nh3_ended_is_said(self):
        """Review 4, M5: an NH₃ of a sample 30 min old whose probe moved 1.5 °C away 15 min ago is stale, and says which
        input ended it and why."""
        with connection.cursor() as cursor:
            cursor.execute('INSERT INTO sensors_reading (channel_no, ts, value) VALUES (%s, %s, 12.0), (%s, %s, 13.5), '
                           '(%s, %s, 13.5)', [self.channel.channel_no, self.ago(hours=0.5), self.channel.channel_no,
                                              self.ago(hours=0.25), self.channel.channel_no, self.now])
        self.sample(hours=0.5, **FULL)
        nh3 = self.unit_water().get(NH3)
        self.assertEqual(nh3.status, Status.STALE)
        self.assertIn('its temperature ended: the probe read 13.5 °C, beyond the 1.0 °C band', nh3.note)
