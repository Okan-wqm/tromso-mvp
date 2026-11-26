"""A water the core refuses is never silent for the alarms, and never alarmed lower than its page shows (the verification
of 2026-11-18, V-A, and its re-check, RC-2 and RC-3). The verifier's water: a fresh stocked unit whose fish have an NH₃-N
limit of 0.025 (critical) and 0.0125 (warning); 12.0 °C, S 0, alkalinity 80, pH 9.00, TAN 5.000. Without a conductivity
its NH₃-N is 0.8924, 36 times the limit, and a warning and a critical alarm open. With a conductivity of 40 000 µS/cm
(stored: it is inside the parameter's range) the core refuses the water (its ionic strength is past the Davies range).

- The judged NH₃ is the larger of the basis the limits were set on and the activity-corrected value (cross review F1),
  and the basis needs no conductivity (chemcore fresh.rs `limits_basis`). So a refused water is judged on its basis
  alone, a value the judged one is at least: past a limit it is that limit's status, critical past the critical one,
  through the same limit levels as any value (decision of 2026-11-18 on the re-check's RC-3: it was a warning). Inside
  the limits on its basis it is "cannot be evaluated" (never OK).
- Beside it, the refusal itself stays said: the unit's "… cannot be evaluated: <the core's reason>", and the alarm
  system's warning for the unit (subject `system:unit:<id>:value_unevaluated:<code>`), which ends once the value can be
  worked out again.
- A unit whose own NH₃ the core refused, judged critical on its page by another fresh value of its water (its loop's
  sample: read.worst_fresh), raises the critical the page shows (RC-2: it had the warning only).
- A refused value never ends a limit alarm: it is no evidence that the level is over."""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.urls import reverse
from django.utils import timezone

from core.models import Profile
from farm.models import WaterLimit
from farm.tests.test_water import WaterTestCase
from farm.water import read as water_read

from .. import engine, read, rules as alarm_rules, sources
from ..models import Alarm, Severity
from . import farm_alarms

# Its oxygen with it: a unit with fish and no fresh oxygen is critical (owner decision of 2026-11-23), which these tests
# are not about (monitoring/tests/test_silent_oxygen.py).
WATER = {'ph': '9.00', 'temperature_c': '12.0', 'salinity_ppt': '0.0', 'alkalinity_mg_l': '80', 'tan_mg_l': '5.000',
         'oxygen_mg_l': '9.00'}
# The same water at pH 7.00 and TAN 0.5: inside the limits on its basis.
LOW = {**WATER, 'ph': '7.00', 'tan_mg_l': '0.500'}
WHY = 'ionic strength above 0.5: outside the range of the Davies equation'
NH3 = 'nh3_n_mg_l'
LABEL = 'Un-ionised ammonia (mg/L NH₃ as N)'


def no_basis():
    """The core gives no basis either (no in-range water is known to: stood in for)."""
    return mock.patch.object(water_read.Context, 'nh3_basis_share', return_value=None)


def on_basis(water):
    """The NH₃-N of a water on the limits' basis alone, as the reading works it out."""
    share = water_read.Context.nh3_basis_share(water['temperature_c'], water['salinity_ppt'], water['ph'], '')
    return (Decimal(water['tan_mg_l']) * share).quantize(Decimal('0.0001'))


class RefusedWaterCase(WaterTestCase):
    def setUp(self):
        super().setUp()
        self.stock()
        self.stock(self.t2)
        self.limit(NH3, critical_high='0.025', warning_high='0.0125')

    def run_pass(self, minutes=0):
        return engine.run_once(self.now + timedelta(minutes=minutes))

    def open_alarms(self, **filters):
        """The open alarms but the alarm system's oxygen one: a stocked unit of the fixture without a sample (T-01 where
        only T-02 is sampled) holds fish and no fresh oxygen, critical (owner decision of 2026-11-23,
        monitoring/tests/test_silent_oxygen.py); these tests are about the NH₃."""
        return (farm_alarms().filter(clearance__isnull=True, **filters).exclude(source='system', parameter='oxygen_mg_l')
                .order_by('source', 'severity'))

    def opened(self):
        return [(alarm.source, alarm.severity, alarm.parameter) for alarm in self.open_alarms()]

    def refuse(self, unit, hours=1, water=LOW):
        return self.sample(unit, hours=hours, **water, conductivity_25_us_cm='40000')


