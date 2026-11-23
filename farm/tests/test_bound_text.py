"""A value shown beside the bound it is past never reads as on it or inside it (round 2 of the live-architecture review,
expert R, section 2).

A worked-out value (the oxygen in its other unit, the NH₃-N) is judged UNROUNDED (`Reading.exact`; the audit of
2026-11-19, F3: the safe side, and it stays) and shown rounded to its parameter's decimals. A true 59.988221 % of
saturation is critical against a limit of 60.0 and is shown 60.0, so a sentence that set the shown value beside the
bound read "O₂ (%) 60.0 < critical limit 60.0". `value_past` (farm/templatetags/water.py) is the one rule for those
sentences: the shown value when it already reads past the bound, else the exact value with the fewest extra decimals that
do (at most `EXTRA_DECIMALS`; past that, cut toward the side it is on). It never judges: its callers hand it the bound
the judgement named (`evaluate.crossed`). The cards' own sentences are held to it in monitoring/tests/test_bound_text.py."""
import re
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal as D
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone, translation

from alarms import sources as alarm_sources
from monitoring.cards import render
from monitoring.tests import ALL_RIGHTS
from monitoring.tests.golden import Tree

from ..templatetags.stock import percent
from ..templatetags.water import EXTRA_DECIMALS, figure_past, proof_of, reading_figure, value_past, water_value
from ..water import parameters, read
from ..water.evaluate import ALERTS, Status, judge
from .helpers import role
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


# ---- every line that says a bound ------------------------------------------------------------------------------------
UNITS, MONITOR, OVERVIEW = (reverse('farm:production_units'), reverse('monitoring:monitor'),
                            reverse('production_home'))
# What says a bound in a line: "critical below 60.0", "warning limit 70.0", the number after a "<" or a ">".
BOUND_WORDS = re.compile(r'(?:(?:critical|warning) (?:limit|below|above) |[<>] )\d[\d.,]*')
ROUNDED = re.compile(r'(?<![\d.,])60\.0(?!\d)')            # 59.988221 % rounded to its one decimal


def lines_with_the_value_rounded_onto_the_bound(html):
    """The lines of a page that say a bound (a drawer row's limits and notes, a card's reasons, the band's chips, a
    title or an accessible name) and show the value 59.988221 % as 60.0 beside it. The bare figure of a cell or a tile
    is not such a line: it says no bound (it keeps its parameter's decimals, the owner's decision)."""
    lines = []
    for node in Tree(html).root.walk():
        if node.tag in ('li', 'th') and not any(each.tag in ('li', 'ul', 'article', 'table') for each in node.walk()
                                                 if each is not node):
            lines.append(' '.join(node.text().split()))
        lines += [' '.join(node.attrs[name].split()) for name in ('title', 'aria-label') if node.attrs.get(name)]
    return [line for line in lines if BOUND_WORDS.search(line) and ROUNDED.search(BOUND_WORDS.sub('', line))]


# A figure on its own that says 60.0: a cell's or a tile's number ("60.0", "60.0 %", Turkish "%60,0"), the saturation beside
# a tile's label ("O₂ · 60.0 %") or the last words of a title.
ALONE = re.compile(r'(?:^|·\s*)%?\s*60[.,]0\s*%?$')


def direct_text(node):
    """What an element says itself: its own text, not its children's, in one line."""
    return ' '.join(' '.join(each for each in node.children if isinstance(each, str)).split())


def figures_rounded_onto_the_bound(html):
    """The figures a page puts on their own (the owner's decision of 2026-11-22: a value judged past a bound shows the
    decimals that prove it everywhere it is shown) that say 59.988221 % as 60.0: the text of an element, a title or an
    accessible name that is, or ends in, 60.0."""
    found = []
    for node in Tree(html).root.walk():
        if node.tag in ('script', 'style'):
            continue
        found += [text for text in (direct_text(node), *(' '.join(node.attrs[name].split())
                                                         for name in ('title', 'aria-label') if node.attrs.get(name)))
                  if ALONE.search(text)]
    return found


