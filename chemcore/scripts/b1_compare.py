"""B1 (owner amendment, 2026-11-05): the three-way comparison of the water chemistry, the source platform's engine,
our Python (golden v1) and the Rust core, over the golden corpus, every output and intermediate.

    python chemcore/scripts/b1_compare.py inputs <out.json>         the golden's inputs for the source's driver
    python chemcore/scripts/b1_compare.py report                    every disagreement above its floor, as text

The source's outputs (chemcore/golden/b1/source.json.gz) come from farm/tests/deffeyes_reference/b1/driver.ts run on
`inputs`; the noise floors (chemcore/golden/b1/floors.toml) were declared before any output was looked at. A
quantity above its floor is a disagreement: chemcore/findings/B1.md says, for each, the inputs, both values, the
formula or constant responsible and which side the literature supports; chemcore/findings/b1-registry.json lists the
quantities each finding covers, and farm/tests/test_b1.py fails on a disagreement no finding covers or a finding
whose disagreement has gone. The owner decides each finding before the Rust core follows either side.

Link checks: the source's downstream functions are also fed OUR upstream value (the Python DIC; for the chart, our
Python evaluated at the source's own DIC), to tell "a different upstream value" from "a different downstream
formula"."""
import functools
import gzip
import json
import math
import sys
import tomllib
from pathlib import Path

SOURCE_NAMES = {'nahco3': 'Sodium Bicarbonate', 'na2co3': 'Sodium Carbonate', 'naoh': 'Sodium Hydroxide',
                'caco3': 'Calcium Carbonate', 'caoh2': 'Calcium Hydroxide', 'cao': 'Calcium Oxide', 'co2': 'Add CO₂',
                'degas': 'De-gas CO₂', 'hcl': 'Muriatic Acid'}
ROOT = Path(__file__).resolve().parent.parent.parent
V1 = ROOT / 'chemcore' / 'golden' / 'v1'
B1 = ROOT / 'chemcore' / 'golden' / 'b1'


def block(name):
    with gzip.open(V1 / f'{name}.jsonl.gz', 'rt', encoding='utf-8') as stream:
        return [json.loads(line) for line in stream]


def complete(record):
    """An analysis record the source can take: every value and limit given, nothing refused."""
    if 'analysis' not in record:
        return False
    water, limits = record['water'], record['limits']
    return (all(water[key] is not None for key in ('tan_mg_l', 'total_sulfide_ug_l'))
            and all(limits.get(key) is not None for key in ('nh3_n_mg_l', 'co2_mg_l', 'h2s_ug_l',
                                                             'alkalinity_low_mg_l', 'alkalinity_high_mg_l'))
            and limits['alkalinity_low_mg_l'] < limits['alkalinity_high_mg_l'] and record['pressure'] == 1.0)


def analysis_cases():
    return ([r for r in block('analysis') if complete(r)]
            + [r for r in block('edges') if r['kind'] == 'b1_case' and complete(r)])


def geometry_cases():
    return [r for r in analysis_cases() if r['water']['calcium_mg_l'] is not None]


def inputs():
    """The golden's inputs that the source's engine can take, in the order of the golden."""
    constants = [{'temp_c': r['temp_c'], 'salinity': r['salinity']} for r in block('constants') if 'temp_c' in r]
    carbonate = [{'temp_c': r['temp_c'], 'salinity': r['salinity'], 'ph': r['ph'], 'alkalinity_meq': r['alkalinity_meq'],
                  'python_dic': r['dic']} for r in block('carbonate')]
    analysis = analysis_cases()
    geometry = geometry_cases()
    dosing = [r for r in block('dosing')]
    return {'constants': constants, 'carbonate': carbonate,
            'analysis': [{key: r[key] for key in ('water', 'limits', 'target')} for r in analysis],
            'geometry': [{key: r[key] for key in ('water', 'limits', 'target')} for r in geometry],
            'dosing': [{key: r[key] for key in r if key not in ('recipes', 'visual', 'steps', 'at_target')}
                       for r in dosing]}


def number(value):
    if isinstance(value, str):
        return float(value.replace('Infinity', 'inf'))
    return value


