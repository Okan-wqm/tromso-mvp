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
        self.stock()
        self.limit(NH3, critical_high='0.025', warning_high='0.0125')
        rows, queries = self.read()
        self.assertLessEqual(rows, 61)
        self.sample(hours=0.1, **self.FULL, conductivity_25_us_cm='40000')
        _rows, more = self.read()
        self.assertLessEqual(more - queries, 1)            # rounds of 2, 4, 8 …: log₂ of the depth
        water = self.unit_water()                          # and the verdict: it cannot be evaluated, and says so
        self.assertEqual(water.get(NH3).judged, Status.UNEVALUATED)
        self.assertEqual([each.code for each in water.unevaluated], [NH3])

    def test_sixty_late_results_are_read_at_most_late_read_and_the_rest_counted(self):
        """Sixty late results, the OLDEST one critical: LATE_READ are read and judged, the others counted, and the read
        says how many it does not say one by one: no cut is silent (review 7, M1)."""
        self.stock()
        self.limit(NH3, critical_high='0.025', warning_high='0.0125')
        self.sample(hours=1, **self.FULL)
        self.sample(hours=40, source='lab', ph='9.00', temperature_c='12.0', salinity_ppt='0.0', tan_mg_l='5.000')
        for hour in range(59, 0, -1):
            self.sample(hours=2 + hour / 2, source='lab', **self.FULL)
        with counting() as rows:
            water = self.unit_water()
        self.assertLessEqual(sum(rows), 2 + 1 + read.LATE_READ)
        nh3 = water.get(NH3)
        self.assertEqual((nh3.judged, nh3.value is not None), (Status.OK, True))
        # The newest of the sixty was fetched with the evidence, to see its minute: 59 in the late query, 50 read; the
        # nine never read hold the critical, so they are said as not read (review 8, N6: no alert is counted unread).
        self.assertIn(f'{59 - read.LATE_READ} older late results were not read: see the history.', nh3.note)
        self.assertNotIn('more late critical', nh3.note)

    def test_the_ceiling_is_exactly_its_value_of_candidates(self):
        """Review 8, N4 and R8-12: at the real judge.CEILING (512, no patch) a point without evidence is read for EXACTLY
        that many candidates, never the next doubling's 1022."""
        import copy
        import uuid

        from ..models import WaterMeasurement
        self.assertEqual(judge.CEILING, 512)
        Tank.objects.filter(pk=self.t1.pk).update(water_type='saltwater', water_origin='seawater')
        self.t1.refresh_from_db()
        template = self.sample(hours=1, tan_mg_l='1.000', ph='7.50', temperature_c='12.0')     # needs the salinity
        rows = []
        for index in range(1, 530):
            row = copy.copy(template)
            row.pk = uuid.uuid4()
            row.measured_at = template.measured_at - timedelta(minutes=index)
            rows.append(row)
        from .. import withdrawal_gate
        with withdrawal_gate.opened('test fixture: samples written straight in the database'):
            WaterMeasurement.objects.bulk_create(rows)
        context = read.Context([self.mid1], self.now - read.WINDOW)
        with counting() as fetched:
            worked = context.worked_at(self.mid1)
        self.assertEqual((len(worked.found), worked.complete), (judge.CEILING, False))
        self.assertEqual(sum(fetched), judge.CEILING)              # (every sample has its own inputs: no other row)
        self.assertTrue(context.verdict(self.mid1, NH3).ceiling)

    def test_the_ceiling_stops_the_look_back_and_the_point_cannot_be_evaluated(self):
        """After judge.CEILING candidates without evidence the look-back stops, fail-closed: a sea unit whose own samples
        never give a value (no salinity anywhere of its own), shown OK from its loop, cannot be evaluated and says why;
        what was fetched is never taken for the whole."""
        Tank.objects.filter(pk=self.t1.pk).update(water_type='saltwater', water_origin='seawater')
        self.t1.refresh_from_db()
        self.stock()
        self.limit(NH3, critical_high='0.025', warning_high='0.0125')
        for hour in range(14, 2, -1):
            self.sample(hours=hour, tan_mg_l='1.000', ph='7.50', temperature_c='12.0')       # needs the salinity
        self.sample(self.loop, hours=1, tan_mg_l='1.000', ph='7.50', temperature_c='12.0', salinity_ppt='30.0')
        with counting() as rows:
            whole = self.unit_water().get(NH3)
        self.assertEqual((whole.point, whole.judged), (self.loop, Status.OK))
        self.assertGreaterEqual(sum(rows), 12)
        with mock.patch.object(judge, 'CEILING', 4), counting() as rows:
            nh3 = self.unit_water().get(NH3)
        self.assertLessEqual(sum(rows), 2 + 4 + 1)             # the unit's two rounds and the loop's one, never the window
        self.assertIn('Middle cannot be evaluated: none of its newest 4 samples gives an evaluable value.', nh3.note)
        self.assertEqual((nh3.point, nh3.judged), (self.loop, Status.UNEVALUATED))


