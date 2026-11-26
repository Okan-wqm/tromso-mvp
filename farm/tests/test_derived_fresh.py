"""A worked-out water value is never fresher than its oldest input (the coordinator's decision of 2026-11-26): its
freshness is the earliest moment any of the values it was worked out with stops being fresh (farm/water/freshness.py
`derived_until`, the inputs each parameter declares in farm/water/parameters.py), never later than its own row's hours.
An NH₃ worked out from a 5-day-old pH was fresh for its own 168 h while the pH it came from was fresh for 72 h. Every
reader asks `read.Reading.fresh` / `fresh_until`, so the pages, the cards and the alarms say it the same way."""
import contextlib
from datetime import timedelta
from unittest import mock
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from monitoring.cards import render

from ..models import SamplingPoint, Tank, WaterFreshness
from ..water import evaluate, freshness, judge, parameters, read
from ..water.evaluate import Status
from .test_water import WaterTestCase


@contextlib.contextmanager
def counting():
    """[the rows of each look-back query] of the reads inside (read.Context._fetch, the one door of those rows; review 6,
    L2: counted by the test, never by the code)."""
    found, fetch = [], read.Context._fetch

    def counted(self, rows):
        rows = fetch(self, rows)
        found.append(len(rows))
        return rows
    with mock.patch.object(read.Context, '_fetch', counted):
        yield found

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


class SampleTemperatureTests(WaterTestCase):
    """An NH₃ is worked out with its own sample's temperature and nothing else (the coordinator's architecture of
    2026-11-26: the place's probe temperature is the probe-temperature branch's): a sample without one gives no NH₃ and
    says so; the oxygen's stored basis never reaches it; and the look-back of a point's worked-out values is bounded."""

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

    def test_no_probe_and_a_manual_basis_elsewhere_gives_no_nh3(self):
        """Review 4, H3: a temperature typed in one sample, a later sample with an oxygen and no temperature (its basis
        that one): no NH₃, never another sample's temperature, and it says why."""
        self.sample(hours=2, temperature_c='12.0')
        sample = self.sample(hours=1, tan_mg_l='1.000', ph='7.50', salinity_ppt='0.0', oxygen_mg_l='9.00')
        sample.refresh_from_db()
        self.assertEqual(sample.oxygen_basis_temperature_c, D('12.0'))
        nh3 = self.unit_water().get(NH3)
        self.assertIsNone(nh3.value)
        self.assertEqual(nh3.note, 'Needs the pH and the temperature of the same sample.')

    def test_the_look_back_reads_a_bounded_number_of_samples(self):
        """Review 5, M3: three points with twenty full samples each: the look-back reads the newest two of each (the
        newest worked-out value and the next, to see the same minute's peers), never the window's sixty."""
        outlets = [SamplingPoint.objects.create(unit=self.t1, name=f'Outlet {number}', kind='outlet')
                   for number in range(2)]
        for point in (self.mid1, *outlets):
            for hour in range(20, 0, -1):
                self.sample(point, hours=hour, **FULL)
        with counting() as rows:
            self.unit_water()
        self.assertLessEqual(sum(rows), 6)


class LookBackBudgetTests(WaterTestCase):
    """Review 6, M3: the look-back is bounded in statements AND rows at depth: sixty samples a point that cannot give a
    value, sixty the core refuses, thirty late results."""
    FULL = {'tan_mg_l': '1.000', 'ph': '7.50', 'temperature_c': '12.0', 'salinity_ppt': '0.0'}

    def read(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with counting() as rows, CaptureQueriesContext(connection) as queries:
            self.unit_water()
        return sum(rows), len(queries)

    def test_sixty_samples_that_cannot_give_a_value_cost_one_row_and_no_chemistry(self):
        for hour in range(60, 0, -1):
            self.sample(hours=hour / 2, tan_mg_l='0.500')
        with mock.patch.object(read.chemistry, 'water_equilibria', side_effect=AssertionError('no core call')):
            rows, _queries = self.read()
        self.assertLessEqual(rows, 1)

    def test_sixty_refused_samples_read_the_window_once_in_a_few_statements(self):
        for hour in range(60, 0, -1):
            self.sample(hours=hour / 2, **self.FULL, conductivity_25_us_cm='40000')
        rows, queries = self.read()
        self.assertLessEqual(rows, 61)
        self.sample(hours=0.1, **self.FULL, conductivity_25_us_cm='40000')
        _rows, more = self.read()
        self.assertLessEqual(more - queries, 1)            # rounds of 2, 4, 8 …: log₂ of the depth

    def test_thirty_late_results_are_read_at_most_late_said(self):
        self.sample(hours=1, **self.FULL)
        for hour in range(30, 0, -1):
            self.sample(hours=2 + hour / 2, source='lab', **self.FULL)
        with counting() as rows:
            water = self.unit_water()
        self.assertLessEqual(sum(rows), 2 + 1 + read.LATE_SAID)
        self.assertIsNotNone(water.get(NH3).value)


class ShellParityTests(WaterTestCase):
    def test_the_database_ranks_as_the_judge_orders(self):
        """Review 6, L4: same minute, same entry moment: the database's ORDER (the uuid) and the judge's (its text) agree."""
        from ..models import WaterMeasurement
        samples = [self.sample(hours=1, **FULL) for _each in range(4)]
        WaterMeasurement.objects.filter(pk__in=[sample.pk for sample in samples]).update(
            created_at=samples[0].created_at)
        context = read.Context([self.mid1], self.now - read.WINDOW)
        ranked = context._ranked(context._window([self.mid1.pk]), 0, 10)
        records = [read.record_of(context.readings(sample)[NH3]) for sample in ranked]
        self.assertEqual([record.id for record in records],
                         [record.id for record in judge.newest_first(records)])

    def test_nh4_follows_nh3s_evidence(self):
        """Review 6, L6: the look-back settles on the NH₃; the NH₄ of the same samples has the same evidence sample."""
        self.sample(hours=3, **FULL)
        self.sample(hours=1, tan_mg_l='0.700')
        context = read.Context([self.mid1], self.now - read.WINDOW)
        nh3, nh4 = (context.verdict(self.mid1, code).evidence for code in (NH3, NH4))
        self.assertEqual(nh3.id, nh4.id)
