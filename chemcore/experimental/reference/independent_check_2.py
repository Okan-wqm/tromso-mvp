"""Second review of chemcore-experimental's gas_exchange (branch wip/chemcore-gas-exchange, 4d72bd91): every expected
value of tests/gas_exchange.rs recomputed directly from the reviewer's own functions (independent_check.py, beside this
file; NOT through the implementer's reference/expected_values.py), the 42-point table compared with the review's listing,
the exponent range of saturation_from_depths, the extrapolation of Douabul & Riley below 2 degC, and the
"water below the air" case. Standard library only:

    python -I independent_check_2.py [worktree]     (default: the checkout holding this file)

The second review's script as delivered (2026-11-28, for 4d72bd91), but for its default path. It holds the expected
values of that commit: the depth test's H2S values it lists predate F3 (the CO2 solubility with its fugacity).
"""
import gzip
import importlib.util
import json
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WT = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parents[3])
CHEMCORE = f'{WT}/chemcore'
spec = importlib.util.spec_from_file_location('ic', HERE / 'independent_check.py')
ic = importlib.util.module_from_spec(spec)
sys.argv = sys.argv[:1]
spec.loader.exec_module(ic)

TEST = Path(f'{CHEMCORE}/experimental/tests/gas_exchange.rs').read_text(encoding='utf-8')
D_FACTOR = 0.712 ** (2 / 3)


def k0c(t, s, p=1.0):
    """CO2 per partial pressure: Weiss per fugacity x the fugacity coefficient (C2)."""
    return ic.k0_co2(t, s) * ic.co2_fugacity_factor(t, p)


def v4_constants():
    out = {}
    with gzip.open(f'{CHEMCORE}/golden/v4/waters.jsonl.gz', 'rt') as f:
        for line in f:
            r = json.loads(line)
            if r['ions'] == {}:
                out[(r['temp_c'], r['salinity'], r['alkalinity_mg_l'])] = r['v4']['constants']
    return out