def figures(html):
    """The numbers a page puts on their own, by what an element says itself: '59.99', '76.4', '59.99 %', '7.07'."""
    return [text for text in (direct_text(node) for node in Tree(html).root.walk() if node.tag not in ('script', 'style'))
            if re.fullmatch(r'%?\s*\d[\d.,]*(?:\s*%)?', text)]


class GuardTests(SimpleTestCase):
    def test_the_guard_finds_what_it_is_there_for(self):
        for bad in ('<ul><li>O₂ (%) 60.0 · critical limit 60.0</li></ul>', '<li>O₂ (%) 60.0 &lt; 70.0</li>',
                    '<table><tr><th>O₂ · Atlantic salmon: critical below 60.0 · reads 60.0 (x)</th></tr></table>',
                    '<td title="O₂ (%) 60.0, critical; limits: critical below 60.0">60.0</td>'):
            with self.subTest(bad=bad):
                self.assertEqual(len(lines_with_the_value_rounded_onto_the_bound(bad)), 1)
        for good in ('<ul><li>O₂ (%) 59.99 · critical limit 60.0</li></ul>', '<td>60.0</td>', '<b>60.0 %</b>',
                     '<th>O₂ · critical below 60.0 · reads 59.99 (x)</th>'):
            with self.subTest(good=good):
                self.assertEqual(lines_with_the_value_rounded_onto_the_bound(good), [])

    def test_the_figure_guard_finds_a_figure_on_its_own_that_says_the_rounded_value(self):
        for bad in ('<td class="wq">60.0<span class="wq-note">*</span></td>', '<b>60.0 %</b>', '<b>%60,0</b>',
                    '<span>O₂ · 60.0 %</span>', '<dt title="Dissolved oxygen (mg/L O₂) · 60.0 %">x</dt>',
                    '<td>60,0</td>'):
            with self.subTest(bad=bad):
                self.assertEqual(len(figures_rounded_onto_the_bound(bad)), 1)
        for good in ('<td>59.99</td>', '<b>59.99 %</b>', '<td>160.0</td>', '<td>60.01</td>', '<th>critical below 60.0</th>',
                     '<span>O₂ (%) 59.99 · critical limit 60.0</span>', '<td>55.0</td>', '<script>var a = 60.0</script>'):
            with self.subTest(good=good):
                self.assertEqual(figures_rounded_onto_the_bound(good), [])
        self.assertEqual(figures('<td>59.99<span>*</span></td><b>76.4 %</b><p>words 1.0</p>'), ['59.99', '76.4 %'])


class FarmPages(WaterTestCase):
    """T-01 of the water farm with a critical limit of 60.0 and 70.0 for the oxygen's saturation, and every page that says
    its water: the Production units drawer, the Production overview, the monitoring page in each mode of its cards."""

    def setUp(self):
        super().setUp()
        self.stock()
        self.limit('oxygen_saturation_pct', critical_low=60, warning_low=70)
        self.reader = get_user_model().objects.create_user('reader', 'reader@example.com', 'x')
        self.reader.groups.add(role('reader role', *ALL_RIGHTS))

    def pages(self):
        """The drawer's Water section and the overview (the water keeper's), the monitoring page in each mode of its cards
        (a reader's)."""
        found = {'drawer': self.client.get(UNITS, {'unit': self.t1.pk}).content.decode(),
                 'overview': self.client.get(OVERVIEW).content.decode()}
        self.client.force_login(self.reader)
        for name, query in (('simple', {}), ('small', {'mode': 'small'}), ('big', {'mode': 'big'}),
                            ('wall', {'wall': '1', 'mode': 'small'})):
            found[name] = self.client.get(MONITOR, query).content.decode()
        self.client.force_login(self.user)
        return found

    def assert_no_line_says_the_rounded_value_beside_a_bound(self, said):
        pages = self.pages()
        for name, html in pages.items():
            with self.subTest(page=name):
                self.assertEqual(lines_with_the_value_rounded_onto_the_bound(html), [])
                self.assertEqual(figures_rounded_onto_the_bound(html), [])
                self.assertNotIn(f'{said} 60.0', html)
        for name in ('simple', 'small', 'big', 'wall'):                  # the band's chip, in every mode
            self.assertRegex(pages[name], r'59\.99 &lt; critical limit 60\.0')
        for name in ('small', 'big'):                                    # the card's own reason
            self.assertRegex(pages[name], r'59\.99</span> ?<span[^>]*>· critical limit 60\.0')
        return pages


