"""The Small card and the screen's view (owner decision 7, 2026-11-12): `mode=small` draws EVERY card of the screen as
the built-in Small template, whatever the rules and the board say; the card is fitted (its template's measure), says
its state, the first reason in short with how many more, the oxygen with its saturation, the temperature, the pH, the
calculated CO₂ and the pH window; an old value is never silent; a chart that cannot be worked out says why; and what
the old cards said is still reachable (every reason, the withdrawal, which template and why, the flip link)."""
import re
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import translation

from farm.handling.withdrawal import WithdrawalBlock
from farm.templatetags.water import water_value
from farm.water import calculation, read as water_read

from .. import read
from ..cards import builtin, catalogue
from ..models import CardTemplateAssignment, MonitorBoard, MonitorBoardUnit
from . import MonitoringCase
from .golden import Tree

PAGE, CARDS = reverse('monitoring:monitor'), reverse('monitoring:cards')
SMALL = {'mode': 'small'}
# What one small card may weigh in the page, in bytes (a wall of 200 is then about 1 MB before compression): measured
# 5.0 to 5.6 KB on the cards of these tests, 2026-11-13 (5.3 to 6.1 KB on a copy of the development data, in Turkish,
# 2026-11-15). Raise it only with a reason; a card that grows is a wall that slows.
SMALL_CARD_BYTES = 6200


def card_of(html, unit):
    return next(node for node in Tree(html).root.walk() if node.attrs.get('data-key') == f'card:{unit.pk}')


def text(node):
    return ' '.join(node.text().split())


def nodes(node, name):
    return [each for each in node.walk() if name in each.classes]


def source(html, unit):
    return re.search(rf'<article[^>]*card:{unit.pk}.*?</article>', html, re.S).group(0)


class SmallCase(MonitoringCase):
    def setUp(self):
        super().setUp()
        self.limit('oxygen_mg_l', critical_low=6, warning_low=7)
        self.limit('temperature_c', warning_high=15, critical_high=18)
        self.limit('ph', critical_low='6.0', warning_low='6.5', warning_high='8.5')
        self.limit('co2_mg_l', warning_high=10, critical_high=15)
        self.limit('nh3_n_mg_l', warning_high='0.0100', critical_high='0.0200')
        self.limit('alkalinity_mg_l', warning_low=70, warning_high=150)
        self.limit('tan_mg_l', warning_high=1, critical_high=2)           # (a value with no limit is never OK: "No limit")

    def good_water(self, unit=None, hours=1, **values):
        """A sample an hour ago with every value the chart needs, all inside their limits but for `values`. (T-02's
        temperature is the worked example's own, 13.2 °C measured now: a test that needs a value past its limit uses
        the oxygen or the pH.)"""
        good = dict(temperature_c='13.2', oxygen_mg_l='8.1', ph='7.2', alkalinity_mg_l='95', tan_mg_l='0.5')
        self.sample(unit or self.t2, hours=hours, **{**good, **values})

    def reasons(self, unit):
        """Every reason of the unit's small card, as the read gives them."""
        return [str(each) for each in read.cards([unit], self.reader, read.resolve.Choice(view=builtin.SMALL))[0]
                .state.reasons]

    def page(self, **query):
        response = self.client.get(PAGE, {**SMALL, **query})
        self.assertEqual(response.status_code, 200)
        return response.content.decode()


