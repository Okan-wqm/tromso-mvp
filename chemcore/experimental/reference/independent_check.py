"""Independent check of chemcore's gas_exchange module (chemcore/experimental/src/gas_exchange.rs as delivered).

Written from the equations, not from the Rust: the vessel is solved for its pH (not its DIC), the bounds are tested
by sampling, and the H2S solubility is taken from its primary source (Douabul & Riley 1979, as the IUPAC Solubility
Data Series vol. 32 prints their data). Standard library only. Run:

    python -I independent_check.py [path-to-chemcore]

The chemcore path (default: the chemcore folder holding this file) is read only for its golden files: formula 1's
constants at 12 degC, S 35 (golden/v1/constants) to prove this file's formula-1 equilibria are the core's, and formula
4's constants (golden/v4/waters) for the formula-4 recomputation.
"""
import gzip
import json
import math
import random
import sys
from pathlib import Path

CHEMCORE = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parents[2])
KELVIN = 273.15
LN10 = math.log(10.0)

# ---------------------------------------------------------------------------------------------------------------------
# 1. Physical constants
# ---------------------------------------------------------------------------------------------------------------------
R_J = 8.314462618            # J/(mol K), CODATA 2018 (exact since the 2019 SI)
L_ATM_J = 101.325            # J per L atm (1 atm = 101325 Pa exactly)
R_LATM = R_J / L_ATM_J       # L atm/(mol K)
M_H2S_2007 = 2 * 1.00794 + 32.065   # IUPAC 2007 standard atomic weights (the core's basis)
M_H2S_2021 = 2 * 1.008 + 32.06     # IUPAC conventional values (2021)
M_CO2 = 12.0107 + 2 * 15.9994      # IUPAC 2007, g/mol (the core's MG_CO2_PER_MMOL)
AIR_CO2 = 420e-6

# The module's PROVISIONAL constants (gas_exchange.rs)
MOD_K0_H2S_25 = 0.1013
MOD_K0_H2S_TEMP = 2100.0
MOD_K0_H2S_SALTING = 0.10
MOD_GAS_CONSTANT = 0.082057366
MOD_G_H2S = 34.08088


def vapour_pressure_atm(t_c):
    """Benson & Krause (1984) as APHA 4500-O, atm (the core's)."""
    t = t_c + KELVIN
    return math.exp(11.8571 - 3840.70 / t - 216961.0 / t ** 2)


# ---- CO2 solubility, Weiss (1974) -----------------------------------------------------------------------------------
WEISS_L = (-58.0931, 90.5069, 22.2940, 0.027766, -0.025888, 0.0050578)    # mol/(L atm)
WEISS_KG = (-60.2409, 93.4517, 23.3585, 0.023517, -0.023656, 0.0047036)   # mol/(kg atm)


def k0_co2(t_c, s, c=WEISS_L):
    x = (t_c + KELVIN) / 100.0
    return math.exp(c[0] + c[1] / x + c[2] * math.log(x) + s * (c[3] + c[4] * x + c[5] * x * x))


def co2_fugacity_factor(t_c, p_atm=1.0):
    """f/p of CO2 in air, Weiss (1974): exp[(B + 2 delta) P / RT], B and delta in cm3/mol."""
    t = t_c + KELVIN
    b = -1636.75 + 12.0408 * t - 3.27957e-2 * t ** 2 + 3.16528e-5 * t ** 3
    delta = 57.7 - 0.118 * t
    return math.exp((b + 2 * delta) * p_atm / (82.057366 * t))


def seawater_density(t, s):
    """UNESCO 1981 one-atmosphere EOS, kg/L."""
    pure = (999.842594 + 6.793952e-2 * t - 9.095290e-3 * t ** 2 + 1.001685e-4 * t ** 3 - 1.120083e-6 * t ** 4
            + 6.536332e-9 * t ** 5)
    a = 8.24493e-1 - 4.0899e-3 * t + 7.6438e-5 * t ** 2 - 8.2467e-7 * t ** 3 + 5.3875e-9 * t ** 4
    b = -5.72466e-3 + 1.0227e-4 * t - 1.6546e-6 * t ** 2
    return (pure + a * s + b * s ** 1.5 + 4.8314e-4 * s * s) / 1000.0


# ---- H2S solubility ---------------------------------------------------------------------------------------------------
def k0_h2s_module(t_c, s):
    t = t_c + KELVIN
    return MOD_K0_H2S_25 * math.exp(MOD_K0_H2S_TEMP * (1 / t - 1 / 298.15)) * (1 - MOD_K0_H2S_SALTING * s / 35)


