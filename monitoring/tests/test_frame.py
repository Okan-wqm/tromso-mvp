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

from ..cards import builtin
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
        html = self.client.get(PAGE, {'occupancy': 'all'}).content.decode()
        pond = card_of(html, self.p1)                                    # P-01 is under maintenance
        status = next(node for node in pond.walk() if 'monitor-status' in node.classes)
        self.assertEqual(text(status), 'Maintenance')
        self.assertIn('monitor-empty', pond.attrs['class'])
        self.t2.status = 'active'
        self.t2.save()
        active = card_of(self.client.get(PAGE).content.decode(), self.t2)
        self.assertFalse([node for node in active.walk() if 'monitor-status' in node.classes])

    def test_a_withdrawal_is_a_note_chip_not_an_alarm(self):
        block = WithdrawalBlock(self.fish, self.today + timedelta(days=5), False, 'Treated.', None)
        with mock.patch('farm.handling.withdrawal._providers', [lambda units, day: {self.t2.pk: [block]}]):
            card = card_of(self.client.get(PAGE).content.decode(), self.t2)
        chip = next(node for node in card.walk() if node.tag == 'span' and 'badge' in node.classes)
        self.assertIn('badge-note', chip.classes)
        self.assertNotIn('badge-critical', chip.classes)
        self.assertTrue(text(chip).startswith('Withdrawal'))

    def test_the_frame_says_which_template_draws_the_card_and_why(self):
        card = card_of(self.client.get(PAGE).content.decode(), self.t2)
        why = next(node for node in card.walk() if 'monitor-why' in node.classes)
        self.assertEqual(text(why), 'Template: Simple · the rule for every unit')
        detailed = card_of(self.client.get(PAGE, {'mode': 'detailed'}).content.decode(), self.t2)
        self.assertIn('Detailed · chosen on this page', text(next(node for node in detailed.walk()
                                                                   if 'monitor-why' in node.classes)))

    def test_a_template_that_cannot_be_drawn_says_so_and_the_card_is_drawn_as_detailed(self):
        mine = CardTemplate.objects.create(name='Hand edited', layout={'schema': 1, 'widgets': []})
        CardTemplate.objects.filter(pk=mine.pk).update(layout={'schema': 1, 'widgets': [
            {'id': 'w1', 'type': 'gauge', 'x': 0, 'y': 0, 'w': 3, 'h': 2}]})      # past the validator, as a hand edit
        CardTemplateAssignment.objects.create(template=mine, unit=self.t2)
        with self.assertLogs('monitoring.cards.resolve'):
            card = card_of(self.client.get(PAGE).content.decode(), self.t2)
        error = next(node for node in card.walk() if 'monitor-template-error' in node.classes)
        self.assertIn('Hand edited', text(error))
        self.assertEqual(card.attrs['data-template'], str(mine.pk))
        self.assertTrue([node for node in card.walk() if 'w-tasks' in node.classes])        # Detailed's widgets


# ---- the colours --------------------------------------------------------------------------------------------------
def tokens():
    found = {}
    for name in ('base.css', 'app.css'):
        found.update(re.findall(r'(--[a-z-]+):\s*(#[0-9A-Fa-f]{6})\s*;', (CSS / name).read_text(encoding='utf-8')))
    return found


def luminance(colour):
    channels = [int(colour[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(one, two):
    light, dark = sorted((luminance(one), luminance(two)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def declared(css, selector, prop):
    """The value of `prop` in the rule whose selector list holds `selector` exactly, resolved through the tokens."""
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)                     # (a comment is not a selector)
    for selectors, body in re.findall(r'([^{}]+)\{([^{}]*)\}', css):
        if selector in [each.strip() for each in selectors.split(',')]:
            found = re.search(rf'(?:^|;)\s*{re.escape(prop)}\s*:\s*([^;]+)', body)
            if found:
                value = found.group(1).strip()
                token = re.fullmatch(r'var\((--[a-z-]+)\)', value)
                return tokens()[token.group(1)] if token else value
    return None


class ColourTests(SimpleTestCase):
    WHITE = '#FFFFFF'

    def css(self, name):
        return (CSS / name).read_text(encoding='utf-8')

    def test_text_that_says_something_is_at_least_4_5_to_1_on_white(self):
        components, monitor = self.css('components.css'), self.css('monitor.css')
        for css, selector in ((components, '.over-text'), (components, '.warn-text'),
                              (components, 'td.wq-warning'), (components, 'td.wq-critical'),
                              (monitor, '.monitor-critical .monitor-state'), (monitor, '.monitor-warning .monitor-state')):
            colour = declared(css, selector, 'color')
            with self.subTest(selector=selector, colour=colour):
                self.assertGreaterEqual(contrast(colour, self.WHITE), 4.5)

    def test_a_border_or_dot_that_carries_meaning_is_at_least_3_to_1_and_never_the_pale_sage(self):
        components, monitor = self.css('components.css'), self.css('monitor.css')
        sage = tokens()['--sage']
        for css, selector, prop in ((monitor, '.monitor-critical', 'border-left-color'),
                                    (monitor, '.monitor-warning', 'border-left-color'),
                                    (monitor, '.monitor-blind', 'border-left-color'),
                                    (monitor, '.monitor-note', 'border-left-color'),
                                    (monitor, '.monitor-ok', 'border-left-color'),
                                    (components, '.wq-critical .wq-dot', 'background'),
                                    (components, '.wq-warning .wq-dot', 'background'),
                                    (components, '.wq-ok .wq-dot', 'background')):
            colour = declared(css, selector, prop)
            with self.subTest(selector=selector, colour=colour):
                self.assertNotEqual(colour.upper(), sage.upper())
                self.assertGreaterEqual(contrast(colour, self.WHITE), 3)

    def test_forced_colours_keep_the_shapes_the_bands_and_the_state_borders(self):
        monitor = self.css('monitor.css')
        block = re.search(r'@media \(forced-colors: active\) \{(.*?)\n\}', monitor, re.S)
        self.assertIsNotNone(block)
        for selector in ('.monitor-shape', '.monitor-bar-svg .band', '.monitor-bar-svg .marker', '.monitor-card'):
            self.assertIn(selector, block.group(1))
