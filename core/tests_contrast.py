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


# Tokens v2 (docs/design/system/README.md, Colour): every text and shape pair of the role tokens, in every theme. Text
# (and an icon that carries a label's meaning) needs 4.5:1 (WCAG 1.4.3), a shape or an edge 3:1 (1.4.11).
TEXT, SHAPE = 4.5, 3
AREAS = ('farm', 'water', 'feed', 'stock', 'neutral')
PAIRS = [
    *[(text, ground, TEXT) for text in ('--text-1', '--text-2', '--text-3')
      for ground in ('--surface-sheet', '--surface-canvas', '--surface-sunken')],
    ('--action', '--surface-sheet', TEXT), ('--action', '--surface-canvas', TEXT), ('--action', '--action-tint', TEXT),
    ('--on-primary', '--primary', TEXT), ('--text-on-rail', '--surface-rail', TEXT), ('--brand', '--surface-rail', SHAPE),
    *[(f'--{role}-text', ground, TEXT) for role in ('ok', 'note', 'warn', 'crit', 'stale')
      for ground in (f'--{role}-tint', '--surface-sheet')],
    *[(f'--{role}', '--surface-sheet', SHAPE) for role in ('ok', 'note', 'warn', 'crit', 'stale')],
    ('--on-crit', '--crit', TEXT),
    *[pair for area in AREAS for pair in ((f'--area-{area}', f'--area-{area}-tint', TEXT),
                                          (f'--area-{area}', '--surface-sheet', TEXT),
                                          (f'--area-{area}-rail', '--surface-rail', TEXT))],
]


def hue_and_chroma(colour):
    """(hue in degrees, chroma 0..1: the largest channel less the smallest) of a #rrggbb colour."""
    import colorsys
    r, g, b = (int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
    hue, _lightness, _saturation = colorsys.rgb_to_hls(r, g, b)
    return hue * 360, max(r, g, b) - min(r, g, b)


def hue_gap(a, b):
    gap = abs(hue_and_chroma(a)[0] - hue_and_chroma(b)[0]) % 360
    return min(gap, 360 - gap)


class RoleContrastTests(SimpleTestCase):
    def test_every_text_and_shape_pair_passes_in_every_theme(self):
        found = themes()
        self.assertEqual(len(found), 5)
        for selector, tokens in found.items():
            for front, ground, least in PAIRS:
                with self.subTest(theme=selector, pair=f'{front} on {ground}'):
                    self.assertIn(front, tokens)
                    self.assertIn(ground, tokens)
                    self.assertGreaterEqual(contrast(tokens[front], tokens[ground]), least)

    def test_an_area_hue_is_never_taken_for_a_status(self):
        """The two colour channels never mix (docs/design/system/README.md, Colour): an area hue (navigation, page heads,
        module icons) is a clear colour at least 30 degrees from every status hue (ok, warn, crit) and from the other
        areas. Note and stale have no hue at all (a note is told by its square and its word, stale by its hatch), so no
        area can be read as either, which an earlier proposal's violet 'people' hue next to a violet stale was."""
        for selector, tokens in themes().items():
            areas = [f'--area-{area}' for area in AREAS if area != 'neutral']
            for area in areas:
                with self.subTest(theme=selector, area=area):
                    self.assertGreaterEqual(hue_and_chroma(tokens[area])[1], 0.25)
                    for other in ('--ok', '--warn', '--crit', *[a for a in areas if a != area]):
                        self.assertGreaterEqual(hue_gap(tokens[area], tokens[other]), 30, other)
            for role in ('--note', '--note-text', '--note-tint', '--stale', '--stale-text', '--stale-tint'):
                with self.subTest(theme=selector, role=role):
                    self.assertLess(hue_and_chroma(tokens[role])[1], 0.2)