# Douabul & Riley (1979), Deep-Sea Res. 26A: 259, the Weiss-form fit as IUPAC SDS vol. 32 (Fogg & Young 1988, p. 53)
# prints it: ln C = A1 + A2 (100/T) + A3 ln(T/100) + S [B1 + B2 (T/100) + B3 (T/100)^2], C mol/dm3 at an H2S fugacity
# of 1 atm. A1..A3 as printed. The B's as the text extraction of that page gives them (-0.60583, 0.379753, -0.602340)
# do not reproduce the tabulated salinity effect by a factor 2 to 5 (see check below); B = (-0.060583, 0.0379753,
# -0.0060234) does to the data's own precision: decimal points lost in the print/extraction. The B's are therefore
# ALSO refitted here by least squares to the 42 tabulated points (DR_TABLE), and the two sets compared.
DR_A = (-41.0563, 66.4005, 15.1060)
DR_B_PRINTED = (-0.60583, 0.379753, -0.602340)
DR_B_READ = (-0.060583, 0.0379753, -0.0060234)

# The 42 tabulated values, IUPAC SDS-32 pp. 52-53 (T/K, S g/kg, C mol/dm3 at fH2S 1 atm)
_S = (9.972, 20.014, 24.958, 29.993, 34.994, 40.028)
DR_TABLE = [(275.25, s, c) for s, c in zip(_S, (0.1910, 0.1878, 0.1862, 0.1846, 0.1831, 0.1816))] + \
           [(278.20, s, c) for s, c in zip(_S, (0.1741, 0.1714, 0.1701, 0.1688, 0.1675, 0.1662))] + \
           [(283.34, s, c) for s, c in zip(_S, (0.1496, 0.1476, 0.1466, 0.1456, 0.1447, 0.1437))] + \
           [(288.19, s, c) for s, c in zip(_S, (0.1299, 0.1284, 0.1276, 0.1269, 0.1262, 0.1255))] + \
           [(293.25, s, c) for s, c in zip(_S, (0.1143, 0.1131, 0.1126, 0.1120, 0.1114, 0.1108))] + \
           [(297.87, s, c) for s, c in zip(_S, (0.1013, 0.1004, 0.0999, 0.0995, 0.0990, 0.0986))] + \
           [(302.97, s, c) for s, c in zip(_S, (0.0907, 0.0898, 0.0894, 0.0891, 0.0887, 0.0884))]


def k0_h2s_dr(t_c, s, b=DR_B_READ, a=DR_A):
    x = (t_c + KELVIN) / 100.0
    return math.exp(a[0] + a[1] / x + a[2] * math.log(x) + s * (b[0] + b[1] * x + b[2] * x * x))


def solve_linear(m, v):
    n = len(v)
    m = [row[:] + [v[i]] for i, row in enumerate(m)]
    for i in range(n):
        p = max(range(i, n), key=lambda r: abs(m[r][i]))
        m[i], m[p] = m[p], m[i]
        for r in range(n):
            if r != i:
                f = m[r][i] / m[i][i]
                m[r] = [m[r][k] - f * m[i][k] for k in range(n + 1)]
    return [m[i][n] / m[i][i] for i in range(n)]


def least_squares(rows, ys):
    k = len(rows[0])
    ata = [[sum(r[i] * r[j] for r in rows) for j in range(k)] for i in range(k)]
    aty = [sum(r[i] * y for r, y in zip(rows, ys)) for i in range(k)]
    return solve_linear(ata, aty)


def refit_dr():
    """All six coefficients refitted to the 42 points (ln C), and the B's alone with the printed A's."""
    rows, ys = [], []
    for t, s, c in DR_TABLE:
        x = t / 100
        rows.append([1.0, 1 / x, math.log(x), s, s * x, s * x * x])
        ys.append(math.log(c))
    full = least_squares(rows, ys)
    rows_b, ys_b = [], []
    for t, s, c in DR_TABLE:
        x = t / 100
        rows_b.append([s, s * x, s * x * x])
        ys_b.append(math.log(c) - (DR_A[0] + DR_A[1] / x + DR_A[2] * math.log(x)))
    b_only = least_squares(rows_b, ys_b)
    return full, b_only