class NotesBesideTheLimitTests(FarmPages):
    """Review of wip/bound-text, findings 1 and 3: the notes a reading keeps beside the limits that judged it said the
    rounded value ("reads 60.0 …", "last own value 60.0 critical …") where the drawer's row prints them right after
    "critical below 60.0". T-01's worked-out oxygen is 59.988221 % (7.07 mg/L at 8.2 °C, 0 ‰, 1 atm) against a critical
    limit of 60.0: the Production units drawer, the alarm's summary and the monitoring cards (the card's reason, the
    band's chip, the bar's name, every mode) say 59.99 and never 60.0 beside the bound."""

    def test_the_worst_fresh_note_says_the_value_that_decided_the_status(self):
        self.sample(self.loop, hours=3, oxygen_mg_l='7.07', temperature_c='8.2')     # the loop's, fresh: 59.988221 %
        self.sample(hours=1, oxygen_mg_l='9', temperature_c='8.2')                   # the unit's own, newer and fine
        reading = self.unit_water().get('oxygen_saturation_pct')
        self.assertEqual((reading.status, reading.worse.value, reading.worse.exact.quantize(D('0.000001'))),
                         (Status.CRITICAL, D('60.0'), D('59.988221')))
        self.assertIn(' reads 59.99 (', reading.note)
        self.assertNotIn(' reads 60.0', reading.note)
        pages = self.assert_no_line_says_the_rounded_value_beside_a_bound('reads')
        self.assertIn(' reads 59.99 (', pages['drawer'])
        self.assertIn('critical below 60.0, warning below 70.0', pages['drawer'])

    def test_the_last_own_value_note_and_the_alarms_summary_say_the_value_that_keeps_the_level(self):
        self.sample(self.loop, hours=1, oxygen_mg_l='9', temperature_c='8.2')        # the loop's stands in, fresh and fine
        self.sample(hours=30, oxygen_mg_l='7.07', temperature_c='8.2')               # the unit's own, old: 59.988221 %
        reading = self.unit_water().get('oxygen_saturation_pct')
        self.assertEqual((reading.status, reading.last_own.value, reading.last_own.status,
                          reading.last_own.exact.quantize(D('0.000001'))),
                         (Status.CRITICAL, D('60.0'), Status.STALE, D('59.988221')))
        self.assertIn('last own value 59.99 critical on ', reading.note)
        self.assertNotIn('last own value 60.0', reading.note)
        summary = alarm_sources._summary(self.mid1, reading)
        self.assertIn('; last own value 59.99 critical on ', summary)
        self.assertNotIn('last own value 60.0', summary)
        pages = self.assert_no_line_says_the_rounded_value_beside_a_bound('last own value')
        self.assertIn('last own value 59.99 critical on ', pages['drawer'])

    def test_a_note_about_a_value_that_is_not_past_a_worked_out_bound_is_said_as_it_always_was(self):
        """An oxygen measured in mg/L is judged through its % row; its own note says the mg/L as entered."""
        self.sample(self.loop, hours=3, oxygen_mg_l='5', temperature_c='8.2')        # measured 5.00 mg/L: about 42 %
        self.sample(hours=1, oxygen_mg_l='9', temperature_c='8.2')
        reading = self.unit_water().get('oxygen_mg_l')
        self.assertEqual((reading.judged, str(reading.worse.value)), (Status.CRITICAL, '5.00'))
        self.assertIn(' reads 5.00 (', reading.note)


def cell_of(html, label):
    """The figure beside a drawer row's head (the row whose head starts with `label`), as the cell says it itself."""
    for head in (node for node in Tree(html).root.walk()
                 if node.tag == 'th' and ' '.join(node.text().split()).startswith(label)):
        (cell,) = [each for each in head.parent.children if getattr(each, 'tag', '') == 'td']
        return direct_text(cell)
    raise AssertionError(f'no row {label!r}')


