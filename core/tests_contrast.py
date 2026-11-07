"""The edge of a form control is seen: WCAG 1.4.11 asks 3:1 against what is next to it for the boundary that tells a
field is there. The pale sage gave 1.68 on white and 1.47 on mist. Controls draw their edge with one token, --control,
and no style sheet draws a control's edge in sage again."""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

CSS = Path(settings.BASE_DIR) / 'static' / 'css'


def luminance(colour):
    channels = [int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a, b):
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def tokens():
    return dict(re.findall(r'(--[a-z-]+):\s*(#[0-9A-Fa-f]{6})\s*;', (CSS / 'base.css').read_text(encoding='utf-8')))


class ControlEdgeTests(SimpleTestCase):
    def test_the_control_edge_is_three_to_one_on_white_and_on_mist(self):
        found = tokens()
        self.assertIn('--control', found)
        for ground in ('--white', '--mist'):
            self.assertGreaterEqual(contrast(found['--control'], found[ground]), 3, ground)

    def test_no_control_is_drawn_with_the_pale_sage_edge(self):
        found = [f'{path.name}:{number}' for path in sorted(CSS.glob('*.css'))
                 for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1)
                 if '1.5px solid var(--sage)' in line]
        self.assertEqual(found, [], 'a control edge uses var(--control)')
