"""The golden reference: what today's Python water chemistry (farm/water/chemistry.py, deffeyes.py, dosing.py,
charts.py, calculation.py) returns for a fixed corpus of waters, recorded once so that the Rust core can be held to
it and so that nothing changes a result silently. Recorded ONLY in the Linux runner image (docker/testrunner.Dockerfile:
Python 3.12, glibc 2.41), never on Windows: the last bits of exp, log and pow are the C library's.

    docker run --rm -v "$PWD:/app" -w /app <runner image> python chemcore/scripts/record_golden.py chemcore/golden/v1

Writes <out>/<block>.jsonl.gz (one JSON object per line, keys sorted, floats as Python repr: an exact round trip;
gzip with mtime 0, so two runs give the same bytes) and <out>/manifest.json (provenance: the formula modules' git
blob ids and sha256, Python, glibc, the seed, the counts). Version v1 is Python as it was and is never re-recorded
silently: a change of any formula module fails farm/tests/test_golden.py until the owner decides.

Blocks
  constants    every constant and scale factor of a (temperature, salinity), oxygen, CO2 from air, pressure
  carbonate    a (T, S, pH, alkalinity): fractions, the isoline, DIC, CO2, carbonate, shares, the pH borders and the
               solver's path signature, the alkalinity floor
  analysis     analyse(water, limits, target, pressure): every value and border with its margin and status
  geometry     geometry(analysis): the box, isolines, regions, boundaries, Omega lines, notes; full vertices for the
               first GEOMETRY_FULL waters, counts, areas, lengths and ends for the rest
  dosing       recipes of every pair of reagents, the simulator's steps
  plots        the four small charts' series (charts.plots)
  edges        the edge cases of block D: impossible pairs at the floor +-1e-9, salinities 0/5/44/50, temperatures
               -3..50 and beyond, non-finite and out-of-domain inputs (which exception Python raised), ties
Path signature of a solve: one bit per bisection step (1: the low end moved), the number of steps and how it ended
('low', 'high' or 'none' at the ends, 'mid' after bisection); recorded by wrapping chemistry.solve with a literal
twin that is checked, call by call, to return exactly what solve returns."""
import dataclasses
import gzip
import hashlib
import io
import json
import math
import os
import platform
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SEED = 20261105
FORMAT = 1
GEOMETRY_FULL = 120
FORMULA_MODULES = ['farm/water/chemistry.py', 'farm/water/deffeyes.py', 'farm/water/dosing.py', 'farm/water/charts.py',
                   'farm/water/calculation.py', 'farm/water/evaluate.py']


def setup():
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from django.utils import translation
    translation.activate('en')