class FigureTests(SimpleTestCase):
    """The owner's decision of 2026-11-22 ("show as many decimals as it takes to show it is past"): a value judged past a bound
    shows the decimals that prove it wherever it is shown, not only in a sentence (`reading_figure`, `proof_of`)."""

    def figure(self, code, exact, **bounds):
        return reading_figure(judged(worked_out(code, exact), row_of(**bounds)))

    def test_a_value_judged_past_a_bound_it_rounds_onto_says_the_decimals_that_prove_it(self):
        self.assertEqual(self.figure('oxygen_saturation_pct', '59.988221', critical_low=60, warning_low=70), '59.99')
        self.assertEqual(self.figure('oxygen_saturation_pct', '69.996', critical_low=60, warning_low=70), '69.996')
        self.assertEqual(self.figure('oxygen_saturation_pct', '110.012', warning_high=110, critical_high=120), '110.01')
        self.assertEqual(self.figure('nh3_n_mg_l', '0.010340', warning_high='0.0103', critical_high='0.02'), '0.01034')

    def test_a_value_clearly_past_its_bound_stays_as_it_was(self):
        for code, exact, bounds, said in (('oxygen_saturation_pct', '54.98', dict(critical_low=60, warning_low=70), '55.0'),
                                          ('oxygen_saturation_pct', '59.94', dict(critical_low=60, warning_low=70), '59.9'),
                                          ('oxygen_saturation_pct', '125.04', dict(warning_high=110, critical_high=120),
                                           '125.0'),
                                          ('nh3_n_mg_l', '0.03123', dict(warning_high='0.0103', critical_high='0.02'),
                                           '0.0312')):
            with self.subTest(exact=exact):
                reading = judged(worked_out(code, exact), row_of(**bounds))
                self.assertIn(reading.judged, ALERTS)
                self.assertEqual(reading_figure(reading), said)
                self.assertEqual(reading_figure(reading), water_value(reading.value, reading.code))
                self.assertIsNone(proof_of(reading))

    def test_a_value_inside_its_bounds_or_measured_is_never_reshaped(self):
        self.assertEqual(self.figure('oxygen_saturation_pct', '60.004', critical_low=60), '60.0')    # on the bound: inside
        self.assertEqual(self.figure('oxygen_saturation_pct', '70.004', warning_low=70), '70.0')
        measured = read.Reading(parameters.get('oxygen_saturation_pct'), D('60.0'),
                                read.Observation(SimpleNamespace(name='Middle', kind='middle'), NOW, read.Origin.MANUAL, {}))
        judged(measured, row_of(critical_low=60))
        self.assertEqual((reading_figure(measured), proof_of(measured)), ('60.0', None))
        self.assertEqual(reading_figure(None), '—')

    def test_it_is_judged_past_the_nearest_bound_of_every_row_that_judges_it(self):
        """Two species judge it: the figure proves the value past the nearer of the two bounds, so past both."""
        reading = worked_out('oxygen_saturation_pct', '59.96')
        reading.limits = [row_of(critical_low='60.0'), row_of(critical_low='60.1')]
        reading.judged = Status.CRITICAL
        self.assertEqual(read.past_bound(reading), ('critical_low', D('60.0')))
        self.assertEqual(reading_figure(reading), '59.96')
        reading.limits = [row_of(critical_low='60.1')]
        self.assertEqual((read.past_bound(reading), reading_figure(reading)), (('critical_low', D('60.1')), '60.0'))
        reading.limits = [row_of(critical_low='59.9')]
        self.assertIsNone(read.past_bound(reading))

    def test_the_card_says_it_in_the_figure_and_beside_the_tiles_label(self):
        reading = judged(worked_out('oxygen_saturation_pct', '59.988221'), row_of(critical_low=60, warning_low=70))
        self.assertEqual(render.face(reading, NOW).value, '59.99')
        for language, said in (('en', '59.99 %'), ('nb', '59,99 %'), ('tr', '%59,99')):
            with self.subTest(language=language), translation.override(language):
                self.assertEqual(percent(*proof_of(reading)), said)

    def test_the_decimal_sign_is_the_languages(self):
        reading = judged(worked_out('oxygen_saturation_pct', '59.988221'), row_of(critical_low=60, warning_low=70))
        for language in ('nb', 'tr'):
            with self.subTest(language=language), translation.override(language):
                self.assertEqual((reading_figure(reading), figure_past(reading)), ('59,99', '59,99'))


