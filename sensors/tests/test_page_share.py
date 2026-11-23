"""A replay page shares one diagram among the frames whose diagram is the same (the expert panel's decision of
2026-11-08: a diagram is shared across frames only after a test proves it invariant). The diagram of a water (its box
fixed by the page) does not read the water's pH, its alkalinity or its oxygen: only where the point sits, which every
frame carries in its own columns. So the page keeps one figure per temperature, salinity, TAN, sulfide and calcium
(with the page's limits and target), its point left out (None)."""
import random

from django.test import SimpleTestCase

from farm.water import deffeyes
from sensors import read

LIMITS = deffeyes.Limits(nh3_n_mg_l=0.0103, co2_mg_l=15.0, h2s_ug_l=2.0, alkalinity_low_mg_l=50.0,
                         alkalinity_high_mg_l=150.0)
TARGET = deffeyes.Target(7.5, 120.0)


def without_point(figure):
    return {**figure, 'point': None}


class InvarianceTests(SimpleTestCase):
    def test_the_diagram_does_not_read_the_ph_the_alkalinity_or_the_oxygen(self):
        """The proof: 300 random pairs of waters equal but for pH, alkalinity and oxygen, fresh to sea water, with and
        without TAN, sulfide, calcium, limits and a target, drawn in one page box: the same diagram but the point."""
        rng = random.Random(20261108)
        for _case in range(300):
            # A conductivity at 25 °C above what the alkalinity's ions need, so the ionic strength (formula 3) is the
            # same for both: the diagram reads the alkalinity only through the equilibria (page_figures keys on them).
            common = dict(temperature_c=rng.uniform(0, 35), salinity_ppt=rng.choice([0.0, 0.2, rng.uniform(0, 45)]),
                          conductivity_25_us_cm=rng.uniform(600, 3000),
                          tan_mg_l=rng.choice([None, rng.uniform(0.01, 8)]),
                          total_sulfide_ug_l=rng.choice([None, rng.uniform(0.1, 400)]),
                          calcium_mg_l=rng.choice([None, rng.uniform(5, 500)]))
            limits = rng.choice([deffeyes.Limits(), LIMITS])
            target = rng.choice([None, TARGET])
            one, two = (deffeyes.analyse(deffeyes.Water(ph=rng.uniform(6.0, 8.8), alkalinity_mg_l=rng.uniform(20, 400),
                                                        oxygen_mg_l=rng.choice([None, 9.0]), **common), limits, target)
                        for _side in range(2))
            extent = [(max(one.dic, two.dic, 0.5), max(one.alkalinity_meq, two.alkalinity_meq))]
            figures = [deffeyes.figure(analysis, deffeyes.geometry(analysis, extent=extent)) for analysis in (one, two)]
            self.assertEqual(without_point(figures[0]), without_point(figures[1]), common)


class SharingTests(SimpleTestCase):
    def page(self):
        """40 frames: 4 temperatures, pH and alkalinity moving every frame."""
        return [deffeyes.analyse(deffeyes.Water(10.0 + (index % 4) * 0.5, 0.2, 6.8 + index * 0.02, 60.0 + index * 3.0,
                                                tan_mg_l=0.5, total_sulfide_ug_l=1.0), LIMITS, TARGET)
                for index in range(40)] + [None]

    def test_one_figure_per_different_diagram_its_point_left_out(self):
        analyses = self.page()
        figures, indexes = read.page_figures(analyses)
        self.assertEqual(len(figures), 4)
        self.assertEqual(indexes[:8], [0, 1, 2, 3, 0, 1, 2, 3])
        self.assertIsNone(indexes[-1])
        points = [(analysis.dic, analysis.alkalinity_meq) for analysis in analyses if analysis is not None]
        extent = [(max(dic for dic, _a in points), max(alkalinity for _d, alkalinity in points))]
        for analysis, index in zip(analyses[:-1], indexes):
            own = deffeyes.figure(analysis, deffeyes.geometry(analysis, extent=extent))
            self.assertEqual(figures[index], without_point(own))
            self.assertIsNone(figures[index]['point'])
