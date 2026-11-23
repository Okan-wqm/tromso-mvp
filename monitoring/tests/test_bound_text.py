"""The card's short reason never reads as on its bound or inside it (round 2 of the live-architecture review, expert R,
section 2; the one rule is farm.templatetags.water.value_past, held to its own cases in farm/tests/test_bound_text.py).

A worked-out value is judged unrounded (`Reading.exact`, the audit of 2026-11-19, F3: the safe side, never changed
here) and shown at its parameter's decimals, so "O₂ (%) 60.0 < critical limit 60.0" stood on a card whose value was a true
59.988221 %. Every sentence that sets a value beside the bound it is past is checked: the card's reason (small, big, the
wall), the band's chip, the bar's name and, with a real farm, the pages."""
import random
from decimal import ROUND_HALF_UP, Decimal as D
from types import SimpleNamespace

from django.test import SimpleTestCase
from django.urls import reverse

from farm.tests.test_bound_text import BOUNDS, decimals_of, judged, row_of, worked_out
from farm.templatetags.water import EXTRA_DECIMALS, water_value
from farm.water import parameters
from farm.water.evaluate import ALERTS, Status, crossed

from .. import read
from ..cards import render
from . import MonitoringCase
from .test_read import NOW, card, water
from .test_small import card_of, nodes, text

PAGE = reverse('monitoring:monitor')


def number_of(shown):
    """The number a shown text says (English: a point for the decimals, a comma between thousands)."""
    return D(shown.replace(',', ''))


def figure_of(brief):
    """The number a brief's figure ends with."""
    return brief.figure.rsplit(' ', 1)[1]


class NeverInsideItsBoundTests(SimpleTestCase):
    """For every parameter a limit can be set on, whatever its decimals, a value judged past a bound (low or high, warning
    or critical) never has its short reason read on the bound or inside it, and what the text says is the value."""

    # how far past or short of a bound the exact value falls, in steps of the parameter: from a hair to a few steps, and
    # around the midpoints where rounding tips
    OFFSETS = [D(each) for each in (
        '0.0000000001', '0.000001', '0.0001', '0.0009', '0.001', '0.0049', '0.01', '0.049', '0.05', '0.09', '0.1',
        '0.2', '0.25', '0.3', '0.4', '0.45', '0.49', '0.4999', '0.5', '0.5001', '0.51', '0.55', '0.6', '0.75', '0.9',
        '0.99', '0.999', '1', '1.5', '2', '7')]

    def brief_of(self, reading):
        found = read._brief(reading, SimpleNamespace(point=None), False)
        self.assertIsNotNone(found, f'no brief for {reading.code} {reading.exact} against {vars(reading.limits[0])}')
        return found

    def draw_row(self, draw, parameter):
        """A limit row on the parameter's grid with two to four ascending bounds, as the model's checks allow them."""
        names = sorted(draw.sample(BOUNDS, draw.randint(2, 4)), key=BOUNDS.index)
        low = D(str(parameter.low))
        most = int(min(parameter.high - parameter.low, 1000) / parameter.step)
        steps = sorted(draw.sample(range(8, most), len(names)))            # clear of the parameter's floor
        return row_of(**{name: low + parameter.step * step for name, step in zip(names, steps)})

    def test_the_text_never_reads_as_inside_the_bound_it_was_judged_against(self):
        draw = random.Random(20261122)
        met = {}
        for parameter in parameters.LIMITED:
            for _round in range(60):
                row = self.draw_row(draw, parameter)
                name = draw.choice([each for each in BOUNDS if getattr(row, each) is not None])
                bound = getattr(row, name)
                for offset in self.OFFSETS:
                    for sign in (-1, 1):
                        reading = judged(worked_out(parameter.code, bound + sign * offset * parameter.step), row)
                        if reading.judged not in ALERTS:
                            continue
                        with self.subTest(code=parameter.code, exact=str(reading.exact), row=vars(row)):
                            self.check(reading, row)
                        crossing = crossed(reading.judged_value, row)[0]
                        met[parameter.code, crossing] = met.get((parameter.code, crossing), 0) + 1
        # every parameter a limit can be set on was met, past a bound of each of the four kinds
        self.assertEqual({code for code, _name in met}, {parameter.code for parameter in parameters.LIMITED})
        self.assertEqual({name for _code, name in met}, set(BOUNDS))

    def check(self, reading, row):
        brief = self.brief_of(reading)
        name, bound = crossed(reading.judged_value, row)
        shown = figure_of(brief)
        figure, limit = number_of(shown), number_of(brief.limit)
        self.assertEqual((brief.sign, limit), ('<' if name.endswith('low') else '>', bound))
        # the value reads strictly past the bound, on the side it was judged
        self.assertTrue(figure < limit if brief.sign == '<' else figure > limit, f'{brief.sentence} for {reading.exact}')
        # and it is the value: within one unit of the last decimal it shows
        self.assertLessEqual(abs(figure - reading.exact), D(1).scaleb(-decimals_of(shown)))
        # never fewer decimals than the parameter keeps, never more than the cap
        decimals = reading.parameter.decimals
        self.assertTrue(decimals <= decimals_of(shown) <= decimals + EXTRA_DECIMALS, shown)
        past = reading.value < bound if brief.sign == '<' else reading.value > bound
        if past:
            self.assertEqual(shown, water_value(reading.value, reading.code))       # where it read past all along
        else:
            self.assertGreater(decimals_of(shown), decimals)
            if decimals_of(shown) > decimals + 1:                      # the fewest decimals that read past
                fewer = reading.exact.quantize(D(1).scaleb(-(decimals_of(shown) - 1)), rounding=ROUND_HALF_UP)
                self.assertFalse(fewer < bound if brief.sign == '<' else fewer > bound,
                                 f'{brief.sentence} for {reading.exact}: one decimal less read past')

    def test_a_measured_value_is_said_as_entered_and_is_never_on_its_bound(self):
        """A measured value is judged as entered, on its parameter's grid: past a bound it is a step or more past it."""
        draw = random.Random(20261123)
        for parameter in parameters.LIMITED:
            for _round in range(20):
                row = self.draw_row(draw, parameter)
                for name in (each for each in BOUNDS if getattr(row, each) is not None):
                    for steps in range(-3, 4):
                        reading = judged(worked_out(parameter.code, getattr(row, name) + steps * parameter.step), row)
                        reading.exact = None
                        if reading.judged not in ALERTS:
                            continue
                        with self.subTest(code=parameter.code, value=str(reading.value), row=vars(row)):
                            brief = self.brief_of(reading)
                            self.assertEqual(figure_of(brief), water_value(reading.value, reading.code))
                            figure, limit = number_of(figure_of(brief)), number_of(brief.limit)
                            self.assertTrue(figure < limit if brief.sign == '<' else figure > limit, brief.sentence)

    def test_the_judgement_is_the_unrounded_values_still(self):
        """The display never feeds back: the 59.988221 % is critical, as `judge` says it, and stays so after its text."""
        reading = judged(worked_out('oxygen_saturation_pct', '59.988221'), row_of(critical_low='60.0', warning_low='70.0'))
        self.assertEqual((reading.value, reading.judged), (D('60.0'), Status.CRITICAL))
        self.assertEqual(self.brief_of(reading).sentence, 'O₂ (%) 59.99 < critical limit 60.0')
        self.assertEqual((reading.value, reading.exact, reading.judged), (D('60.0'), D('59.988221'), Status.CRITICAL))