class ViewTests(SmallCase):
    def test_the_view_draws_every_card_small_whatever_the_rules_say(self):
        CardTemplateAssignment.objects.create(template_id=builtin.DETAILED, unit=self.t1)
        plain = self.client.get(PAGE).content.decode()
        self.assertEqual(card_of(plain, self.t1).attrs['data-template'], str(builtin.DETAILED))     # the unit's rule
        html = self.page()
        for unit in (self.t1, self.t2):
            card = card_of(html, unit)
            self.assertEqual(card.attrs['data-template'], str(builtin.SMALL))
            self.assertEqual(card.classes[:5], ['monitor-card', f'monitor-{card.attrs["data-state"]}', 'is-fit',
                                                'mw-31', 'mh-10'])
            self.assertEqual([each.classes for each in card.walk() if 'card-grid' in each.classes], [['card-grid', 'gr-5']])
        # which template draws the card and why is still said, in the name's title
        named = next(each for each in card_of(html, self.t1).walk() if each.tag == 'p' and each.attrs.get('title'))
        self.assertIn('Template: Small · the view chosen on this screen', named.attrs['title'])

    def test_on_a_board_too_and_the_boards_own_cards_without_it(self):
        board = MonitorBoard.objects.create(name='Hall A', default_template_id=builtin.DETAILED)
        for unit in (self.t1, self.t2):
            MonitorBoardUnit.objects.create(board=board, unit=unit, template_id=builtin.DETAILED)
        own = self.client.get(PAGE, {'board': str(board.pk)}).content.decode()
        self.assertEqual(card_of(own, self.t2).attrs['data-template'], str(builtin.DETAILED))
        small = self.page(board=str(board.pk))
        self.assertEqual(card_of(small, self.t2).attrs['data-template'], str(builtin.SMALL))
        fragment = self.client.get(CARDS, {**SMALL, 'board': str(board.pk)}).content.decode()
        self.assertEqual(card_of(fragment, self.t2).attrs['data-template'], str(builtin.SMALL))

    def test_the_flip_link_shows_the_whole_card_and_comes_back(self):
        html = self.page()
        link = next(each for each in card_of(html, self.t2).walk() if 'monitor-flip' in each.classes)
        self.assertEqual((text(link), link.attrs['id']), ('Detailed', f'flip-{self.t2.pk}'))
        self.assertEqual(link.attrs['href'], f'{PAGE}?flip={self.t2.pk}&mode=small')
        self.assertEqual(link.attrs['data-poll-url'], f'{CARDS}?flip={self.t2.pk}&mode=small')
        flipped = self.client.get(link.attrs['href']).content.decode()
        whole = card_of(flipped, self.t2)
        self.assertEqual(whole.attrs['data-template'], str(builtin.DETAILED))
        self.assertNotIn('is-fit', whole.classes)
        back = next(each for each in whole.walk() if 'monitor-flip' in each.classes)
        self.assertEqual((text(back), back.attrs['href']), ('Small', f'{PAGE}?mode=small'))
        self.assertEqual(card_of(flipped, self.t1).attrs['data-template'], str(builtin.SMALL))      # the others stay

    def test_the_toolbar_offers_small_and_the_old_cards_are_as_they_were(self):
        html = self.page()
        self.assertIn('<option value="small" selected>Small</option>', html)
        plain = self.client.get(PAGE).content.decode()
        self.assertIn('<option value="small">Small</option>', plain)
        self.assertNotIn('is-fit', plain)                                 # Simple flows, as it always did
        self.assertNotIn('is-fit', self.client.get(PAGE, {'mode': 'detailed'}).content.decode())