@functools.lru_cache(maxsize=1)
def floors():
    return tomllib.loads((B1 / 'floors.toml').read_text(encoding='utf-8'))


def above(python, source, floor):
    """How far apart two values are beyond the floor: 0 when within it, else the absolute difference. A floor is
    {abs, rel}: within when |a - b| <= abs + rel * max(|a|, |b|). None/NaN must match exactly."""
    a, b = number(python), number(source)
    if a is None or b is None or (isinstance(a, float) and math.isnan(a)) or (isinstance(b, float) and math.isnan(b)):
        same = (a is None or (isinstance(a, float) and math.isnan(a))) == (b is None or (isinstance(b, float) and math.isnan(b)))
        return 0.0 if same else math.inf
    if isinstance(a, str) or isinstance(b, str):
        return 0.0 if a == b else math.inf
    if math.isinf(a) or math.isinf(b):
        return 0.0 if a == b else math.inf
    difference = abs(a - b)
    return 0.0 if difference <= floor.get('abs', 0.0) + floor.get('rel', 0.0) * max(abs(a), abs(b)) else difference


class Tally:
    def __init__(self, keep=False):
        self.rows, self.keep = {}, keep

    def add(self, quantity, floor_name, python, source, case, extra=None):
        row = self.rows.setdefault(quantity, {'floor': floor_name, 'n': 0, 'disagree': 0, 'max': 0.0, 'example': None})
        row['n'] += 1
        gap = above(python, source, floors()['floors'][floor_name]) if floor_name != 'exact' else (
            0.0 if python == source else math.inf)
        if gap:
            row['disagree'] += 1
            if self.keep:
                row.setdefault('all', []).append((case, python, source, extra))
            if row['example'] is None or gap > row['max']:
                row['max'] = gap
                row['example'] = {'inputs': case, 'python': python, 'source': source}


