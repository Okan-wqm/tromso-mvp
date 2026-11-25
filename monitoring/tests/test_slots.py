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
            mw, mh = (31, 12) if draw.random() < 0.5 else (draw.randint(12, 64), draw.randint(6, 64))
            pad_x, pad_y = draw.uniform(0, 40), draw.uniform(0, 20)
            found = slots.slots(count, width, height, gap, mw, mh, slots.FLOOR, pad_x, pad_y)
            where = dict(count=count, width=width, height=height, gap=gap, mw=mw, mh=mh, pad_x=pad_x, pad_y=pad_y,
                         found=found)
            cells = found.cols * found.rows
            self.assertGreaterEqual(cells * found.pages, count, where)             # no card without a cell
            self.assertLess((found.pages - 1) * cells, count, where)               # no page without a card
            if found.pages > 1 and found.u < slots.FLOOR - 1e-6:
                # paged, never shrunk: under the floor only one card a page, at the largest unit (a window too small)
                self.assertEqual((found.cols, found.rows, found.pages), (1, 1, count), where)
            if found.pages > 1:
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

    def test_a_legible_unit_no_grid_reaches_gives_one_card_a_page_at_the_largest_unit(self):
        """Review round 2, B3: a board read from farther than its screen allows got the DENSEST grid (4 to 6 px type);
        it gets one card a page, at the largest unit a cell gives."""
        room = named('small x 20 on 1920x1080')
        largest = min((room['width'] - room['pad_x']) / room['mw'], (room['height'] - room['pad_y']) / room['mh'])
        for inches, distance in ((24, 3), (24, 5), (55, 5)):
            least = slots.legible_unit(inches, distance, 1920, 1080)
            self.assertGreater(least, largest)
            found = slots.slots(20, room['width'], room['height'], room['gap'], room['mw'], room['mh'], least,
                                room['pad_x'], room['pad_y'])
            self.assertEqual((found.cols, found.rows, found.pages), (1, 1, 20), (inches, distance))
            self.assertAlmostEqual(found.u, largest)
        draw = random.Random(20261124)
        for _round in range(300):
            count = draw.randint(1, 60)
            width, height, gap = draw.uniform(600, 4600), draw.uniform(300, 2300), draw.uniform(0, 14)
            mw, mh, pad_x, pad_y = draw.randint(12, 63), draw.randint(6, 63), draw.uniform(0, 40), draw.uniform(0, 20)
            least = slots.FLOOR + draw.uniform(0, 200)
            found = slots.slots(count, width, height, gap, mw, mh, least, pad_x, pad_y)
            if found.u < least - 1e-6:
                cell = max(height, mh * slots.FLOOR + pad_y)
                self.assertEqual((found.cols, found.rows, found.pages), (1, 1, count))
                self.assertAlmostEqual(found.u, min((width - pad_x) / mw, (cell - pad_y) / mh))

    def test_no_card_and_a_window_too_small_still_answer(self):
        self.assertEqual(slots.slots(0, 1900, 900, 8, 31, 10).pages, 1)
        tiny = slots.slots(8, 200, 100, 6, 31, 10)
        self.assertGreaterEqual(tiny.cols * tiny.rows * tiny.pages, 8)


