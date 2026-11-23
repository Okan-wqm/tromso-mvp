"""The card's picture of a Deffeyes figure (farm/water/deffeyes.py: `close_window`, `full_window`, `picture`): the two
views of owner decision 12. The CLOSE rule is held to the mock-up's own (`closeWindow` of final/chart.mjs) on its 19
waters and its 7 hard cases (close_vectors.json, written by that code), and to what the rule promises on waters it has
never seen (the property tests); the picture is held to the figure: nothing is drawn that the core did not give, every
coordinate is a plain number with a dot, and a number that is printed is the window's real one."""
import json
import random
import re
from pathlib import Path

from django.test import SimpleTestCase
from django.utils import translation

from ..water import chemistry, deffeyes
from ..water.deffeyes import CLOSE, FULL, Limits, Target, Water, analyse

VECTORS = json.loads((Path(__file__).parent / 'close_vectors.json').read_text(encoding='utf-8'))
NUMBER = re.compile(r'^-?\d+(\.\d)?$')


def figure_of(case, **changes):
    """A figure with what the rule reads, from a vector."""
    made = {'box': [*case['box'], 1, 1], 'point': case['point'], 'target': case['target'],
            'boundaries': [[key, '', flat] for key, flat in case['boundaries']]}
    return {**made, **changes}


class CloseVectorTests(SimpleTestCase):
    def test_the_19_waters_and_the_7_hard_cases_give_the_mock_ups_windows(self):
        self.assertEqual(len(VECTORS), 26)
        self.assertEqual([case['name'] for case in VECTORS[19:]],
                         ['edge-lo', 'edge-hi', 'far-co2', 'far+tgt', 'on-co2', 'no-nh3', 'no-bord'])
        for case in VECTORS:
            with self.subTest(case=case['name']):
                found = deffeyes.close_window(figure_of(case), case['band'], case['target_active'])
                for mine, theirs in zip(found.ends, case['window']):
                    self.assertAlmostEqual(mine, theirs, places=8)
                self.assertAlmostEqual(found.zoom, case['zoom'], places=8)
                self.assertEqual(found.full, case['full'])
                for mine, theirs in ((found.co2, case['co2']), (found.nh3, case['nh3'])):
                    if theirs is None:
                        self.assertIsNone(mine)
                    else:
                        self.assertAlmostEqual(mine, theirs, places=8)

    def test_what_the_vectors_say_in_words(self):
        """The cases a reader of REPORT.md knows by name."""
        by_name = {case['name']: deffeyes.close_window(figure_of(case), case['band'], case['target_active'])
                   for case in VECTORS}
        zooms = [by_name[case['name']].zoom for case in VECTORS[:17]]
        self.assertEqual((round(min(zooms), 1), round(max(zooms), 1)), (5.0, 8.2))             # the fresh tanks
        self.assertEqual([round(by_name[name].zoom, 1) for name in ('TG-M01', 'TG-M04')], [2.2, 2.1])   # the sea cages
        self.assertTrue(by_name['far-co2'].full and by_name['far+tgt'].full)                   # close IS full scale
        self.assertAlmostEqual(by_name['no-bord'].zoom, 12.0)                                  # the smallest window
        smallest = by_name['no-bord']
        self.assertAlmostEqual(smallest.dic[1] - smallest.dic[0], deffeyes.CLOSE_MIN)

    def test_the_full_window_is_the_cores_box(self):
        for case in VECTORS:
            found = deffeyes.full_window(figure_of(case))
            self.assertEqual((found.ends, found.zoom, found.full), ((0.0, 6.0, 0.0, 6.0), 1.0, True))
        self.assertEqual(deffeyes.window_of(figure_of(VECTORS[0]), FULL), deffeyes.full_window(figure_of(VECTORS[0])))
        self.assertEqual(deffeyes.window_of(figure_of(VECTORS[0]), CLOSE, VECTORS[0]['band']),
                         deffeyes.close_window(figure_of(VECTORS[0]), VECTORS[0]['band']))


