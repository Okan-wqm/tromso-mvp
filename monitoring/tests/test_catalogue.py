"""The widget catalogue (monitoring/cards/catalogue.py, the one truth of what a card can hold) and the one validator of a
card template's layout (monitoring/cards/validate.py): every error code, every warning, the upgrade chain, the option
descriptors (core.schema.Schema, the spike that chose it) and the geometry vectors the TypeScript grid shares."""
import copy
import json
from pathlib import Path
from unittest import mock

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from django.utils import translation

from core.schema import Schema
from farm.models.water_point import PointKind
from farm.water import parameters

from ..cards import catalogue, validate
from ..cards.catalogue import WIDGETS

VECTORS = Path(__file__).with_name('layout_vectors.json')


def widget(id='w1', type='value', x=0, y=0, w=3, h=2, **extra):
    found = {'id': id, 'type': type, 'x': x, 'y': y, 'w': w, 'h': h}
    if type in ('value', 'bar') and 'bind' not in extra:
        found['bind'] = {'parameter': parameters.OXYGEN_MG_L}
    found.update(extra)
    return found


def layout(*widgets, schema=1):
    return {'schema': schema, 'widgets': list(widgets)}


def codes(problems, severity='error'):
    return sorted((problem.code, problem.widget) for problem in problems if problem.severity == severity)


class CatalogueTests(SimpleTestCase):
    def test_the_v1_widgets_and_their_sources(self):
        self.assertEqual(sorted(WIDGETS), ['bar', 'chart', 'deffeyes', 'dosing', 'experiment', 'feeding', 'fish',
                                           'health', 'ph_window', 'points', 'spark', 'stock', 'tasks', 'value',
                                           'water_table'])
        self.assertEqual(WIDGETS['chart'].sources, ('water', 'chart'))          # the Big card's picture of the chart
        self.assertEqual(WIDGETS['value'].sources, ('water',))
        self.assertEqual(WIDGETS['ph_window'].sources, ('water', 'chart'))      # drawn from the unit's chart
        self.assertEqual(WIDGETS['health'].sources, ('events', 'treatments', 'lice'))
        self.assertEqual(WIDGETS['fish'].sources, ('stock',))
        self.assertEqual(WIDGETS['experiment'].sources, ('chips',))
        self.assertFalse(WIDGETS['spark'].enabled)                      # until a bulk series read exists
        self.assertTrue(all(spec.enabled for name, spec in WIDGETS.items() if name != 'spark'))

    def test_every_size_fits_the_grid_and_the_default_lies_within_the_bounds(self):
        for name, spec in WIDGETS.items():
            with self.subTest(widget=name):
                self.assertEqual(spec.type, name)
                self.assertTrue(1 <= spec.min_w <= spec.default_w <= spec.max_w <= catalogue.COLUMNS)
                self.assertTrue(1 <= spec.min_h <= spec.default_h <= spec.max_h)
                self.assertEqual(spec.renderer, f'monitoring/widgets/_{name}.html')

    def test_the_options_are_schemas_without_colour_font_threshold_unit_or_free_text(self):
        for name, spec in WIDGETS.items():
            with self.subTest(widget=name):
                self.assertIsInstance(spec.options, Schema)
                for entry in spec.options.entries:
                    self.assertIn(entry['type'], ('select', 'boolean'))
                    self.assertNotIn(entry['name'], ('colour', 'color', 'font', 'threshold', 'unit', 'text', 'label'))
        self.assertEqual([entry['name'] for entry in WIDGETS['value'].options.entries], ['size'])
        self.assertEqual([entry['name'] for entry in WIDGETS['water_table'].options.entries], ['points', 'parameters'])

    def test_the_catalogue_for_the_designer_is_plain_data_in_the_persons_language(self):
        with translation.override('nb'):
            data = catalogue.as_data()
        self.assertEqual(data['columns'], 12)
        self.assertEqual(json.loads(json.dumps(data)), data)            # json_script can carry it
        value = next(each for each in data['widgets'] if each['type'] == 'value')
        self.assertEqual((value['min_w'], value['min_h'], value['bind'], value['enabled']), (2, 2, 'parameter', True))
        self.assertNotEqual(value['label'], 'Value')                    # translated
        self.assertTrue(data['parameters'])
        self.assertIn(PointKind.MIDDLE, [point['value'] for point in data['points']])