class WorkedOutCardTests(SimpleTestCase):
    """On hand-made cards: the card's reason, the band's chip and the bar's name."""

    ROW = dict(critical_low='60.0', warning_low='70.0', warning_high='110.0', critical_high='120.0')

    def worked(self, exact, code='oxygen_saturation_pct', **row):
        return judged(worked_out(code, exact), row_of(**(row or self.ROW)))

    def card_of(self, code, reading):
        return card(unit=SimpleNamespace(code=code, pk=code), water=(water(reading),))

    def test_the_cards_reason_says_the_exact_value_where_the_rounded_one_reads_as_the_bound(self):
        for exact, sentence in (('59.988221', 'O₂ (%) 59.99 < critical limit 60.0'),
                                ('69.97', 'O₂ (%) 69.97 < 70.0'),
                                ('110.03', 'O₂ (%) 110.03 > 110.0'),
                                ('120.012', 'O₂ (%) 120.01 > critical limit 120.0'),
                                ('59.7', 'O₂ (%) 59.7 < critical limit 60.0'),          # reads past already: as it was
                                ('110.4', 'O₂ (%) 110.4 > 110.0')):
            with self.subTest(exact=exact):
                brief = read.brief_of(self.card_of('A', self.worked(exact)).state.reasons[0])
                self.assertEqual(brief.sentence, sentence)

    def test_the_card_shows_the_figure_and_the_bound_as_two_parts(self):
        brief = read.brief_of(self.card_of('A', self.worked('59.988221')).state.reasons[0])
        self.assertEqual((brief.figure, brief.sign, brief.bound, brief.limit, brief.critical),
                         ('O₂ (%) 59.99', '<', 'critical limit 60.0', '60.0', True))

    def test_an_old_value_says_the_same_and_that_it_is_old(self):
        reading = self.worked('59.988221')
        reading.status = Status.STALE
        brief = read.brief_of(self.card_of('A', reading).state.reasons[0])
        self.assertEqual(brief.sentence, 'O₂ (%) 59.99 < critical limit 60.0, no recent data')

    def test_the_band_chip_says_the_worst_of_units_past_the_same_bound_by_their_exact_figures(self):
        """Two units both shown 60.0 % under one critical limit: the chip says the lower of the two, whichever comes first."""
        near, far = self.card_of('A', self.worked('59.99')), self.card_of('B', self.worked('59.97'))
        for cards in ([near, far], [far, near]):
            found = read.band(cards, chips=6, codes=4)
            self.assertEqual([(chip.state, chip.text, len(chip.cards)) for chip in found.chips],
                             [('critical', 'O₂ (%) 59.97 < critical limit 60.0', 2)])
        high_near, high_far = (self.card_of('A', self.worked('120.03')), self.card_of('B', self.worked('120.01')))
        self.assertEqual([chip.text for chip in read.band([high_near, high_far]).chips],
                         ['O₂ (%) 120.03 > critical limit 120.0'])

    def test_the_bars_name_says_the_value_past_the_limit_it_lists(self):
        reading = self.worked('59.988221')
        said = render.bar(render.face(reading, NOW)).sentence
        self.assertEqual(said, 'O₂ (%) 59.99, critical; limits: critical below 60.0, warning below 70.0, '
                               'warning above 110.0, critical above 120.0')

    def test_a_value_inside_its_bounds_or_measured_reads_as_it_did(self):
        ok = self.worked('60.004')                                      # shown 60.0, judged as 60.004: a warning
        self.assertEqual(ok.judged, Status.WARNING)
        said = render.bar(render.face(ok, NOW)).sentence
        self.assertTrue(said.startswith('O₂ (%) 60.0, warning;'), said)                 # a warning past 70.0 only
        clear = self.worked('90.04')
        self.assertEqual(clear.judged, Status.OK)
        self.assertTrue(render.bar(render.face(clear, NOW)).sentence.startswith('O₂ (%) 90.0, ok;'))