class ClosePropertyTests(SimpleTestCase):
    """What the rule promises, on 2,000 made-up waters: each a vector's borders with the point, the target, the band
    and the box's shape moved (seeded: the same waters at every run)."""

    def waters(self):
        rng = random.Random(20261115)
        for _number in range(2000):
            case = rng.choice(VECTORS)
            box = [rng.choice([6.0, 6.0, 8.0, 12.0]), rng.choice([6.0, 6.0, 10.0])]
            point = [rng.uniform(0.02, box[0] - 0.02), rng.uniform(0.02, box[1] - 0.02)]
            target = [rng.uniform(0.05, box[0] - 0.05), rng.uniform(0.05, box[1] - 0.05)] if rng.random() < 0.5 else None
            boundaries = [[key, '', flat] for key, flat in case['boundaries'] if rng.random() < 0.8]
            low = rng.choice([None, rng.uniform(0.2, 3.0)])
            top = rng.choice([None, (low or 1.0) + rng.uniform(0.2, 2.5)])
            if top is not None:
                top = min(top, box[1])
            figure = {'box': [*box, 1, 1], 'point': point, 'target': target, 'boundaries': boundaries}
            yield figure, (low, top), target is not None and rng.random() < 0.6

    def test_the_rule_keeps_its_promises(self):
        seen = {'full': 0, 'close': 0, 'smallest': 0}
        for figure, band, active in self.waters():
            found = deffeyes.close_window(figure, band, active)
            xa, xb, ya, yb = found.ends
            box_dic, box_alkalinity = figure['box'][:2]
            dic, alkalinity = figure['point']
            with self.subTest(point=figure['point'], band=band, active=active, box=figure['box'][:2]):
                # inside the core's box, never larger than it, in the box's own proportion
                self.assertGreaterEqual(xa, -1e-9)
                self.assertGreaterEqual(ya, -1e-9)
                self.assertLessEqual(xb, box_dic + 1e-9)
                self.assertLessEqual(yb, box_alkalinity + 1e-9)
                self.assertAlmostEqual((xb - xa) / (yb - ya), box_dic / box_alkalinity, places=9)
                # the zoom is 1 (the box itself) or between 1.25 and what the smallest window gives
                self.assertAlmostEqual(found.zoom, box_dic / (xb - xa), places=9)
                if found.full:
                    self.assertEqual((xa, xb, ya, yb, found.zoom), (0.0, box_dic, 0.0, box_alkalinity, 1.0))
                else:
                    self.assertGreater(found.zoom, 1 / deffeyes.CLOSE_FULL - 1e-9)
                    self.assertLessEqual(found.zoom, box_dic / deffeyes.CLOSE_MIN + 1e-9)
                    self.assertGreaterEqual(xb - xa, deffeyes.CLOSE_MIN - 1e-9)
                # the water is in the picture; so are the borders at its alkalinity and the active target
                self.assertTrue(xa - 1e-9 <= dic <= xb + 1e-9 and ya - 1e-9 <= alkalinity <= yb + 1e-9)
                for border in (found.co2, found.nh3):
                    if border is not None and 0 <= border <= box_dic:
                        self.assertTrue(xa - 1e-9 <= border <= xb + 1e-9, border)
                if active:
                    self.assertTrue(xa - 1e-9 <= figure['target'][0] <= xb + 1e-9)
                    self.assertTrue(ya - 1e-9 <= figure['target'][1] <= yb + 1e-9)
                # outside the band, the band's nearer end is in the picture
                low, top = band
                if low is not None and alkalinity < low:
                    self.assertLessEqual(min(low, box_alkalinity), yb + 1e-9)
                if top is not None and alkalinity > top:
                    self.assertGreaterEqual(top, ya - 1e-9)
                # pure: asked again, the same window
                self.assertEqual(deffeyes.close_window(figure, band, active), found)
            seen['full' if found.full else 'close'] += 1
            seen['smallest'] += abs(xb - xa - deffeyes.CLOSE_MIN) < 1e-9
        self.assertGreater(min(seen.values()), 20, seen)                     # every branch of the rule was walked

    def test_between_the_borders_the_window_hangs_on_the_borders_not_on_the_water(self):
        """A new pH moves the point inside a picture that stays put."""
        case = next(case for case in VECTORS if case['name'] == 'HA-R01')
        first = deffeyes.close_window(figure_of(case), case['band'])
        between = first.nh3 + (first.co2 - first.nh3) * 0.2, first.nh3 + (first.co2 - first.nh3) * 0.9
        windows = {deffeyes.close_window(figure_of(case, point=[dic, case['point'][1]]), case['band']).ends
                   for dic in between}
        self.assertEqual(len(windows), 1)
        (ends,) = windows
        for mine, theirs in zip(ends, first.ends):
            self.assertAlmostEqual(mine, theirs, places=9)
        # the two borders sit at a quarter and at three quarters of it
        self.assertAlmostEqual((first.nh3 - first.dic[0]) / (first.dic[1] - first.dic[0]), 0.25)
        self.assertAlmostEqual((first.co2 - first.dic[0]) / (first.dic[1] - first.dic[0]), 0.75)

    def test_a_missing_border_mirrors_the_one_there_is_and_a_missing_band_end_asks_nothing(self):
        case = next(case for case in VECTORS if case['name'] == 'no-nh3')
        found = deffeyes.close_window(figure_of(case), case['band'])
        dic = case['point'][0]
        self.assertAlmostEqual((dic - found.dic[0]) / (found.dic[1] - found.dic[0]), 0.5)      # the water in the middle
        self.assertEqual(deffeyes.close_window(figure_of(case), (None, None)), found)        # inside the band anyway
        low = figure_of(case, point=[0.9, 0.4])                    # beside its CO₂ border, under the band
        self.assertNotEqual(deffeyes.close_window(low, case['band']), deffeyes.close_window(low, (None, None)))