class ReadingTests(RefusedWaterCase):
    def test_the_same_water_without_the_conductivity_is_36_times_the_limit(self):
        self.sample(self.t2, **WATER)
        reading = self.unit_water(self.t2).get(NH3)
        self.assertEqual((str(reading.value), reading.status), ('0.8924', 'critical'))
        self.run_pass()
        self.assertEqual(self.opened(), [('water_limit', 'critical', NH3), ('water_limit', 'warning', NH3)])

    def test_the_basis_needs_no_conductivity_and_is_never_above_the_judged_value(self):
        basis = on_basis(WATER)
        self.assertGreater(basis, Decimal('0.025'))                  # past the critical limit on its basis alone
        self.assertLessEqual(basis, Decimal('0.8924'))               # the judged value is the larger of the two
        self.assertLess(on_basis(LOW), Decimal('0.0125'))            # inside the warning limit

    def test_a_refused_water_past_the_critical_limit_on_its_basis_is_critical_and_says_why(self):
        self.refuse(self.t2, water=WATER)
        water = self.unit_water(self.t2)
        reading = water.get(NH3)
        self.assertEqual((reading.value, reading.status, reading.judged), (on_basis(WATER), 'critical', 'critical'))
        self.assertIn(WHY, reading.refused)
        self.assertIn(f'Cannot be worked out: {WHY}', str(reading.note))
        self.assertIn('Judged on the safe-side basis alone', str(reading.note))
        self.assertEqual(reading.measured, 'at least: the safe-side basis')
        self.assertEqual(water.status, 'critical')
        # The refusal stays said beside it: the unit's "cannot be evaluated".
        self.assertEqual([each.code for each in water.unevaluated], [NH3])
        self.assertEqual(len(water.why_unevaluated), 1)
        self.assertTrue(str(water.why_unevaluated[0]).startswith(f'{LABEL} cannot be evaluated: {WHY}'))

    def test_a_refused_water_inside_the_limits_on_its_basis_cannot_be_evaluated(self):
        self.refuse(self.t2)
        water = self.unit_water(self.t2)
        reading = water.get(NH3)
        self.assertEqual((reading.value, reading.status, reading.judged), (on_basis(LOW), 'unevaluated', 'unevaluated'))
        self.assertEqual(water.status, 'unevaluated')
        self.assertEqual([each.code for each in water.unevaluated], [NH3])

    def test_without_a_basis_either_it_has_no_value_and_cannot_be_evaluated(self):
        self.refuse(self.t2, water=WATER)
        with no_basis():
            water = self.unit_water(self.t2)
        reading = water.get(NH3)
        self.assertEqual((reading.value, reading.status, reading.measured), (None, 'unevaluated', ''))
        self.assertEqual(str(reading.note), f'Cannot be worked out: {reading.refused}.')
        self.assertIn(WHY, reading.refused)
        self.assertEqual(water.status, 'unevaluated')

    def test_a_fine_value_beside_it_never_makes_the_unit_ok(self):
        self.limit('ph', critical_low=6, warning_low='6.5', warning_high='9.5', critical_high=10)
        self.refuse(self.t2)
        water = self.unit_water(self.t2)
        self.assertEqual((water.get('ph').status, water.status), ('ok', 'unevaluated'))

    def test_a_critical_value_beside_it_stays_the_units_status(self):
        self.limit('ph', critical_low='7.5', warning_low='8.0')
        self.refuse(self.t2)
        self.assertEqual(self.unit_water(self.t2).status, 'critical')

    def test_without_a_limit_or_without_fish_nothing_is_judged_so_nothing_is_said(self):
        self.refuse(self.t2, water=WATER)
        WaterLimit.objects.all().delete()
        water = self.unit_water(self.t2)
        self.assertEqual((water.get(NH3).status, water.unevaluated), ('no_limit', []))
        self.run_pass()
        self.assertFalse(self.open_alarms().exists())
        # none raised and cleared either: the only alarm of the pass is the unsampled T-01's oxygen (2026-11-23)
        self.assertEqual(list(farm_alarms().values_list('source', 'parameter')), [('system', 'oxygen_mg_l')])

    def test_the_history_row_says_it(self):
        for hours, (water, wanted) in enumerate(((LOW, 'unevaluated'), (WATER, 'critical')), start=1):
            sample = self.refuse(self.t2, hours=hours, water=water)
            row = water_read.history([sample])[0]
            self.assertEqual((row.readings[NH3].status, row.status), (wanted, wanted))

    def test_another_fresh_value_judges_it_as_the_page_shows(self):
        """RC-2: the loop's fresh sample (no conductivity, 0.8924) beside T-02's own newer refused one."""
        self.sample(self.loop, hours=2, **WATER)
        self.refuse(self.t2)
        reading = self.unit_water(self.t2).get(NH3)
        self.assertEqual((reading.value, reading.judged, reading.worse.value),
                         (on_basis(LOW), 'critical', Decimal('0.8924')))
        self.assertTrue(reading.unevaluated)


