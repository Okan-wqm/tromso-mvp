"""A replay page's box is worked out once for the page, not once per figure (the expert panel's decision of 2026-11-08,
before the replay moves into the core): the box reads only the largest DIC and the largest alkalinity of the page's
points (deffeyes.box_of), so the page passes that one point, and every figure is exactly the one the whole extent gave."""
from unittest import mock

from django.test import SimpleTestCase

from farm.water import deffeyes
from sensors import read


def waters(count):
    """A page of different waters (temperature, pH and alkalinity moving), with limits and a target, as the replay has."""
    limits = deffeyes.Limits(nh3_n_mg_l=0.0103, co2_mg_l=15.0, h2s_ug_l=2.0, alkalinity_low_mg_l=50.0,
                             alkalinity_high_mg_l=150.0)
    target = deffeyes.Target(7.5, 120.0)
    return [deffeyes.analyse(deffeyes.Water(10.0 + index * 0.05, 0.2, 6.8 + (index % 13) * 0.04, 60.0 + (index % 7) * 30.0,
                                            tan_mg_l=0.5, total_sulfide_ug_l=1.0), limits, target)
            for index in range(count)] + [None]


class PageBoxTests(SimpleTestCase):
    def test_every_figure_is_the_one_the_whole_extent_gave(self):
        analyses = waters(40)
        extent = [(analysis.dic, analysis.alkalinity_meq) for analysis in analyses if analysis is not None]
        figures, indexes = read.page_figures(analyses)
        expected = [{**deffeyes.figure(analysis, deffeyes.geometry(analysis, extent=extent)), 'point': None}
                    for analysis in analyses if analysis is not None]       # a page's figure leaves its point out
        self.assertEqual(figures, expected)
        self.assertEqual(indexes, list(range(40)) + [None])

    def test_the_page_passes_one_point_for_its_box_not_every_point(self):
        seen = []
        geometry = deffeyes.geometry

        def counting(analysis, *args, extent=(), **kwargs):
            seen.append(len(extent))
            return geometry(analysis, *args, extent=extent, **kwargs)

        with mock.patch.object(deffeyes, 'geometry', counting):
            read.page_figures(waters(40))
        self.assertEqual(len(seen), 40)
        self.assertEqual(set(seen), {1})
