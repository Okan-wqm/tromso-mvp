"""The edge of a form control is seen: WCAG 1.4.11 asks 3:1 against what is next to it for the boundary that tells a
field is there (the old pale sage gave 1.68 on white). Every theme of the design system (static/css/tokens.css) sets
--line-control, the one token a control draws its edge with, at 3:1 or more against the page and the sheet, and no
style sheet draws a control's edge with another colour."""
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


def themes():
    """{the block's selector: {token: colour}} for every block of tokens.css that sets the control's edge."""
    found = {}
    for selector, body in re.findall(r'([^{}]+)\{([^{}]*)\}', (CSS / 'tokens.css').read_text(encoding='utf-8')):
        tokens = dict(re.findall(r'(--[a-z0-9-]+):\s*(#[0-9A-Fa-f]{6})\s*;', body))
        if '--line-control' in tokens:
            found[selector.strip()] = tokens
    return found


class ControlEdgeTests(SimpleTestCase):
    def test_every_theme_draws_the_control_edge_at_three_to_one(self):
        found = themes()
        self.assertGreaterEqual(len(found), 5)
        for selector, tokens in found.items():
            for ground in ('--surface-canvas', '--surface-sheet'):
                if ground in tokens:
                    with self.subTest(theme=selector, ground=ground):
                        self.assertGreaterEqual(contrast(tokens['--line-control'], tokens[ground]), 3)

    def test_a_control_edge_is_the_control_token(self):
        found = [f'{path.name}:{number}' for path in sorted(CSS.glob('*.css'))
                 for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1)
                 if re.search(r'1\.5px solid var\(--(?!line-control\))', line)]
        self.assertEqual(found, [], 'a control edge uses var(--line-control)')
