"""Which bound a value is past (evaluate.crossed, read.crossed): what a short sentence names beside a critical or warning
value ("O₂ (mg/L) 5.00 < critical limit 6.00": a monitoring card's one line, the band's chip). It is never a second
judgement: for any value and any limit row it names a bound exactly when `judge` says critical or warning, the bound of
that rung; and for a reading, the value and the bound are those that gave the reading its status (the worse fresh value
when that decided it, the value in its other unit when a row on that unit judged the oxygen)."""
import random
from decimal import Decimal as D
from types import SimpleNamespace

from django.test import SimpleTestCase

from ..water import read
from ..water.evaluate import Status, crossed, judge
from .test_water import WaterTestCase

BOUNDS = ('critical_low', 'warning_low', 'warning_high', 'critical_high')


def limit(**bounds):
    values = {name: None for name in BOUNDS}
    values.update({name: D(str(value)) for name, value in bounds.items()})
    return SimpleNamespace(**values)


class CrossedTests(SimpleTestCase):
    def test_the_bound_of_the_rung_judge_gives(self):
        row = limit(critical_low=60, warning_low=80, warning_high=110, critical_high=120)
        cases = [('59.9', ('critical_low', D(60))), ('60', ('warning_low', D(80))), ('79.9', ('warning_low', D(80))),
                 ('80', None), ('110', None), ('110.1', ('warning_high', D(110))), ('120', ('warning_high', D(110))),
                 ('120.1', ('critical_high', D(120)))]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(crossed(D(value), row), expected)
        self.assertEqual(crossed(D(5), limit(critical_high=4)), ('critical_high', D(4)))     # open bounds are open
        self.assertIsNone(crossed(D(-1), limit(critical_high=4)))
        self.assertIsNone(crossed(D(7), limit()))

    def test_a_worked_out_value_is_named_past_the_bound_its_unrounded_value_was_judged_by(self):
        """Main's audit of 2026-11-19, F3: a worked-out value is judged unrounded (`Reading.exact`), so a true 0.01034
        mg/L NH₃-N shown as 0.0103 is critical against a limit of 0.0103; the short sentence names that bound too,
        never "no bound" beside a critical card."""
        from django.utils import timezone

        from ..water import parameters
        observation = read.Observation(SimpleNamespace(name='Middle', kind='middle'), timezone.now(),
                                       read.Origin.MANUAL, {})
        reading = read.Reading(parameters.get('nh3_n_mg_l'), D('0.0103'), observation, True, exact=D('0.01034'))
        reading.limits, reading.judged = [limit(critical_high='0.0103')], Status.CRITICAL
        source, name, bound = read.crossed(reading)
        self.assertEqual((source, name, bound), (reading, 'critical_high', D('0.0103')))

    def test_it_never_disagrees_with_judge(self):
        draw = random.Random(20261113)
        for _round in range(2000):
            chosen = sorted(draw.sample(range(0, 200), 4))
            row = limit(**{name: bound for name, bound in zip(BOUNDS, chosen) if draw.random() < 0.7})
            value = D(draw.randint(-10, 210))
            found, status = crossed(value, row), judge(value, row)
            with self.subTest(value=value, row=vars(row)):
                if status == Status.OK:
                    self.assertIsNone(found)
                else:
                    name, bound = found
                    self.assertTrue(name.startswith(str(status)))
                    self.assertEqual(bound, getattr(row, name))
                    self.assertTrue(value < bound if name.endswith('low') else value > bound)


class ReadingCrossedTests(WaterTestCase):
    def setUp(self):
        super().setUp()
        self.stock()
        self.limit('oxygen_mg_l', critical_low=6, warning_low=7)
        self.limit('co2_mg_l', warning_high=10, critical_high=15)

    def test_a_critical_and_a_warning_reading_name_their_value_and_bound(self):
        self.sample(oxygen_mg_l='5', co2_mg_l='12', temperature_c='10')
        water = self.unit_water()
        source, name, bound = read.crossed(water.get('oxygen_mg_l'))
        self.assertEqual((source.value, name, bound), (D('5.00'), 'critical_low', D(6)))
        source, name, bound = read.crossed(water.get('co2_mg_l'))
        self.assertEqual((source.value, name, bound), (D('12.0'), 'warning_high', D(10)))
        self.assertIsNone(read.crossed(water.get('temperature_c')))            # no limit: no bound
        self.sample(hours=0.5, oxygen_mg_l='9')
        self.assertIsNone(read.crossed(self.unit_water().get('oxygen_mg_l')))  # inside its limits

    def test_an_old_value_keeps_the_bound_it_was_past(self):
        self.sample(hours=30, oxygen_mg_l='5')                                  # an oxygen says something for 24 hours
        reading = self.unit_water().get('oxygen_mg_l')
        self.assertEqual((reading.status, reading.judged), (Status.STALE, Status.CRITICAL))
        source, name, bound = read.crossed(reading)
        self.assertEqual((source.value, name, bound), (D('5.00'), 'critical_low', D(6)))

    def test_the_worse_fresh_value_is_the_one_named_when_it_decided_the_status(self):
        """Owner decision 2026-11-08 (worst_fresh): the value shown is the newest, the status the worst fresh one's."""
        self.sample(self.loop, hours=3, oxygen_mg_l='5')                        # the loop's sample: critical, still fresh
        self.sample(hours=1, oxygen_mg_l='9')                                   # the unit's own, newer: the value shown
        reading = self.unit_water().get('oxygen_mg_l')
        self.assertEqual((reading.value, reading.judged), (D('9.00'), Status.CRITICAL))
        self.assertIsNotNone(reading.worse)
        source, name, bound = read.crossed(reading)
        self.assertEqual((source.value, source.point, name, bound), (D('5.00'), self.loop, 'critical_low', D(6)))

    def test_the_oxygen_judged_through_its_other_unit_names_that_value_and_row(self):
        from ..models import WaterLimit
        WaterLimit.objects.filter(parameter='oxygen_mg_l').delete()
        self.limit('oxygen_saturation_pct', critical_low=60, warning_low=80)
        self.sample(oxygen_mg_l='5', temperature_c='10')
        reading = self.unit_water().get('oxygen_mg_l')
        self.assertEqual(reading.judged, Status.CRITICAL)                       # about 44 % of saturation at 10 °C
        source, name, bound = read.crossed(reading)
        self.assertEqual((source.code, name, bound), ('oxygen_saturation_pct', 'critical_low', D(60)))
        self.assertEqual(source.value, reading.through.value)
