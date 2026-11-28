"""Third review of chemcore-experimental's gas_exchange (branch wip/chemcore-gas-exchange, 2660645d): every expected
value of tests/gas_exchange.rs as it now stands, recomputed from the reviewer's own functions (independent_check.py in
the same folder: written from the equations, the vessel solved for its pH where the Rust solves for its DIC), with the
corrections of reviews 1 and 2 and this round's choices:

- C1: Douabul & Riley (1979) for H2S, B read as review 1 gives it;
- C2: CO2 per partial pressure = Weiss's K0 x the fugacity coefficient of CO2 in air, in every CO2 gas/water ratio;
- C3: a saturation for each gas;
- C4: the depth test's H2S exponent 2 (K0_H2S / K0_CO2,per partial pressure) (0.712)^(2/3) (F3: CO2 with its fugacity);
- review 2, Q2: H2S extrapolated below 2 degC down to the freezing point of the water (UNESCO 1983), measured 2-30 degC;
- review 2, F2: the CO2 side of a contact given where H2S has no solubility (above 30 degC, below freezing).

It also checks the cold values against the IUPAC low-temperature pure-water equation and the extrapolated exponent range.
Standard library only. Run:

    python -I independent_check_3.py [chemcore folder]

The chemcore folder is read for its golden files (formula 1 at 0 and 12 degC, S 35, golden/v1; formula 4, golden/v4) and,
when present, experimental/tests/gas_exchange.rs, whose every long literal is then matched against these values. Default:
the chemcore folder holding this file when it sits in chemcore/experimental/reference/; otherwise give it.
"""
import gzip
import importlib.util
import json
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if len(sys.argv) > 1:
    CHEMCORE = Path(sys.argv[1])
elif HERE.name == 'reference' and HERE.parent.name == 'experimental':
    CHEMCORE = HERE.parents[1]
else:
    sys.exit('give the chemcore folder: python -I independent_check_3.py <chemcore>')

spec = importlib.util.spec_from_file_location('independent_check_reviewer', HERE / 'independent_check.py')
ic = importlib.util.module_from_spec(spec)
_argv = sys.argv
sys.argv = [sys.argv[0], str(CHEMCORE)]
spec.loader.exec_module(ic)
sys.argv = _argv

D_FACTOR = 0.712 ** (2 / 3)
MEASURED_T = (2.0, 30.0)
SALINITY = (0.0, 40.028)


def freezing_point(s):
    """UNESCO (1983), Fofonoff & Millard, at 0 dbar: -0.0575 S + 1.710523e-3 S^1.5 - 2.154996e-4 S^2."""
    return -0.0575 * s + 1.710523e-3 * s ** 1.5 - 2.154996e-4 * s * s


def h2s_validity(t, s):
    if not (SALINITY[0] <= s <= SALINITY[1]) or t > MEASURED_T[1]:
        return None
    if t >= MEASURED_T[0]:
        return 'measured'
    return 'extrapolated' if t >= freezing_point(s) else None


def k0c(t, s, p=1.0):
    return ic.k0_co2(t, s) * ic.co2_fugacity_factor(t, p)


def iupac_pure(t):
    """IUPAC SDS-32 (1988) p. 1, low-temperature equation, as mol/L per atm partial pressure (review 2)."""
    return ic.x_to_molar(math.exp(-14.761 + 2507.2 / (t + ic.KELVIN)), t)


def depth(ratio, t, s, p=1.0):
    x = 1 / ratio - 1
    co2 = 1 - x * x
    if h2s_validity(t, s) is None:
        return co2, None
    k = ic.k0_h2s_dr(t, s) / k0c(t, s, p) * D_FACTOR
    return co2, 1 - x ** (2 * k)


def contact(e, ta, ph, r, sc, sh, p=1.0):
    t, s = e.t_c, e.s
    kh = ic.k0_h2s_dr(t, s) if h2s_validity(t, s) else 1.0   # the H2S part is dropped where invalid
    got = ic.contact(e, ta, ph, r, ic.AIR_CO2, p, sc, sh, k0c(t, s, p), kh)
    return got if h2s_validity(t, s) else (got[0], got[1], got[2], None)


def v1_equilibria(t, s):
    with gzip.open(CHEMCORE / 'golden' / 'v1' / 'constants.jsonl.gz', 'rt') as f:
        for line in f:
            r = json.loads(line)
            if r.get('temp_c') == t and r.get('salinity') == s:
                return r['equilibria']
    return None


