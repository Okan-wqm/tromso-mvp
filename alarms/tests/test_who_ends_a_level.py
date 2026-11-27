"""Which value can end a water limit level (alarms/sources.py, the rule at the top; the verification of FIX3, F3-1 and
F3-7): a level the unit's own value raised ends only on the unit's own evidence; a level another fresh value of its
water raised (read.worst_fresh) ends when the values that judge it are clear. One matrix: who raised it × what came
next, each asserting both levels' state and cause and that nothing opened twice. Fresh stocked T-01 and T-02 in loop R1,
NH₃-N limits 0.0125 (warning) and 0.025 (critical).

Who raised (12 h ago, raised by three passes):
- OWN: T-02's own full sample, NH₃-N 0.8924;
- OTHER_TAN: the loop's full sample 0.8924, T-02's own newest a TAN without a pH (no value of its own: F3-1);
- OTHER_OK: the loop's full sample 0.8924, T-02's own newest a full sample inside the limits (0.0011).
- STAND_IN: the loop's full sample 0.8924 standing in for T-02, which has no sample of its own (read.latest).
Each also as OPEN WHEN 0014 LANDS (`<raiser>_landed`, F3-8): raised, then every row's `own_held` false as the
migration leaves it, then the first pass after landing works it out.
What came next (6 h ago): an own full sample OK or critical, an own TAN without a pH, the loop OK or critical, an own
TAN without a pH then the loop OK (F3-1 / S4b; for OWN the probe S9 of F3-7), nothing, the bad sample voided; and, on a
timeline raised 200 h ago, the bad value going stale (its temperature 24 h, its TAN 168 h) while the loop's OK sample stands in (F3-9, decision
of 2026-11-19: a value measured on the unit is confirmed over only by measuring the unit again)."""
from datetime import timedelta

from farm.tests.test_water import WaterTestCase
from farm.water import services as water_services

from .. import engine
from ..models import Alarm, AlarmSubjectState
from ..sources import water_key
from . import ran_clean

WATER = {'ph': '9.00', 'temperature_c': '12.0', 'salinity_ppt': '0.0', 'alkalinity_mg_l': '80', 'tan_mg_l': '5.000'}
LOW = {**WATER, 'ph': '7.00', 'tan_mg_l': '0.500'}
TAN_ONLY = {'tan_mg_l': '5.000'}
NH3 = 'nh3_n_mg_l'
OPEN = 'open'
BASE = ('own', 'other_tan', 'other_ok', 'stand_in')
RAISERS = (*BASE, *(f'{raiser}_landed' for raiser in BASE))
EVENTS = ('own_ok', 'own_bad', 'own_tan', 'loop_ok', 'loop_bad', 'own_tan_then_loop_ok', 'nothing', 'void',
          'stale_then_loop_ok')
STALE = 'stale_then_loop_ok'
EXPECTED = {
    # Raised by T-02's own value: only T-02's own evidence ends it.
    ('own', 'own_ok'): 'returned', ('own', 'own_bad'): OPEN, ('own', 'own_tan'): OPEN, ('own', 'loop_ok'): OPEN,
    ('own', 'loop_bad'): OPEN, ('own', 'own_tan_then_loop_ok'): OPEN, ('own', 'nothing'): OPEN, ('own', 'void'): OPEN,
    # Raised by the loop's value, T-02's own value-less: the loop's values end it.
    ('other_tan', 'own_ok'): OPEN, ('other_tan', 'own_bad'): OPEN, ('other_tan', 'own_tan'): OPEN,
    ('other_tan', 'loop_ok'): 'returned', ('other_tan', 'loop_bad'): OPEN,
    ('other_tan', 'own_tan_then_loop_ok'): 'returned', ('other_tan', 'nothing'): OPEN, ('other_tan', 'void'): OPEN,
    # Raised by the loop's value, T-02's own value clear: the loop's values end it; voided, T-02's own OK value, taken
    # after the bad one, is evidence (an OLDER value newest again would not be: defect 4).
    ('other_ok', 'own_ok'): OPEN, ('other_ok', 'own_bad'): OPEN, ('other_ok', 'own_tan'): OPEN,
    ('other_ok', 'loop_ok'): 'returned', ('other_ok', 'loop_bad'): OPEN,
    ('other_ok', 'own_tan_then_loop_ok'): 'returned', ('other_ok', 'nothing'): OPEN, ('other_ok', 'void'): 'returned',
    # Raised by the loop standing in for T-02, which has no sample of its own: the loop's values end it.
    ('stand_in', 'own_ok'): OPEN, ('stand_in', 'own_bad'): OPEN, ('stand_in', 'own_tan'): OPEN,
    ('stand_in', 'loop_ok'): 'returned', ('stand_in', 'loop_bad'): OPEN,
    ('stand_in', 'own_tan_then_loop_ok'): 'returned', ('stand_in', 'nothing'): OPEN, ('stand_in', 'void'): OPEN,
    # The bad value stale, the loop's OK value standing in: a value measured on T-02 holds (F3-9); the loop's ends.
    ('own', STALE): OPEN, ('other_tan', STALE): 'returned', ('other_ok', STALE): 'returned',
    ('stand_in', STALE): 'returned',
}
# Open when 0014 lands: the same outcome as raised after it.
EXPECTED.update({(f'{raiser}_landed', event): outcome for (raiser, event), outcome in list(EXPECTED.items())})