# ---- values as JSON -------------------------------------------------------------------------------------------
def plain(value):
    """A value as JSON: floats exact (repr), non-finite floats as the strings 'nan', 'inf', '-inf', enums by value,
    lazy texts in English, dataclasses as dicts, tuples as lists."""
    if isinstance(value, bool) or value is None or isinstance(value, (int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else repr(value)
    if hasattr(value, 'value') and value.__class__.__module__.endswith('evaluate'):
        return value.value
    if dataclasses.is_dataclass(value):
        return {field.name: plain(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [plain(item) for item in (sorted(value) if isinstance(value, (set, frozenset)) else value)]
    return str(value)


def attempt(function, *args, **kwargs):
    """{'value': result} or {'raises': exception class name}: which inputs Python refuses is part of the reference."""
    try:
        return {'value': plain(function(*args, **kwargs))}
    except Exception as error:          # noqa: BLE001  (the class is what is recorded)
        return {'raises': type(error).__name__}


# ---- the solver's path ----------------------------------------------------------------------------------------
class PathRecorder:
    """Wraps chemistry.solve: a literal twin records the sign decisions, and every call is checked to return the
    same float as the original (the recorder never changes a result)."""

    def __init__(self, chemistry):
        self.chemistry, self.original, self.paths = chemistry, chemistry.solve, []

    def twin(self, function, low, high):
        at_low, at_high = function(low), function(high)
        if at_low == 0:
            return low, 'low', 0, 0
        if at_high == 0:
            return high, 'high', 0, 0
        if (at_low > 0) == (at_high > 0):
            return None, 'none', 0, 0
        bits = steps = 0
        for _step in range(200):
            middle = (low + high) / 2
            at_middle = function(middle)
            moved_low = (at_middle > 0) == (at_low > 0)
            bits = (bits << 1 | moved_low) & 0xFFFFFFFFFFFFFFFF
            steps += 1
            if moved_low:
                low, at_low = middle, at_middle
            else:
                high = middle
            if high - low < 1e-10:
                break
        return (low + high) / 2, 'mid', steps, bits

    def solve(self, function, low, high):
        result = self.original(function, low, high)
        twin, end, steps, bits = self.twin(function, low, high)
        if not (result == twin or (result is None and twin is None)):
            raise AssertionError(f'the path recorder disagrees with solve: {result!r} != {twin!r}')
        self.paths.append({'end': end, 'steps': steps, 'bits': f'{bits:016x}'})
        return result

    def __enter__(self):
        self.chemistry.solve = self.solve
        return self

    def __exit__(self, *exc):
        self.chemistry.solve = self.original

    def take(self):
        paths, self.paths = self.paths, []
        return paths


# ---- the corpus -------------------------------------------------------------------------------------------------
TEMPERATURES = [-3.0, 0.0, 2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0, 25.0, 28.0, 30.0, 33.0, 35.0,
                40.0, 45.0, 50.0]
SALINITIES = [0.0, 0.001, 0.01, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0, 2.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0, 44.0,
              50.0]
PRESSURES = [1.0, 0.95, 0.9, 0.8, 1.02]
ALTITUDES = [0.0, 100.0, 500.0, 1000.0, 2500.0]


def constants_block(c, rng):
    pairs = [(t, s) for t in TEMPERATURES for s in SALINITIES]
    pairs += [(round(rng.uniform(-3, 50), 3), round(rng.uniform(0, 50), 3)) for _ in range(600)]
    pairs += [(rng.uniform(-3, 50), rng.uniform(0, 50)) for _ in range(200)]          # full-precision draws
    for t, s in pairs:
        eq = c.equilibria(t, s)
        yield {'temp_c': t, 'salinity': s, 'equilibria': plain(eq),
               'free_to_sws': c._free_to_sws(t, s), 'free_to_total': c._free_to_total(t, s),
               'sws_to_nbs': c._sws_to_nbs(t, s), 'activity_h': c._activity_coefficient_h(t, s),
               'ionic_strength': c._ionic_strength(s), 'total_boron': c._total_boron(s),
               'total_sulfate': c._total_sulfate(s), 'total_fluoride': c._total_fluoride(s),
               'ks': attempt(c._ks, t, s), 'kf': attempt(c._kf, t, s),
               'k1_sws': c.k1_sws(t, s), 'k2_sws': c.k2_sws(t, s), 'kw_total': c.kw_total(t, s),
               'kb_total': c.kb_total(t, s), 'k_nh4_sws': c.k_nh4_sws(t, s), 'pk_nh4': c.pk_nh4(t, s),
               'k_h2s_total': c.k_h2s_total(t, s), 'ksp_calcite': c.ksp_calcite(t, s),
               'ksp_aragonite': c.ksp_aragonite(t, s), 'k0_co2': c.k0_co2(t, s),
               'vapour_pressure_atm': c.vapour_pressure_atm(t),
               'oxygen_solubility': {repr(p): c.oxygen_solubility(t, s, p) for p in PRESSURES},
               'co2_from_air': {repr(p): c.co2_from_air(t, s, p) for p in PRESSURES},
               'ph_free_7': c.ph_free(7.0, t, s), 'nh3_fraction_7_5': c.nh3_fraction(7.5, t, s)}
    for altitude in ALTITUDES + [rng.uniform(0, 3000) for _ in range(20)]:
        yield {'altitude_m': altitude, 'pressure_atm': c.pressure_atm(altitude)}


def carbonate_block(c, d, recorder, rng):
    grid = [(t, s, ph, alk) for t in (0.0, 8.0, 15.0, 25.0, 40.0) for s in (0.0, 1.0, 15.0, 35.0)
            for ph in (4.5, 6.0, 7.0, 7.5, 8.0, 9.0, 11.0) for alk in (10.0, 80.0, 300.0)]
    grid += [(rng.uniform(0, 40), rng.choice([0.0, 0.2, rng.uniform(0, 45)]), rng.uniform(4, 12), rng.uniform(1, 800))
             for _ in range(1500)]
    for t, s, ph, alk_mg in grid:
        eq = c.equilibria(t, s)
        alk = alk_mg / c.MG_CACO3_PER_MEQ
        dic = eq.dic(alk, ph)
        record = {'temp_c': t, 'salinity': s, 'ph': ph, 'alkalinity_mg_l': alk_mg, 'alkalinity_meq': alk,
                  'hydrogen': eq.hydrogen(ph), 'fractions': plain(eq.fractions(ph)), 'isoline': plain(eq.isoline(ph)),
                  'dic': dic, 'alkalinity_back': eq.alkalinity(dic, ph), 'co2': eq.co2(dic, ph),
                  'carbonate': eq.carbonate(dic, ph), 'nh3_share': eq.nh3_share(ph), 'h2s_share': eq.h2s_share(ph),
                  'ph_of_hydrogen': eq.ph_of(eq.hydrogen(ph)),
                  'alkalinity_floor': d.alkalinity_floor(t, s, ph)}
        recorder.take()
        record['ph_at'] = attempt(eq.ph_at, dic, alk)
        record['ph_at_path'] = recorder.take()
        for co2_mg in (5.0, 15.0, 40.0):
            key = f'ph_where_co2_{co2_mg:g}'
            record[key] = attempt(eq.ph_where_co2, alk, co2_mg / c.MG_CO2_PER_MMOL)
            record[key + '_path'] = recorder.take()
        record['ph_where_co2_at_dic'] = attempt(eq.ph_where_co2_at_dic, dic, 0.3)
        record['ph_where_carbonate'] = attempt(eq.ph_where_carbonate, dic, 0.05)
        record['ph_where_nh3'] = attempt(eq.ph_where_nh3, 0.5, 0.0103)
        record['ph_where_h2s'] = attempt(eq.ph_where_h2s, 3.0 * c.H2S_PER_S, 2.0)
        yield record


LIMIT_SETS = [
    {}, {'nh3_n_mg_l': 0.0103, 'co2_mg_l': 15.0, 'h2s_ug_l': 2.0, 'alkalinity_low_mg_l': 50.0, 'alkalinity_high_mg_l': 150.0},
    {'nh3_n_mg_l': 0.02, 'co2_mg_l': 10.0, 'alkalinity_low_mg_l': 80.0, 'alkalinity_high_mg_l': 200.0},
    {'nh3_n_mg_l': 0.05, 'co2_mg_l': 40.0, 'h2s_ug_l': 25.0, 'alkalinity_low_mg_l': 50.0, 'alkalinity_high_mg_l': 600.0},
    {'co2_mg_l': 15.0, 'alkalinity_low_mg_l': 50.0, 'alkalinity_high_mg_l': 150.0},
    {'nh3_n_mg_l': 0.0103, 'co2_mg_l': 15.0, 'alkalinity_low_mg_l': 150.0, 'alkalinity_high_mg_l': 50.0},
]


def waters(d, rng, count):
    """Seeded waters from fresh to sea water, with and without each optional value, with a limit set and a target."""
    for _ in range(count):
        s = rng.choice([0.0, 0.2, 1.0, rng.uniform(0, 45), 35.0])
        water = d.Water(temperature_c=rng.uniform(0, 35), salinity_ppt=s, ph=rng.uniform(5.5, 9.5),
                        alkalinity_mg_l=rng.uniform(5, 600),
                        tan_mg_l=rng.choice([None, rng.uniform(0.01, 10)]),
                        total_sulfide_ug_l=rng.choice([None, rng.uniform(0.1, 500)]),
                        calcium_mg_l=rng.choice([None, rng.uniform(5, 500)]),
                        oxygen_mg_l=rng.choice([None, rng.uniform(2, 14)]))
        limits = d.Limits(**rng.choice(LIMIT_SETS))
        target = rng.choice([None, d.Target(rng.uniform(6.5, 8.5), rng.uniform(30, 300))])
        pressure = rng.choice([1.0, 1.0, 0.95, 0.88])
        yield water, limits, target, pressure


def analysis_record(d, recorder, water, limits, target, pressure):
    recorder.take()
    record = {'water': plain(water), 'limits': plain(limits), 'target': plain(target), 'pressure': pressure}
    try:
        a = d.analyse(water, limits, target, pressure)
    except Exception as error:          # noqa: BLE001
        record['raises'] = type(error).__name__
        return record, None
    fields = {field.name: plain(getattr(a, field.name)) for field in dataclasses.fields(a)
              if field.name not in ('water', 'limits', 'target', 'equilibria')}
    for name in ('co2', 'nh3', 'h2s'):
        border = getattr(a, name)
        fields[name].update(on_chart=border.on_chart, everywhere=border.everywhere, off_chart=border.off_chart)
    fields['nh3_share_pct'] = a.nh3_share_pct
    fields['h2s_share_pct'] = a.h2s_share_pct
    record['analysis'] = fields
    record['paths'] = recorder.take()
    return record, a


def area(polygon):
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1])) / 2


def length(polyline):
    return sum(math.dist(p, q) for p, q in zip(polyline, polyline[1:]))


def summary(points):
    points = [tuple(point) for point in points]
    return {'count': len(points), 'area': area(points) if len(points) >= 3 else 0.0, 'length': length(points),
            'first': plain(points[0]) if points else None, 'last': plain(points[-1]) if points else None}


def geometry_record(d, shape, full):
    record = {'box': plain(shape.box), 'point': plain(shape.point), 'target': plain(shape.target),
              'notes': [str(note) for note in shape.notes],
              'isolines': [[iso.ph, iso.labelled, plain(iso.segment)] for iso in shape.isolines]}
    if full:
        record['regions'] = plain(shape.regions)
        record['boundaries'] = plain(shape.boundaries)
        record['omega'] = plain(shape.omega)
    else:
        record['regions'] = {key: summary(polygon) for key, polygon in shape.regions.items()}
        record['boundaries'] = {key: [summary(line) for line in lines] for key, lines in shape.boundaries.items()}
        record['omega'] = {key: [summary(line) for line in lines] for key, lines in shape.omega.items()}
    return record


def analysis_and_geometry_blocks(c, d, recorder, rng):
    analyses, geometries = [], []
    for index, (water, limits, target, pressure) in enumerate(waters(d, rng, 1500)):
        record, a = analysis_record(d, recorder, water, limits, target, pressure)
        analyses.append(record)
        if a is not None and index < 600:
            recorder.take()
            try:
                shape = d.geometry(a)
                geometries.append({'water': record['water'], 'limits': record['limits'], 'target': record['target'],
                                   'pressure': pressure, 'full': index < GEOMETRY_FULL,
                                   'geometry': geometry_record(d, shape, index < GEOMETRY_FULL),
                                   'solves': len(recorder.take())})
            except Exception as error:      # noqa: BLE001
                geometries.append({'water': record['water'], 'raises': type(error).__name__})
    return analyses, geometries


def dosing_block(c, d, dosing, rng):
    keys = [reagent.key for reagent in dosing.REAGENTS]
    pairs = [[a, b] for i, a in enumerate(keys) for b in keys[i + 1:]]
    starts = [(12.0, 1.0, 7.0, 80.0), (25.0, 35.0, 8.1, 115.0), (8.0, 0.0, 6.6, 30.0)]
    targets = [(7.5, 100.0), (7.2, 60.0), (6.8, 150.0), (8.3, 80.0), (6.5, 40.0), (7.0, 80.0), (8.0, 200.0)]
    for t, s, ph, alk_mg in starts:
        eq = c.equilibria(t, s)
        start = (eq.dic(alk_mg / c.MG_CACO3_PER_MEQ, ph), alk_mg / c.MG_CACO3_PER_MEQ)
        for target_ph, target_mg in targets:
            end = (eq.dic(target_mg / c.MG_CACO3_PER_MEQ, target_ph), target_mg / c.MG_CACO3_PER_MEQ)
            for chosen in [dosing.DEFAULT_REAGENTS, keys] + pairs:
                for volume in (None, 1.0, 37.5):
                    yield {'kind': 'recipes', 'temp_c': t, 'salinity': s, 'ph': ph, 'alkalinity_mg_l': alk_mg,
                           'target': [target_ph, target_mg], 'chosen': list(chosen), 'volume': volume,
                           'recipes': attempt(dosing.recipes, start, end, list(chosen), volume),
                           'visual': attempt(dosing.visual, start, end, list(chosen)),
                           'at_target': dosing.at_target(start, end)}
        for amounts in ({'nahco3': 50.0}, {'naoh': 20.0, 'degas': 30.0}, {'hcl': 40.0},
                        {'na2co3': 10.0, 'caco3': 5.0, 'caoh2': 5.0, 'cao': 5.0, 'co2': 10.0}, {'degas': 500.0},
                        {'hcl': 4000.0}):
            for volume in (1.0, 2.5):
                yield {'kind': 'simulate', 'temp_c': t, 'salinity': s, 'ph': ph, 'alkalinity_mg_l': alk_mg,
                       'amounts': amounts, 'volume': volume,
                       'steps': attempt(dosing.simulate, eq, start, ph, amounts, volume,
                                        c.co2_from_air(t, s, 1.0))}


def plots_block(d, charts, rng):
    for water, limits, target, pressure in waters(d, rng, 40):
        try:
            a = d.analyse(water, limits, target, pressure)
        except Exception as error:          # noqa: BLE001
            yield {'water': plain(water), 'raises': type(error).__name__}
            continue
        found = {}
        for key, plot in charts.plots(a).items():
            found[key] = None if plot is None else {
                'x': plain(plot.x), 'y': plain(plot.y), 'unit': plot.unit,
                'series': [[name, plain(points)] for name, _label, points in plot.series],
                'bands': plain([band[:3] for band in plot.bands]) if plot.bands else [],
                'verticals': plain([vertical[:2] for vertical in plot.verticals]),
                'horizontals': plain([horizontal[:2] for horizontal in plot.horizontals]),
                'dots': plain([dot[:3] for dot in plot.dots])}
        yield {'water': plain(water), 'limits': plain(limits), 'plots': found}


# [temperature, salinity, pH, alkalinity mg/L, changes]: driver.ts's edges, then its chart waters
B1_CASES = [
    (12.0, 1.0, 7.0, 80.0, {'tan_mg_l': 0.0103}), (12.0, 1.0, 7.0, 80.0, {'tan_mg_l': 0.005}),
    (12.0, 1.0, 7.0, 80.0, {'tan_mg_l': 0.01031}), (12.0, 1.0, 7.0, 80.0, {'total_sulfide_ug_l': 0.0}),
    (12.0, 1.0, 7.0, 80.0, {'h2s_ug_l': 1e6}), (12.0, 1.0, 7.0, 80.0, {'total_sulfide_ug_l': 20000.0, 'h2s_ug_l': 0.01}),
    (12.0, 1.0, 7.0, 80.0, {'total_sulfide_ug_l': 10.0, 'h2s_ug_l': 10 * 34.08088 / 32.065 * 0.99999}),
    (12.0, 1.0, 6.25, 80.0, {}), (12.0, 1.0, 11.25, 80.0, {}), (12.0, 35.0, 6.25, 120.0, {}),
    (12.0, 35.0, 11.25, 120.0, {}), (12.0, 0.0, 4.5, 20.0, {}), (12.0, 0.0, 10.5, 800.0, {}), (0.0, 50.0, 8.0, 115.0, {}),
    (40.0, 0.0, 6.0, 20.0, {}), (12.0, 1.0, 7.0, 0.5, {}), (25.0, 35.0, 8.1, 115.0, {}),
] + [(t, s, ph, alk, {'tan_mg_l': tan, 'nh3_n_mg_l': nh3, 'co2_mg_l': co2, 'total_sulfide_ug_l': st, 'h2s_ug_l': 2.0,
                      'calcium_mg_l': 412 * s / 35 if s >= 5 else 400.0})
     for t, s in ((12.0, 1.0), (12.0, 0.0), (4.0, 35.0), (25.0, 35.0), (20.0, 15.0), (8.0, 5.0), (30.0, 0.0), (0.0, 50.0))
     for ph, alk, tan, nh3, co2, st in ((7.0, 80.0, 0.5, 0.0103, 15.0, 1.0), (7.5, 150.0, 2.0, 0.02, 10.0, 2.5),
                                        (6.6, 40.0, 6.0, 0.05, 40.0, 3000.0))]


def edges_block(c, d, recorder):
    """Block D: the borders of the domain and the ties, each with what Python did."""
    for t, s in [(-273.15, 0.0), (-273.15, 35.0), (60.0, 0.0), (100.0, 35.0), (10.0, -1.0), (10.0, 1000.0),
                 (10.0, 995.0), (float('nan'), 0.0), (10.0, float('nan')), (float('inf'), 35.0), (-3.0, 0.0),
                 (50.0, 50.0), (10.0, 4.999999999), (10.0, 5.0), (10.0, 44.0), (10.0, 44.000000001)]:
        yield {'kind': 'equilibria', 'temp_c': plain(t), 'salinity': plain(s), 'result': attempt(c.equilibria, t, s),
               'oxygen': attempt(c.oxygen_solubility, t, s, 1.0), 'co2_from_air': attempt(c.co2_from_air, t, s, 1.0)}
    for altitude in (-500.0, 44330.0, 44331.0, 1e6, float('nan')):
        yield {'kind': 'pressure', 'altitude_m': plain(altitude), 'result': attempt(c.pressure_atm, altitude)}
    # impossible pH and alkalinity pairs: at the floor and 1e-9 either side
    for t, s, ph in [(10.0, 0.0, 9.0), (10.0, 0.0, 10.0), (10.0, 0.0, 11.0), (10.0, 0.0, 12.0), (25.0, 35.0, 9.0),
                     (25.0, 35.0, 12.0), (2.0, 0.2, 10.5), (30.0, 15.0, 11.5)]:
        floor = d.alkalinity_floor(t, s, ph)
        for alk in (floor - 1e-9, floor, floor + 1e-9, math.nextafter(floor, math.inf)):
            recorder.take()
            yield {'kind': 'floor', 'temp_c': t, 'salinity': s, 'ph': ph, 'alkalinity_mg_l': alk, 'floor': floor,
                   'possible': d.possible(t, s, ph, alk),
                   'analysis': analysis_record(d, recorder, d.Water(t, s, ph, alk), d.Limits(co2_mg_l=15.0), None,
                                               1.0)[0]}
    # pH outside the chart and the solver's range
    for ph in (-1.0, 0.0, 3.99, 12.51, 14.0, 15.0):
        yield {'kind': 'ph', 'ph': ph, 'analysis': analysis_record(d, recorder, d.Water(12.0, 1.0, ph, 80.0, 0.5),
                                                                    d.Limits(0.0103, 15.0), None, 1.0)[0]}
    # limits on the TAN, at and beside it
    for tan in (0.0103, 0.0102999999, 0.0103000001, 0.0):
        yield {'kind': 'nh3_limit', 'tan': tan, 'analysis': analysis_record(
            d, recorder, d.Water(12.0, 1.0, 7.0, 80.0, tan_mg_l=tan), d.Limits(nh3_n_mg_l=0.0103), None, 1.0)[0]}
    # the box's edges: needed x 1.1 at 6 and at a 1-2-5 step
    for needed_meq in (6 / 1.1, math.nextafter(6 / 1.1, 0), math.nextafter(6 / 1.1, 10), 12 / 1.1, 60 / 1.1, 7e8):
        mg = needed_meq * c.MG_CACO3_PER_MEQ
        try:
            a = d.analyse(d.Water(12.0, 1.0, 7.0, 80.0), d.Limits(alkalinity_low_mg_l=50.0, alkalinity_high_mg_l=mg))
            box = attempt(d.box_of, a)
        except Exception as error:          # noqa: BLE001
            box = {'raises': type(error).__name__}
        yield {'kind': 'box', 'alkalinity_high_mg_l': mg, 'box': box}
    # the B1 cases (owner amendment B1): the edges of farm/tests/deffeyes_reference/driver.ts and its 24 chart
    # waters, each a complete water the source's engine takes as well
    for t, s, ph, alk, changes in B1_CASES:
        values = {'tan_mg_l': 0.5, 'total_sulfide_ug_l': 1.0, 'calcium_mg_l': 400.0, 'nh3_n_mg_l': 0.0103,
                  'co2_mg_l': 15.0, 'h2s_ug_l': 2.0, **changes}
        water = d.Water(t, s, ph, alk, tan_mg_l=values['tan_mg_l'], total_sulfide_ug_l=values['total_sulfide_ug_l'],
                        calcium_mg_l=values['calcium_mg_l'])
        limits = d.Limits(values['nh3_n_mg_l'], values['co2_mg_l'], values['h2s_ug_l'], 50.0, 150.0)
        record, _analysis = analysis_record(d, recorder, water, limits, d.Target(7.5, 120.0), 1.0)
        yield {'kind': 'b1_case', **record}
    # Omega's salinity window and calcium
    for s in (4.999, 5.0, 44.0, 44.001):
        a = d.analyse(d.Water(10.0, s, 8.0, 115.0, calcium_mg_l=400.0), d.Limits())
        yield {'kind': 'omega', 'salinity': s,
               'geometry': geometry_record(d, d.geometry(a, layers=frozenset({'omega'})), True)}


# ---- writing ----------------------------------------------------------------------------------------------------
def encode(records):
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode='wb', mtime=0, compresslevel=9) as stream:
        for record in records:
            stream.write(json.dumps(record, sort_keys=True, allow_nan=False, ensure_ascii=False).encode('utf-8'))
            stream.write(b'\n')
    return buffer.getvalue()