def v4_constants():
    out = {}
    with gzip.open(CHEMCORE / 'golden' / 'v4' / 'waters.jsonl.gz', 'rt') as f:
        for line in f:
            r = json.loads(line)
            if r['ions'] == {}:
                out[(r['temp_c'], r['salinity'], r['alkalinity_mg_l'])] = r['v4']['constants']
    return out


def main():
    values = []   # (name, value)

    def put(name, value):
        values.append((name, value))

    # -- the formula-1 equilibria against golden v1 at the temperatures the vessel tests use
    for t in (0.0, 12.0):
        gold, mine = v1_equilibria(t, 35.0), ic.formula1(t, 35.0)
        worst = max(abs(getattr(mine, k) / gold[k] - 1) for k in ('k1', 'k2', 'kw', 'kb', 'boron', 'k_h2s', 'ph_offset'))
        print(f'formula 1 at {t} C, S35 against golden v1: worst relative difference {worst:.1e}')

    # -- C1 and the cold extrapolation
    for t, s in ((12, 35), (25, 0), (2, 0), (2, 40), (30, 0), (30, 40), (0, 35), (-1.9, 35), (1, 35), (0, 0)):
        put(f'k0_h2s({t}, {s}) [{h2s_validity(t, s)}]', ic.k0_h2s_dr(t, s))
    put('freezing_point(35)', freezing_point(35))
    put('freezing_point(40)', freezing_point(40))
    put('IUPAC pure water 0 C', iupac_pure(0.0))
    put('IUPAC pure water -1.9 C', iupac_pure(-1.9))
    put('D&R(0, 0) / IUPAC(0) - 1', ic.k0_h2s_dr(0, 0) / iupac_pure(0.0) - 1)
    salting = math.exp(35 * (ic.DR_B_READ[0] + ic.DR_B_READ[1] * (271.25 / 100) + ic.DR_B_READ[2] * (271.25 / 100) ** 2))
    put('D&R(-1.9, 35) / salting / IUPAC(-1.9) - 1', ic.k0_h2s_dr(-1.9, 35) / salting / iupac_pure(-1.9) - 1)
    for t, s in ((1.99, 35), (2.0, 35), (30.0, 40.028), (-1.92, 35), (-1.93, 35), (30.01, 35), (-0.01, 0), (12, 40.03)):
        put(f'h2s_validity({t}, {s}) = {h2s_validity(t, s)}', float('nan'))

    # -- conversions
    t, s = 12.0, 35.0
    rt = ic.R_LATM * (t + ic.KELVIN)
    kd = ic.k0_h2s_dr(t, s)
    put('gas_over_water H2S 12/35', 1 / (kd * rt))
    put('gas_over_water(k0_co2) 12/35', 1 / (ic.k0_co2(t, s) * rt))
    put('h2s_from_gas(117, 12, 35, 1)', 117e-9 * kd * ic.M_H2S_2007 * 1e6)
    put('dried_gas_factor(12, 1)', 1 - ic.vapour_pressure_atm(12))
    for tc, p in ((5, 1), (12, 1), (20, 1), (12, 2)):
        put(f'co2_fugacity_coefficient({tc}, {p})', ic.co2_fugacity_factor(tc, p))
    put('co2_from_gas(3852, 12, 35, 1)', 3852e-6 * k0c(t, s) * ic.M_CO2 * 1000)
    put('co2_from_gas(3852, 12, 35, 1), partial pressure only (review 1)', 3852e-6 * ic.k0_co2(t, s) * ic.M_CO2 * 1000)

    # -- total sulfide and the vessel, formula 1 and 4 at 12 C S35, 2 meq/L, pH 7.2
    v4 = v4_constants()
    e1, e4 = ic.formula1(t, s), ic.from_constants(t, s, v4[(t, s, 200.0)])
    put('total_sulfide(0.5, f1, 7.2)', 0.5 / ic.share_h2s(e1, 7.2))
    put('total_sulfide(0.5, f4, 7.2)', 0.5 / ic.share_h2s(e4, 7.2))
    for label, e in (('f1', e1), ('f4', e4)):
        for r, sc, sh in ((0.01, 1.0, 1.0), (0.1, 1.0, 1.0), (0.01, 0.9, 0.9), (0.01, 0.9, 0.9975), (0.0, 1.0, 1.0)):
            if label == 'f4' and (r, sh) in ((0.01, 0.9975), (0.0, 1.0)):
                continue
            got = contact(e, 2.0, 7.2, r, sc, sh)
            for part, v in zip(('pH', 'co2_gas', 'co2_ratio', 'h2s_ratio'), got):
                put(f'{label} contact(r {r}, s {sc}/{sh}) {part}', v)
    a, b = contact(e1, 2.0, 7.2, 0.1, 1.0, 1.0), contact(e4, 2.0, 7.2, 0.1, 1.0, 1.0)
    put('F1: co2_ratio f4 - f1 at r 0.1', b[2] - a[2])
    put('F1: h2s_ratio f4 - f1 at r 0.1', b[3] - a[3])
    fresh = ic.from_constants(12.0, 0.0, v4[(12.0, 0.0, 200.0)])
    for part, v in zip(('pH', 'co2_gas', 'co2_ratio', 'h2s_ratio'), contact(fresh, 200 / 50.04345, 7.2, 0.01, 1.0, 1.0)):
        put(f'f4 fresh 12 C 200 mg/L contact(r 0.01) {part}', v)

    # -- F2: the CO2 side never waits on H2S (formula 1, S35, 2 meq/L, pH 7.2, r 0.01, s 1/1)
    for tc in (0.0, 32.0, -2.5):
        got = contact(ic.formula1(tc, 35.0), 2.0, 7.2, 0.01, 1.0, 1.0)
        for part, v in zip(('pH', 'co2_gas', 'co2_ratio', 'h2s_ratio'), got):
            put(f'f1 {tc} C contact(r 0.01) {part} [{h2s_validity(tc, 35.0)}]', v if v is not None else float('nan'))

    # -- bounds and the depth test (F3)
    hc, hh = 1 / (k0c(t, s) * rt), 1 / (kd * rt)
    put('ph_rise_bound(12, 35, 0.01, 1)', math.log10(1 + 0.01 * hc))
    put('h2s worst case at r 0.1', 1 / ((1 + 0.1 * hc) * (1 + 0.1 * hh)))
    for ratio in (0.8, 0.55):
        co2, h2s = depth(ratio, t, s)
        put(f'saturation_from_depths({ratio}, 12, 35, 1) CO2', co2)
        put(f'saturation_from_depths({ratio}, 12, 35, 1) H2S', h2s)
    before = 1 - (1 / 0.8 - 1) ** (2 * kd / ic.k0_co2(t, s) * D_FACTOR)
    put('saturation_from_depths(0.8) H2S without the fugacity (review 2)', before)
    ks = [(ic.k0_h2s_dr(tc / 10, sv) / k0c(tc / 10, sv) * f, tc / 10, sv, name)
          for tc in range(-19, 301) for sv in (0, 5, 10, 20, 30, 35, 40)
          if h2s_validity(tc / 10, sv)
          for f, name in ((D_FACTOR, '0.712^(2/3)'), (0.71 ** (2 / 3), '0.71^(2/3)'), (0.80 ** 0.5, '0.80^(1/2)'))]
    meas = [k for k in ks if k[1] >= 2.0]
    print(f'k over 2-30 C: {min(meas)[0]:.4f} to {max(meas)[0]:.4f}; with the extrapolated range: {min(ks)[0]:.4f} '
          f'({min(ks)[1]} C, S{min(ks)[2]}, {min(ks)[3]}) to {max(ks)[0]:.4f}')

    width = max(len(n) for n, _ in values)
    for name, v in values:
        print(f'{name:<{width}}  {v!r}')

    test = CHEMCORE / 'experimental' / 'tests' / 'gas_exchange.rs'
    if test.exists():
        text = test.read_text(encoding='utf-8')
        start = text.index('const DOUABUL_RILEY')
        table = text[start:text.index('];', start)]
        found = [tuple(map(float, m)) for m in re.findall(r'\((\d+\.\d+), (\d+\.\d+), (\d+\.\d+)\),', table)]
        print(f'\nthe 42-point table of the test is the review\'s listing: {found == [tuple(r) for r in ic.DR_TABLE]}')
        rest = text[:start] + text[text.index('];', start):]
        literals = [float(m) for m in re.findall(r'(?<![\w.])(\d+\.\d{8,})', rest)]
        mine = [abs(v) for _, v in values if v is not None and not math.isnan(v)]
        unmatched = [lit for lit in literals if not any(abs(lit - v) <= 1e-9 * max(1.0, lit) for v in mine)]
        print(f'long literals in the test: {len(literals)}; matched by a value above to 1e-9: '
              f'{len(literals) - len(unmatched)}; unmatched: {unmatched}')


if __name__ == '__main__':
    main()