class WhoEndsALevelCase(WaterTestCase):
    def setUp(self):
        super().setUp()
        self.stock()
        self.stock(self.t2)
        self.limit(NH3, critical_high='0.025', warning_high='0.0125')

    def passes(self, *minutes):
        for each in minutes:
            ran_clean(self, engine.run_once(self.now + timedelta(minutes=each)))

    def levels(self):
        return Alarm.objects.filter(source='water_limit', point=self.mid2).order_by('severity')

    def own_held(self):
        return AlarmSubjectState.objects.get(key=water_key(self.t2.pk, NH3, 'critical')).own_held

    def raise_by(self, raiser, hours=12):
        base, landed = raiser.removesuffix('_landed'), raiser.endswith('_landed')
        if base == 'own':
            bad = self.sample(self.t2, hours=hours, **WATER)
        else:
            bad = self.sample(self.loop, hours=hours, **WATER)
            if base != 'stand_in':
                self.sample(self.t2, hours=hours - 1, **(TAN_ONLY if base == 'other_tan' else LOW))
        start = -60 * hours
        self.passes(start + 20, start + 21, start + 80)
        if landed:                  # alarms 0014 lands: every row's own_held false; the next pass works it out
            AlarmSubjectState.objects.update(own_held=False)
            self.passes(start + 90)
        self.assertEqual([(alarm.severity, alarm.clearance_or_none) for alarm in self.state()],
                         [('critical', None), ('warning', None)])
        return bad

    def state(self):
        found = list(self.levels())
        for alarm in found:
            alarm.clearance_or_none = alarm.clearance.cause if hasattr(alarm, 'clearance') else None
        return found

    def then(self, event, bad):
        if event == 'own_ok':
            self.sample(self.t2, hours=6, **LOW)
        elif event == 'own_bad':
            self.sample(self.t2, hours=6, **WATER)
        elif event == 'own_tan':
            self.sample(self.t2, hours=6, **TAN_ONLY)
        elif event == 'loop_ok':
            self.sample(self.loop, hours=6, **LOW)
        elif event == 'loop_bad':
            self.sample(self.loop, hours=6, **WATER)
        elif event == 'own_tan_then_loop_ok':
            self.sample(self.t2, hours=6, **TAN_ONLY)
            self.sample(self.loop, hours=5, **LOW)
        elif event == 'void':
            water_services.void(self.user, bad, 'a typo')
        elif event == STALE:
            self.sample(self.loop, hours=2, **LOW)
            self.passes(-110, -109, -50, 0, 600)
            return
        self.passes(-350, -349, -290, -230, 0, 600)

    def outcome(self):
        alarms = self.state()
        self.assertEqual(len(alarms), 2, 'a level opened twice')
        causes = {alarm.clearance_or_none or OPEN for alarm in alarms}
        self.assertEqual(len(causes), 1, f'the two levels disagree: {causes}')
        return causes.pop()


class MatrixTests(WhoEndsALevelCase):
    """One test per cell of the matrix (`test_<raiser>_then_<event>`, made below)."""

    def test_the_matrix_is_whole(self):
        self.assertEqual(set(EXPECTED), {(raiser, event) for raiser in RAISERS for event in EVENTS})

    def test_0014_leaves_who_raised_it_to_the_first_pass(self):
        """F3-8: the migration adds the column and decides nothing (it set every open level true, which kept a level the
        loop raised for a unit without a sample of its own open after the loop recovered)."""
        import importlib
        migration = importlib.import_module('alarms.migrations.0014_subject_own_held').Migration
        self.assertEqual([type(operation).__name__ for operation in migration.operations], ['AddField'])


def _cell(raiser, event):
    def test(self):
        bad = self.raise_by(raiser, hours=200 if event == STALE else 12)
        self.then(event, bad)
        self.assertEqual(self.outcome(), EXPECTED[raiser, event])
    test.__doc__ = f'Raised by {raiser}, then {event}: {EXPECTED[raiser, event]}.'
    return test


def _remembers(raiser):
    def test(self):
        self.raise_by(raiser)
        self.assertEqual(self.own_held(), raiser.removesuffix('_landed') == 'own')
    test.__doc__ = f'Raised by {raiser}: the row says whether the unit’s own value holds it.'
    return test


for _raiser in RAISERS:
    for _event in EVENTS:
        setattr(MatrixTests, f'test_{_raiser}_then_{_event}', _cell(_raiser, _event))
    setattr(MatrixTests, f'test_the_row_remembers_who_raised_it_{_raiser}', _remembers(_raiser))