class SchemaSpikeTests(SimpleTestCase):
    """core.schema.Schema checks a widget's options as the form would store them: select, boolean, unknown names."""

    def test_the_schema_checks_options(self):
        schema = WIDGETS['water_table'].options
        schema.check({'points': 'all', 'parameters': 'key'})
        schema.check({})
        for wrong in ({'points': 'some'}, {'points': 3}, {'other': 'x'}):
            with self.subTest(options=wrong), self.assertRaises(ValidationError):
                schema.check(wrong)
        feeding = WIDGETS['feeding'].options
        feeding.check({'week': True})
        with self.assertRaises(ValidationError):
            feeding.check({'week': 'yes'})                               # not the form it is saved in


class ValidateTests(SimpleTestCase):
    def test_a_good_layout_has_no_problem_and_an_empty_one_is_legal(self):
        self.assertEqual(validate.validate(layout(widget(), widget('w2', 'fish', x=0, y=2, w=12, h=5))), [])
        self.assertEqual(codes(validate.validate(layout())), [])

    def test_the_shape(self):
        for wrong in (None, [], 'x', {'widgets': []}, {'schema': 1}, {'schema': 1, 'widgets': {}},
                      {'schema': 1, 'widgets': [], 'extra': 1}, {'schema': 1, 'widgets': ['w1']}):
            with self.subTest(layout=wrong):
                self.assertEqual(codes(validate.validate(wrong))[0][0], 'shape')

    def test_the_version(self):
        for version in (0, 2, '1', None, True):
            with self.subTest(version=version):
                self.assertEqual(codes(validate.validate(layout(schema=version))), [('schema', '')])

    def test_at_most_forty_widgets_and_32_kilobytes(self):
        many = [widget(f'w{number}', 'tasks', x=(number % 4) * 3, y=(number // 4) * 2) for number in range(41)]
        self.assertIn(('too_many', ''), codes(validate.validate(layout(*many))))
        self.assertNotIn(('too_many', ''), codes(validate.validate(layout(*many[:40]))))
        big = layout(widget(opts={'size': 'normal'}, padding='x' * 33000))
        self.assertIn(('too_large', ''), codes(validate.validate(big)))

    def test_keys_ids_and_types(self):
        self.assertEqual(codes(validate.validate(layout(widget(colour='red')))), [('keys', 'w1')])
        missing = widget()
        del missing['h']
        self.assertEqual(codes(validate.validate(layout(missing))), [('keys', 'w1')])
        for wrong in ('', 'W1', '1w', 'w 1', 'w' * 17, 7):
            with self.subTest(id=wrong):
                self.assertEqual(codes(validate.validate(layout(widget(id=wrong))))[0][0], 'id')
        self.assertIn(('duplicate', 'w1'), codes(validate.validate(layout(widget(), widget(x=6)))))
        self.assertEqual(codes(validate.validate(layout(widget(type='gauge')))), [('type', 'w1')])
        self.assertEqual(codes(validate.validate(layout(widget(type='spark', w=6, h=2)))), [('disabled', 'w1')])

    def test_places_and_sizes(self):
        for field in ('x', 'y', 'w', 'h'):
            for wrong in ('1', 1.5, True, None):
                with self.subTest(field=field, value=wrong):
                    self.assertEqual(codes(validate.validate(layout(widget(**{field: wrong})))), [('number', 'w1')])
        self.assertEqual(codes(validate.validate(layout(widget(x=-1)))), [('bounds', 'w1')])
        self.assertEqual(codes(validate.validate(layout(widget(y=-1)))), [('bounds', 'w1')])
        self.assertEqual(codes(validate.validate(layout(widget(x=10, w=3)))), [('bounds', 'w1')])
        self.assertEqual(codes(validate.validate(layout(widget(x=9, w=3)))), [])
        self.assertEqual(codes(validate.validate(layout(widget(w=1)))), [('size', 'w1')])
        self.assertEqual(codes(validate.validate(layout(widget(h=9)))), [('size', 'w1')])

    def test_an_overlap_names_both_widgets_once(self):
        found = validate.validate(layout(widget(), widget('w2', x=2, y=1), widget('w3', x=3, y=0)))
        overlaps = [problem for problem in found if problem.code == 'overlap']
        self.assertEqual([(problem.widget, dict(problem.params)['other']) for problem in overlaps], [('w1', 'w2'),
                                                                                                     ('w2', 'w3')])
        self.assertIn('w1', overlaps[0].message)
        self.assertIn('w2', overlaps[0].message)

    def test_bindings(self):
        unbound = widget()
        del unbound['bind']
        self.assertEqual(codes(validate.validate(layout(unbound))), [('binding', 'w1')])
        for bind in ({'parameter': 'gold_mg_l'}, {'parameter': parameters.PH, 'point': 'roof'}, {'parameter': 7},
                     {'parameter': parameters.PH, 'colour': 'red'}, 'ph'):
            with self.subTest(bind=bind):
                self.assertEqual(codes(validate.validate(layout(widget(bind=bind)))), [('binding', 'w1')])
        self.assertEqual(codes(validate.validate(layout(widget(bind={'parameter': parameters.PH,
                                                                   'point': PointKind.INLET})))), [])
        self.assertEqual(codes(validate.validate(layout(widget('w1', 'tasks', w=6, h=2,
                                                               bind={'parameter': 'ph'})))), [('unbound', 'w1')])
        self.assertEqual(codes(validate.validate(layout(widget(type='bar', w=4,
                                                               bind={'parameter': parameters.OXYGEN_PCT})))), [])

    def test_options_go_through_the_widgets_schema(self):
        self.assertEqual(codes(validate.validate(layout(widget(opts={'size': 'large'})))), [])
        for opts in ({'size': 'huge'}, {'colour': 'red'}, ['large'], {'size': None}):
            with self.subTest(opts=opts):
                self.assertEqual(codes(validate.validate(layout(widget(opts=opts)))), [('option', 'w1')])

    def test_the_warnings_never_block(self):
        tasks = widget('w1', 'tasks', w=6, h=2)
        self.assertEqual(codes(validate.validate(layout(tasks)), 'warning'), [('no_oxygen', '')])
        self.assertEqual(codes(validate.validate(layout(tasks)), 'error'), [])
        table = widget('w2', 'water_table', y=2, w=12, h=4)
        self.assertEqual(codes(validate.validate(layout(tasks, table)), 'warning'), [])
        large = [widget(f'w{number}', opts={'size': 'large'}, x=number * 3) for number in range(3)]
        self.assertEqual(codes(validate.validate(layout(*large)), 'warning'), [('large', '')])
        many = [widget(f'w{number}', 'tasks', x=(number % 4) * 3, y=(number // 4) * 2) for number in range(17)]
        self.assertIn(('many', ''), codes(validate.validate(layout(*many, widget('wx', y=20))), 'warning'))
        self.assertEqual(codes(validate.validate(layout())), [])          # an empty card: the frame alone, no warning

    def test_every_problem_has_a_message_in_the_persons_language(self):
        for code in validate.MESSAGES:
            problem = validate.Problem('error', 'w1', code, (('other', 'w2'), ('label', 'x'), ('version', 9),
                                                             ('detail', 'y'), ('option', 'z'), ('count', 16),
                                                             ('min_w', 1), ('min_h', 1), ('max_w', 2), ('max_h', 2),
                                                             ('max', 40), ('most', 24), ('rows', 26), ('has', '2.2'),
                                                             ('needs', '4.0')))
            with self.subTest(code=code):
                self.assertTrue(problem.message)
                with translation.override('nb'):
                    self.assertTrue(problem.message)                     # (each msgid's translation: core/test_catalogs)
                if code in validate.ABOUT_A_WIDGET:
                    self.assertIn('w1', problem.message)

    def test_the_input_is_never_changed(self):
        given = layout(widget(), widget('w2', x=1))
        before = copy.deepcopy(given)
        validate.validate(given)
        self.assertEqual(given, before)

    def test_clean_raises_the_errors_only(self):
        validate.clean(layout(widget('w1', 'tasks', w=6, h=2)))           # a warning only
        with self.assertRaises(ValidationError) as caught:
            validate.clean(layout(widget(x=11)))
        self.assertIn('w1', caught.exception.messages[0])


class UpgradeTests(SimpleTestCase):
    def test_the_current_version_is_returned_as_it_is(self):
        given = layout(widget())
        self.assertIs(validate.upgrade(given), given)
        self.assertEqual(catalogue.SCHEMA_VERSION, 1)

    def test_an_older_version_is_upgraded_one_pure_step_at_a_time(self):
        def to_2(old):
            return {**old, 'schema': 2, 'widgets': [{**each, 'h': each['h'] + 1} for each in old['widgets']]}

        with mock.patch.object(catalogue, 'SCHEMA_VERSION', 2), mock.patch.dict(validate.UPGRADES, {1: to_2}):
            given = layout(widget())
            upgraded = validate.upgrade(given)
            self.assertEqual((upgraded['schema'], upgraded['widgets'][0]['h']), (2, 3))
            self.assertEqual(given['widgets'][0]['h'], 2)                   # the stored one is untouched
            self.assertEqual(validate.validate(given), [])                  # an old layout is checked as upgraded

    def test_every_version_has_a_fixture_that_passes(self):
        for version in range(1, catalogue.SCHEMA_VERSION + 1):
            fixture = json.loads((Path(__file__).parent / 'layouts' / f'v{version}.json').read_text(encoding='utf-8'))
            with self.subTest(version=version):
                self.assertEqual(fixture['schema'], version)
                self.assertEqual(codes(validate.validate(fixture)), [])


class VectorTests(SimpleTestCase):
    """monitoring/tests/layout_vectors.json: the geometry both validators agree on (frontend/grid runs it too)."""

    def test_the_vectors_sizes_are_the_catalogues(self):
        vectors = json.loads(VECTORS.read_text(encoding='utf-8'))
        self.assertEqual(vectors['columns'], catalogue.COLUMNS)
        self.assertEqual(vectors['sizes'], {name: [spec.min_w, spec.min_h, spec.max_w, spec.max_h]
                                            for name, spec in WIDGETS.items()})

    def test_the_python_validator_says_what_each_vector_expects(self):
        vectors = json.loads(VECTORS.read_text(encoding='utf-8'))
        self.assertGreaterEqual(len(vectors['cases']), 12)
        for case in vectors['cases']:
            with self.subTest(case=case['name']):
                found = []
                for problem in validate.validate(layout(*case['widgets'])):
                    if problem.code in validate.GEOMETRY:
                        found.append([problem.code, problem.widget] + ([dict(problem.params)['other']]
                                                                        if problem.code == 'overlap' else []))
                self.assertEqual(found, case['problems'])


class CalculatedTests(SimpleTestCase):
    """A value widget may be bound to a value the unit's Deffeyes chart works out (owner decision 2, 2026-11-12: the
    chart's CO₂ is always the calculated one), as to a water parameter."""

    def test_the_calculated_co2_is_bindable_and_is_not_a_water_parameter_yet(self):
        code = catalogue.CO2_CALCULATED
        self.assertIn(code, catalogue.bindable())
        self.assertNotIn(code, parameters.BY_CODE)                      # Phase 1: shown and tagged, not judged
        self.assertEqual(codes(validate.validate(layout(widget(bind={'parameter': code})))), [])
        self.assertEqual(codes(validate.validate(layout(widget(bind={'parameter': 'co2_guessed_mg_l'})))),
                         [('binding', 'w1')])
        described = catalogue.described(code)
        self.assertEqual((str(described.short), described.shown_as, described.figure),
                         ('CO₂ calc. (mg/L)', 'co2_mg_l', 'co2_mg_l'))
        self.assertIs(catalogue.described('ph'), parameters.get('ph'))
        from farm.water.deffeyes import Analysis
        self.assertIn(described.figure, Analysis.__dataclass_fields__)   # the analysis's own figure, by its name

    def test_the_designer_is_offered_it_among_the_parameters(self):
        with translation.override('en'):
            offered = {each['value']: each['label'] for each in catalogue.as_data()['parameters']}
        self.assertEqual(offered[catalogue.CO2_CALCULATED], 'Carbon dioxide, calculated (mg/L CO₂)')
        self.assertTrue(set(parameters.BY_CODE) <= set(offered))

    def test_a_fitted_cards_bounds_are_the_classes_the_style_sheet_holds(self):
        from ..cards import render
        css = render.grid_css()
        (low_w, high_w), (low_h, high_h) = catalogue.MEASURE_W, catalogue.MEASURE_H
        for name, low, high in (('mw', low_w, high_w), ('mh', low_h, high_h), ('gr', 1, catalogue.FIT_ROWS)):
            for size in (low, high):
                self.assertIn(f'.{name}-{size}{{--{name}:{size}}}', css)
            for size in (low - 1, high + 1):
                self.assertNotIn(f'.{name}-{size}{{', css)