def iupac_x_h2s(t_k):
    """Fogg & Young (IUPAC SDS-32, 1988, p. 1): mole fraction at an H2S partial pressure of 1.013 bar.
    273.2-283.2 K: ln x = -14.761 + 2507.2/T; 283.2-603.2 K: ln x = -24.912 + 3477.1/T + 0.3993 ln T + 0.015700 T."""
    if t_k < 283.2:
        return math.exp(-14.761 + 2507.2 / t_k)
    return math.exp(-24.912 + 3477.1 / t_k + 0.3993 * math.log(t_k) + 0.015700 * t_k)


def water_density(t):
    return seawater_density(t, 0.0)


def x_to_molar(x, t_c):
    """mol/L of solution from a mole fraction (dilute: solution volume taken as the water's)."""
    return x / (1 - x) * water_density(t_c) * 1000 / 18.01528


# ---------------------------------------------------------------------------------------------------------------------
# 2. Formula-1 equilibria (the core's constant set, written from the published equations)
# ---------------------------------------------------------------------------------------------------------------------
class Eq:
    pass


def formula1(t_c, s):
    t = t_c + KELVIN
    lt = math.log(t)
    e = Eq()
    e.t_c, e.s = t_c, s
    i = 19.924 * s / (1000 - 1.005 * s)
    st = 0.1400 / 96.062 * s / 1.80655
    ft = 0.000067 / 18.998 * s / 1.80655
    e.boron = 0.000232 / 10.811 * s / 1.80655
    if s > 0:
        ks = math.exp(-4276.1 / t + 141.328 - 23.093 * lt + (-13856 / t + 324.57 - 47.986 * lt) * math.sqrt(i)
                      + (35474 / t - 771.54 + 114.723 * lt) * i - 2698 / t * i ** 1.5 + 1776 / t * i * i
                      + math.log(1 - 0.001005 * s))
        kf = math.exp(1590.2 / t - 12.641 + 1.525 * math.sqrt(i) + math.log(1 - 0.001005 * s))
        to_sws = 1 + st / ks + ft / kf
        to_total = 1 + st / ks
        a = 1.82e6 * (79 * t) ** -1.5
        gamma_h = 10 ** -(a * (math.sqrt(i) / (1 + math.sqrt(i)) - 0.2 * i))
    else:
        to_sws = to_total = gamma_h = 1.0
    e.ph_offset = math.log10(gamma_h / (1 - 0.001005 * s)) + math.log10(to_sws)
    rs = math.sqrt(s)
    pk1 = (-126.34048 + 6320.813 / t + 19.568224 * lt + 13.4191 * rs + 0.0331 * s - 5.33e-5 * s * s
           + (-530.123 * rs - 6.103 * s) / t - 2.06950 * rs * lt)
    pk2 = (-90.18333 + 5143.692 / t + 14.613358 * lt + 21.0894 * rs + 0.1248 * s - 3.687e-4 * s * s
           + (-772.483 * rs - 20.051 * s) / t - 3.3336 * rs * lt)
    e.k1 = 10 ** -pk1 / to_sws
    e.k2 = 10 ** -pk2 / to_sws
    e.kw = math.exp(148.9652 - 13847.26 / t - 23.6521 * lt + (-5.977 + 118.67 / t + 1.0495 * lt) * rs
                    - 0.01615 * s) / to_total
    e.kb = math.exp((-8966.90 - 2890.53 * rs - 77.942 * s + 1.728 * s * rs - 0.0996 * s * s) / t + 148.0248
                    + 137.1942 * rs + 1.62142 * s + (-24.4344 - 25.085 * rs - 0.2474 * s) * lt
                    + 0.053105 * rs * t) / to_total
    e.k_h2s = math.exp(225.838 - 13275.3 / t - 34.6435 * lt + 0.3449 * rs - 0.0274 * s) / to_total
    return e


def from_constants(t_c, s, c):
    e = Eq()
    e.t_c, e.s = t_c, s
    for k in ('k1', 'k2', 'kw', 'kb', 'boron', 'k_h2s', 'ph_offset'):
        setattr(e, k, c[k])
    return e


def h_of(e, ph):
    return 10 ** -(ph + e.ph_offset)


def share_h2s(e, ph):
    h = h_of(e, ph)
    return h / (h + e.k_h2s)


def alpha(e, ph):
    h = h_of(e, ph)
    d = h * h + h * e.k1 + e.k1 * e.k2
    return h * h / d, h * e.k1 / d, e.k1 * e.k2 / d