class AlarmTests(RefusedWaterCase):
    def test_a_refused_water_inside_its_limits_raises_a_warning_of_the_alarm_system_for_the_unit(self):
        self.refuse(self.t2)
        summary = self.run_pass()
        self.assertEqual(summary.failed_steps, [])
        alarm = self.open_alarms().get()
        self.assertEqual((alarm.source, alarm.severity, alarm.parameter, alarm.site, alarm.production_department),
                         ('system', 'warning', NH3, self.bergen, self.hall))
        self.assertTrue(alarm.summary.startswith(f'T-02: {LABEL} cannot be evaluated: {WHY}'), alarm.summary)
        self.assertLessEqual(len(alarm.summary), 300)
        self.run_pass(minutes=1)                                        # the same pass again: one alarm, not two
        self.assertEqual(self.open_alarms().count(), 1)

    def test_a_refused_water_past_the_critical_limit_on_its_basis_raises_the_critical(self):
        """RC-3: the limit levels judge the basis as any value, and the refusal's warning stays beside them."""
        self.refuse(self.t2, water=WATER)
        self.run_pass()
        self.assertEqual(self.opened(), [('system', 'warning', NH3), ('water_limit', 'critical', NH3),
                                         ('water_limit', 'warning', NH3)])
        critical = self.open_alarms(source='water_limit', severity='critical').get()
        self.assertEqual(critical.summary, f'T-02 · Middle: {LABEL} at least {on_basis(WATER)} (critical)')  # F3-5
        self.assertEqual(critical.point, self.mid2)

    def test_the_page_and_the_alarm_agree_when_another_fresh_value_decides(self):
        """RC-2: T-02's own newer sample refused (inside the limits on its basis), its loop's fresh sample critical."""
        self.sample(self.loop, hours=2, **WATER)
        self.refuse(self.t2)
        for minutes in (0, 1, 60):
            self.run_pass(minutes=minutes)
        page = self.client.get(reverse('farm:water'))
        status = {row['owner']: row['water'].status for row in page.context['rows']}
        self.assertEqual(status[self.t2], 'critical')
        t2 = self.open_alarms(summary__startswith='T-02')
        self.assertEqual([(alarm.source, alarm.severity) for alarm in t2],
                         [('system', 'warning'), ('water_limit', 'critical'), ('water_limit', 'warning')])

    def test_without_a_basis_the_page_and_the_alarm_still_agree(self):
        """RC-2 where the core gives no basis either: the own reading has no value; the loop's value decided the page,
        and the alarm names it."""
        self.sample(self.loop, hours=2, **WATER)
        self.refuse(self.t2, water=WATER)
        with no_basis():
            # T-02's own refused sample is no worked-out value: the loop's critical is the value shown (review 4 of
            # derived-fresh), and the refusal is still "cannot be evaluated" (PointWater.refused_newer).
            water = self.unit_water(self.t2)
            reading = water.get(NH3)
            self.assertEqual((reading.value, reading.judged), (Decimal('0.8924'), 'critical'))
            self.assertEqual([each.code for each in water.unevaluated], [NH3])
            self.run_pass()
        critical = self.open_alarms(source='water_limit', severity='critical', summary__startswith='T-02').get()
        self.assertEqual(critical.summary, f'T-02 · Middle: {LABEL} 0.8924 (critical)')
        self.assertTrue(self.open_alarms(source='system', summary__startswith='T-02').exists())

    def stuck(self, own_hours):
        """The verification of FIX3, F3-1 (its probe Stuck.test_s4): T-02's own TAN without a pH (NH₃ "needs the pH": no
        value, not refused), the loop's fresh full sample critical decides it; then the loop's next sample is OK."""
        self.sample(self.loop, hours=6, **WATER)
        self.sample(self.t2, hours=own_hours, tan_mg_l='5.000')
        for minutes in (-290, -289, -230):
            self.run_pass(minutes=minutes)
        t2 = Alarm.objects.filter(source='water_limit', summary__startswith='T-02')
        raised = t2.filter(clearance__isnull=True).order_by('severity')
        said = f'T-02 · Middle: {LABEL} 0.8924 (critical)'
        self.assertEqual([(alarm.severity, alarm.summary) for alarm in raised], [('critical', said), ('warning', said)])
        self.sample(self.loop, hours=1, **LOW)
        # T-02's own TAN alone is no worked-out value: the loop's newer OK value is the value shown (review 4 of
        # derived-fresh), and T-02's TAN is said.
        reading = self.unit_water(self.t2).get(NH3)
        self.assertEqual((reading.judged, reading.worse, reading.point), ('ok', None, self.loop))
        self.assertIn('at Middle gives no value', reading.note)
        for minutes in (0, 1, 30, 60, 600, 3000):
            self.run_pass(minutes=minutes)
        # Ended once the water that raised them is back inside the limit, with that cause; never opened again.
        self.assertEqual(sorted((alarm.severity, alarm.clearance.cause) for alarm in t2),
                         [('critical', 'returned'), ('warning', 'returned')])
        self.assertFalse(self.open_alarms(source='water_limit').exists())

    def test_a_level_another_value_raised_ends_when_that_water_recovers(self):
        self.stuck(own_hours=5)

    def test_it_ends_too_when_the_units_own_value_less_sample_is_the_oldest(self):
        """The own TAN-only sample older than the loop's critical one: the evidence is the loop's newer value's time."""
        self.stuck(own_hours=7)

    def test_it_ends_with_no_fish_only_when_the_waters_values_no_longer_judge_it(self):
        """Its own "not measured" is no cause ("no fish" would be untrue): with the limit removed, the loop's values are
        no longer judged, and the levels end "limit removed"."""
        self.sample(self.loop, hours=6, **WATER)
        self.sample(self.t2, hours=5, tan_mg_l='5.000')
        for minutes in (-290, -289, -230):
            self.run_pass(minutes=minutes)
        WaterLimit.objects.all().delete()
        self.run_pass(minutes=0)
        causes = {alarm.clearance.cause for alarm in Alarm.objects.filter(source='water_limit',
                                                                          summary__startswith='T-02')}
        self.assertEqual(causes, {'limit_removed'})

    def test_it_ends_once_the_value_can_be_worked_out_and_the_limit_judges_it(self):
        self.refuse(self.t2, hours=2, water=WATER)
        self.run_pass()
        warning = self.open_alarms(source='system').get()
        limits = list(self.open_alarms(source='water_limit'))
        self.sample(self.t2, hours=1, **WATER, conductivity_25_us_cm='500')
        for minutes in (1, 2, 60):
            self.run_pass(minutes=minutes)
        self.assertFalse(read.is_open(warning))
        self.assertEqual(warning.clearance.cause, 'restored')
        self.assertTrue(all(read.is_open(alarm) for alarm in limits))       # the worked-out value is critical too
        self.assertEqual(self.opened(), [('water_limit', 'critical', NH3), ('water_limit', 'warning', NH3)])

    def test_an_alarm_already_open_is_not_cleared_by_the_refusal(self):
        self.sample(self.t1, hours=3, **WATER)
        self.run_pass()
        self.assertEqual(self.open_alarms(source='water_limit').count(), 2)
        self.refuse(self.t1, hours=1)
        for minutes in (0, 1, 2, 60, 600):
            self.run_pass(minutes=minutes)
        self.assertEqual([each.severity for each in self.open_alarms(source='water_limit')], ['critical', 'warning'])
        self.assertIn('T-01', self.open_alarms(source='system').get().summary)

    def test_a_refused_value_is_no_evidence_that_a_level_is_over(self):
        """Its basis inside the limits says nothing of the judged value, which may be past them: never a clearance."""
        rules = alarm_rules.current()
        self.refuse(self.t2)
        refused = self.unit_water(self.t2).get(NH3)
        self.sample(self.t1, **LOW)
        worked = self.unit_water(self.t1).get(NH3)
        self.assertEqual((refused.judged, worked.judged), ('unevaluated', 'ok'))
        now = timezone.now()
        for severity in (Severity.WARNING, Severity.CRITICAL):
            with self.subTest(severity=severity):
                self.assertFalse(sources.clear_evidence(refused, severity, rules, None, now))
                self.assertTrue(sources.clear_evidence(worked, severity, rules, None, now))

    def test_a_30_hour_old_conductivity_of_the_point_refuses_a_new_sample_and_the_unit_alarms(self):
        """The looked-up case: the new sample has no conductivity; the point's own of 30 hours ago is fresh for days."""
        self.sample(self.t2, hours=30, conductivity_25_us_cm='45000')
        self.sample(self.t2, hours=1, **WATER)
        reading = self.unit_water(self.t2).get(NH3)
        self.assertEqual((reading.value, reading.status), (on_basis(WATER), 'critical'))
        self.run_pass()
        self.assertEqual(self.opened(), [('system', 'warning', NH3), ('water_limit', 'critical', NH3),
                                         ('water_limit', 'warning', NH3)])
        self.assertIn(f'T-02: {LABEL} cannot be evaluated: {WHY}', self.open_alarms(source='system').get().summary)

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

    def test_the_limit_gone_ends_it_with_that_cause(self):
        self.refuse(self.t2)
        self.run_pass()
        alarm = self.open_alarms().get()
        WaterLimit.objects.all().delete()                           # nothing judges the value any more
        for minutes in (1, 2, 60):
            self.run_pass(minutes=minutes)
        self.assertFalse(read.is_open(alarm))
        self.assertEqual(alarm.clearance.cause, 'limit_removed')

    def test_a_later_sample_without_a_ph_does_not_end_it(self):
        """RC-4 (a): a TAN without its pH works nothing out; it ended the warning "restored"."""
        self.refuse(self.t2, hours=5)
        for minutes in (0, 1, 60):
            self.run_pass(minutes=minutes)
        alarm = self.open_alarms().get()
        self.sample(self.t2, hours=0, tan_mg_l='5.000')
        # The refused value (on its basis) stays the point's newest worked-out value (review 4 of derived-fresh).
        self.assertEqual(self.unit_water(self.t2).get(NH3).status, 'unevaluated')
        for minutes in (61, 62, 120, 600):
            self.run_pass(minutes=minutes)
        self.assertTrue(read.is_open(alarm))

    def test_the_sample_leaving_the_window_does_not_end_it(self):
        """RC-4 (b): nobody samples again; at day 31 the refused sample leaves the 30-day window. Nothing was worked out:
        it stays open, as a limit alarm whose value is read no more does."""
        self.refuse(self.t2)
        for minutes in (0, 1, 60):
            self.run_pass(minutes=minutes)
        alarm = self.open_alarms().get()
        for days in (8, 29, 31, 32):
            self.run_pass(minutes=days * 24 * 60)
        self.assertTrue(read.is_open(alarm))


