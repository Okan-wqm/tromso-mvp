"""The water-chemistry audit of 2026-11-19, F3: a TAN's NH₃-N is judged UNROUNDED and rounded only where it is shown.

Before, the NH₃-N was rounded to its four decimals (0.0001 mg/L) and that rounded value was judged with a strict `>`: a
true 0.01034 mg/L read 0.0103 and was OK against a limit of 0.0103. The excess hidden is at most 0.00005 mg/L, 0.5 % of
0.0103 but 2.5 % of a 0.002 mg/L limit. Now the reading keeps the exact value (`Reading.exact`) and the limits, the
alarm's deadband test and every page's status read it (`Reading.judged_value`); the number shown keeps four decimals."""
from decimal import Decimal as D

from alarms import sources as alarm_sources

from ..water import chemistry, parameters, read
from ..water.evaluate import Status
from .test_water import WaterTestCase

LIMIT = D('0.0103')
HALF_STEP = D('0.00005')


class UnroundedJudgementTests(WaterTestCase):
    PH, TEMPERATURE = 7.5, 12.0

    def setUp(self):
        super().setUp()
        self.stock()
        self.row = self.limit('nh3_n_mg_l', warning_high=LIMIT, critical_high='0.02')

    def tan_between(self, share, low, high):
        """The first TAN at its three decimals whose exact NH₃-N (TAN × share) lies strictly between low and high."""
        for thousandths in range(1, 100_000):
            tan = D(thousandths) / 1000
            if low < tan * share < high:
                return tan
        self.fail('no TAN gives an NH₃-N in the window')

    def share(self):
        """The judged share of the sample's water as the read path works it out (fresh water, nothing else measured)."""
        return D(chemistry.water_equilibria(self.TEMPERATURE, 0.0, water_origin=read.common_origin([self.t1]))
                 .nh3_share(self.PH))

    def nh3(self):
        return read.latest([self.mid1])[self.mid1.pk].get('nh3_n_mg_l')

    def test_just_over_the_limit_is_a_warning_though_it_reads_as_the_limit(self):
        share = self.share()
        tan = self.tan_between(share, LIMIT, LIMIT + HALF_STEP)
        self.sample(hours=1, tan_mg_l=tan, ph=self.PH, temperature_c=self.TEMPERATURE)
        nh3 = self.nh3()
        self.assertEqual(nh3.value, LIMIT)                                  # shown at four decimals: 0.0103
        self.assertEqual(nh3.judged_value, tan * share)                     # judged as it is
        self.assertGreater(nh3.judged_value, LIMIT)
        self.assertEqual((nh3.judged, nh3.status), (Status.WARNING, Status.WARNING))
        history = read.history(read.samples_of(points=[self.mid1]))[0].readings['nh3_n_mg_l']
        self.assertEqual((history.value, history.judged), (LIMIT, Status.WARNING))
        self.assertEqual(self.unit_water().status, Status.WARNING)

    def test_just_under_the_limit_is_ok_and_reads_as_the_limit(self):
        share = self.share()
        tan = self.tan_between(share, LIMIT - HALF_STEP, LIMIT)
        self.sample(hours=1, tan_mg_l=tan, ph=self.PH, temperature_c=self.TEMPERATURE)
        nh3 = self.nh3()
        self.assertEqual(nh3.value, LIMIT)
        self.assertLessEqual(nh3.judged_value, LIMIT)
        self.assertEqual((nh3.judged, nh3.status), (Status.OK, Status.OK))

    def test_a_measured_value_is_judged_as_it_was_entered(self):
        """A measured value has no exact one apart from itself: it is judged as entered."""
        self.limit('ph', warning_high='8.00')
        self.sample(hours=1, ph='8.01')
        ph = read.latest([self.mid1])[self.mid1.pk].get('ph')
        self.assertEqual((ph.exact, ph.judged_value, ph.judged), (None, D('8.01'), Status.WARNING))

    def test_the_basis_alone_of_a_refused_water_is_judged_unrounded_too(self):
        """A water the core refuses (a conductivity past the Davies range) has its NH₃ judged on the limits' basis alone
        (read.Context._ammonia_on_basis): unrounded as well, so just past the limit it is a warning, not "cannot be
        evaluated"."""
        share = read.Context.nh3_basis_share(self.TEMPERATURE, 0, self.PH, read.common_origin([self.t1]))
        tan = self.tan_between(share, LIMIT, LIMIT + HALF_STEP)
        self.sample(hours=1, tan_mg_l=tan, ph=self.PH, temperature_c=self.TEMPERATURE, conductivity_25_us_cm='40000')
        nh3 = self.nh3()
        self.assertTrue(nh3.refused)
        self.assertEqual((nh3.value, nh3.judged_value), (LIMIT, tan * share))
        self.assertEqual(nh3.judged, Status.WARNING)

    def test_the_alarms_deadband_test_reads_the_exact_value(self):
        """An alarm clears only when the value is clear of the limit by the deadband both ways
        (alarms/sources.judged_clear): through the exact value as well, never the rounded one."""
        class NoDeadband:
            @staticmethod
            def deadband(code):
                return D(0)
        observation = read.Observation(self.mid1, self.now, read.Origin.MANUAL, {})
        reading = read.Reading(parameters.NH3_N, LIMIT, observation, True, limits=[self.row],
                               exact=LIMIT + D('0.00003'))
        self.assertEqual(alarm_sources.judged_clear(reading, NoDeadband()), Status.WARNING)
        reading.exact = LIMIT - D('0.00003')
        self.assertEqual(alarm_sources.judged_clear(reading, NoDeadband()), Status.OK)
