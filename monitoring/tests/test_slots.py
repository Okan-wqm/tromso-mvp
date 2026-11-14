"""The slot rule of a monitoring wall of fitted cards (monitoring/cards/slots.py) against the vectors it shares with the
browser's rule (frontend/wall/slots.ts; frontend/wall/slots.test.ts runs the same file), the screens the design
names, and the rule's own properties on random screens."""
import json
import random
from pathlib import Path

from django.test import SimpleTestCase

from ..cards import builtin, slots

VECTORS = json.loads(Path(__file__).with_name('slot_vectors.json').read_text(encoding='utf-8'))
WIDE = ('3440x1440', '5120x1440', '2560x1440', '3840x2160', '1920x1080')


def named(name):
    return next(case for case in VECTORS['cases'] if case['name'] == name)


def answer(case):
    return slots.slots(case['count'], case['width'], case['height'], case['gap'], case['mw'], case['mh'], case['min_u'],
                       case['pad_x'], case['pad_y'])


class SlotVectorTests(SimpleTestCase):
    def test_the_vectors_shared_with_the_browsers_rule(self):
        self.assertEqual(VECTORS['floor'], slots.FLOOR)
        self.assertGreaterEqual(len(VECTORS['cases']), 50)
        for case in VECTORS['cases']:
            with self.subTest(case=case['name']):
                found = answer(case)
                self.assertEqual((found.cols, found.rows, found.pages), (case['cols'], case['rows'], case['pages']))
                self.assertAlmostEqual(found.u, case['u'], places=5)
                self.assertEqual(slots.roomy(found, case['width'], case['height'], case['gap'], case['mw'], case['mh'],
                                             case['pad_x'], case['pad_y']), case['roomy'])

    def test_the_small_cases_are_of_the_built_in_small_templates_measure(self):
        width, height = builtin.SMALL_MEASURE
        small = [case for case in VECTORS['cases'] if case['name'].startswith('small ')]
        self.assertTrue(small)
        self.assertEqual({(case['mw'], case['mh']) for case in small}, {(width, height)})

    def test_the_screens_the_design_names(self):
        """Owner decision 8: three big cards on 3440x1440, four on 5120x1440, two on a 16:9 screen; twenty small cards
        are one page on every wide screen and never under the floor; a low screen turns pages rather than shrink."""
        big = [named(f'big x 20 on {screen}') for screen in WIDE]
        self.assertEqual([case['cols'] * case['rows'] for case in big], [3, 4, 2, 2, 2])
        self.assertEqual({case['rows'] for case in big}, {1})                    # full height
        for screen in WIDE:
            with self.subTest(screen=screen):
                small = named(f'small x 20 on {screen}')
                self.assertEqual(small['pages'], 1)
                self.assertGreaterEqual(small['u'], slots.FLOOR)
        low = named('small x 20 on 1280x720')
        self.assertGreater(low['pages'], 1)
        self.assertGreaterEqual(low['u'], slots.FLOOR)


class SlotRuleTests(SimpleTestCase):
    def test_every_card_has_a_cell_and_a_wall_turns_pages_rather_than_shrink_the_type(self):
        draw = random.Random(20261113)
        for _round in range(400):
            count = draw.randint(1, 220)
            width, height, gap = draw.uniform(600, 5600), draw.uniform(300, 2500), draw.uniform(0, 14)
            mw, mh = (31, 10) if draw.random() < 0.5 else (draw.randint(12, 64), draw.randint(6, 64))
            pad_x, pad_y = draw.uniform(0, 40), draw.uniform(0, 20)
            found = slots.slots(count, width, height, gap, mw, mh, slots.FLOOR, pad_x, pad_y)
            where = dict(count=count, width=width, height=height, gap=gap, mw=mw, mh=mh, pad_x=pad_x, pad_y=pad_y,
                         found=found)
            cells = found.cols * found.rows
            self.assertGreaterEqual(cells * found.pages, count, where)             # no card without a cell
            self.assertLess((found.pages - 1) * cells, count, where)               # no page without a card
            if found.pages > 1:
                self.assertGreaterEqual(found.u, slots.FLOOR - 1e-6, where)        # paged, never shrunk
                # ... and only when no grid that holds every card gives a unit that can be read
                for cols in range(1, slots.MAX_COLS + 1):
                    for rows in range(-(-count // cols), slots.MAX_ROWS + 1):
                        room = (height - (rows - 1) * gap) / rows
                        unit = min(((width - (cols - 1) * gap) / cols - pad_x) / mw, (room - pad_y) / mh)
                        self.assertLess(unit, slots.FLOOR, (where, cols, rows))

    def test_one_page_takes_the_grid_of_the_largest_unit(self):
        found = slots.slots(20, 3400, 1300, 8, 31, 10)
        best = max(min((3400 - (cols - 1) * 8) / cols / 31, (1300 - (rows - 1) * 8) / rows / 10)
                   for cols in range(1, 17) for rows in range(1, 13) if cols * rows >= 20)
        self.assertAlmostEqual(found.u, best)
        self.assertEqual(found.pages, 1)

    def test_no_card_and_a_window_too_small_still_answer(self):
        self.assertEqual(slots.slots(0, 1900, 900, 8, 31, 10).pages, 1)
        tiny = slots.slots(8, 200, 100, 6, 31, 10)
        self.assertGreaterEqual(tiny.cols * tiny.rows * tiny.pages, 8)