class PageTests(RefusedWaterCase):
    SAID = f'{LABEL} cannot be evaluated: {WHY}'

    def test_the_water_page_says_the_units_state_and_the_reason(self):
        self.refuse(self.t2)
        page = self.client.get(reverse('farm:water'))
        row = next(row for row in page.context['rows'] if row['owner'] == self.t2)
        self.assertEqual(row['water'].status, 'unevaluated')
        body = page.content.decode()
        self.assertIn('wq-unevaluated', body)
        self.assertIn('<span>Cannot be evaluated</span>', body)
        self.assertIn(self.SAID, body)
        self.assertIn('at least: the safe-side basis', body)

    def test_past_the_critical_limit_on_its_basis_the_page_says_critical_and_the_reason(self):
        self.refuse(self.t2, water=WATER)
        page = self.client.get(reverse('farm:water'))
        row = next(row for row in page.context['rows'] if row['owner'] == self.t2)
        self.assertEqual(row['water'].status, 'critical')
        body = page.content.decode()
        self.assertIn(self.SAID, body)
        self.assertIn('at least: the safe-side basis', body)

    def test_the_historys_alerts_only_keeps_the_refused_sample(self):
        """RC-5: "Only warnings and criticals" dropped the sample whose NH₃ cannot be evaluated."""
        self.refuse(self.t2, hours=2)
        self.sample(self.t2, hours=1, ph='5.00', temperature_c='12.0')
        self.limit('ph', critical_low=6, warning_low='6.5')
        url = reverse('farm:water')
        self.assertEqual(self.client.get(url, {'view': 'history'}).context['page'].paginator.count, 2)
        alerts = self.client.get(url, {'view': 'history', 'alerts': '1'}).context['page']
        self.assertEqual(sorted(str(row.status) for row in alerts.object_list), ['critical', 'unevaluated'])

    def test_in_norwegian_and_turkish(self):
        self.refuse(self.t2)
        for language, said, basis in (('nb', 'Kan ikke vurderes', 'minst: grunnlaget for den sikre siden'),
                                      ('tr', 'Değerlendirilemiyor', 'en az: güvenli taraftaki temel')):
            with self.subTest(language=language):
                Profile.objects.update_or_create(user=self.user, defaults={'language': language})
                page = self.client.get(reverse('farm:water'))
                self.assertContains(page, said)
                self.assertContains(page, basis)