def record_all():
    """{block: [records]} of the whole corpus."""
    setup()
    from farm.water import charts, chemistry as c, deffeyes as d, dosing
    rng = random.Random(SEED)
    c.equilibria.cache_clear()
    with PathRecorder(c) as recorder:
        blocks = {'constants': list(constants_block(c, rng)),
                  'carbonate': list(carbonate_block(c, d, recorder, rng))}
        blocks['analysis'], blocks['geometry'] = analysis_and_geometry_blocks(c, d, recorder, rng)
        blocks['dosing'] = list(dosing_block(c, d, dosing, rng))
        blocks['plots'] = list(plots_block(d, charts, rng))
        blocks['edges'] = list(edges_block(c, d, recorder))
    return blocks


def git_blob(path):
    try:
        return subprocess.run(['git', 'hash-object', str(path)], capture_output=True, text=True, check=True,
                              cwd=ROOT).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        data = path.read_bytes().replace(b'\r\n', b'\n')
        return hashlib.sha1(b'blob %d\0' % len(data) + data).hexdigest()


def manifest(encoded):
    return {
        'format': FORMAT, 'golden_version': 'v1', 'seed': SEED,
        'recorded_with': {'python': platform.python_version(), 'libc': list(platform.libc_ver()),
                          'machine': platform.machine(), 'system': platform.system()},
        'formula_modules': {name: {'git_blob': git_blob(ROOT / name),
                                   'sha256': hashlib.sha256((ROOT / name).read_bytes().replace(b'\r\n', b'\n')).hexdigest()}
                            for name in FORMULA_MODULES},
        'recorder_sha256': hashlib.sha256(Path(__file__).read_bytes().replace(b'\r\n', b'\n')).hexdigest(),
        'blocks': {name: {'records': count, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
                   for name, (count, data) in encoded.items()},
    }


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    if platform.system() != 'Linux':
        raise SystemExit('The golden reference is recorded in the Linux runner image only (README, chemcore).')
    encoded = {name: (len(records), encode(records)) for name, records in record_all().items()}
    for name, (_count, data) in encoded.items():
        (out / f'{name}.jsonl.gz').write_bytes(data)
    (out / 'manifest.json').write_text(json.dumps(manifest(encoded), indent=2, sort_keys=True) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else ROOT / 'chemcore' / 'golden' / 'v1')
