"""A value shown beside the bound it is past never reads as on it or inside it (round 2 of the live-architecture review,
expert R, section 2).

A worked-out value (the oxygen in its other unit, the NH₃-N) is judged UNROUNDED (`Reading.exact`; the audit of
2026-11-19, F3: the safe side, and it stays) and shown rounded to its parameter's decimals. A true 59.988221 % of
saturation is critical against a limit of 60.0 and is shown 60.0, so a sentence that set the shown value beside the
bound read "O₂ (%) 60.0 < critical limit 60.0". `value_past` (farm/templatetags/water.py) is the one rule for those
sentences: the shown value when it already reads past the bound, else the exact value with the fewest extra decimals that
do (at most `EXTRA_DECIMALS`; past that, cut toward the side it is on). It never judges: its callers hand it the bound
the judgement named (`evaluate.crossed`). The cards' own sentences are held to it in monitoring/tests/test_bound_text.py."""
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal as D
from types import SimpleNamespace

from django.test import SimpleTestCase
from django.utils import timezone, translation

from ..templatetags.water import EXTRA_DECIMALS, value_past, water_value
from ..water import parameters, read
from ..water.evaluate import Status, judge
from .test_water import WaterTestCase

BOUNDS = ('critical_low', 'warning_low', 'warning_high', 'critical_high')
NOW = timezone.now()


def worked_out(code, exact):
    """A worked-out Reading as read.Context makes one: its `value` quantized (half-even) to the parameter's decimals, its
    `exact` as it was worked out."""
    parameter = parameters.get(code)
    observation = read.Observation(SimpleNamespace(name='Middle', kind='middle'), NOW, read.Origin.MANUAL, {})
    exact = D(exact)
    return read.Reading(parameter, exact.quantize(parameter.step), observation, True, exact=exact)


def row_of(**bounds):
    values = {name: None for name in BOUNDS}
    values.update({name: D(str(bound)) for name, bound in bounds.items()})
    return SimpleNamespace(**values)


def judged(reading, row):
    """The reading judged as `Context.judge` does: its unrounded value against the row."""
    reading.limits = [row]
    reading.judged = reading.status = judge(reading.judged_value, row)
    return reading


def decimals_of(shown):
    return len(shown.split('.')[1]) if '.' in shown else 0