class EvidenceTests(RefusedWaterCase):
    """Review 5 of derived-fresh (the coordinator's round 6): per point and tier, the EVIDENCE value is the newest
    worked-out value that is not refused and was fresh at its own time; every value newer than it or of the same minute
    is judged beside it, and the point is the worst of them."""

    def test_a_refused_sample_with_a_basis_value_ahead_of_a_late_lab_critical_raises_the_critical(self):
        """H1 (2): T-02's own refused sample (inside the limits on its basis) 5 h ago; the lab's critical measured 8 h
        ago, keyed in now: the critical raises beside the refusal's warning."""
        self.refuse(self.t2, hours=5)
        self.sample(self.t2, hours=8, source='lab', **WATER)
        for minutes in (0, 1, 60):
            self.run_pass(minutes=minutes)
        t2 = {(alarm.source, alarm.severity) for alarm in self.open_alarms(summary__startswith='T-02')}
        self.assertIn(('water_limit', 'critical'), t2)
        self.assertEqual(self.unit_water(self.t2).get(NH3).judged, 'critical')

    def test_a_loop_only_unit_says_its_loops_refused_sample(self):
        """H2, scenario A: T-01 read at its loop alone; the loop's worked-out OK 10 h ago, then a loop sample the core
        refused with no basis 1 h ago: T-01 cannot be evaluated, its warning raised, never the older OK alone."""
        self.sample(self.loop, hours=10, **LOW)
        with no_basis():
            self.refuse(self.loop, hours=1, water=LOW)
            water = self.unit_water(self.t1)
            self.assertEqual([each.code for each in water.unevaluated], [NH3])
            for minutes in (0, 1, 60):
                self.run_pass(minutes=minutes)
        self.assertTrue(self.open_alarms(source='system', parameter=NH3, summary__startswith='T-01').exists())

    def test_a_tan_alone_after_a_refused_sample_does_not_end_its_warning(self):
        """H2, scenario B (RC-4 (a) again): T-02's middle OK 20 h ago, a refused no-basis sample 5 h ago (its warning
        raised), then a TAN alone now: the warning stays open, never "restored" on the older value."""
        self.sample(self.t2, hours=20, **LOW)
        with no_basis():
            self.refuse(self.t2, hours=5, water=LOW)
            for minutes in (0, 1, 60):
                self.run_pass(minutes=minutes)
            warning = self.open_alarms(source='system', parameter=NH3).get()
            self.sample(self.t2, hours=0, tan_mg_l='0.500')
            for minutes in (61, 62, 120, 600):
                self.run_pass(minutes=minutes)
        self.assertTrue(read.is_open(warning))
