"""The chart's figure (owner amendment A8): `deffeyes.figure` gives a chart's whole geometry (isolines, regions, borders,
Ω lines, the point, the target, the dosing layer, the simulator, the region names and the notes) as numbers and words a
JSON document holds, and `deffeyes.render` draws the SVG's parts from that figure alone. The server's SVG and the replay's
player draw from this one shape: `draw` is `render` of the figure, and a figure sent through JSON draws the same chart."""
import json

from django.test import SimpleTestCase
from django.utils import translation

from ..water import calculation, deffeyes, dosing
from ..water.deffeyes import Limits, Target, Water, analyse

from .test_deffeyes import default_analysis


def through_json(figure):
    return json.loads(json.dumps(figure))


def numbers(values):
    return all(isinstance(value, float) for value in values)


class FigureTests(SimpleTestCase):
    def cases(self):
        """(name, analysis, geometry arguments): every layer and none, every limit and none, Ω, an extent."""
        yield 'every layer', default_analysis(), {}
        yield 'no limits', analyse(Water(12, 1, 7.0, 80)), {}
        yield 'sea water with calcium', analyse(Water(8, 33, 8.0, 120, tan_mg_l=0.4, calcium_mg_l=400),
                                                Limits(0.01, 10, None, 90, 140), Target(7.8, 130)), {}
        yield 'NH₃ toxic everywhere', analyse(Water(25, 1, 9.0, 120, tan_mg_l=50), Limits(0.0001, 15, 2, 50, 100)), {}
        yield 'some layers', default_analysis(), {'layers': frozenset({'isolines', 'co2'})}
        yield 'an extent', default_analysis(), {'extent': [(9.5, 7.0), (0.5, 0.2)]}

    def test_the_svg_is_drawn_from_the_figure_alone(self):
        for name, analysis, arguments in self.cases():
            with self.subTest(name):
                figure = deffeyes.figure(analysis, deffeyes.geometry(analysis, **arguments))
                self.assertEqual(deffeyes.render(through_json(figure)), deffeyes.draw(analysis, **arguments))

    def test_the_dosing_layer_and_the_simulator_go_through_the_figure_too(self):
        arguments = {'water': Water(12, 1, 7.0, 80, tan_mg_l=0.5, total_sulfide_ug_l=2),
                     'limits': Limits(0.0103, 15, 2, 50, 100), 'target': Target(7.5, 100), 'pressure': 1.0,
                     'layers': deffeyes.ALL_LAYERS, 'chosen': ['nahco3', 'naoh'], 'volume': 1.0,
                     'amounts': {'naoh': 25, 'hcl': 60}, 'plots': False}
        made = calculation.calculate(**arguments)
        self.assertTrue(made.chart.reagent_lines and made.chart.simulator)
        analysis = made.analysis
        start, end = (analysis.dic, analysis.alkalinity_meq), (analysis.target_dic, analysis.target_alkalinity_meq)
        simulator = [(judged.step.dic, judged.step.alkalinity) for judged in made.steps if judged.step.ph is not None]
        shape = deffeyes.geometry(analysis, deffeyes.ALL_LAYERS, dosing.visual(start, end, ['nahco3', 'naoh']), simulator)
        self.assertEqual(deffeyes.render(through_json(deffeyes.figure(analysis, shape))), made.chart)

    def test_the_figure_is_numbers_in_flat_arrays_and_words(self):
        analysis = analyse(Water(8, 33, 8.0, 120, tan_mg_l=0.4, calcium_mg_l=400), Limits(0.01, 10, None, 90, 140),
                           Target(7.8, 130))
        shape = deffeyes.geometry(analysis)
        figure = deffeyes.figure(analysis, shape)
        self.assertEqual(figure, through_json(figure))
        self.assertEqual(figure['box'], [shape.box.dic, shape.box.alkalinity, shape.box.dic_step,
                                         shape.box.alkalinity_step])
        self.assertEqual(figure['point'], [analysis.dic, analysis.alkalinity_meq])
        self.assertEqual(len(figure['isolines']), len(shape.isolines))
        for row, isoline in zip(figure['isolines'], shape.isolines):
            self.assertEqual(row, [isoline.ph, int(isoline.labelled), *isoline.segment[0], *isoline.segment[1]])
        for key, name, points in figure['regions']:
            self.assertEqual(points, [value for point in shape.regions[key] for value in point])
            self.assertTrue(numbers(points) and len(points) % 2 == 0 and isinstance(name, str))
        self.assertEqual({key for key, _name, _points in figure['regions']}, set(shape.regions))
        self.assertEqual({key for key, _points in figure['omega']}, {'calcite', 'aragonite'})
        for _key, points in figure['omega']:
            self.assertTrue(numbers(points) and len(points) % 2 == 0)
        self.assertTrue(all(isinstance(note, str) for note in figure['notes']))

    def test_the_words_are_in_the_active_language(self):
        analysis = default_analysis()
        with translation.override('nb'):
            figure = deffeyes.figure(analysis, deffeyes.geometry(analysis))
            self.assertEqual(deffeyes.render(through_json(figure)), deffeyes.draw(analysis))
        names = {key: name for key, name, _points in figure['regions']}
        self.assertRegex(names['nh3'], r'pH > \d+,\d\d') # the Norwegian decimal comma
