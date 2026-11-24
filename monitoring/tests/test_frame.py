"""The frame of a card, which no template can remove: the unit's status when it is not in use, the withdrawal as a note
chip (it lasts weeks; it is not an alarm), which template draws the card and why, and a visible line when the stored
template could not be drawn; and the colours a card says anything with, checked against the token table (text at least
4.5:1 on white, a shape or a border that carries meaning at least 3:1; the pale sage never carries meaning), with rules
for forced colours."""
import re
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase
from django.urls import reverse

from farm.handling.withdrawal import WithdrawalBlock

from ..models import CardTemplate, CardTemplateAssignment
from . import MonitoringCase
from .golden import Tree

PAGE = reverse('monitoring:monitor')
CSS = Path(settings.BASE_DIR) / 'static' / 'css'


def card_of(html, unit):
    return next(node for node in Tree(html).root.walk() if node.attrs.get('data-key') == f'card:{unit.pk}')


def text(node):
    return ' '.join(node.text().split())


class FrameTests(MonitoringCase):
    def test_a_unit_not_in_use_says_its_status_on_the_frame_and_its_state_is_unchanged(self):
        html = self.client.get(PAGE, {'full': '1', 'occupancy': 'all'}).content.decode()
        pond = card_of(html, self.p1)                                    # P-01 is under maintenance
        status = next(node for node in pond.walk() if 'monitor-status' in node.classes)
        self.assertEqual(text(status), 'Maintenance')
        self.assertIn('monitor-empty', pond.attrs['class'])
        self.t2.status = 'active'
        self.t2.save()
        active = card_of(self.client.get(PAGE, {'full': '1'}).content.decode(), self.t2)
        self.assertFalse([node for node in active.walk() if 'monitor-status' in node.classes])

    def test_a_withdrawal_is_a_note_chip_not_an_alarm(self):
        block = WithdrawalBlock(self.fish, self.today + timedelta(days=5), False, 'Treated.', None)
        with mock.patch('farm.handling.withdrawal._providers', [lambda units, day: {self.t2.pk: [block]}]):
            card = card_of(self.client.get(PAGE, {'full': '1'}).content.decode(), self.t2)
        chip = next(node for node in card.walk() if node.tag == 'span' and 'badge' in node.classes)
        self.assertIn('badge-note', chip.classes)
        self.assertNotIn('badge-critical', chip.classes)
        self.assertTrue(text(chip).startswith('Withdrawal'))

    def test_the_frame_says_which_template_draws_the_card_and_why(self):
        card = card_of(self.client.get(PAGE, {'full': '1'}).content.decode(), self.t2)
        why = next(node for node in card.walk() if 'monitor-why' in node.classes)
        self.assertEqual(text(why), 'Template: Simple · the rule for every unit')
        detailed = card_of(self.client.get(PAGE, {'full': '1', 'mode': 'detailed'}).content.decode(), self.t2)
        self.assertIn('Detailed · chosen on this page', text(next(node for node in detailed.walk()
                                                                   if 'monitor-why' in node.classes)))

    def test_a_template_that_cannot_be_drawn_says_so_and_the_card_is_drawn_as_detailed(self):
        mine = CardTemplate.objects.create(name='Hand edited', layout={'schema': 1, 'widgets': []})
        CardTemplate.objects.filter(pk=mine.pk).update(layout={'schema': 1, 'widgets': [
            {'id': 'w1', 'type': 'gauge', 'x': 0, 'y': 0, 'w': 3, 'h': 2}]})      # past the validator, as a hand edit
        CardTemplateAssignment.objects.create(template=mine, unit=self.t2)
        with self.assertLogs('monitoring.cards.resolve'):
            card = card_of(self.client.get(PAGE, {'full': '1'}).content.decode(), self.t2)
        error = next(node for node in card.walk() if 'monitor-template-error' in node.classes)
        self.assertIn('Hand edited', text(error))
        self.assertEqual(card.attrs['data-template'], str(mine.pk))
        self.assertTrue([node for node in card.walk() if 'w-tasks' in node.classes])        # Detailed's widgets


# ---- the colours --------------------------------------------------------------------------------------------------
# The design system's themes (static/css/tokens.css): the default block (:root, Industry) and each theme's own.
THEMES = ('industry', 'fjord', 'polarnatt', 'nordlys', 'tang', 'laks')


def tokens(theme='fjord'):
    """The colour tokens in force in `theme`: the :root ones, then the theme's block over them."""
    css = re.sub(r'/\*.*?\*/', '', (CSS / 'tokens.css').read_text(encoding='utf-8'), flags=re.S)
    found = {}
    for selectors, body in re.findall(r'([^{}]+)\{([^{}]*)\}', css):
        names = [each.strip() for each in selectors.split(',')]
        if ':root' in names or f'[data-theme="{theme}"]' in names:
            found.update(re.findall(r'(--[a-z0-9-]+):\s*(#[0-9A-Fa-f]{6})\s*;', body))
    return found