class NamedTests(WhoEndsALevelCase):
    def test_s9_own_critical_then_own_tan_only_then_loop_ok_stays_open(self):
        """F3-7, the verifier's probe S9: T-02's own critical, then its own TAN without a pH, then the loop OK. The loop
        says nothing of T-02's own NH₃: both levels stay open (c690439 ended them "returned")."""
        self.sample(self.t2, hours=12, **WATER)
        self.passes(-710, -709, -650)
        self.sample(self.t2, hours=8, **TAN_ONLY)
        self.passes(-470, -469, -440)
        self.sample(self.loop, hours=6, **LOW)
        self.passes(-350, -349, -320, -290, 0)
        self.assertEqual(self.outcome(), OPEN)
        # The unit's own full OK sample ends them.
        self.sample(self.t2, hours=1, **LOW)
        self.passes(1, 2, 70)
        self.assertEqual(self.outcome(), 'returned')

    def test_s4b_raised_by_the_loop_ended_by_the_loop_and_not_raised_again(self):
        """F3-1 / S4b: raised by the loop over T-02's own TAN without a pH; the loop's OK sample ends both; T-02's own
        full OK sample afterwards opens nothing."""
        self.sample(self.loop, hours=12, **WATER)
        self.sample(self.t2, hours=11, **TAN_ONLY)
        self.passes(-650, -649, -590)
        self.sample(self.loop, hours=8, **LOW)
        self.passes(-470, -469, -440, -410)
        self.assertEqual(self.outcome(), 'returned')
        self.sample(self.t2, hours=1, **LOW)
        self.passes(0, 1, 30, 60, 600)
        self.assertEqual(self.outcome(), 'returned')


class LastOwnTests(WhoEndsALevelCase):
    """F3-9, decision of 2026-11-19: T-02's own critical (0.8924) goes stale and the loop's OK sample (0.0011) stands in.
    The level stays open, and the page, the card and the alarm agree: critical, with T-02's last own value marked stale
    beside the loop's and "measure this unit" (read.last_own)."""
    SAID = 'last own value 0.8924 critical on '
    TAIL = ', no recent data: measure this unit'

    def stale_own(self, raise_first=True):
        self.sample(self.t2, hours=200, **WATER)
        if raise_first:
            self.passes(-11980, -11979, -11920)
        self.sample(self.loop, hours=2, **LOW)
        self.passes(-110, -109, -50, 0)

    def test_the_page_the_card_and_the_alarm_say_the_same(self):
        from django.urls import reverse
        from monitoring import read as monitoring_read
        from monitoring.tests import chosen
        self.stale_own()
        self.assertEqual(self.outcome(), OPEN)
        reading = self.unit_water(self.t2).get(NH3)
        self.assertEqual((str(reading.value), reading.status, str(reading.last_own.value), reading.last_own.status),
                         ('0.0011', 'critical', '0.8924', 'stale'))
        self.assertTrue(reading.last_own_said.startswith(self.SAID) and reading.last_own_said.endswith(self.TAIL))
        page = self.client.get(reverse('farm:water'))
        row = next(row for row in page.context['rows'] if row['owner'] == self.t2)
        self.assertEqual(row['water'].status, 'critical')
        self.assertContains(page, 'wq-last-own')
        self.assertContains(page, self.TAIL)
        from core.models import Profile
        from farm.tests.helpers import role
        from monitoring.tests import ALL_RIGHTS
        reader = self.user.__class__.objects.create_user('reader', 'r@example.com', 'x')
        reader.groups.add(role('reader role', *ALL_RIGHTS))
        card = monitoring_read.cards([self.t2], reader, chosen({self.t2.pk: 'simple'}))[0]
        state = monitoring_read.state_of(card)
        self.assertEqual(state.key, 'critical')
        self.assertTrue(any(str(reason).endswith(self.TAIL) for reason in state.reasons), state.reasons)
        for language, words in (('nb', 'mål denne enheten'), ('tr', 'bu birimi ölçün')):
            with self.subTest(language=language):
                Profile.objects.update_or_create(user=self.user, defaults={'language': language})
                self.assertContains(self.client.get(reverse('farm:water')), words)

    def test_a_level_raised_in_that_state_says_it(self):
        """Nothing raised while the own value was fresh (the loop of passes was not running): raised now, its summary
        says the last own value and "measure this unit"."""
        self.stale_own(raise_first=False)
        summaries = {alarm.severity: alarm.summary for alarm in self.levels()}
        self.assertEqual(set(summaries), {'critical', 'warning'})
        for summary in summaries.values():
            self.assertTrue(summary.startswith(f'T-02 · Middle: Un-ionised ammonia (mg/L NH₃ as N) 0.0011 (critical); '
                                               f'{self.SAID}'), summary)
            self.assertTrue(summary.endswith(self.TAIL), summary)

    def test_a_fresh_own_sample_ends_it(self):
        self.stale_own()
        self.sample(self.t2, hours=1, **LOW)
        self.passes(1, 2, 70)
        self.assertEqual(self.outcome(), 'returned')
        self.assertIsNone(self.unit_water(self.t2).get(NH3).last_own)