class SmallCardTests(SmallCase):
    def test_the_four_values_and_the_ph_window(self):
        self.good_water()
        html = self.page()
        card = card_of(html, self.t2)
        # every value is inside its limits: the water gives the card no reason (the worked example's T-02 was weighed 15
        # days ago, a note of its own)
        self.assertEqual((card.attrs['data-state'], self.reasons(self.t2)), ('note', ['Weigh soon']), text(card))
        labels = [text(each) for each in card.walk() if each.tag == 'dt']
        self.assertRegex(labels[0], r'^O₂ · \d\d\.\d %$')                   # the oxygen, with its saturation beside it
        self.assertEqual(labels[1:], ['°C', 'pH', 'CO₂ calc.'])
        figures = [text(each) for each in card.walk() if each.tag == 'b']
        chart = calculation.chart_of(self.t2)
        co2 = water_value(water_read.as_parameter('co2_mg_l', chart.calculation.analysis.co2_mg_l), 'co2_mg_l')
        self.assertEqual(figures, ['8.10', '13.2', '7.20', co2])
        # the full label of each is its title; the line under a figure says how old it is (never cut: a tile is narrow),
        # and its title its status, where it came from and what it was worked out from
        titles = [each.attrs['title'] for each in card.walk() if each.tag == 'dt']
        self.assertTrue(titles[0].startswith('Dissolved oxygen (mg/L O₂) · '))
        self.assertEqual(titles[3], 'Carbon dioxide, calculated (mg/L CO₂)')
        under = nodes(card, 'monitor-roomy')
        self.assertEqual([text(each) for index, each in enumerate(under) if index != 1], ['1 h ago'] * 3)
        self.assertRegex(text(under[1]), r'^(just now|\d+ s ago|\d+ min ago)$')      # the fixture's own temperature
        self.assertRegex(under[0].attrs['title'], r'^OK · .+ · 1 h ago$')
        self.assertEqual(under[3].attrs['title'], 'calculated · 1 h ago · Calculated from the pH, the alkalinity, the '
                                                  'temperature and the salinity. The salinity is assumed: fresh water.')
        # the pH window: a picture drawn by the server, in percentages, its name every number in words
        (window,) = nodes(card, 'monitor-ph-window')
        self.assertEqual((window.tag, window.classes, window.attrs.get('viewbox')), ('svg', ['monitor-ph-window'], None))
        analysis = chart.calculation.analysis
        self.assertEqual(window.attrs['aria-label'],
                         f'pH window, T-02: pH 7.20; CO₂ passes its limit below pH {analysis.co2.ph:.2f}; '
                         f'NH₃ passes its limit above pH {analysis.nh3.ph:.2f}')
        regions = [each.classes[-1] for each in window.walk() if 'chart-region' in each.classes]
        self.assertEqual(regions, ['chart-region-co2', 'chart-region-safe', 'chart-region-nh3'])
        for each in window.walk():
            for name in ('x', 'cx', 'width'):
                if name in each.attrs:
                    self.assertRegex(each.attrs[name], r'^\d+\.\d%$')
        low, high = catalogue.PH_WINDOW
        (mark,) = [each for each in window.walk() if 'chart-water' in each.classes]
        self.assertEqual(mark.attrs['cx'], f'{(7.2 - low) / (high - low) * 100:.1f}%')
        # nothing the Content-Security-Policy would block; the card's one reason stands where a card with none says its
        # fish (that card, OK with its fish line, is G-00 of the golden scenario `small`)
        self.assertNotIn(' style=', source(html, self.t2))
        self.assertTrue(text(nodes(card, 'monitor-reasons')[0]).startswith('Weigh soon'))
        self.assertFalse(nodes(card, 'monitor-card-fish'))

    def test_the_first_reason_in_short_and_how_many_more_and_every_reason_still_there(self):
        self.good_water(oxygen_mg_l='5', ph='5.9')
        card = card_of(self.page(), self.t2)
        self.assertEqual(card.attrs['data-state'], 'critical')
        (reasons,) = nodes(card, 'monitor-reasons')
        first, more = [each for each in reasons.children if not isinstance(each, str)]
        self.assertEqual(first.attrs['title'], 'Dissolved oxygen (mg/L O₂): Critical')
        self.assertTrue(text(first).startswith('O₂ (mg/L) 5.00 · critical limit 6.00'))
        self.assertIn('tw:text-crit-text', first.classes)
        self.assertIn('+1', text(more))
        self.assertEqual(more.attrs['title'], 'pH (NBS scale): Critical')
        # every reason is on the card in full, for a screen reader and a pointer; none is only a count
        for reason in read.cards([self.t2], self.reader, read.resolve.Choice(view=builtin.SMALL))[0].state.reasons:
            self.assertIn(str(reason), text(reasons))
        # the figure past its limit takes the state's shape and tone, and its word under it
        figure = next(each for each in card.walk() if each.tag == 'b' and '5.00' in text(each))
        self.assertIn('tw:text-crit-text', figure.classes)
        self.assertTrue(nodes(figure, 'monitor-shape-critical'))
        self.assertRegex(nodes(card, 'monitor-roomy')[0].attrs['title'], r'^Critical · .+ · 1 h ago')

    def test_a_warning_says_the_warning_bound(self):
        self.good_water(oxygen_mg_l='6.5')
        card = card_of(self.page(), self.t2)
        (reasons,) = nodes(card, 'monitor-reasons')
        self.assertTrue(text(reasons).startswith('O₂ (mg/L) 6.50 · warning limit 7.00'))
        self.assertIn('tw:text-warn-text', [each for each in reasons.children if not isinstance(each, str)][0].classes)

    def test_water_in_the_co2_region_tints_it_and_phase_1_leaves_the_state_alone(self):
        """Phase 1 of the build: the calculated CO₂ is shown, tagged as calculated, and the window shows the water in the
        CO₂ region; the card's state is what the readings say until the calculated CO₂ is a judged value (Phase 2)."""
        self.good_water(ph='6.60')
        card = card_of(self.page(), self.t2)
        (window,) = nodes(card, 'monitor-ph-window')
        self.assertEqual(window.classes, ['monitor-ph-window', 'in-co2', 'is-critical'])
        analysis = calculation.chart_of(self.t2).calculation.analysis
        self.assertGreater(analysis.co2_mg_l, 15)
        self.assertEqual((card.attrs['data-state'], self.reasons(self.t2)), ('note', ['Weigh soon']), text(card))
        figure = [each for each in card.walk() if each.tag == 'b'][3]
        self.assertIn('tw:text-ink-1', figure.classes)                    # shown, not judged: ink, no shape

    def test_an_old_value_says_old_whatever_the_cards_height(self):
        self.sample(self.t2, hours=1, temperature_c='13.2', oxygen_mg_l='8.1', alkalinity_mg_l='95')
        self.sample(self.t2, hours=100, ph='7.4', tan_mg_l='0.5')                    # a pH says something for 72 hours
        card = card_of(self.page(), self.t2)
        labels = [each for each in card.walk() if each.tag == 'dt']
        self.assertEqual([text(each) for each in labels][1:], ['°C', 'pH old', 'CO₂ calc. old'])
        self.assertEqual([bool([node for node in each.walk() if 'data-old' in node.attrs]) for each in labels],
                         [False, False, True, True])
        figures = [each for each in card.walk() if each.tag == 'b']
        self.assertEqual(['tw:italic' in each.classes for each in figures], [False, False, True, True])
        (window,) = nodes(card, 'monitor-ph-window')
        self.assertIn('is-old', window.classes)
        self.assertIn('last known position, old: pH', window.attrs['aria-label'])
        self.assertEqual(text(nodes(card, 'monitor-roomy')[3]), '4 d ago')
        self.assertTrue(nodes(card, 'monitor-roomy')[3].attrs['title'].startswith('calculated · 4 d ago · '))

    def test_a_chart_that_cannot_be_worked_out_says_why_and_draws_nothing(self):
        html = self.page()
        card = card_of(html, self.t1)                                     # T-01 has no sampling point at all
        self.assertFalse(nodes(card, 'monitor-ph-window'))
        (line,) = nodes(card, 'monitor-ph-refused')
        self.assertEqual(text(line), 'The pH window cannot be drawn: no active middle sampling point.')
        self.assertEqual(line.attrs['title'], text(line))
        values = [text(each) for each in card.walk() if each.tag == 'dd' and 'monitor-roomy' not in each.classes]
        self.assertEqual(values, ['no data'] * 4)                         # words, never a dash
        self.assertFalse([each for each in card.walk() if each.tag == 'b'])
        # T-02 has a point and a temperature, and nothing else: the values the chart lacks are named
        partly = card_of(html, self.t2)
        self.assertEqual(text(nodes(partly, 'monitor-ph-refused')[0]),
                         'The pH window cannot be drawn: no value of pH (NBS scale), Alkalinity (mg/L as CaCO₃).')
        self.assertEqual([text(each) for each in partly.walk() if each.tag == 'b'], ['13.2'])
        missing = next(each for each in partly.walk() if each.tag == 'span' and each.attrs.get('title', '').startswith('Not'))
        self.assertEqual(missing.attrs['title'], 'Not worked out: no value of pH (NBS scale), Alkalinity (mg/L as CaCO₃).')

    def test_a_missing_limit_is_never_drawn_as_a_safe_side(self):
        from farm.models import WaterLimit
        WaterLimit.objects.filter(parameter='nh3_n_mg_l').delete()
        self.good_water()
        card = card_of(self.page(), self.t2)
        (window,) = nodes(card, 'monitor-ph-window')
        regions = [each.classes[-1] for each in window.walk() if 'chart-region' in each.classes]
        self.assertEqual(regions, ['chart-region-co2'])                   # no safe stretch without both limits
        self.assertIn('no NH₃ limit for these fish', window.attrs['aria-label'])
        self.assertIn('no NH₃ limit', text(window))

    def test_without_the_water_right_nothing_of_the_water_is_read_or_shown(self):
        self.good_water()
        self.as_person('stock-only', 'view_stockoperation')
        with mock.patch.object(read.water_calculation, 'charts_of') as charts:
            html = self.page()
        charts.assert_not_called()
        card = card_of(html, self.t2)
        self.assertEqual([text(each) for each in nodes(card, 'monitor-hidden')], ['Water: not shown to you'] * 5)
        for figure in ('8.10', '13.2', '7.20'):
            self.assertNotIn(figure, text(card))
        self.assertIn('State from: Fish', source(html, self.t2))

    def test_the_chart_that_cannot_be_read_is_said_on_the_frame_and_the_card_stays(self):
        self.good_water()
        with mock.patch.dict(read.FAILED_AT, clear=True), \
                mock.patch.object(read.water_calculation, 'charts_of', side_effect=RuntimeError('core')), \
                self.assertLogs('monitoring.read', 'ERROR'):
            card = card_of(self.page(), self.t2)
        self.assertEqual(text(nodes(card, 'monitor-failed')[0]), 'Could not be read: Deffeyes chart')
        self.assertEqual([text(each) for each in card.walk() if each.tag == 'b'], ['8.10', '13.2', '7.20'])
        self.assertIn('no data', text(nodes(card, 'w-ph_window')[0]))

    def test_the_withdrawal_and_a_unit_not_in_use_are_on_the_frame(self):
        self.good_water()
        block = WithdrawalBlock(self.fish, self.today + timedelta(days=5), False, 'Treated.', None)
        with mock.patch('farm.handling.withdrawal._providers', [lambda units, day: {self.t2.pk: [block]}]):
            html = self.page(occupancy='all')
        card = card_of(html, self.t2)
        (chip,) = nodes(card, 'monitor-withdrawal')
        self.assertEqual(text(chip), 'Withdrawal')
        self.assertIn(self.fish.code, chip.attrs['title'])
        self.assertEqual(card.attrs['data-state'], 'note')
        self.assertRegex(text(nodes(card, 'monitor-reasons')[0]), r'^Medicine withdrawal in force · until \d\d\.\d\d\.\d{4}')
        pond = card_of(html, self.p1)                                     # P-01 is under maintenance, and empty
        self.assertEqual(text(nodes(pond, 'monitor-status')[0]), 'Maintenance')
        self.assertEqual(pond.attrs['data-state'], 'empty')

    def test_a_small_card_stays_light(self):
        self.good_water(oxygen_mg_l='5', ph='5.9')
        self.good_water(self.t1)
        html = self.page()
        for unit in (self.t1, self.t2):
            self.assertLessEqual(len(source(html, unit).encode()), SMALL_CARD_BYTES, unit.code)


