"""The alarm engine judges a worked-out value's freshness as every reader does (farm/water/read.py `Reading.fresh`,
`freshness.derived_until`: never fresher than its oldest input): an NH₃ whose temperature has run out is stale, and a
stale value never ends an alarm, exactly as the stale temperature it was worked out from does not. T-01 stocked, NH₃-N
limits 0.0125 (warning) and 0.025 (critical), a temperature limit 11 °C (critical above) beside it as the measured
control (a critical opens the warning level beside it). Raised 40 h ago by a full sample (NH₃-N 0.8924, 12 °C); then a full sample inside both limits."""
from datetime import timedelta

from farm.tests.test_water import WaterTestCase

from .. import engine
from ..models import Alarm

BAD = {'ph': '9.00', 'temperature_c': '12.0', 'salinity_ppt': '0.0', 'alkalinity_mg_l': '80', 'tan_mg_l': '5.000'}
GOOD = {**BAD, 'ph': '7.00', 'tan_mg_l': '0.500', 'temperature_c': '10.0'}
NH3, TEMPERATURE = 'nh3_n_mg_l', 'temperature_c'
OPEN = 'open'


class DerivedStaleAlarmTests(WaterTestCase):
    def setUp(self):
        super().setUp()
        self.stock()
        self.limit(NH3, critical_high='0.025', warning_high='0.0125')
        self.limit(TEMPERATURE, critical_high='11.0')
        self.sample(self.t1, hours=40, **BAD)
        self.passes(-2380, -2379, -2320)
        self.assertEqual(self.outcome(NH3), {'critical': OPEN, 'warning': OPEN})
        self.assertEqual(self.outcome(TEMPERATURE), {'critical': OPEN, 'warning': OPEN})

    def passes(self, *minutes):
        for each in minutes:
            engine.run_once(self.now + timedelta(minutes=each))

    def outcome(self, parameter):
        found = {}
        for alarm in Alarm.objects.filter(source='water_limit', parameter=parameter):
            self.assertNotIn(alarm.severity, found, f'{parameter} {alarm.severity} opened twice')
            found[alarm.severity] = alarm.clearance.cause if hasattr(alarm, 'clearance') else OPEN
        return found

    def test_a_good_value_worked_out_from_an_expired_input_ends_nothing(self):
        """The good sample 30 h old when the passes run: its TAN (168 h), its pH (72 h) and the NH₃ row (168 h) are
        fresh, its temperature (24 h) is not. The NH₃ is stale and holds both levels, as the temperature holds its own."""
        self.sample(self.t1, hours=30, **GOOD)
        self.passes(0, 1, 60, 120, 600)
        self.assertEqual(self.outcome(TEMPERATURE), {'critical': OPEN, 'warning': OPEN})
        self.assertEqual(self.outcome(NH3), {'critical': OPEN, 'warning': OPEN})
        reading = self.unit_water().get(NH3)
        self.assertEqual(reading.status, 'stale')
        self.assertFalse(reading.fresh(self.now))

    def test_the_same_good_value_fresh_ends_them(self):
        """The control: the good sample 10 h old, every input fresh: both end, as the temperature's does."""
        self.sample(self.t1, hours=10, **GOOD)
        self.passes(0, 1, 60, 120, 600)
        self.assertEqual(self.outcome(TEMPERATURE), {'critical': 'returned', 'warning': 'returned'})
        self.assertEqual(self.outcome(NH3), {'critical': 'returned', 'warning': 'returned'})


class OwnPointEvidenceTests(WaterTestCase):
    """The review of 2026-11-26, F1 (the coordinator's rule): a worked-out alarm raised at one of the unit's own points
    ends only on new evidence from THAT point, a fresh value there back inside the limits; a newer OK value at another
    own point is not that evidence, and a late lab critical at a point still raises beside one. T-01 stocked, its middle
    point and an outlet (both its own water, A9.1), NH₃-N limits 0.0125 and 0.025."""

    def setUp(self):
        super().setUp()
        from farm.models import SamplingPoint
        self.stock()
        self.limit(NH3, critical_high='0.025', warning_high='0.0125')
        self.outlet = SamplingPoint.objects.create(unit=self.t1, name='Outlet', kind='outlet')

    passes = DerivedStaleAlarmTests.passes
    outcome = DerivedStaleAlarmTests.outcome

    def test_a_newer_ok_middle_does_not_end_the_outlets_critical(self):
        """The outlet critical 40 h ago (its temperature, so its NH₃, stale since 16 h ago; its TAN still fresh), the
        middle OK 2 h ago: both levels stay open, and the page says which point to measure. The outlet measured again,
        fresh and OK, ends them."""
        self.sample(self.outlet, hours=40, **BAD)
        self.passes(-2380, -2379, -2320)
        self.assertEqual(self.outcome(NH3), {'critical': OPEN, 'warning': OPEN})
        self.sample(self.t1, hours=2, **GOOD)
        self.passes(0, 1, 60, 120, 600)
        self.assertEqual(self.outcome(NH3), {'critical': OPEN, 'warning': OPEN})
        reading = self.unit_water().get(NH3)
        self.assertEqual((reading.point, reading.judged, reading.worse.point), (self.mid1, 'critical', self.outlet))
        self.assertIn('last value at Outlet 0.8924 critical on ', reading.note)
        self.assertIn('no recent data: measure there', reading.note)
        self.sample(self.outlet, hours=1, **GOOD)
        self.passes(601, 602, 660, 720, 1200)
        self.assertEqual(self.outcome(NH3), {'critical': 'returned', 'warning': 'returned'})

    def test_a_late_lab_critical_at_the_outlet_raises_beside_a_newer_ok_middle(self):
        """The middle OK 2 h ago; the lab's outlet result, taken 30 h ago, keyed in now: critical, already stale. It
        raises both levels at once."""
        self.sample(self.t1, hours=2, **GOOD)
        self.sample(self.outlet, hours=30, source='lab', **BAD)
        self.passes(0, 1, 60)
        self.assertEqual(self.outcome(NH3), {'critical': OPEN, 'warning': OPEN})

    def test_a_newer_sample_at_the_outlet_that_cannot_be_worked_out_ends_nothing(self):
        """The outlet critical 40 h ago; then a TAN at the outlet without a pH or a temperature (3 h ago): its NH₃ cannot
        be worked out, which says nothing of the water being better. The middle OK 2 h ago. Both levels stay open, and
        the place says the outlet's newer sample lacks the inputs."""
        self.sample(self.outlet, hours=40, **BAD)
        self.passes(-2380, -2379, -2320)
        self.sample(self.outlet, hours=3, tan_mg_l='0.500')
        self.sample(self.t1, hours=2, **GOOD)
        self.passes(0, 1, 60, 120, 600)
        self.assertEqual(self.outcome(NH3), {'critical': OPEN, 'warning': OPEN})
        reading = self.unit_water().get(NH3)
        self.assertEqual((reading.judged, reading.worse.point, str(reading.worse.value)), ('critical', self.outlet,
                                                                                           '0.8924'))
        self.assertIn('last worked-out value at Outlet 0.8924 critical on ', reading.note)
        self.assertIn('lacks what it is worked out from: measure there again', reading.note)