class PictureTests(SimpleTestCase):
    """The picture of a real figure of the core: a fresh water between its two borders, with every limit set."""

    def setUp(self):
        self.limits = Limits(nh3_n_mg_l=0.0125, co2_mg_l=15, alkalinity_low_mg_l=70, alkalinity_high_mg_l=150)
        self.analysis = analyse(Water(11.5, 0, 7.3, 110, tan_mg_l=0.6), self.limits)
        self.figure = deffeyes.card_figure(self.analysis)
        self.band = (70 / chemistry.MG_CACO3_PER_MEQ, 150 / chemistry.MG_CACO3_PER_MEQ)

    def picture(self, view=CLOSE, figure=None, active=False):
        figure = figure or self.figure
        return deffeyes.picture(figure, deffeyes.window_of(figure, view, self.band, active), view, active)

    def test_the_figure_holds_the_cards_layers_and_nothing_of_the_calculators(self):
        self.assertEqual([key for key, _name, _flat in self.figure['regions']], ['co2', 'nh3', 'safe'])
        self.assertEqual(sorted({key for key, _name, _flat in self.figure['boundaries']}), ['co2', 'nh3'])
        self.assertEqual((self.figure['omega'], self.figure['reagent_lines'], self.figure['simulator']), ([], [], []))
        self.assertTrue(self.figure['isolines'])

    def test_both_views_draw_the_same_figure_in_their_own_window(self):
        close, full = self.picture(CLOSE), self.picture(FULL)
        self.assertFalse(close.window.full)
        self.assertTrue(full.window.full)
        self.assertGreater(close.window.zoom, 4)
        for made in (close, full):
            self.assertEqual([key for key, _points in made.regions], ['nh3', 'co2', 'safe'])
            self.assertEqual([key for key, _points in made.bounds], ['co2', 'nh3'])
            self.assertEqual(made.plot, ('3.6', '0.8', '95.9', '94.4'))
            self.assertIsNone(made.dose)
            self.assertIsNone(made.target)
        # the water is where the window puts it: full scale from the origin, close near the middle
        dic, alkalinity = self.figure['point']
        self.assertEqual(full.water, (deffeyes._one(3.6 + dic / 6 * 95.9), deffeyes._one(0.8 + (1 - alkalinity / 6) * 94.4)))
        self.assertTrue(30 < float(close.water[0]) < 75 and 40 < float(close.water[1]) < 60, close.water)
        # the close view says where it is in the whole; the full view is the whole
        self.assertIsNone(full.locator)
        left, top, width, height = (float(value) for value in close.locator)
        self.assertAlmostEqual(left, close.window.dic[0] / 6 * 100, places=1)
        self.assertAlmostEqual(width, max(100 / close.window.zoom, deffeyes.LOCATOR_MARK), places=1)   # never a dash
        self.assertAlmostEqual(top, 100 - close.window.alkalinity[1] / 6 * 100, places=0)

    def test_every_coordinate_is_a_plain_number_with_a_dot_whatever_the_language(self):
        with translation.override('tr'):
            made = self.picture(CLOSE)
        flat = [*made.plot, *made.water, *made.old_at, *made.corner, *made.x_axis, *made.locator]
        flat += [value for _half, *line in made.isolines for value in line]
        flat += [value for line in made.leads for value in line]
        flat += [value for at in made.names.values() for value in at]
        flat += [value for _ph, _decimals, *at in made.ph_names for value in at]
        flat += [value for _number, *at in made.y_ticks for value in at]
        flat += [value for _number, _decimals, *at in made.x_ticks for value in at]
        for _key, points in (*made.regions, *made.bounds):
            flat += [value for pair in points.split(' ') for value in pair.split(',')]
        self.assertGreater(len(flat), 60)
        for value in flat:
            self.assertRegex(value, NUMBER)

    def test_the_ticks_are_the_windows_real_numbers(self):
        for view in (CLOSE, FULL):
            made = self.picture(view)
            xa, xb, ya, yb = made.window.ends
            self.assertGreaterEqual(len(made.x_ticks), 3)
            self.assertGreaterEqual(len(made.y_ticks), 2)
            for dic, _decimals, x, _y in made.x_ticks:
                self.assertTrue(xa < dic < xb)
                self.assertAlmostEqual(float(x), 3.6 + (dic - xa) / (xb - xa) * 95.9, places=1)
            for mg, _x, y in made.y_ticks:
                alkalinity = mg / chemistry.MG_CACO3_PER_MEQ
                self.assertTrue(ya < alkalinity < yb)
                self.assertAlmostEqual(float(y), 0.8 + (1 - (alkalinity - ya) / (yb - ya)) * 94.4 + 1.1, places=1)
        self.assertEqual([mg for mg, _x, _y in self.picture(FULL).y_ticks], [100, 200])
        self.assertEqual([dic for dic, _decimals, _x, _y in self.picture(FULL).x_ticks], [1, 2, 3, 4, 5])

    def test_the_lines_of_equal_ph_are_named_every_quarter_close_and_every_half_at_full_scale(self):
        close, full = self.picture(CLOSE), self.picture(FULL)
        self.assertTrue(all(6 <= ph <= 9 for ph, *_rest in (*close.ph_names, *full.ph_names)))
        self.assertTrue(all((ph * 2) % 1 == 0 for ph, *_rest in full.ph_names))
        self.assertTrue(any((ph * 2) % 1 for ph, *_rest in close.ph_names), close.ph_names)
        self.assertEqual({decimals for ph, decimals, *_at in close.ph_names if (ph * 2) % 1}, {2})
        self.assertGreaterEqual(len(full.ph_names), 3)
        # every line in the picture is a line the core drew, a quarter of a pH apart
        self.assertGreater(len(full.isolines), len(close.isolines))
        self.assertLessEqual(len(full.isolines), 13)

    def test_the_regions_say_what_they_are_inside_themselves(self):
        for view in (CLOSE, FULL):
            made = self.picture(view)
            self.assertEqual(sorted(made.names), ['co2', 'nh3', 'safe'])
            xa, xb, ya, yb = made.window.ends
            rings = {key: deffeyes._pairs(flat) for key, _name, flat in self.figure['regions']}
            for key, (x, y) in made.names.items():
                dic = xa + (float(x) - 3.6) / 95.9 * (xb - xa)
                alkalinity = yb - (float(y) - (1 if key == 'safe' else 0) - 0.8) / 94.4 * (yb - ya)
                self.assertTrue(deffeyes._inside(rings[key], (dic, alkalinity)), (view, key))

    def test_a_missing_limit_draws_no_region_and_no_name_for_it(self):
        analysis = analyse(Water(11.5, 0, 7.3, 110, tan_mg_l=0.6), Limits(co2_mg_l=15))
        figure = deffeyes.card_figure(analysis)
        made = self.picture(CLOSE, figure)
        self.assertEqual([key for key, _points in made.regions], ['co2'])
        self.assertEqual(sorted(made.names), ['co2'])
        self.assertIsNone(made.window.nh3)
        self.assertAlmostEqual((self.figure['point'][0] - made.window.dic[0]) / (made.window.dic[1] - made.window.dic[0]), 0.5)

    def test_the_target_is_drawn_only_when_it_is_active(self):
        analysis = analyse(Water(11.5, 0, 6.6, 110, tan_mg_l=0.6), self.limits, Target(7.2, 110))
        figure = deffeyes.card_figure(analysis)
        self.assertIsNotNone(figure['target'])
        quiet, active = self.picture(CLOSE, figure), self.picture(CLOSE, figure, active=True)
        self.assertEqual((quiet.target, quiet.dose), (None, None))
        self.assertRegex(active.target[0], NUMBER)
        self.assertEqual(active.dose[:2], active.leads[1][:2])                     # from the water
        self.assertTrue(0 <= float(active.target[0]) <= 100 and 0 <= float(active.target[1]) <= 100)

    def test_one_box_for_many_waters_through_the_extent(self):
        """FULL shares one box per screen and water type: the box that holds every water's point."""
        small = analyse(Water(11.5, 0, 7.3, 110, tan_mg_l=0.6), self.limits)
        large = analyse(Water(11.5, 0, 7.3, 420, tan_mg_l=0.6), self.limits)
        own = [deffeyes.card_figure(each)['box'] for each in (small, large)]
        self.assertNotEqual(own[0], own[1])
        extent = [(max(each.dic for each in (small, large)), max(each.alkalinity_meq for each in (small, large)))]
        shared = [deffeyes.card_figure(each, extent)['box'] for each in (small, large)]
        self.assertEqual(shared[0], shared[1])
        self.assertEqual(shared[1], own[1])                                        # no larger than the largest needs

    def test_a_simplified_border_stays_within_a_pixel_of_the_cores(self):
        line = [(float(index), (index % 7) * 0.05 + index * 2.0) for index in range(200)]
        kept = deffeyes._simplify(line, 0.8)
        self.assertLess(len(kept), len(line))
        self.assertEqual((kept[0], kept[-1]), (line[0], line[-1]))
        for x, y in line:                                                          # each dropped point is near the kept line
            near = min(abs((bx - ax) * (ay - y) - (ax - x) * (by - ay)) / ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
                       for (ax, ay), (bx, by) in zip(kept, kept[1:]) if ax <= x <= bx)
            self.assertLessEqual(near, 0.8 + 1e-9)