class LegibleUnitTests(SimpleTestCase):
    """How large a wall's type must be to be read from where it is watched (slots.legible_unit, CONSENSUS §9)."""

    def test_the_vectors_shared_with_the_browsers_rule(self):
        self.assertGreaterEqual(len(VECTORS['legible']), 10)
        for case in VECTORS['legible']:
            with self.subTest(case=case):
                self.assertAlmostEqual(slots.legible_unit(case['inches'], case['distance_m'], case['screen_w'],
                                                          case['screen_h']), case['u'], places=5)

    def test_the_state_word_and_the_smallest_text_subtend_what_the_standards_ask(self):
        import math
        # 20 arcmin for a state's word; 16 for every other text: the least character height of ANSI/HFES 100 and ISO
        # 9241-303 (review round 2: 15 was under it)
        self.assertEqual((slots.ARCMIN_CRITICAL, slots.ARCMIN_SECONDARY), (20, 16))
        for inches, distance, width, height in ((55, 3, 3840, 2160), (24, 1, 1920, 1080), (65, 5, 1920, 1080)):
            unit = slots.legible_unit(inches, distance, width, height)
            px_mm = inches * 25.4 / math.hypot(width, height)

            def arcmin(font):
                return math.degrees(2 * math.atan(font * slots.CAP * px_mm / 2 / (distance * 1000))) * 60
            self.assertGreaterEqual(arcmin(unit * slots.STEP_STATE), slots.ARCMIN_CRITICAL - 1e-6)
            self.assertGreaterEqual(arcmin(unit * slots.STEP_SMALLEST), slots.ARCMIN_SECONDARY - 1e-6)
            # and not a pixel more than the larger of the two asks (the wall keeps as many cards as it can)
            self.assertTrue(math.isclose(arcmin(unit * slots.STEP_SMALLEST), slots.ARCMIN_SECONDARY, rel_tol=1e-9)
                            or math.isclose(arcmin(unit * slots.STEP_STATE), slots.ARCMIN_CRITICAL, rel_tol=1e-9)
                            or unit == slots.FLOOR)

    def test_the_same_physical_screen_gives_the_same_physical_type_at_any_pixel_ratio(self):
        # a 4K TV whose browser says 1920 x 1080 CSS px (a pixel ratio of 2) gets half the CSS px: the same millimetres
        self.assertAlmostEqual(slots.legible_unit(55, 3, 3840, 2160), 2 * slots.legible_unit(55, 3, 1920, 1080))

    def test_a_farther_wall_needs_larger_type_and_a_board_that_says_nothing_keeps_the_floor(self):
        near, far = slots.legible_unit(55, 2, 1920, 1080), slots.legible_unit(55, 4, 1920, 1080)
        self.assertAlmostEqual(far, 2 * near, places=6)
        for missing in ((None, 3), (55, None), (0, 3)):
            self.assertEqual(slots.legible_unit(*missing, 1920, 1080), slots.FLOOR)


class ReachTests(SimpleTestCase):
    """Whether a board's screen and distance can be met at all (slots.reach): what the board's form refuses or warns of
    (review round 2, B3)."""

    def test_the_reviewers_pairs_on_a_full_hd_screen(self):
        small = builtin.SMALL_MEASURE
        for inches, distance in ((24, 3), (24, 5), (55, 5)):
            with self.subTest(inches=inches, distance=distance):
                found = slots.reach(inches, distance, 1920, 1080, *small)
                self.assertEqual(found.per_page, 0)
                self.assertGreater(found.least, found.most)
                # the farthest distance that works is said, and it does work
                self.assertLess(found.farthest, distance)
                self.assertGreaterEqual(slots.reach(inches, found.farthest, 1920, 1080, *small).per_page, 1)
                self.assertEqual(slots.reach(inches, found.farthest + 0.1, 1920, 1080, *small).per_page, 0)
        three = slots.reach(55, 3, 1920, 1080, *small)
        self.assertEqual(three.per_page, 1)                                   # met, one card a page
        self.assertGreaterEqual(slots.reach(55, 2, 1920, 1080, *small).per_page, 4)

    def test_it_follows_the_wall_and_the_pixel_ratio_cancels_out(self):
        small = builtin.SMALL_MEASURE
        # the wall's own room for one card a page on 1920x1080 (slot_vectors.json, under a band of a sixth at most)
        room = named('small x 20 on 1920x1080')
        self.assertLessEqual(slots.reach(55, 3, 1920, 1080, *small).most,
                             min((room['width'] - room['pad_x']) / small[0], (room['height'] - room['pad_y']) / small[1]))
        # a 4K panel that says 3840 x 2160 and one that says 1920 x 1080 CSS px are the same screen
        for inches, distance in ((55, 3), (24, 3), (65, 5)):
            self.assertEqual(slots.reach(inches, distance, 3840, 2160, *small).per_page,
                             slots.reach(inches, distance, 1920, 1080, *small).per_page)

    def test_no_screen_or_no_distance_is_always_met(self):
        found = slots.reach(None, 3, 1920, 1080, *builtin.SMALL_MEASURE)
        self.assertEqual(found.least, slots.FLOOR)
        self.assertGreater(found.per_page, 2)
        self.assertIsNone(found.farthest)