def compare(source, keep=False):
    tally = Tally(keep)
    cons = [r for r in block('constants') if 'temp_c' in r]
    for ours, theirs in zip(cons, source['constants']):
        case = {'temp_c': ours['temp_c'], 'salinity': ours['salinity']}
        eq = ours['equilibria']
        mine = {'k1_sws': ours['k1_sws'], 'k2_sws': ours['k2_sws'], 'kw_total': ours['kw_total'],
                'kb_total': ours['kb_total'], 'k_nh4_sws': ours['k_nh4_sws'], 'k_h2s_total': ours['k_h2s_total'],
                'ks': ours['ks'].get('value'), 'kf': ours['kf'].get('value'), 'ionic_strength': ours['ionic_strength'],
                'total_boron': ours['total_boron'], 'total_sulfate': ours['total_sulfate'],
                'total_fluoride': ours['total_fluoride'], 'activity_h': ours['activity_h'],
                'free_to_sws': ours['free_to_sws'], 'free_to_total': ours['free_to_total'],
                'sws_to_nbs': ours['sws_to_nbs'], 'ksp_calcite': ours['ksp_calcite'],
                'ksp_aragonite': ours['ksp_aragonite'], 'ph_free_7': ours['ph_free_7'], 'k1_free': eq['k1'],
                'k2_free': eq['k2'], 'kw_free': eq['kw'], 'kb_free': eq['kb'], 'k_nh4_free': eq['k_nh4'],
                'k_h2s_free': eq['k_h2s'], 'nh3_fraction_7_5': ours['nh3_fraction_7_5']}
        for name, value in mine.items():
            if ours['salinity'] == 0 and name in ('ks', 'kf'):
                continue                    # log(1 - 0.001005 S) at S 0: both finite, unused (scale factor 1)
            tally.add(f'constants.{name}', 'closed_form', value, theirs[name], case)
    for ours, theirs in zip(block('carbonate'), source['carbonate']):
        case = {key: ours[key] for key in ('temp_c', 'salinity', 'ph', 'alkalinity_mg_l')}
        for name in ('hydrogen', 'dic', 'alkalinity_back', 'carbonate', 'nh3_share', 'h2s_share'):
            tally.add(f'carbonate.{name}', 'closed_form', ours[name], theirs[name], case)
        tally.add('carbonate.co2', 'closed_form', ours['co2'], theirs['co2'], case)
        for index, name in enumerate(('alpha0', 'alpha1', 'alpha2')):
            tally.add(f'carbonate.{name}', 'closed_form', ours['fractions'][index], theirs['fractions'][index], case)
        tally.add('carbonate.isoline_slope', 'closed_form', ours['isoline'][0], theirs['isoline'][0], case)
        tally.add('carbonate.isoline_intercept', 'meq', ours['isoline'][1], theirs['isoline'][1], case)
        tally.add('carbonate.alkalinity_floor', 'meq', ours['alkalinity_floor'], theirs['alkalinity_floor'], case)
        tally.add('carbonate.ph_at', 'source_bisection_ph', ours['ph_at'].get('value'), theirs['ph_at'], case)
        for co2 in (5, 15, 40):
            tally.add(f'carbonate.ph_where_co2_{co2}', 'source_bisection_ph', ours[f'ph_where_co2_{co2}'].get('value'),
                      theirs[f'ph_where_co2_{co2}'], case)
        tally.add('carbonate.ph_where_co2_at_dic', 'source_bisection_ph', ours['ph_where_co2_at_dic'].get('value'),
                  theirs['ph_where_co2_at_dic'], case)
        tally.add('carbonate.ph_where_nh3', 'source_bisection_ph', ours['ph_where_nh3'].get('value'),
                  theirs['ph_where_nh3'], case)
        tally.add('carbonate.ph_where_h2s', 'source_bisection_ph', ours['ph_where_h2s'].get('value'),
                  theirs['ph_where_h2s'], case)
        # links: the source's downstream on OUR DIC
        tally.add('link.alkalinity_of_python_dic', 'closed_form', ours['alkalinity_back'],
                  theirs['link_alkalinity_back_of_python_dic'], case)
        tally.add('link.co2_of_python_dic', 'closed_form', ours['co2'], theirs['link_co2_of_python_dic'], case)
        tally.add('link.carbonate_of_python_dic', 'closed_form', ours['carbonate'], theirs['link_carbonate_of_python_dic'],
                  case)
    for ours, theirs in zip(analysis_cases(), source['analysis']):
        a = ours['analysis']
        case = {key: ours[key] for key in ('water', 'limits', 'target')}
        tally.add('analysis.dic', 'closed_form', a['dic'], theirs['dic'], case)
        tally.add('analysis.co2_mg_l', 'closed_form', a['co2_mg_l'], theirs['co2_mg_l'], case)
        if ours['target'] is not None:
            tally.add('analysis.target_dic', 'closed_form', a['target_dic'], theirs['target_dic'], case)
            tally.add('analysis.target_co2_mg_l', 'closed_form', a['target_co2_mg_l'], theirs['target_co2_mg_l'], case)
        tally.add('analysis.co2_border', 'source_bisection_ph', a['co2']['ph'], theirs['co2_border'], case)
        tally.add('analysis.nh3_border', 'source_bisection_ph', a['nh3']['ph'], theirs['nh3_border'], case)
        tally.add('analysis.h2s_border', 'source_bisection_ph', a['h2s']['ph'], theirs['h2s_border'], case)
        tally.add('analysis.nh3_n_mg_l', 'closed_form', a['nh3_n_mg_l'], theirs['nh3_n_mg_l'], case)
        tally.add('analysis.safe_tan_mg_l', 'closed_form', a['safe_tan_mg_l'], theirs['safe_tan_mg_l'], case)
        tally.add('analysis.nh3_share_at_border_pct', 'border_share', a['nh3_share_at_border_pct'],
                  theirs['nh3_share_at_border_pct'], case)
        tally.add('analysis.h2s_ug_l', 'closed_form', a['h2s_ug_l'], theirs['h2s_ug_l'], case)
        tally.add('analysis.safe_total_sulfide_h2s_basis', 'closed_form',
                  None if a['safe_total_sulfide_ug_l'] is None else a['safe_total_sulfide_ug_l'] * 34.08088 / 32.065,
                  theirs['safe_total_sulfide_h2s_basis'], case)
        tally.add('analysis.nh3_status', 'exact', a['nh3']['status'], theirs['nh3_status'], case)
        tally.add('analysis.h2s_status', 'exact', a['h2s']['status'], theirs['h2s_status'], case)
    for ours, theirs in zip(geometry_cases(), source['geometry']):
        chart_links(tally, ours, theirs)
    for ours, theirs in zip(block('dosing'), source['dosing']):
        case = {key: ours[key] for key in ours if key not in ('recipes', 'visual', 'steps', 'at_target')}
        if ours['kind'] == 'recipes':
            mine = ours['recipes'].get('value') or []
            tally.add('dosing.recipe_count', 'exact', len(mine), len(theirs['recipes']), case)
            if len(mine) == len(theirs['recipes']):
                volume = ours['volume'] or 1.0
                for recipe, other in zip(mine, theirs['recipes']):
                    grams = sorted((SOURCE_NAMES[dose['reagent']['key']], dose['grams'] if dose['grams'] is not None
                                    else dose['concentration'] * dose['reagent']['molar_mass'] * volume)
                                   for dose in recipe['doses'])
                    their_grams = sorted((step[0], step[1]) for step in other)
                    tally.add('dosing.recipe_reagents', 'exact', [name for name, _g in grams],
                              [name for name, _g in their_grams], case)
                    if [name for name, _g in grams] == [name for name, _g in their_grams]:
                        for (_name, one), (_other, two) in zip(grams, their_grams):
                            tally.add('dosing.recipe_grams', 'closed_form', one, two, case)
        else:
            mine = ours['steps'].get('value') or []
            for step, other in zip(mine, theirs['steps']):
                tally.add('dosing.simulate_ph', 'source_bisection_ph', step['ph'], other[2], case)
                tally.add('dosing.simulate_dic', 'closed_form', step['dic'], other[0], case)
    return tally.rows