def luminance(colour):
    channels = [int(colour[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(one, two):
    light, dark = sorted((luminance(one), luminance(two)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def declared(css, selector, prop, theme='fjord'):
    """The value of `prop` in the rule whose selector list holds `selector` exactly, resolved through `theme`'s
    tokens."""
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)                     # (a comment is not a selector)
    for selectors, body in re.findall(r'([^{}]+)\{([^{}]*)\}', css):
        if selector in [each.strip() for each in selectors.split(',')]:
            found = re.search(rf'(?:^|;)\s*{re.escape(prop)}\s*:\s*([^;]+)', body)
            if found:
                value = found.group(1).strip()
                token = re.fullmatch(r'var\((--[a-z0-9-]+)\)', value)
                return tokens(theme)[token.group(1)] if token else value
    return None


class ColourTests(SimpleTestCase):
    """In each of the six themes, against the theme's sheet (the card's ground)."""

    def css(self, name):
        return (CSS / name).read_text(encoding='utf-8')

    def test_text_that_says_something_is_at_least_4_5_to_1_on_white(self):
        components, monitor = self.css('components.css'), self.css('monitor.css')
        for css, selector in ((components, '.over-text'), (components, '.warn-text'),
                              (components, 'td.wq-warning'), (components, 'td.wq-critical'),
                              (monitor, '.monitor-critical .monitor-state'), (monitor, '.monitor-warning .monitor-state')):
            for theme in THEMES:
                colour = declared(css, selector, 'color', theme)
                with self.subTest(selector=selector, theme=theme, colour=colour):
                    self.assertGreaterEqual(contrast(colour, tokens(theme)['--surface-sheet']), 4.5)

    def test_a_border_or_dot_that_carries_meaning_is_at_least_3_to_1_and_never_the_hair_line(self):
        components, monitor = self.css('components.css'), self.css('monitor.css')
        for css, selector, prop in ((monitor, '.monitor-critical', 'border-left-color'),
                                    (monitor, '.monitor-warning', 'border-left-color'),
                                    (monitor, '.monitor-blind', 'border-left-color'),
                                    (monitor, '.monitor-note', 'border-left-color'),
                                    (monitor, '.monitor-ok', 'border-left-color'),
                                    (components, '.wq-critical .wq-dot', 'background'),
                                    (components, '.wq-warning .wq-dot', 'background'),
                                    (components, '.wq-ok .wq-dot', 'background')):
            for theme in THEMES:
                colour, theirs = declared(css, selector, prop, theme), tokens(theme)
                with self.subTest(selector=selector, theme=theme, colour=colour):
                    self.assertNotEqual(colour.upper(), theirs['--line-hair'].upper())
                    self.assertGreaterEqual(contrast(colour, theirs['--surface-sheet']), 3)

    def test_forced_colours_keep_the_shapes_the_bands_and_the_state_borders(self):
        monitor = self.css('monitor.css')
        block = re.search(r'@media \(forced-colors: active\) \{(.*?)\n\}', monitor, re.S)
        self.assertIsNotNone(block)
        for selector in ('.monitor-shape', '.monitor-bar-svg .band', '.monitor-bar-svg .marker', '.monitor-card'):
            self.assertIn(selector, block.group(1))

    def test_the_fitted_card_the_band_and_the_ph_window_say_everything_at_4_5_to_1(self):
        """The pairs of text and ground the fitted card, the band and the pH window use (the final mock-up's
        measure/contrast.txt, here in all six themes): the three inks on the sheet, the band's inks on the canvas,
        the state's text on the sheet and on its tint, a border's number on the grey region, on the safe stretch and
        on the critical tint."""
        pairs = (('--text-1', '--surface-sheet'), ('--text-2', '--surface-sheet'), ('--text-3', '--surface-sheet'),
                 ('--crit-text', '--surface-sheet'), ('--warn-text', '--surface-sheet'),
                 ('--text-1', '--surface-canvas'), ('--text-2', '--surface-canvas'), ('--text-3', '--surface-canvas'),
                 ('--crit-text', '--surface-canvas'), ('--warn-text', '--surface-canvas'),
                 ('--text-2', '--surface-sunken'), ('--text-2', '--zone-safe'), ('--crit-text', '--crit-tint'))
        for theme in THEMES:
            theirs = tokens(theme)
            for ink, ground in pairs:
                with self.subTest(theme=theme, ink=ink, ground=ground):
                    self.assertGreaterEqual(contrast(theirs[ink], theirs[ground]), 4.5)

    def test_the_ph_windows_tones_are_the_ones_measured(self):
        """The window's styles name the tokens the pairs above are of, and the mark is ink (never a state's colour)."""
        monitor = self.css('monitor.css')
        for selector, prop, token in (
                ('.monitor-ph-window .chart-name', 'fill', '--text-2'),
                ('.monitor-ph-window .chart-region-co2', 'fill', '--surface-sunken'),
                ('.monitor-ph-window .chart-region-safe', 'fill', '--zone-safe'),
                ('.monitor-ph-window.in-co2.is-critical .chart-region-co2', 'fill', '--crit-tint'),
                ('.monitor-ph-window.in-co2.is-critical .chart-name-co2', 'fill', '--crit-text'),
                ('.monitor-ph-window .chart-water', 'fill', '--text-1')):
            with self.subTest(selector=selector):
                self.assertEqual(declared(monitor, selector, prop), tokens()[token])

    def test_forced_colours_keep_the_ph_windows_regions_and_its_mark(self):
        monitor = self.css('monitor.css')
        block = re.search(r'@media \(forced-colors: active\) \{(.*?)\n\}', monitor, re.S).group(1)
        for selector in ('.monitor-ph-window .chart-region', '.monitor-ph-window .chart-water'):
            self.assertIn(selector, block)