class FiguresTests(FarmPages):
    """With T-01's own oxygen at 59.988221 % (7.07 mg/L at 8.2 °C, 0 ‰, 1 atm) against a critical limit of 60.0: no place
    that shows it says 60.0 beside "critical below 60.0", or on its own: the drawer's cell, the overview's figure, the
    cards' figure, the tile's saturation beside its label, the alarm's summary; in English, Norwegian and Turkish."""

    def setUp(self):
        super().setUp()
        self.sample(hours=1, oxygen_mg_l='7.07', temperature_c='8.2')

    def texts(self, html):
        return [direct_text(each) for each in Tree(html).root.walk() if each.tag not in ('script', 'style')]

    def says(self, html, number):
        return any(number in text for text in self.texts(html))

    def test_no_place_says_the_rounded_value(self):
        reading = self.unit_water().get('oxygen_saturation_pct')
        self.assertEqual((reading.judged, reading.value, reading.exact.quantize(D('0.000001'))),
                         (Status.CRITICAL, D('60.0'), D('59.988221')))
        self.assertEqual(reading_figure(reading), '59.99')
        pages = self.pages()
        for name, html in pages.items():
            with self.subTest(page=name):
                self.assertEqual(figures_rounded_onto_the_bound(html), [])
                self.assertEqual(lines_with_the_value_rounded_onto_the_bound(html), [])
                self.assertTrue(self.says(html, '59.99'), name)
        self.assertEqual(cell_of(pages['drawer'], 'Oxygen saturation'), '59.99')
        self.assertIn('critical below 60.0, warning below 70.0', pages['drawer'])
        for name in ('small', 'wall'):                                  # the tile's saturation beside its label
            self.assertTrue([text for text in self.texts(pages[name]) if text.endswith('· 59.99 %')], name)
        summary = alarm_sources._summary(self.mid1, reading)
        self.assertIn('Oxygen saturation (% of air saturation) 59.99 (critical)', summary)
        self.assertNotIn('60.0', summary)

    def test_a_value_clearly_past_stays_as_it_was_on_every_page(self):
        self.sample(hours=0.5, oxygen_mg_l='6.48', temperature_c='8.2')           # 54.98 %: shown 55.0, past 60.0 by far
        reading = self.unit_water().get('oxygen_saturation_pct')
        self.assertTrue(D('54.9') < reading.exact < D('55.1'), reading.exact)
        self.assertEqual((reading.value, reading.judged, reading_figure(reading)), (D('55.0'), Status.CRITICAL, '55.0'))
        pages = self.pages()
        self.assertEqual(cell_of(pages['drawer'], 'Oxygen saturation'), '55.0')
        self.assertTrue(self.says(pages['overview'], '55.0'))
        for name in ('simple', 'small', 'big', 'wall'):
            self.assertRegex(pages[name], r'O₂ \(%\) 55\.0 &lt; critical limit 60\.0')
        self.assertIn('Oxygen saturation (% of air saturation) 55.0 (critical)',
                      alarm_sources._summary(self.mid1, reading))

    def test_in_norwegian_and_turkish_the_decimal_comma_is_theirs(self):
        from core.models import Profile
        for language in ('nb', 'tr'):
            for person in (self.user, self.reader):
                Profile.objects.update_or_create(user=person, defaults={'language': language})
            pages = self.pages()
            for name, html in pages.items():
                with self.subTest(language=language, page=name):
                    self.assertEqual(figures_rounded_onto_the_bound(html), [])
                    self.assertTrue(self.says(html, '59,99'))