def noncarb_alk(e, ph):
    """meq/L: OH - H + borate (the core's isoline intercept, mol/kg taken as mol/L)."""
    h = h_of(e, ph)
    return (e.kw / h - h + e.boron * e.kb / (e.kb + h)) * 1000


def dic_of(e, ta, ph):
    a0, a1, a2 = alpha(e, ph)
    return (ta - noncarb_alk(e, ph)) / (a1 + 2 * a2)


def co2_of(e, ta, ph):
    return dic_of(e, ta, ph) * alpha(e, ph)[0]


def bisect(f, lo, hi, n=200):
    flo = f(lo)
    for _ in range(n):
        mid = 0.5 * (lo + hi)
        fm = f(mid)
        if (fm > 0) == (flo > 0):
            lo, flo = mid, fm
        else:
            hi = mid
        if hi - lo < 1e-15:
            break
    return 0.5 * (lo + hi)


def contact(e, ta, ph_in, r, x_air, p, s_co2, s_h2s, k0c, k0h):
    """Fully mixed vessel at steady state, solved for its pH. Returns pH, leaving x_CO2, co2 ratio, h2s ratio."""
    rt = R_LATM * (e.t_c + KELVIN)
    hc = 1 / (k0c * rt)       # Cg/Cw CO2
    hh = 1 / (k0h * rt)       # Cg/Cw H2S
    dic_in = dic_of(e, ta, ph_in)
    co2_in = dic_in * alpha(e, ph_in)[0]
    c_air = x_air * p / rt * 1000          # mmol per L of gas

    def g(ph_v):  # increasing in ph_v
        dic_v = dic_of(e, ta, ph_v)
        return dic_in - dic_v - r * s_co2 * (hc * dic_v * alpha(e, ph_v)[0] - c_air)

    ph_v = ph_in if r == 0 else bisect(g, ph_in - 3, ph_in + 3)
    co2_v = co2_of(e, ta, ph_v)
    c_out = c_air + s_co2 * (hc * co2_v - c_air)
    x_out = c_out * rt / (1000 * p)
    co2_ratio = (c_out / hc) / co2_in
    # sulfide: ST_in = 1/share_in (free H2S in = 1); ST_in = ST_v (1 + r s hh share_v)
    sh_v, sh_in = share_h2s(e, ph_v), share_h2s(e, ph_in)
    st_v = (1 / sh_in) / (1 + r * s_h2s * hh * sh_v)
    h2s_ratio = s_h2s * sh_v * st_v   # (leaving air / hh) over the entering water's free H2S (=1)
    return ph_v, x_out, co2_ratio, h2s_ratio


# ---------------------------------------------------------------------------------------------------------------------
# 3. Run
# ---------------------------------------------------------------------------------------------------------------------
def rel(a, b):
    return (a - b) / b


