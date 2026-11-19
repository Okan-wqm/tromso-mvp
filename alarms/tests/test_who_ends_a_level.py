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
What came next (6 h ago): an own full sample OK or critical, an own TAN without a pH, the loop OK or critical, an own
TAN without a pH then the loop OK (F3-1 / S4b; for OWN the probe S9 of F3-7), nothing, the bad sample voided."""
from datetime import timedelta

from farm.tests.test_water import WaterTestCase
from farm.water import services as water_services

from .. import engine
from ..models import Alarm, AlarmSubjectState
from ..sources import water_key

WATER = {'ph': '9.00', 'temperature_c': '12.0', 'salinity_ppt': '0.0', 'alkalinity_mg_l': '80', 'tan_mg_l': '5.000'}
LOW = {**WATER, 'ph': '7.00', 'tan_mg_l': '0.500'}
TAN_ONLY = {'tan_mg_l': '5.000'}
NH3 = 'nh3_n_mg_l'
OPEN = 'open'
RAISERS = ('own', 'other_tan', 'other_ok', 'stand_in')
EVENTS = ('own_ok', 'own_bad', 'own_tan', 'loop_ok', 'loop_bad', 'own_tan_then_loop_ok', 'nothing', 'void')
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
}


class WhoEndsALevelCase(WaterTestCase):
    def setUp(self):
        super().setUp()
        self.stock()
        self.stock(self.t2)
        self.limit(NH3, critical_high='0.025', warning_high='0.0125')

    def passes(self, *minutes):
        for each in minutes:
            engine.run_once(self.now + timedelta(minutes=each))

    def levels(self):
        return Alarm.objects.filter(source='water_limit', point=self.mid2).order_by('severity')

    def own_held(self):
        return AlarmSubjectState.objects.get(key=water_key(self.t2.pk, NH3, 'critical')).own_held

    def raise_by(self, raiser):
        if raiser == 'own':
            bad = self.sample(self.t2, hours=12, **WATER)
        else:
            bad = self.sample(self.loop, hours=12, **WATER)
            if raiser != 'stand_in':
                self.sample(self.t2, hours=11, **(TAN_ONLY if raiser == 'other_tan' else LOW))
        self.passes(-700, -699, -640)
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


def _cell(raiser, event):
    def test(self):
        bad = self.raise_by(raiser)
        self.then(event, bad)
        self.assertEqual(self.outcome(), EXPECTED[raiser, event])
    test.__doc__ = f'Raised by {raiser}, then {event}: {EXPECTED[raiser, event]}.'
    return test


def _remembers(raiser):
    def test(self):
        self.raise_by(raiser)
        self.assertEqual(self.own_held(), raiser == 'own')
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