class BoundTextPageTests(MonitoringCase):
    """With a real farm: 7.07 mg/L at 8.2 °C, 0 ‰ and 1 atm is 59.988221 % of saturation, judged critical against 60.0."""

    def setUp(self):
        super().setUp()
        self.limit('oxygen_saturation_pct', critical_low=60, warning_low=70)
        self.sample(self.t2, hours=1, temperature_c='8.2', oxygen_mg_l='7.07')

    def cards(self):
        return read.cards([self.t2], self.reader, read.resolve.Choice())

    def test_the_reason_the_chip_and_the_bar_say_59_99(self):
        (found,) = self.cards()
        reading = found.water[0].get('oxygen_mg_l')
        self.assertEqual((reading.judged, reading.through.value), (Status.CRITICAL, D('60.0')))
        self.assertEqual(reading.through.exact.quantize(D('0.000001')), D('59.988221'))
        self.assertEqual(read.brief_of(found.state.reasons[0]).sentence, 'O₂ (%) 59.99 < critical limit 60.0')
        self.assertEqual(read.band([found]).chips[0].text, 'O₂ (%) 59.99 < critical limit 60.0')
        percent = found.water[0].get('oxygen_saturation_pct')
        self.assertTrue(render.bar(render.face(percent, found.now)).sentence.startswith('O₂ (%) 59.99, critical;'))

    def test_every_mode_of_the_page_says_it(self):
        for query in ({}, {'mode': 'small'}, {'mode': 'big'}, {'mode': 'detailed'}, {'wall': '1'},
                      {'wall': '1', 'mode': 'small'}):
            with self.subTest(query=query):
                html = self.client.get(PAGE, {**query, 'full': '1'}).content.decode()
                self.assertIn('O₂ (%) 59.99', html)
                self.assertNotIn('60.0 < critical limit 60.0', html)
                self.assertNotIn('O₂ (%) 60.0 · critical limit 60.0', html)

    def test_the_small_and_the_big_card_name_the_bound_beside_the_figure(self):
        for mode in ('small', 'big'):
            reasons = nodes(card_of(self.client.get(PAGE, {'mode': mode, 'full': '1'}).content.decode(), self.t2), 'monitor-reasons')
            with self.subTest(mode=mode):
                # (the Big card's markup leaves no space before the dot: "5.00· critical limit 6.00" in its golden file)
                self.assertRegex(text(reasons[0]), r'^O₂ \(%\) 59\.99 ?· critical limit 60\.0')