def chart_links(tally, ours, theirs):
    """The source's chart points against ours evaluated at the source's own DIC (the implementation as it is now:
    farm/water/chemistry.py, later the Rust core behind it)."""
    from farm.water import chemistry as c
    water, limits, a = ours['water'], ours['limits'], ours['analysis']
    eq = c.equilibria(water['temperature_c'], water['salinity_ppt'])
    case = {key: ours[key] for key in ('water', 'limits', 'target')}
    tally.add('chart.current_dic', 'closed_form', a['dic'], theirs['current'][0], case)
    tally.add('chart.nh3_zone_drawn', 'exact', a['nh3']['ph'] is not None, theirs['nh3_zone'] is not None, case)
    if a['nh3']['ph'] is not None and theirs['nh3_zone']:
        for dic, alk in theirs['nh3_zone'][::20]:
            tally.add('chart.nh3_boundary', 'chart_point', eq.alkalinity(dic, a['nh3']['ph']), alk, case)
    tally.add('chart.h2s_zone_drawn', 'exact', a['h2s']['ph'] is not None and a['h2s']['ph'] >= 4.0,
              theirs['h2s_zone'] is not None, case)
    if a['h2s']['ph'] is not None and theirs['h2s_zone']:
        for dic, alk in theirs['h2s_zone'][::20]:
            tally.add('chart.h2s_boundary', 'chart_point', eq.alkalinity(dic, a['h2s']['ph']), alk, case)
    co2 = limits['co2_mg_l'] / c.MG_CO2_PER_MMOL
    for dic, alk in (theirs['co2_zone'] or [])[::10]:
        ph = eq.ph_where_co2_at_dic(dic, co2)
        tally.add('chart.co2_boundary', 'chart_point', None if ph is None else eq.alkalinity(dic, ph), alk, case)
    for key, ksp in (('calcite', eq.ksp_calcite), ('aragonite', eq.ksp_aragonite)):
        carbonate = ksp / (water['calcium_mg_l'] / c.MG_CALCIUM_PER_MOL) * 1000
        # The source prints each point's DIC rounded to 4 decimals but works its alkalinity out at the DIC of its
        # scan (deffeyes-data.ts generateOmegaIsopleth: from max(CO3 + 0.01, 0.05) by 8 / 200); near the line's start
        # the alkalinity is steep in the DIC, so ours is evaluated at the scan's own DIC, rebuilt as the source adds it.
        scan, dic = {}, max(ksp / (water['calcium_mg_l'] / 40078) * 1000 + 0.01, 0.05)
        while dic <= 8:
            scan.setdefault(round(dic, 4), dic)
            dic += 8 / 200
        for rounded, alk in (theirs[key] or [])[::10]:
            dic = scan.get(round(rounded, 4), rounded)
            ph = eq.ph_where_carbonate(dic, carbonate)
            tally.add(f'chart.omega_{key}', 'chart_point', None if ph is None else eq.alkalinity(dic, ph), alk, case)
    for ph, at_zero, dic_end, at_end in theirs['isolines']:
        slope, intercept = eq.isoline(ph)
        tally.add('chart.isoline_start', 'chart_point', intercept, at_zero, case)
        tally.add('chart.isoline_end', 'chart_point', slope * dic_end + intercept, at_end, case)
    from farm.water import deffeyes as d
    # By formula 1, as everything here (golden v1's records, `eq`): the comparison with the source is formula 1's, and
    # its edge cases hold waters below their alkalinity floor, which formula 3 refuses (ImpossibleWaterError).
    analysis = d.analyse(d.Water(**{**water, 'formula': 1}), d.Limits(**limits),
                         d.Target(**ours['target']) if ours['target'] else None)
    tally.add('chart.safe_zone_drawn', 'exact', bool(d.safe_zone(analysis, d.box_of(analysis))),
              theirs['safe_zone'] is not None, case, extra=theirs['safe_zone'])
    if theirs['safe_zone'] and a['nh3']['ph'] is not None:
        top_left, top_right, bottom_right, _bottom_left = theirs['safe_zone']
        tally.add('chart.safe_zone_nh3_side', 'chart_bisected', eq.dic(top_left[1], a['nh3']['ph']), top_left[0], case)
        for corner in (top_right, bottom_right):
            border = eq.ph_where_co2(corner[1], co2)
            tally.add('chart.safe_zone_co2_side', 'chart_bisected',
                      None if border is None else eq.dic(corner[1], border), corner[0], case)