def main():
    rows = []

    def row(name, want, got, tol):
        rows.append((name, want, got, got - want, abs(got - want) <= tol))

    rel = 1e-7
    t, s = 12.0, 35.0
    rt = ic.R_LATM * (t + ic.KELVIN)
    kd = ic.k0_h2s_dr(t, s)
    for (tc, sc, want) in ((12, 35, 0.1372513877665758), (25, 0, 0.1019504857840442), (2, 0, 0.19507990370865505),
                           (2, 40, 0.18228729585575598), (30, 0, 0.09077570549507918), (30, 40, 0.0878610504504237)):
        row(f'k0_h2s({tc}, {sc})', want, ic.k0_h2s_dr(tc, sc), rel * want)
    row('gas_over_water H2S 12/35', 0.3113811419911722, 1 / (kd * rt), rel * 0.31)
    row('gas_over_water(k0_co2) 12/35', 1.0122273837161964, 1 / (ic.k0_co2(t, s) * rt), rel)
    row('h2s_from_gas(117, 12, 35, 1)', 0.5472848249278183, 117e-9 * kd * ic.M_H2S_2007 * 1e6, rel * 0.55)
    row('dried_gas_factor(12, 1)', 0.9861608398007197, 1 - ic.vapour_pressure_atm(12), rel)
    for tc, p, want in ((5, 1, 0.9958898969240669), (12, 1, 0.9962480968397126), (20, 1, 0.9966083945861017),
                        (12, 2, 0.9925102704567494)):
        row(f'co2_fugacity_coefficient({tc}, {p})', want, ic.co2_fugacity_factor(tc, p), rel)
    row('co2_from_gas(3852, 12, 35, 1)', 7.1306839373666, 3852e-6 * k0c(t, s) * ic.M_CO2 * 1000, rel * 7.13)
    e1 = ic.formula1(t, s)
    v4 = v4_constants()
    e4 = ic.from_constants(t, s, v4[(t, s, 200.0)])
    row('total_sulfide f1', 1.5765892793905285, 0.5 / ic.share_h2s(e1, 7.2), rel * 1.58)
    row('total_sulfide f4', 1.6653942428024509, 0.5 / ic.share_h2s(e4, 7.2), rel * 1.67)
    contacts = [
        ('f1', e1, 0.01, 1.0, 1.0, (7.2033821212367215, 0.0038663102567234615, 0.9920960480067164, 0.9937136394922534)),
        ('f1', e1, 0.1, 1.0, 1.0, (7.232134322060043, 0.003613923053279545, 0.9273334370215407, 0.9413381162281969)),
        ('f1', e1, 0.01, 0.9, 0.9, (7.203045704103651, 0.0035244270846338703, 0.9043687521125877, 0.8949039824038976)),
        ('f1', e1, 0.01, 0.9, 0.9975, (7.203045704103651, 0.0035244270846338703, 0.9043687521125877,
                                        0.9917569654532955)),
        ('f1', e1, 0.0, 1.0, 1.0, (7.2, 0.003897112849599101, 1.0, 1.0)),
        ('f4', e4, 0.01, 1.0, 1.0, (7.2032769551952605, 0.0035669734905498, 0.9923294656417763, 0.9938037074528514)),
        ('f4', e4, 0.1, 1.0, 1.0, (7.231123629311229, 0.0033408895614940007, 0.9294330788016392, 0.9422067598709907)),
        ('f4', e4, 0.01, 0.9, 0.9, (7.20295101179881, 0.0032547359764031397, 0.9054652132475948, 0.8949769647372665)),
    ]
    got_of = {}
    for name, e, r, sc_, sh_, want in contacts:
        got = ic.contact(e, 2.0, 7.2, r, ic.AIR_CO2, 1.0, sc_, sh_, k0c(t, s), kd)
        got_of[(name, r, sc_, sh_)] = got
        tag = f'{name} contact(r {r}, s {sc_}/{sh_})'
        row(tag + ' pH', want[0], got[0], 1e-8)
        row(tag + ' co2_gas', want[1], got[1], rel * want[1])
        row(tag + ' co2_ratio', want[2], got[2], rel)
        row(tag + ' h2s_ratio', want[3], got[3], rel)
    moved_c = got_of[('f4', 0.1, 1.0, 1.0)][2] - got_of[('f1', 0.1, 1.0, 1.0)][2]
    moved_h = got_of[('f4', 0.1, 1.0, 1.0)][3] - got_of[('f1', 0.1, 1.0, 1.0)][3]
    rows.append(('F1 co2_ratio moved (0.0020..0.0022)', 0.0021, moved_c, 0, 0.0020 <= moved_c <= 0.0022))
    rows.append(('F1 h2s_ratio moved (0.0008..0.0010)', 0.0009, moved_h, 0, 0.0008 <= moved_h <= 0.0010))
    f4fresh = ic.from_constants(12.0, 0.0, v4[(12.0, 0.0, 200.0)])
    got = ic.contact(f4fresh, 200 / 50.04345, 7.2, 0.01, ic.AIR_CO2, 1.0, 1.0, 1.0, k0c(12, 0), ic.k0_h2s_dr(12, 0))
    for i, (part, want) in enumerate(zip(('pH', 'co2_gas', 'co2_ratio', 'h2s_ratio'),
                                         (7.203559109920308, 0.013037458687274833, 0.9918272399850134,
                                          0.9943135982147704))):
        row(f'f4 fresh 12 C alk 200 contact {part}', want, got[i], 1e-8 if i == 0 else rel * (want if i == 1 else 1))
    hc, hh = 1 / (k0c(t, s) * rt), 1 / (kd * rt)
    row('ph_rise_bound(12, 35, 0.01, 1)', 0.004390337131769065, math.log10(1 + 0.01 * hc), rel * 0.0044)
    row('h2s worst case r 0.1', 0.8803546789606475, 1 / ((1 + 0.1 * hc) * (1 + 0.1 * hh)), rel)
    ratio = kd / ic.k0_co2(t, s) * D_FACTOR
    x = 1 / 0.8 - 1
    row('saturation_from_depths(0.8) H2S', 0.9992433561777758, 1 - x ** (2 * ratio), 1e-9)
    x = 1 / 0.55 - 1
    row('saturation_from_depths(0.55) CO2', 0.33057851239669434, 1 - x * x, 1e-12)
    row('saturation_from_depths(0.55) H2S', 0.6466466469707662, 1 - x ** (2 * ratio), 1e-9)

    print('== every expected value of tests/gas_exchange.rs ==')
    for name, want, got, diff, ok in rows:
        print(f'  {name:<44} expected {want:.15g}  mine {got:.15g}  diff {diff:+.1e}  {"match" if ok else "MISMATCH"}')
    print(f'  {sum(r[4] for r in rows)} of {len(rows)} match')

    # every literal number of the test file accounted for? list the floats with >= 8 significant digits not checked
    checked = {round(r[1], 12) for r in rows}
    literals = {float(m) for m in re.findall(r'(?<![\w.])(\d+\.\d{8,})', TEST)}
    table = {float(m) for m in re.findall(r'\((\d+\.\d+), (\d+\.\d+), (\d+\.\d+)\)', TEST) for m in m}
    missing = sorted(v for v in literals if round(v, 12) not in checked and v not in table)
    print(f'  long literals in the test file not in this list: {missing}')

    print('\n== the 42-point table ==')
    block = TEST[TEST.index('const DOUABUL_RILEY'):]
    block = block[:block.index('];')]
    found = [tuple(map(float, m)) for m in re.findall(r'\((\d+\.\d+), (\d+\.\d+), (\d+\.\d+)\),', block)]
    print(f'  {len(found)} rows in the test; identical to the review\'s listing: {found == [tuple(r) for r in ic.DR_TABLE]}')
    worst = max(abs(ic.k0_h2s_dr(tk - ic.KELVIN, sv) / c - 1) for tk, sv, c in ic.DR_TABLE)
    print(f'  worst deviation {worst:.5f}; measured range {min(r[0] for r in ic.DR_TABLE) - ic.KELVIN:.2f} to '
          f'{max(r[0] for r in ic.DR_TABLE) - ic.KELVIN:.2f} C, S {min(r[1] for r in ic.DR_TABLE)} to '
          f'{max(r[1] for r in ic.DR_TABLE)}')

    print('\n== C4: k = (K0 H2S / K0 CO2) (D ratio)^n over 2-30 C, S 0-40 ==')
    for label, factor in (('0.712^(2/3) (implemented)', D_FACTOR), ('0.71^(2/3)', 0.71 ** (2 / 3)),
                          ('0.80^(1/2)', 0.80 ** 0.5), ('1 (no D)', 1.0)):
        vals = [(ic.k0_h2s_dr(tc, sv) / ic.k0_co2(tc, sv) * factor, tc, sv)
                for tc in range(2, 31) for sv in (0, 5, 10, 20, 30, 35, 40)]
        lo, hi = min(vals), max(vals)
        print(f'  factor {label:<26} {factor:.4f}: k from {lo[0]:.3f} ({lo[1]} C, S{lo[2]}) to {hi[0]:.3f} '
              f'({hi[1]} C, S{hi[2]})')

    print('\n== below 2 C: Douabul & Riley extrapolated vs independent pure-water data ==')
    winkler_0 = ic.x_to_molar(0.003747, 0.05)   # Winkler 1906, 273.2 K, x at 1.013 bar (IUPAC SDS-32 data sheet)
    for tc in (-1.9, 0.0, 0.05, 1.0, 2.0):
        iu = ic.x_to_molar(ic.iupac_x_h2s(tc + ic.KELVIN), tc)
        print(f'  {tc:>5} C S0: D&R {ic.k0_h2s_dr(tc, 0):.5f}  IUPAC low-T eq {iu:.5f} ({ic.k0_h2s_dr(tc, 0) / iu - 1:+.2%})')
    print(f'  Winkler (1906) 273.2 K x 0.003747 -> {winkler_0:.5f}; D&R at 0.05 C {ic.k0_h2s_dr(0.05, 0):.5f} '
          f'({ic.k0_h2s_dr(0.05, 0) / winkler_0 - 1:+.2%})')
    for sv in (0, 35):
        slope = (math.log(ic.k0_h2s_dr(2.0, sv)) - math.log(ic.k0_h2s_dr(2.1, sv))) / -0.1
        print(f'  S{sv}: d ln K0/dT at 2 C {slope:+.4f}/C; S-term at -1.9 C vs 2 C: '
              f'{ic.k0_h2s_dr(-1.9, 35) / ic.k0_h2s_dr(-1.9, 0):.4f} vs {ic.k0_h2s_dr(2, 35) / ic.k0_h2s_dr(2, 0):.4f}'
              if sv == 35 else f'  S{sv}: d ln K0/dT at 2 C {slope:+.4f}/C')
    print(f'  seawater freezing point at S35 about {-0.0575 * 35 + 1.710523e-3 * 35 ** 1.5 - 2.154996e-4 * 35 ** 2:.2f} C '
          '(UNESCO 1983)')

    print('\n== (7) a water below the air (formula 1, 2 C fresh, alk 0.5, pH 8.5, air 50 %, s 1/1) ==')
    e = ic.formula1(2.0, 0.0)
    got = ic.contact(e, 0.5, 8.5, 0.5, ic.AIR_CO2, 1.0, 1.0, 1.0, k0c(2, 0), ic.k0_h2s_dr(2, 0))
    co2_in = ic.co2_of(e, 0.5, 8.5)
    rt2 = ic.R_LATM * (2 + ic.KELVIN)
    print(f'  water CO2 {co2_in * ic.M_CO2:.3f} mg/L, air-equilibrium {ic.AIR_CO2 * k0c(2, 0) * ic.M_CO2 * 1000:.3f} mg/L;'
          f' vessel pH {got[0]:.4f}; co2_ratio {got[2]:.4f}; h2s_ratio {got[3]:.4f}; '
          f'H2S share in {ic.share_h2s(e, 8.5):.4f} vessel {ic.share_h2s(e, got[0]):.4f}')
    hc2 = 1 / (k0c(2, 0) * rt2)
    lost = ic.dic_of(e, 0.5, 8.5) - ic.dic_of(e, 0.5, got[0])
    carried = 0.5 * (got[1] - ic.AIR_CO2) * 1000 / rt2
    print(f'  DIC lost {lost:.6e} mmol/L, carried by the air {carried:.6e} (diff {lost - carried:+.1e}); '
          f'Hc {hc2:.4f}')

    print('\n== the fugacity in the vessel: a reading at equilibrium is the water\'s own ==')
    got = ic.contact(e1, 2.0, 7.2, 0.0, ic.AIR_CO2, 1.0, 1.0, 1.0, k0c(t, s), kd)
    ppm = got[1] * 1e6
    print(f'  r 0: leaving {ppm:.2f} ppm -> co2_from_gas {ppm * 1e-6 * k0c(t, s) * ic.M_CO2 * 1000:.5f} mg/L; '
          f'water {ic.co2_of(e1, 2.0, 7.2) * ic.M_CO2:.5f} mg/L')


if __name__ == '__main__':
    main()