def main():
    out = []
    p = out.append

    p('== 1. constants ==')
    p(f'R = {R_J}/{L_ATM_J} = {R_LATM:.10f} L atm/(mol K); module 0.082057366, rel diff {rel(MOD_GAS_CONSTANT, R_LATM):.2e}')
    p(f'M(H2S) IUPAC 2007 = {M_H2S_2007:.5f}; IUPAC 2021 conventional = {M_H2S_2021:.5f} (rel {rel(M_H2S_2021, M_H2S_2007):.2e})')
    p(f'M(CO2) = {M_CO2:.4f} g/mol')
    lnk = math.log(k0_co2(25, 35, WEISS_KG))
    p(f'Weiss 1974 per kg, ln K0(25 C, S35) = {lnk:.5f} (check value -3.5617, DOE 1994 / Dickson et al. 2007)')
    for t, s in ((12, 35), (25, 35), (12, 0), (5, 35)):
        ratio = k0_co2(t, s) / k0_co2(t, s, WEISS_KG)
        p(f'  K0 per L / per kg at {t} C, S{s}: {ratio:.5f}; density {seawater_density(t, s):.5f} kg/L '
          f'(diff {rel(ratio, seawater_density(t, s)):+.2e})')
    for t in (5, 12, 20, 25):
        p(f'  CO2 fugacity/partial pressure in air at {t} C, 1 atm: {co2_fugacity_factor(t):.5f}')

    p('\n== 1b. Douabul & Riley (1979) ==')
    worst_read = max(abs(rel(k0_h2s_dr(t - KELVIN, s), c)) for t, s, c in DR_TABLE)
    worst_print = max(abs(rel(k0_h2s_dr(t - KELVIN, s, DR_B_PRINTED), c)) for t, s, c in DR_TABLE)
    p(f'fit with B as extracted ({DR_B_PRINTED}): worst rel. dev from table {worst_print:.3f}')
    p(f'fit with B = {DR_B_READ}: worst rel. dev from table {worst_read:.4f} (authors: fit within 0.5 %)')
    full, b_only = refit_dr()
    p(f'refit, all six: A = {full[0]:.4f}, {full[1]:.4f}, {full[2]:.4f}; B = {full[3]:.6f}, {full[4]:.6f}, {full[5]:.7f}')
    p(f'refit, B only (A as printed): B = {b_only[0]:.6f}, {b_only[1]:.6f}, {b_only[2]:.7f}')
    worst_full = max(abs(rel(math.exp(full[0] + full[1] * 100 / t + full[2] * math.log(t / 100)
                                      + s * (full[3] + full[4] * t / 100 + full[5] * (t / 100) ** 2)), c))
                     for t, s, c in DR_TABLE)
    p(f'refit (six) worst rel. dev {worst_full:.4f}')
    p('pure water at 25 C: D&R fit S=0 {:.5f}; IUPAC x=0.001830 at p=1.013 bar -> {:.5f} mol/L per atm partial pressure;'
      ' module 0.1013; Sander Hcp 1.0e-3 mol/(m3 Pa) = {:.5f} mol/(L atm)'.format(
          k0_h2s_dr(25, 0), x_to_molar(0.001830, 25), 1.0e-3 * 101325 / 1000))
    for t_c in (2, 5, 10, 12, 20, 25, 30):
        p(f'  pure water {t_c:>2} C: D&R {k0_h2s_dr(t_c, 0):.5f}  IUPAC-x {x_to_molar(iupac_x_h2s(t_c + KELVIN), t_c):.5f}'
          f'  module {k0_h2s_module(t_c, 0):.5f}  (module vs D&R {rel(k0_h2s_module(t_c, 0), k0_h2s_dr(t_c, 0)):+.2%})')
    p('effective d ln K0/d(1/T) of D&R (S=0), K: ' + ', '.join(
        f'{t} C {100 * DR_A[1] - DR_A[2] * (t + KELVIN):.0f}' for t in (5, 12, 20, 25)))
    p('salting-out at S35 (1 - K0(S35)/K0(S0)), D&R: ' + ', '.join(
        f'{t} C {1 - k0_h2s_dr(t, 35) / k0_h2s_dr(t, 0):.4f}' for t in (2, 5, 12, 20, 25, 30)) + '; module 0.10 at every T')
    p('\nmodule K0_H2S vs Douabul & Riley (relative error of the module):')
    p('  T C |   S0      S10     S35')
    for t_c in (5, 12, 20):
        p(f'  {t_c:>3} | ' + '  '.join(f'{rel(k0_h2s_module(t_c, s), k0_h2s_dr(t_c, s)):+.2%}' for s in (0, 10, 35)))
    p('  values D&R (mol/(L atm)):')
    for t_c in (5, 12, 20):
        p(f'  {t_c:>3} | ' + '  '.join(f'{k0_h2s_dr(t_c, s):.5f}' for s in (0, 10, 35)) + '   module: '
          + '  '.join(f'{k0_h2s_module(t_c, s):.5f}' for s in (0, 10, 35)))

    p('\n== 3. every expected value of tests_gas_exchange.rs, recomputed (module constants, formula 1) ==')
    e1 = formula1(12.0, 35.0)
    gold = None
    with gzip.open(f'{CHEMCORE}/golden/v1/constants.jsonl.gz', 'rt') as f:
        for line in f:
            r = json.loads(line)
            if r.get('temp_c') == 12.0 and r.get('salinity') == 35.0:
                gold = r['equilibria']
    for k in ('k1', 'k2', 'kw', 'kb', 'boron', 'k_h2s', 'ph_offset'):
        p(f'  formula 1 {k:>9} mine {getattr(e1, k):.15e} golden v1 {gold[k]:.15e} rel {rel(getattr(e1, k), gold[k]):+.1e}')
    p(f'  k0_co2(12,35) mine {k0_co2(12, 35):.15e} golden v1 {0.042221238577568564:.15e}')
    rows = []

    def row(name, want, got, tol):
        ok = abs(got - want) <= tol
        rows.append((name, want, got, got - want, 'match' if ok else 'MISMATCH'))

    t, s = 12.0, 35.0
    rt = R_LATM * (t + KELVIN)
    k0h = k0_h2s_module(t, s)
    k0c = k0_co2(t, s)
    row('k0_h2s(12,35)', 0.12569223744761449, k0h, 1e-7 * 0.1257)
    row('k0_h2s(25,0)', 0.1013, k0_h2s_module(25, 0), 1e-7 * 0.1013)
    row('gas_over_water H2S 12/35', 0.34001697138870374, 1 / (k0h * rt), 1e-7 * 0.34)
    row('gas_over_water CO2 12/35', 1.0122273846962273, 1 / (k0c * rt), 1e-7 * 1.01)
    row('h2s_from_gas(117 ppb) ug/L', 0.5011931411818877, 117e-9 * 1.0 * k0h * M_H2S_2007 * 1e6, 1e-7 * 0.5)
    row('co2_from_gas(3852 ppm) mg/L', 7.157538328039449, 3852e-6 * 1.0 * k0c * M_CO2 * 1000, 1e-7 * 7.16)
    row('dried_gas_factor(12,1)', 0.9861608398007197, 1 - vapour_pressure_atm(12), 1e-7)
    row('total_sulfide(0.5, pH 7.2)', 1.5765892793905285, 0.5 / share_h2s(e1, 7.2), 1e-7 * 1.58)
    cases = [((0.01, 1.0), (7.2033679689666315, 0.003851932145296956, 0.9921289934110448, 0.9936461112901878)),
             ((0.1, 1.0), (7.232005364061479, 0.0036014549240287338, 0.9276144318779057, 0.9407272232633087)),
             ((0.01, 0.9), (7.203032953362708, 0.003511465154435521, 0.9044360745870549, 0.8948492208819272)),
             ((0.0, 1.0), (7.2, 0.0038824912593951088, 1.0, 1.0))]
    for (r_, sat), want in cases:
        got = contact(e1, 2.0, 7.2, r_, AIR_CO2, 1.0, sat, sat, k0c, k0h)
        tag = f'contact(r={r_}, s={sat})'
        row(tag + ' pH', want[0], got[0], 1e-8)
        row(tag + ' co2_gas', want[1], got[1], 1e-7 * want[1])
        row(tag + ' co2_ratio', want[2], got[2], 1e-7)
        row(tag + ' h2s_ratio', want[3], got[3], 1e-7)
    bound = math.log10(1 + 0.01 / (k0c * rt))
    row('ph_rise_bound(12,35,0.01)', 0.0043739476864790815, bound, 1e-7 * 0.00437)
    x = 1 / 0.8 - 1
    row('saturation_from_depths(0.8) CO2', 0.9375, 1 - x * x, 1e-12)
    row('saturation_from_depths(0.8) H2S', 0.9997397768507817, 1 - x ** (2 * k0h / k0c), 1e-9)
    for name, want, got, diff, verdict in rows:
        p(f'  {name:<38} expected {want:.12g}  mine {got:.12g}  diff {diff:+.2e}  {verdict}')

    p('\n== 3b. the same with formula 4 (golden v4 constants) ==')
    v4 = {}
    with gzip.open(f'{CHEMCORE}/golden/v4/waters.jsonl.gz', 'rt') as f:
        for line in f:
            r = json.loads(line)
            if r['ions'] == {}:
                v4[(r['temp_c'], r['salinity'], r['alkalinity_mg_l'])] = r['v4']['constants']
    e4 = from_constants(12.0, 35.0, v4[(12.0, 35.0, 200.0)])
    p(f'  12 C S35: ph_offset f1 {e1.ph_offset:.5f} f4 {e4.ph_offset:.5f}; kw f1 {e1.kw:.4e} f4 {e4.kw:.4e}; k1,k2,kb,k_h2s identical: '
      f'{all(abs(rel(getattr(e1, k), getattr(e4, k))) < 1e-14 for k in ("k1", "k2", "kb", "k_h2s", "boron"))} (to 1e-14)')
    p(f'  total_sulfide(0.5, 7.2): f1 {0.5 / share_h2s(e1, 7.2):.6f} f4 {0.5 / share_h2s(e4, 7.2):.6f} '
      f'({rel(0.5 / share_h2s(e4, 7.2), 0.5 / share_h2s(e1, 7.2)):+.2%})')
    for (r_, sat), _ in cases:
        a = contact(e1, 2.0, 7.2, r_, AIR_CO2, 1.0, sat, sat, k0c, k0h)
        b = contact(e4, 2.0, 7.2, r_, AIR_CO2, 1.0, sat, sat, k0c, k0h)
        p(f'  contact r={r_} s={sat}: f1 pH {a[0]:.6f} co2r {a[2]:.6f} h2sr {a[3]:.6f} | f4 pH {b[0]:.6f} co2r {b[2]:.6f} '
          f'h2sr {b[3]:.6f} | diff dpH {b[0] - a[0] - 0:+.1e} (rise f1 {a[0] - 7.2:.5f}, f4 {b[0] - 7.2:.5f}) '
          f'co2r {b[2] - a[2]:+.1e} h2sr {b[3] - a[3]:+.1e}')
    for (t_c, s_, alk) in ((12.0, 35.0, 200.0), (12.0, 0.0, 200.0), (25.0, 35.0, 200.0)):
        f1 = formula1(t_c, s_)
        f4 = from_constants(t_c, s_, v4[(t_c, s_, alk)])
        ta = alk / 50.04345
        c1, c4 = co2_of(f1, ta, 7.2), co2_of(f4, ta, 7.2)
        p(f'  {t_c} C S{s_} alk {alk} mg/L pH 7.2: H2S share f1 {share_h2s(f1, 7.2):.4f} f4 {share_h2s(f4, 7.2):.4f} '
          f'({rel(share_h2s(f4, 7.2), share_h2s(f1, 7.2)):+.2%}); CO2 f1 {c1 * M_CO2:.3f} f4 {c4 * M_CO2:.3f} mg/L '
          f'({rel(c4, c1):+.2%})')
    f4fresh = from_constants(12.0, 0.0, v4[(12.0, 0.0, 200.0)])
    f1fresh = formula1(12.0, 0.0)
    for name, e in (('f1', f1fresh), ('f4', f4fresh)):
        c = contact(e, 200 / 50.04345, 7.2, 0.01, AIR_CO2, 1.0, 1.0, 1.0, k0_co2(12, 0), k0_h2s_module(12, 0))
        p(f'  fresh 12 C alk 200 mg/L pH 7.2 r 0.01 s 1, {name}: pH {c[0]:.6f} co2r {c[2]:.6f} h2sr {c[3]:.6f}')

    p('\n== 2d. ph_rise_bound and the H2S-share claim, sampled (formula 1, s=1, air without CO2 and with) ==')
    rnd = random.Random(20261127)
    worst_ph, worst_share, n = -1e9, -1e9, 0
    for _ in range(3000):
        t_c = rnd.uniform(0, 30)
        s_ = rnd.choice([0.0, rnd.uniform(0, 40)])
        e = formula1(t_c, s_)
        ph = rnd.uniform(5.5, 9.5)
        ta = rnd.uniform(0.05, 8.0)
        if ta <= noncarb_alk(e, ph) + 1e-6:
            continue
        r_ = 10 ** rnd.uniform(-3, 0.5)
        x_air = rnd.choice([0.0, AIR_CO2])
        k0c_ = k0_co2(t_c, s_)
        rt_ = R_LATM * (t_c + KELVIN)
        bound_ = math.log10(1 + r_ / (k0c_ * rt_))
        ph_v, _, _, _ = contact(e, ta, ph, r_, x_air, 1.0, 1.0, 1.0, k0c_, k0_h2s_module(t_c, s_))
        worst_ph = max(worst_ph, (ph_v - ph) / bound_)
        fall = 1 - share_h2s(e, ph_v) / share_h2s(e, ph)
        worst_share = max(worst_share, fall / (LN10 * bound_))
        n += 1
    p(f'  {n} waters: max (pH rise / bound) = {worst_ph:.6f} (must be <= 1); max (share fall / (ln10 x bound)) = '
      f'{worst_share:.6f} (must be <= 1)')

    p('\n== 2e. saturation_from_depths exponent: K0 ratio and diffusivity ==')
    for t_c, s_ in ((12, 35), (12, 0), (5, 35), (20, 35)):
        p(f'  {t_c} C S{s_}: K0H2S/K0CO2 module {k0_h2s_module(t_c, s_) / k0_co2(t_c, s_):.3f}, '
          f'D&R {k0_h2s_dr(t_c, s_) / k0_co2(t_c, s_):.3f}')
    k_ratio = k0_h2s_dr(12, 35) / k0_co2(12, 35)
    for ratio in (0.55, 0.6, 0.7, 0.8, 0.9):
        x = 1 / ratio - 1
        same_d = 1 - x ** (2 * k_ratio)
        lo = 1 - x ** (2 * k_ratio * 0.712 ** (2 / 3))
        hi = 1 - x ** (2 * k_ratio * 0.80 ** 0.5)
        p(f'  ratio {ratio}: CO2 sat {1 - x * x:.4f}; H2S sat equal-D {same_d:.4f}; with D_H2S/D_CO2 0.71-0.80, '
          f'n 2/3-1/2: {lo:.4f} to {hi:.4f}')

    p('\n== 3c. the test values with the H2S solubility of Douabul & Riley (B read as above), formula 1 ==')
    kd = k0_h2s_dr(12, 35)
    p(f'  k0_h2s(12,35) {kd:.6f} (module {k0h:.6f}, {rel(k0h, kd):+.2%}); k0_h2s(25,0) {k0_h2s_dr(25, 0):.6f}')
    p(f'  gas_over_water H2S 12/35 {1 / (kd * rt):.4f} (module 0.3400)')
    p(f'  h2s_from_gas(117 ppb, 12, 35, 1 atm) {117e-9 * kd * M_H2S_2007 * 1e6:.4f} ug/L (module 0.5012)')
    for (r_, sat), want in cases:
        got = contact(e1, 2.0, 7.2, r_, AIR_CO2, 1.0, sat, sat, k0c, kd)
        p(f'  contact r={r_} s={sat}: h2s_ratio {got[3]:.6f} (module {want[3]:.6f}, diff {got[3] - want[3]:+.1e})')
    x = 1 / 0.8 - 1
    p(f'  saturation_from_depths(0.8) H2S, equal D: {1 - x ** (2 * kd / k0c):.7f}; with (D ratio)^n 0.80: '
      f'{1 - x ** (2 * kd / k0c * 0.80):.7f}')
    full, _ = refit_dr()
    t100 = (12 + KELVIN) / 100
    k_refit = math.exp(full[0] + full[1] / t100 + full[2] * math.log(t100)
                       + 35 * (full[3] + full[4] * t100 + full[5] * t100 ** 2))
    p(f'  printed-A/read-B vs six-coefficient refit at 12 C S35: {kd:.5f} vs {k_refit:.5f} ({rel(k_refit, kd):+.2%})')

    p('\n== 3d. one saturation for both gases is not what the bubble model gives ==')
    for s_c in (0.9, 0.5):
        phi_c = 1 - s_c
        for dfac in (1.0, 0.80):
            s_h = 1 - phi_c ** (kd / k0c * dfac)
            got = contact(e1, 2.0, 7.2, 0.01, AIR_CO2, 1.0, s_c, s_h, k0c, kd)
            same = contact(e1, 2.0, 7.2, 0.01, AIR_CO2, 1.0, s_c, s_c, k0c, kd)
            p(f'  r 0.01, s_CO2 {s_c}, D factor {dfac}: s_H2S {s_h:.4f}; h2s_ratio {got[3]:.4f} (one saturation: '
              f'{same[3]:.4f})')

    p('\n== 4. the module against the source at the sensor targets ==')
    for t_c, s_ in ((5, 0), (12, 0), (12, 35), (20, 35)):
        k_m, k_d = k0_h2s_module(t_c, s_), k0_h2s_dr(t_c, s_)
        ppb = 2.0e-6 / (k_d * M_H2S_2007)   # gas mole fraction (atm at 1 atm) for 2 ug/L free H2S, x 1e9 -> ppb
        p(f'  {t_c} C S{s_}: 2 ug/L free H2S <-> {ppb * 1e9:.0f} ppb (D&R); module would report '
          f'{2.0 * k_m / k_d:.3f} ug/L for that air')
        ppm = 10e-3 / (k0_co2(t_c, s_) * M_CO2) / co2_fugacity_factor(t_c)
        p(f'          10 mg/L CO2 <-> {ppm * 1e6:.0f} ppm moist air (fugacity-corrected); without: '
          f'{10e-3 / (k0_co2(t_c, s_) * M_CO2) * 1e6:.0f} ppm')
    p('  1 C error of water vs gas temperature at 12 C: K0 CO2 {:+.2%}/C, K0 H2S {:+.2%}/C'.format(
        k0_co2(13, 35) / k0_co2(12, 35) - 1, k0_h2s_dr(13, 35) / k0_h2s_dr(12, 35) - 1))

    print('\n'.join(out))
    return rows


if __name__ == '__main__':
    main()