def disagreements(source, quantity):
    """Every (inputs, ours, the source's, extra) of a quantity above its floor."""
    return compare(source, keep=True).get(quantity, {}).get('all', [])


def recipe_doses(source):
    """(inputs, (reagent key, our grams in the volume), the source's grams) of every dose of the recipes both sides
    give with the same reagents."""
    names = {name: key for key, name in SOURCE_NAMES.items()}
    for ours, theirs in zip(block('dosing'), source['dosing']):
        if ours['kind'] != 'recipes':
            continue
        volume = ours['volume'] or 1.0
        for recipe, other in zip(ours['recipes'].get('value') or [], theirs['recipes']):
            mine = {dose['reagent']['key']: dose['grams'] if dose['grams'] is not None
                    else dose['concentration'] * dose['reagent']['molar_mass'] * volume for dose in recipe['doses']}
            their = {names[step[0]]: step[1] for step in other}
            if set(mine) == set(their):
                for key, grams in mine.items():
                    yield ours, (key, grams), their[key]


def report(rows):
    lines = []
    for quantity, row in sorted(rows.items()):
        if row['disagree']:
            lines.append(f"{quantity}: {row['disagree']} of {row['n']} above floor {row['floor']}, max {row['max']:.3g}")
            lines.append(f"    example {json.dumps(row['example'], sort_keys=True)[:600]}")
    agreed = sorted(quantity for quantity, row in rows.items() if not row['disagree'])
    lines.append(f'agree within their floors ({len(agreed)}): ' + ', '.join(agreed))
    return '\n'.join(lines)


def load_source():
    with gzip.open(B1 / 'source.json.gz', 'rt', encoding='utf-8') as stream:
        return json.load(stream)


def setup():
    sys.path.insert(0, str(ROOT))
    import os
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()


if __name__ == '__main__':
    setup()
    if sys.argv[1] == 'inputs':
        Path(sys.argv[2]).write_text(json.dumps(inputs()), encoding='utf-8')
    elif sys.argv[1] == 'report':
        print(report(compare(load_source())))