class ShellParityTests(WaterTestCase):
    def test_the_database_ranks_as_the_judge_orders(self):
        """The one order: nine samples of three measurement times, three entry moments (their order against the
        measurement's) and their ids (three share both times): the database's ORDER and the judge's order agree, field
        by field, on more rows than the look-back's first rounds fetch."""
        from ..models import WaterMeasurement
        samples = [self.sample(hours=1 + index // 3, **FULL) for index in range(9)]
        base = samples[0].created_at
        for index, sample in enumerate(samples):
            entered = base if index >= 6 else base + timedelta(minutes=(index * 7) % 5)
            WaterMeasurement.objects.filter(pk=sample.pk).update(created_at=entered)
        self.assertEqual([each.expression.name for each in read.ORDER], list(judge.ORDER_FIELDS))
        self.assertEqual(read.ORDER_BY, tuple(f'-{name}' for name in judge.ORDER_FIELDS))
        context = read.Context([self.mid1], self.now - read.WINDOW)
        ranked = [sample for offset, size in ((0, 2), (2, 4), (6, 8))
                  for sample in context._ranked(context._window([self.mid1.pk]), offset, size)]
        self.assertEqual(len(ranked), 9)
        records = [read.record_of(context.readings(sample)[NH3]) for sample in ranked]
        self.assertEqual([record.id for record in records], [record.id for record in judge.newest_first(records)])
        self.assertEqual([record.order for record in records],
                         [(sample.measured_at, sample.created_at, str(sample.pk)) for sample in ranked])

    def test_nh4_follows_nh3s_evidence(self):
        """Review 6, L6: the look-back settles on the NH₃; the NH₄ of the same samples has the same evidence sample."""
        self.sample(hours=3, **FULL)
        self.sample(hours=1, tan_mg_l='0.700')
        context = read.Context([self.mid1], self.now - read.WINDOW)
        nh3, nh4 = (context.verdict(self.mid1, code).evidence for code in (NH3, NH4))
        self.assertEqual(nh3.id, nh4.id)


class ShellRecordTests(WaterTestCase):
    """The shell's one Record builder (read.record_of) and where a value belongs (read.bound_at), field by field."""

    def live(self, point, origin):
        observation = read.Observation(point, self.ago(hours=0.01), origin, {TAN: D('0.500')}, fresh_for=180)
        return read.Reading(parameters.get(NH3), D('0.0010'), observation, True,
                            inputs_until={code: self.now + timedelta(hours=1) for code in parameters.get(NH3).inputs})

    def test_a_live_value_belongs_where_its_sensor_is_bound(self):
        """Review 7, H1: a system's own sensor observed at a unit's point is the SYSTEM's; a probe on the point, and the
        system's sensor at its loop point, are the point's."""
        from ..water import sources
        system = read.record_of(self.live(self.mid1, read.Origin.SYSTEM_SENSOR), self.now)
        self.assertEqual(system.point, (sources.SYSTEM, self.ras.pk))
        self.assertEqual((system.stored, system.id, system.fresh_now), (False, f'live:{system.point}', True))
        self.assertEqual(system.created_at, system.measured_at)
        self.assertEqual(read.record_of(self.live(self.mid1, read.Origin.SENSOR)).point, self.mid1.pk)
        self.assertEqual(read.record_of(self.live(self.loop, read.Origin.SYSTEM_SENSOR)).point, self.loop.pk)
        self.assertEqual(read.bound_at(self.live(self.t1, read.Origin.SYSTEM_SENSOR)), (sources.SYSTEM, self.ras.pk))

    def test_a_record_without_a_moment_says_fresh_now_is_not_known(self):
        self.sample(hours=1, **FULL)
        nh3 = self.unit_water().get(NH3)
        record = read.record_of(nh3)
        self.assertIsNone(record.fresh_now)
        self.assertEqual((record.stored, record.value, record.refused, record.fresh_at_own_time, record.status),
                         (True, True, False, True, Status.NOT_MEASURED))
        self.assertTrue(read.record_of(nh3, self.now).fresh_now)
        self.assertFalse(read.record_of(nh3, self.now + timedelta(hours=30)).fresh_now)

    def test_a_value_stale_from_its_start_is_no_evidence(self):
        """Its salinity, looked up from a sample exactly its 168 h older, ends at the sample's own moment: stale from its
        start (fresh_at_own_time False), so the judge never takes it for evidence."""
        Tank.objects.filter(pk=self.t1.pk).update(water_type='saltwater', water_origin='seawater')
        self.t1.refresh_from_db()
        self.sample(hours=170, salinity_ppt='30.0')
        self.sample(hours=2, tan_mg_l='1.000', ph='7.50', temperature_c='12.0')
        context = read.Context([self.mid1], self.now - read.WINDOW)
        verdict = context.verdict(self.mid1, NH3)
        self.assertIsNone(verdict.evidence)
        self.assertEqual([(record.value, record.fresh_at_own_time) for record in verdict.judged], [(True, False)])


class CanGiveAValueTests(WaterTestCase):
    """Review 7, M7: what a sample must hold itself for its ammonia to give a value is defined once (read.OWN_INPUTS): the
    derivation and the look-back's two streams agree on all eight combinations of a TAN, a pH and a temperature."""

    def test_the_streams_and_the_derivation_agree(self):
        import itertools

        from ..models import WaterMeasurement
        self.assertEqual(read.OWN_INPUTS, parameters.AMMONIA_OWN)
        values = {TAN: '1.000', PH: '7.50', TEMPERATURE: '12.0'}
        context = read.Context([self.mid1], self.now - read.WINDOW)
        for index, held in enumerate(itertools.product((True, False), repeat=3)):
            chosen = {code: value for (code, value), has in zip(values.items(), held) if has}
            sample = self.sample(hours=1 + index, salinity_ppt='0.0', **chosen)
            can = WaterMeasurement.objects.filter(read.HAS_TAN & read.CAN_GIVE, pk=sample.pk).exists()
            cannot = WaterMeasurement.objects.filter(read.CANNOT_GIVE, pk=sample.pk).exists()
            nh3 = context.readings(sample).get(NH3)
            with self.subTest(held=sorted(chosen)):
                self.assertEqual(can, all(held))
                self.assertEqual(can + cannot, 1 if TAN in chosen else 0)       # a TAN: exactly one stream
                self.assertEqual(nh3 is not None and nh3.value is not None, can)
                self.assertEqual(read.gives_value(lambda code, sample=sample: getattr(sample, code)), all(held))


class LateResultTests(WaterTestCase):
    """Review 7, M1 to M3: a late critical is always said (the page, its history row, the activity log), whatever the
    order of entry and however many late results there are; the log keeps it in English; a late check that fails never
    blocks the sample and leaves its trace."""
    BAD = {'ph': '9.00', 'temperature_c': '12.0', 'salinity_ppt': '0.0', 'tan_mg_l': '5.000'}
    SAID = 'Late result: critical 0.8942 at Middle on '

    def setUp(self):
        super().setUp()
        self.stock()
        self.limit(NH3, critical_high='0.025', warning_high='0.0125')
        self.sample(hours=1, **FULL)                                    # this morning's kit: the evidence

    def logged(self, sample):
        from core.models import AuditLog
        return AuditLog.objects.get(entity_type='water sample', action='create',
                                    entity_id=str(sample.pk)).changes.get('Late result')

    def six(self, critical_first):
        """The lab's results of the last week keyed in after the kit's: the oldest critical, five newer ones OK."""
        hours = [150, 120, 96, 72, 48, 24]
        made = {}
        for hour in (hours if critical_first else reversed(hours)):
            made[hour] = self.sample(hours=hour, source='lab', **(self.BAD if hour == 150 else FULL))
        return made[150], [made[hour] for hour in hours[1:]]

    def said_everywhere(self, critical_first):
        critical, others = self.six(critical_first)
        self.assertTrue(self.logged(critical)[1].startswith(self.SAID), self.logged(critical))
        self.assertEqual([self.logged(each) for each in others], [None] * 5)
        self.assertIn(self.SAID, self.unit_water().get(NH3).note)
        rows = {row.sample.pk: row for row in read.history([critical, *others])}
        self.assertIn(self.SAID, rows[critical.pk].readings[NH3].note)
        self.assertNotIn('Late result', rows[others[0].pk].readings[NH3].note)

    def test_a_late_critical_keyed_first_of_six_is_said_everywhere(self):
        self.said_everywhere(critical_first=True)

    def test_a_late_critical_keyed_last_of_six_is_said_everywhere(self):
        self.said_everywhere(critical_first=False)

    def test_more_late_alerts_than_are_said_one_by_one_are_counted(self):
        for hour in range(8):
            self.sample(hours=30 + hour, source='lab', **self.BAD)
        note = self.unit_water().get(NH3).note
        self.assertEqual(note.count('Late result: critical'), read.LATE_SAID)
        self.assertIn(f'And {8 - read.LATE_SAID} more late critical or warning results: see the history.', note)

    def test_one_more_late_alert_is_said_in_the_singular(self):
        for hour in range(read.LATE_SAID + 1):
            self.sample(hours=30 + hour, source='lab', **self.BAD)
        note = self.unit_water().get(NH3).note
        self.assertIn('And 1 more late critical or warning result: see the history.', note)

    def test_late_ok_results_are_never_counted_as_alerts(self):
        for hour in range(8):
            self.sample(hours=30 + hour, source='lab', **FULL)
        self.assertNotIn('more late', self.unit_water().get(NH3).note)

    def test_late_criticals_at_one_point_come_before_late_warnings_at_another(self):
        """Review 8, N2: five late warnings at the middle, two late criticals at the outlet: the two criticals are among
        the five said one by one, first; two warnings are counted."""
        outlet = SamplingPoint.objects.create(unit=self.t1, name='Outlet', kind='outlet')
        self.sample(outlet, hours=1, **FULL)
        for hour in range(5):
            self.sample(hours=20 + hour, source='lab', **{**FULL, 'tan_mg_l': '2.600'})          # a warning
        for hour in range(2):
            self.sample(outlet, hours=30 + hour, source='lab', **self.BAD)
        note = self.unit_water().get(NH3).note
        self.assertEqual((note.count('Late result: critical'), note.count('Late result: warning')), (2, 3))
        self.assertLess(note.rindex('Late result: critical'), note.index('Late result: warning'))
        self.assertIn('at Outlet on ', note)
        self.assertIn('And 2 more late critical or warning results: see the history.', note)

    def test_the_log_keeps_the_words_in_english_whatever_the_users_language(self):
        from django.utils import translation
        for language in ('tr', 'nb'):
            with self.subTest(language=language), translation.override(language):
                sample = self.sample(hours=30 if language == 'tr' else 31, source='lab', **self.BAD)
                value = self.logged(sample)[1]
                self.assertTrue(value.startswith(self.SAID), value)
                self.assertIn(', superseded by ', value)

    def test_a_late_check_that_fails_never_blocks_the_sample_and_says_so_in_its_entry(self):
        from django.db import connection

        from ..models import WaterMeasurement
        from ..water import services

        def bad_statement(_samples):
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1 / 0')

        for failure in (ValueError('an input left out'), bad_statement):
            with self.subTest(failure=str(failure)), self.assertLogs('farm.water.services', level='ERROR'), \
                    mock.patch.object(services, 'late_results_of', side_effect=failure):
                sample = self.sample(hours=30 if isinstance(failure, ValueError) else 31, source='lab', **self.BAD)
            self.assertTrue(WaterMeasurement.objects.filter(pk=sample.pk).exists())       # stored, the transaction usable
            self.assertEqual(self.logged(sample), [None, 'could not be checked'])

    def test_one_unreadable_point_does_not_strip_the_others_words(self):
        from ..models import WaterMeasurement
        from ..water import services
        late = self.sample(hours=30, source='lab', **self.BAD)
        other = self.sample(self.t2, hours=30, source='lab', **self.BAD)
        tan_only = self.sample(self.t2, hours=31, source='lab', tan_mg_l='5.000')    # never checked: gives no value
        samples = list(WaterMeasurement.objects.select_related(*read.POINT_RELATED).filter(
            pk__in=[late.pk, other.pk, tan_only.pk]))
        real = read.late_results_of

        def unreadable_at_t2(group):
            if any(sample.point_id == self.mid2.pk for sample in group):
                raise ValueError('T-02 cannot be read')
            return real(group)

        with self.assertLogs('farm.water.services', level='ERROR'), \
                mock.patch.object(services, 'late_results_of', side_effect=unreadable_at_t2):
            words = services._late_words(samples)
        self.assertTrue(words[late.pk].startswith(self.SAID), words)
        self.assertEqual(words[other.pk], 'could not be checked')
        self.assertNotIn(tan_only.pk, words)                  # review 8, N5: the one predicate (read.gives_value)


class ResultWordsTests(TestCase):
    """Review 10, F3: one table of what a superseded result is said as, one entry a word of the judge."""

    def test_every_word_has_its_one_message(self):
        from ..water import messages
        self.assertEqual(set(messages.RESULT_SAID), {judge.COUNTED, judge.LATE, judge.EARLIER, judge.UNCHECKED})


class PointOwnStatusTests(WaterTestCase):
    """Review 7, M5: a point's OWN status, and a point read on its own, are the judge's: the worst of its judged set."""

    def test_an_outlets_own_row_is_the_worst_of_its_minute(self):
        from ..water import services
        self.stock()
        self.limit(NH3, critical_high='0.025', warning_high='0.0125')
        outlet = SamplingPoint.objects.create(unit=self.t1, name='Outlet', kind='outlet')
        at = self.ago(hours=30)
        for source, values in (('lab', LateResultTests.BAD), ('manual', FULL)):          # the kit's OK keyed in last
            services.record(self.user, point=outlet, measured_at=at, source=source,
                            values={code: D(value) for code, value in values.items()})
        water = read.latest([outlet])[outlet.pk]
        self.assertFalse(water.for_unit)
        self.assertEqual(water.point_status, Status.CRITICAL)
        self.assertEqual(water.get(NH3).judged, Status.CRITICAL)
