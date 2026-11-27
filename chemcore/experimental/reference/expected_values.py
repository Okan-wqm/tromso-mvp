"""The expected values of chemcore-experimental's gas_exchange tests after the science review's corrections (C1 to C4),
computed with the reviewer's independent implementation (independent_check.py in this folder: written from the
equations, the vessel solved for its pH, not a mirror of the Rust) and only these choices on top of it:

- C1: the H2S solubility of Douabul & Riley (1979) with B read as the review gives it (k0_h2s_dr, DR_B_READ);
- C2: the CO2 solubility per partial pressure is Weiss's K0 times the fugacity coefficient of CO2 in air
  (co2_fugacity_factor); the vessel's CO2 gas-over-water is 1 / (K0 phi R T), so a reading at equilibrium is the water's;
- C3: the vessel takes two saturations (independent_check.contact already does);
- C4: the depth test's H2S exponent is 2 (K0_H2S / K0_CO2) (D_H2S / D_CO2)^n with D ratio 0.712 and n = 2/3.

independent_check.py is the reviewer's file as delivered (2026-11-27), unchanged; its golden files are read from the
chemcore folder (default: this checkout's). Never run by the server or the tests: it wrote the numbers of
tests/gas_exchange.rs once, and runs again only when a constant or a choice above changes. Run (Python 3.12, standard
library), e.g. in the test runner's image:

    python -I chemcore/experimental/reference/expected_values.py [path-to-chemcore]
"""
import importlib.util
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('independent_check', HERE / 'independent_check.py')
ic = importlib.util.module_from_spec(spec)
sys.argv = sys.argv[:2]
spec.loader.exec_module(ic)
CHEMCORE = sys.argv[1] if len(sys.argv) > 1 else str(HERE.parent.parent)

D_RATIO, FILM_N = 0.712, 2.0 / 3.0


def k0c_eff(t, s, p=1.0):
    return ic.k0_co2(t, s) * ic.co2_fugacity_factor(t, p)


def show(name, value):
    print(f'{name:<58} {value!r}')


def main():
    t, s = 12.0, 35.0
    rt = ic.R_LATM * (t + ic.KELVIN)
    kd = ic.k0_h2s_dr(t, s)
    show('k0_h2s(12, 35)', kd)
    for tc, sc in ((25.0, 0.0), (2.0, 0.0), (30.0, 40.0), (2.0, 40.0), (30.0, 0.0)):
        show(f'k0_h2s({tc}, {sc})', ic.k0_h2s_dr(tc, sc))
    show('gas_over_water(k0_h2s(12,35), 12)', 1 / (kd * rt))
    show('gas_over_water(k0_co2(12,35), 12)', 1 / (ic.k0_co2(t, s) * rt))
    show('h2s_from_gas(117, 12, 35, 1)', 117e-9 * 1.0 * kd * ic.M_H2S_2007 * 1e6)
    for tc in (5.0, 12.0, 20.0):
        show(f'co2_fugacity_coefficient({tc}, 1)', ic.co2_fugacity_factor(tc, 1.0))
    show('co2_fugacity_coefficient(12, 2)', ic.co2_fugacity_factor(12.0, 2.0))
    show('co2_from_gas(3852, 12, 35, 1)', 3852e-6 * 1.0 * k0c_eff(t, s) * ic.M_CO2 * 1000)
    show('co2_from_gas(3852, 12, 35, 1) partial pressure only', 3852e-6 * 1.0 * ic.k0_co2(t, s) * ic.M_CO2 * 1000)
    e1 = ic.formula1(t, s)
    show('total_sulfide(0.5, f1 12/35, 7.2)', 0.5 / ic.share_h2s(e1, 7.2))
    cases = ((0.01, 1.0, 1.0), (0.1, 1.0, 1.0), (0.01, 0.9, 0.9), (0.01, 0.9, 0.9975), (0.0, 1.0, 1.0))
    for r, sc_, sh_ in cases:
        got = ic.contact(e1, 2.0, 7.2, r, ic.AIR_CO2, 1.0, sc_, sh_, k0c_eff(t, s), kd)
        show(f'f1 contact(r {r}, s_co2 {sc_}, s_h2s {sh_}) ph,x,co2r,h2sr', got)
    show('ph_rise_bound(12, 35, 0.01, 1)', math.log10(1 + 0.01 / (k0c_eff(t, s) * rt)))
    hc, hh = 1 / (k0c_eff(t, s) * rt), 1 / (kd * rt)
    show('h2s_ratio bound at s 1, r 0.1', (1 / (1 + 0.1 * hc)) / (1 + 0.1 * hh))
    factor = D_RATIO ** FILM_N
    show('diffusivity factor 0.712^(2/3)', factor)
    x = 1 / 0.8 - 1
    show('saturation_from_depths(0.8, 12, 35) h2s', 1 - x ** (2 * kd / ic.k0_co2(t, s) * factor))
    x = 1 / 0.55 - 1
    show('saturation_from_depths(0.55, 12, 35) co2', 1 - x * x)
    show('saturation_from_depths(0.55, 12, 35) h2s', 1 - x ** (2 * kd / ic.k0_co2(t, s) * factor))
    # formula 4, golden v4's constants
    import gzip
    import json
    v4 = {}
    with gzip.open(f'{CHEMCORE}/golden/v4/waters.jsonl.gz', 'rt') as f:
        for line in f:
            r = json.loads(line)
            if r['ions'] == {}:
                v4[(r['temp_c'], r['salinity'], r['alkalinity_mg_l'])] = r['v4']['constants']
    e4 = ic.from_constants(t, s, v4[(t, s, 200.0)])
    show('total_sulfide(0.5, f4 12/35, 7.2)', 0.5 / ic.share_h2s(e4, 7.2))
    for r, sc_, sh_ in cases[:3]:
        got = ic.contact(e4, 2.0, 7.2, r, ic.AIR_CO2, 1.0, sc_, sh_, k0c_eff(t, s), kd)
        show(f'f4 contact(r {r}, s_co2 {sc_}, s_h2s {sh_}) ph,x,co2r,h2sr', got)
        one = ic.contact(e1, 2.0, 7.2, r, ic.AIR_CO2, 1.0, sc_, sh_, k0c_eff(t, s), kd)
        show('    f4 - f1 (ph, co2r, h2sr)', (got[0] - one[0], got[2] - one[2], got[3] - one[3]))
    f4fresh = ic.from_constants(12.0, 0.0, v4[(12.0, 0.0, 200.0)])
    got = ic.contact(f4fresh, 200 / 50.04345, 7.2, 0.01, ic.AIR_CO2, 1.0, 1.0, 1.0, k0c_eff(12.0, 0.0),
                     ic.k0_h2s_dr(12.0, 0.0))
    show('f4 fresh 12 C alk 200 mg/L contact(r 0.01, 1, 1)', got)
    worst = max(abs(ic.k0_h2s_dr(tk - ic.KELVIN, sv) / c - 1) for tk, sv, c in ic.DR_TABLE)
    show('worst deviation of the 42 points', worst)


if __name__ == '__main__':
    main()