class TemplateTypeTests(SimpleTestCase):
    """The design's rule (owner decision 10: a short type scale): a monitoring template sets type in the card's four
    sizes and two weights and nothing else."""

    def test_the_monitoring_templates_use_only_the_four_sizes_and_two_weights(self):
        sizes = {'tw:text-u-s', 'tw:text-u-m', 'tw:text-u-l', 'tw:text-u-xl'}
        tones = re.compile(r'^tw:text-(ink-[123]|crit-text|warn-text|ok-text|action|inherit|left|right|center)$')
        used = set()
        for path in sorted((Path(settings.BASE_DIR) / 'templates' / 'monitoring').rglob('*.html')):
            for name in re.findall(r'(?<![\w-])tw:(?:[a-z]+:)*((?:text|font|leading|tracking)-[\w\[\]./%-]+)', path.read_text(encoding='utf-8')):
                name = f'tw:{name}'
                used.add(name)
                with self.subTest(template=path.name, utility=name):
                    if name.startswith('tw:text-'):
                        self.assertTrue(name in sizes or tones.match(name), 'a type size outside the card\'s four')
                    elif name.startswith('tw:font-'):
                        self.assertIn(name, {'tw:font-semibold', 'tw:font-normal'})
                    else:
                        self.fail('line height and tracking are the scale\'s own')
        self.assertTrue(sizes <= used)                                    # (the check has something to check)

    def test_the_scale_is_four_steps_of_the_cards_unit(self):
        theme = (Path(settings.BASE_DIR) / 'frontend' / 'tailwind.css').read_text(encoding='utf-8')
        self.assertEqual(dict(re.findall(r'--text-(u-[a-z]+):\s*([\d.]+em);', theme)),
                         {'u-s': '.8em', 'u-m': '1em', 'u-l': '1.25em', 'u-xl': '2.4em'})

    def test_a_tiles_short_label_fits_in_every_language(self):
        for language in ('en', 'nb', 'tr'):
            with translation.override(language):
                for code, label in catalogue.TILE_LABELS.items():
                    with self.subTest(language=language, code=code):
                        self.assertLessEqual(len(str(label)), catalogue.TILE_LABEL_LENGTH, str(label))
                self.assertLessEqual(len(translation.gettext('old')), 6)        # 'pH · old' on the label's one line
        self.assertTrue(set(catalogue.TILE_LABELS) <= set(catalogue.bindable()))