class ValuePastTests(SimpleTestCase):
    def shown(self, code, exact, bound, below):
        return value_past(worked_out(code, exact), D(str(bound)), below)

    def test_the_review_example_reads_past_its_bound(self):
        """7.07 mg/L at 8.2 °C, 0 ‰, 1 atm is 59.988221 % of saturation: critical against 60.0, and shown 60.0."""
        reading = worked_out('oxygen_saturation_pct', '59.988221')
        self.assertEqual(water_value(reading.value, reading.code), '60.0')                 # the rounded value, as before
        self.assertEqual(value_past(reading, D('60.0'), True), '59.99')

    def test_a_high_bound_the_same_way(self):
        self.assertEqual(self.shown('oxygen_saturation_pct', '110.012', '110.0', False), '110.01')
        self.assertEqual(self.shown('nh3_n_mg_l', '0.010340', '0.0103', False), '0.01034')

    def test_the_fewest_extra_decimals_that_read_past(self):
        # one more decimal would round to the bound again: 59.996 -> 60.00
        self.assertEqual(self.shown('oxygen_saturation_pct', '59.996', '60.0', True), '59.996')
        self.assertEqual(self.shown('oxygen_saturation_pct', '59.9951', '60.0', True), '59.995')
        self.assertEqual(self.shown('oxygen_saturation_pct', '59.96', '60.0', True), '59.96')
        self.assertEqual(self.shown('oxygen_saturation_pct', '110.04', '110.0', False), '110.04')

    def test_a_midpoint_the_stored_value_rounded_onto_the_bound(self):
        """59.95 is the midpoint of 59.9 and 60.0: the stored value rounds half to even, up to 60.0, the bound."""
        reading = worked_out('oxygen_saturation_pct', '59.95')
        self.assertEqual(reading.value, D('60.0'))
        self.assertEqual(value_past(reading, D('60.0'), True), '59.95')
        # and above a bound, where half to even rounds 60.05 down onto 60.0 while half up would have said 60.1
        reading = worked_out('oxygen_saturation_pct', '60.05')
        self.assertEqual(reading.value, D('60.0'))
        self.assertEqual(value_past(reading, D('60.0'), False), '60.05')

    def test_past_the_cap_it_is_cut_toward_the_side_it_is_on_never_rounded_onto_the_bound(self):
        # 59.99999999 would round to 60.0000 at the cap (four decimals): cut, it is still below
        self.assertEqual(self.shown('oxygen_saturation_pct', '59.99999999', '60.0', True), '59.9999')
        self.assertEqual(self.shown('oxygen_saturation_pct', '60.00000001', '60.0', False), '60.0001')
        self.assertEqual(self.shown('nh3_n_mg_l', '0.0103000000001', '0.0103', False), '0.0103001')

    def test_every_parameter_cuts_on_the_side_it_is_on_where_the_cap_is_reached(self):
        """Within a ten-millionth of a step of a bound, rounding at any decimal up to the cap lands on the bound."""
        for parameter in parameters.LIMITED:
            bound = D('3') * parameter.step
            for below in (True, False):
                exact = bound + (-1 if below else 1) * parameter.step * D('0.0000001')
                shown = value_past(worked_out(parameter.code, exact), bound, below)
                cut = exact.quantize(D(1).scaleb(-decimals_of(shown)), rounding=ROUND_FLOOR if below else ROUND_CEILING)
                with self.subTest(code=parameter.code, below=below):
                    self.assertEqual((D(shown), decimals_of(shown)), (cut, parameter.decimals + EXTRA_DECIMALS))
                    self.assertTrue(D(shown) < bound if below else D(shown) > bound)

    def test_a_value_that_already_reads_past_is_shown_as_it_always_was(self):
        reading = worked_out('oxygen_saturation_pct', '59.94')
        self.assertEqual(value_past(reading, D('60.0'), True), '59.9')
        self.assertEqual(value_past(reading, D('60.0'), True), water_value(reading.value, reading.code))

    def test_a_measured_value_is_judged_as_entered_so_it_is_shown_as_entered(self):
        observation = read.Observation(SimpleNamespace(name='Middle', kind='middle'), NOW, read.Origin.MANUAL, {})
        reading = read.Reading(parameters.get('oxygen_saturation_pct'), D('60.0'), observation)
        self.assertIsNone(reading.exact)
        self.assertEqual(value_past(reading, D('60.0'), True), '60.0')

    def test_a_value_the_bound_does_not_name_is_never_reshaped(self):
        """Never a judgement: where the exact value is not past the bound it is given, the shown value stands."""
        self.assertEqual(self.shown('oxygen_saturation_pct', '60.004', '60.0', True), '60.0')
        self.assertEqual(self.shown('oxygen_saturation_pct', '59.996', '60.0', False), '60.0')

    def test_in_norwegian_and_turkish_the_decimal_sign_is_theirs(self):
        for language in ('nb', 'tr'):
            with self.subTest(language=language), translation.override(language):
                self.assertEqual(self.shown('oxygen_saturation_pct', '59.988221', '60.0', True), '59,99')

    def test_the_cap_is_three_extra_decimals(self):
        self.assertEqual(EXTRA_DECIMALS, 3)


class JudgedThroughTests(WaterTestCase):
    """The sentence a page keeps beside an oxygen judged through its other unit ("Judged as … %. … Limit: …") says the
    value as the card's reason does."""

    def test_the_note_of_a_value_judged_as_its_other_unit_reads_past_the_limit_it_names(self):
        self.stock()
        self.limit('oxygen_saturation_pct', critical_low=60, warning_low=70)
        self.sample(hours=1, oxygen_mg_l='7.07', temperature_c='8.2')              # 59.988221 % at 8.2 °C, 0 ‰, 1 atm
        reading = self.unit_water().get('oxygen_mg_l')
        self.assertEqual(reading.judged, Status.CRITICAL)
        self.assertEqual((reading.through.value, reading.through.exact.quantize(D('0.000001'))),
                         (D('60.0'), D('59.988221')))
        self.assertIn('Judged as 59.99 %.', reading.note)
        self.assertNotIn('Judged as 60.0 %', reading.note)
        self.assertIn('Limit: Atlantic salmon: critical below 60.0, warning below 70.0.', reading.note)
        # the judgement is the unrounded value's, as before
        source, name, bound = read.crossed(reading)
        self.assertEqual((source.code, name, bound), ('oxygen_saturation_pct', 'critical_low', D('60.0')))

    def test_a_value_clear_of_every_bound_reads_as_it_did(self):
        self.stock()
        self.limit('oxygen_saturation_pct', critical_low=60, warning_low=70)
        self.sample(hours=1, oxygen_mg_l='9', temperature_c='8.2')                  # about 76 %: inside the bounds
        reading = self.unit_water().get('oxygen_mg_l')
        self.assertEqual(reading.judged, Status.OK)
        self.assertRegex(reading.note, r'Judged as \d\d\.\d %\.')
