"""The Rust core's dosing (chemcore/core/src/dosing.rs, through farm/water/native.py) against golden v1: the reagents'
molar masses from the atomic weights, the recipes of every pair and of the chosen sets (doses, grams, waypoint, order,
at most six), the chart's dosing layer (lines, wedge, path, waypoint, its note as a code that farm/water/messages.py
says), the at-target rule, and the simulator's steps (pH, CO2, a stripping below the air's flagged, the stop where no
water is left), within the classes of chemcore/tolerances.toml."""
import gzip
import importlib.util
import json
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase
from django.utils import translation

from ..water import native

ROOT = Path(settings.BASE_DIR)
V1 = ROOT / 'chemcore' / 'golden' / 'v1'


def block(name):
    with gzip.open(V1 / f'{name}.jsonl.gz', 'rt', encoding='utf-8') as stream:
        return [json.loads(line) for line in stream]


def parity():
    spec = importlib.util.spec_from_file_location('golden_parity', ROOT / 'chemcore' / 'scripts' / 'golden_parity.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.compare


def start_of(record):
    eq = native.equilibria(record['temp_c'], record['salinity'])
    alkalinity = record['alkalinity_mg_l'] / native.MG_CACO3_PER_MEQ
    return eq, (eq.dic(alkalinity, record['ph']), alkalinity)


def golden_recipes(value):
    return [{'doses': [[dose['reagent']['key'], dose['concentration'], dose['grams'], dose['delta_dic'],
                        dose['delta_alkalinity']] for dose in recipe['doses']],
             'waypoint': recipe['waypoint'], 'below_air': recipe['below_air']} for recipe in value]


class DosingParityTests(SimpleTestCase):
    def test_the_molar_masses_are_golden_v1s(self):
        golden = {}
        for record in block('dosing'):
            for recipe in (record['recipes'].get('value') or []) if record['kind'] == 'recipes' else []:
                for dose in recipe['doses']:
                    golden[dose['reagent']['key']] = (dose['reagent']['molar_mass'], dose['reagent']['dic'],
                                                      dose['reagent']['alkalinity'])
        ours = {key: (mass, dic, alkalinity) for key, mass, dic, alkalinity, _angle in native.reagents()}
        self.assertEqual([key for key, *_rest in native.reagents()],
                         ['nahco3', 'na2co3', 'naoh', 'caco3', 'caoh2', 'cao', 'co2', 'degas', 'hcl'])
        for key, values in golden.items():
            self.assertEqual(ours[key], tuple(values), key)

    def test_every_recipe_layer_and_step_of_golden_v1_within_its_class(self):
        from ..water import messages
        compare, found, counted = parity(), [], {'recipes': 0, 'simulate': 0}
        with translation.override('en'):
            for record in block('dosing'):
                eq, start = start_of(record)
                if record['kind'] == 'recipes':
                    end = (eq.dic(record['target'][1] / native.MG_CACO3_PER_MEQ, record['target'][0]),
                           record['target'][1] / native.MG_CACO3_PER_MEQ)
                    ours = native.recipes(start, end, record['chosen'], record['volume'])
                    found += compare(golden_recipes(record['recipes']['value']), json.loads(json.dumps(ours)))
                    layer = native.visual(start, end, record['chosen'])
                    golden = record['visual']['value']
                    found += compare({**golden, 'lines': [[line[0]['key'], line[1]] for line in golden['lines']]},
                                     json.loads(json.dumps({**layer, 'note': str(messages.dosing_note(layer['note']))})))
                    self.assertEqual(native.at_target(start, end), record['at_target'])
                else:
                    steps = native.simulate(record['temp_c'], record['salinity'], start, record['ph'],
                                            list(record['amounts'].items()), record['volume'],
                                            native.co2_from_air(record['temp_c'], record['salinity'], 1.0))
                    golden = [[None if step['reagent'] is None else step['reagent']['key'], step['grams'], step['dic'],
                               step['alkalinity'], step['ph'], step['co2_mg_l'], step['below_air']]
                              for step in record['steps']['value']]
                    found += compare(golden, json.loads(json.dumps(steps)))
                counted[record['kind']] += 1
        self.assertEqual(counted, {'recipes': 2394, 'simulate': 36})
        self.assertEqual(found[:5], [])

    def test_a_stripping_below_the_airs_co2_is_flagged_whichever_dose_goes_first(self):
        eq = native.equilibria(12.0, 1.0)
        start = (eq.dic(80 / native.MG_CACO3_PER_MEQ, 7.0), 80 / native.MG_CACO3_PER_MEQ)
        end = (eq.dic(80 / native.MG_CACO3_PER_MEQ, 9.5), 80 / native.MG_CACO3_PER_MEQ)
        air = (12.0, 1.0, native.co2_from_air(12.0, 1.0, 1.0))
        flagged = [recipe for recipe in native.recipes(start, end, ['nahco3', 'degas'], 1.0, air) if recipe['below_air']]
        self.assertEqual([[dose[0] for dose in recipe['doses']] for recipe in flagged], [['degas']])
        self.assertFalse(any(recipe['below_air'] for recipe in native.recipes(start, end, ['nahco3', 'degas'], 1.0)))

    def test_an_unknown_reagent_is_refused_and_a_note_has_its_words(self):
        from ..water import messages
        with self.assertRaises(ValueError):
            native.split((1.0, 1.0), (2.0, 2.0), 'nahco3', 'no-such')
        self.assertEqual(set(messages.DOSING_NOTES), {'dosing.cannot_reach', 'dosing.tick_one_or_two'})
        self.assertEqual(messages.dosing_note(None), '')
