"""Independent anchors: the constants and one carbonate chain at three waters, worked out at 50 significant digits
with mpmath from the formulas AS PUBLISHED (typed from the papers, not copied from farm/water/chemistry.py or from
the Rust core), each paper's own check value asserted first. Two implementations that share a typo agree with each
other; they do not agree with this. Writes chemcore/golden/anchors.json; farm/tests/test_golden.py compares today's
Python with it (and the Rust core, as each function moves).

    docker run --rm -v "$PWD:/app" -w /app python:3.12-slim@sha256:aa943ce4... sh -c \
        'pip install --require-hashes -r chemcore/scripts/anchors.lock && python chemcore/scripts/anchors_mpmath.py'

mpmath 1.3.0 (BSD-3-Clause), used only here, never by the server."""
import json
import sys
from pathlib import Path

import mpmath as mp

mp.mp.dps = 50
OUT = Path(__file__).resolve().parent.parent / 'golden' / 'anchors.json'
WATERS = [(mp.mpf(25), mp.mpf(35)), (mp.mpf(10), mp.mpf(0)), (mp.mpf(15), mp.mpf(15))]
K = mp.mpf('273.15')


def ln(x):
    return mp.log(x)


# -- Dickson (1990) J. Chem. Thermodyn. 22: 113, bisulfate, free scale, mol/kg-H2O then to mol/kg-soln; and the
#    ionic strength of sea water I = 19.924 S / (1000 - 1.005 S) (DOE 1994, chapter 5) --
def ionic(S):
    return mp.mpf('19.924') * S / (1000 - mp.mpf('1.005') * S)


def ks(t, S):
    T, I = t + K, ionic(S)
    return mp.exp(mp.mpf('-4276.1') / T + mp.mpf('141.328') - mp.mpf('23.093') * ln(T)
                  + (mp.mpf('-13856') / T + mp.mpf('324.57') - mp.mpf('47.986') * ln(T)) * mp.sqrt(I)
                  + (mp.mpf('35474') / T - mp.mpf('771.54') + mp.mpf('114.723') * ln(T)) * I
                  - mp.mpf('2698') / T * I ** mp.mpf('1.5') + mp.mpf('1776') / T * I ** 2
                  + ln(1 - mp.mpf('0.001005') * S))


# -- Dickson & Riley (1979) Mar. Chem. 7: 89, hydrogen fluoride, free scale --
def kf(t, S):
    T, I = t + K, ionic(S)
    return mp.exp(mp.mpf('1590.2') / T - mp.mpf('12.641') + mp.mpf('1.525') * mp.sqrt(I) + ln(1 - mp.mpf('0.001005') * S))


# totals: sulfate Morris & Riley (1966) 0.1400 g/kg per Cl, fluoride Riley (1965) 6.7e-5, boron Uppstroem (1974)
# 2.32e-4 g/kg per chlorinity; chlorinity = S / 1.80655
def st(S):
    return mp.mpf('0.14') / mp.mpf('96.062') * S / mp.mpf('1.80655')


def ft(S):
    return mp.mpf('0.000067') / mp.mpf('18.998') * S / mp.mpf('1.80655')


def bt(S):
    return mp.mpf('0.000232') / mp.mpf('10.811') * S / mp.mpf('1.80655')


# -- Millero, Graham, Huang, Bustos-Serrano & Pierrot (2006) Mar. Chem. 100: 80, seawater scale --
def pk1(t, S):
    T = t + K
    return (mp.mpf('-126.34048') + mp.mpf('6320.813') / T + mp.mpf('19.568224') * ln(T)
            + mp.mpf('13.4191') * mp.sqrt(S) + mp.mpf('0.0331') * S - mp.mpf('5.33e-5') * S ** 2
            + (mp.mpf('-530.123') * mp.sqrt(S) - mp.mpf('6.103') * S) / T - mp.mpf('2.06950') * mp.sqrt(S) * ln(T))


def pk2(t, S):
    T = t + K
    return (mp.mpf('-90.18333') + mp.mpf('5143.692') / T + mp.mpf('14.613358') * ln(T)
            + mp.mpf('21.0894') * mp.sqrt(S) + mp.mpf('0.1248') * S - mp.mpf('3.687e-4') * S ** 2
            + (mp.mpf('-772.483') * mp.sqrt(S) - mp.mpf('20.051') * S) / T - mp.mpf('3.3336') * mp.sqrt(S) * ln(T))


# -- Kw as formula 1 takes it (the core's `kw_total`): Dickson, Sabine & Christian (2007), Guide to Best Practices, ch. 5,
# eq. (62), the total scale: Millero's (1995, Geochim. Cosmochim. Acta 59: 661) seawater-scale constant 148.9802 less the
# 0.015 of the Guide's footnote 5, an approximate shift (not Millero's own number; formula 3 takes his, `kw_sws`, which
# has no anchor here). NH4+: Millero (1995), seawater scale --
def kw(t, S):
    T = t + K
    return mp.exp(mp.mpf('148.9652') - mp.mpf('13847.26') / T - mp.mpf('23.6521') * ln(T)
                  + (mp.mpf('-5.977') + mp.mpf('118.67') / T + mp.mpf('1.0495') * ln(T)) * mp.sqrt(S) - mp.mpf('0.01615') * S)


def knh4(t, S):
    T = t + K
    return mp.exp(mp.mpf('-6285.33') / T + mp.mpf('0.0001635') * T - mp.mpf('0.25444')
                  + (mp.mpf('0.46532') - mp.mpf('123.7184') / T) * mp.sqrt(S)
                  + (mp.mpf('-0.01992') + mp.mpf('3.17556') / T) * S)


# -- Dickson (1990) Deep-Sea Res. 37: 755, boric acid, total scale --
def kb(t, S):
    T, r = t + K, mp.sqrt(S)
    return mp.exp((mp.mpf('-8966.90') - mp.mpf('2890.53') * r - mp.mpf('77.942') * S + mp.mpf('1.728') * S * r
                   - mp.mpf('0.0996') * S ** 2) / T
                  + mp.mpf('148.0248') + mp.mpf('137.1942') * r + mp.mpf('1.62142') * S
                  - (mp.mpf('24.4344') + mp.mpf('25.085') * r + mp.mpf('0.2474') * S) * ln(T)
                  + mp.mpf('0.053105') * r * T)


# -- Millero, Plese & Fernandez (1988) Limnol. Oceanogr. 33: 269, H2S, total scale --
def kh2s(t, S):
    T = t + K
    return mp.exp(mp.mpf('225.838') - mp.mpf('13275.3') / T - mp.mpf('34.6435') * ln(T)
                  + mp.mpf('0.3449') * mp.sqrt(S) - mp.mpf('0.0274') * S)


# -- Mucci (1983) Am. J. Sci. 283: 780, stoichiometric solubility products --
def ksp(t, S, mineral):
    T, r = t + K, mp.sqrt(S)
    if mineral == 'calcite':
        log_k = (mp.mpf('-171.9065') - mp.mpf('0.077993') * T + mp.mpf('2839.319') / T + mp.mpf('71.595') * mp.log10(T)
                 + (mp.mpf('-0.77712') + mp.mpf('0.0028426') * T + mp.mpf('178.34') / T) * r
                 - mp.mpf('0.07711') * S + mp.mpf('0.0041249') * S * r)
    else:
        log_k = (mp.mpf('-171.945') - mp.mpf('0.077993') * T + mp.mpf('2903.293') / T + mp.mpf('71.595') * mp.log10(T)
                 + (mp.mpf('-0.068393') + mp.mpf('0.0017276') * T + mp.mpf('88.135') / T) * r
                 - mp.mpf('0.10018') * S + mp.mpf('0.0059415') * S * r)
    return mp.power(10, log_k)


# -- Benson & Krause (1984) Limnol. Oceanogr. 29: 620, as APHA 4500-O gives it, mg/L at 1 atm moist air --
def oxygen(t, S):
    T = t + K
    return mp.exp(mp.mpf('-139.34411') + mp.mpf('1.575701e5') / T - mp.mpf('6.642308e7') / T ** 2
                  + mp.mpf('1.243800e10') / T ** 3 - mp.mpf('8.621949e11') / T ** 4
                  - S * (mp.mpf('1.7674e-2') - mp.mpf('10.754') / T + mp.mpf('2140.7') / T ** 2))


# -- Weiss (1974) Mar. Chem. 2: 203, CO2 solubility: per kg (check value) and per litre (the one used) --
def k0(t, S, per='litre'):
    T = (t + K) / 100
    a = ((mp.mpf('-60.2409'), mp.mpf('93.4517'), mp.mpf('23.3585'), mp.mpf('0.023517'), mp.mpf('-0.023656'),
          mp.mpf('0.0047036')) if per == 'kg' else
         (mp.mpf('-58.0931'), mp.mpf('90.5069'), mp.mpf('22.2940'), mp.mpf('0.027766'), mp.mpf('-0.025888'),
          mp.mpf('0.0050578')))
    return mp.exp(a[0] + a[1] / T + a[2] * ln(T) + S * (a[3] + a[4] * T + a[5] * T ** 2))


def check(name, value, expected, tolerance):
    if abs(value - expected) > tolerance:
        raise SystemExit(f'check value of {name}: {mp.nstr(value, 12)} != {expected} (+-{tolerance})')


def checks():
    t, S = mp.mpf(25), mp.mpf(35)
    check('ln KB, Dickson 1990 (DOE 1994)', ln(kb(t, S)), mp.mpf('-19.7964'), mp.mpf('0.00005'))
    check('ln Kw, Millero 1995 (DOE 1994)', ln(kw(t, S)), mp.mpf('-30.434'), mp.mpf('0.0005'))
    check('ln KS, Dickson 1990 (DOE 1994)', ln(ks(t, S)), mp.mpf('-2.30'), mp.mpf('0.005'))
    check('ln K0 per kg, Weiss 1974 (DOE 1994)', ln(k0(t, S, 'kg')), mp.mpf('-3.5617'), mp.mpf('0.00005'))
    check('Ksp calcite 25/35, Mucci 1983', ksp(t, S, 'calcite') * mp.mpf('1e7'), mp.mpf('4.27'), mp.mpf('0.005'))
    check('Ksp aragonite 25/35, Mucci 1983', ksp(t, S, 'aragonite') * mp.mpf('1e7'), mp.mpf('6.48'), mp.mpf('0.005'))
    check('O2 25 degC fresh, APHA 4500-O table 8.26', oxygen(t, 0), mp.mpf('8.26'), mp.mpf('0.005'))
    check('pK NH4 25 degC fresh vs Emerson 1975', -mp.log10(knh4(t, 0)), mp.mpf('0.09018') + mp.mpf('2729.92') / (t + K),
          mp.mpf('0.002'))
    check('pK1 25 degC fresh, Harned & Davis 6.352', pk1(t, 0), mp.mpf('6.352'), mp.mpf('0.003'))
    check('pK2 25 degC fresh, Harned & Scholes 10.329', pk2(t, 0), mp.mpf('10.329'), mp.mpf('0.003'))


def anchors():
    rows = []
    for t, S in WATERS:
        to_sws = 1 + st(S) / ks(t, S) + ft(S) / kf(t, S) if S > 0 else mp.mpf(1)
        to_total = 1 + st(S) / ks(t, S) if S > 0 else mp.mpf(1)
        k1, k2 = mp.power(10, -pk1(t, S)) / to_sws, mp.power(10, -pk2(t, S)) / to_sws
        kw_free, kb_free = kw(t, S) / to_total, kb(t, S) / to_total
        # one chain on the free scale: pH_free 7.5, alkalinity 2 meq/L (Deffeyes 1965: DIC = (A - [OH] + [H] -
        # [B(OH)4]) / (a1 + 2 a2))
        h = mp.power(10, -mp.mpf('7.5'))
        whole = h * h + h * k1 + k1 * k2
        a0, a1, a2 = h * h / whole, h * k1 / whole, k1 * k2 / whole
        borate = bt(S) * kb_free / (kb_free + h)
        dic = (2 - (kw_free / h - h + borate) * 1000) / (a1 + 2 * a2)
        rows.append({'temp_c': float(t), 'salinity': float(S), 'values': {name: mp.nstr(value, 40) for name, value in {
            'free_to_sws': to_sws, 'free_to_total': to_total, 'k1_free': k1, 'k2_free': k2, 'kw_free': kw_free,
            'kb_free': kb_free, 'k_nh4_free': knh4(t, S) / to_sws, 'k_h2s_free': kh2s(t, S) / to_total,
            'k1_sws': mp.power(10, -pk1(t, S)), 'k2_sws': mp.power(10, -pk2(t, S)), 'kw_total': kw(t, S),
            'kb_total': kb(t, S), 'k_nh4_sws': knh4(t, S), 'k_h2s_total': kh2s(t, S),
            'ksp_calcite': ksp(t, S, 'calcite'), 'ksp_aragonite': ksp(t, S, 'aragonite'),
            'oxygen_solubility': oxygen(t, S), 'k0_co2': k0(t, S), 'total_boron': bt(S),
            'dic_at_ph_free_7_5_alk_2': dic, 'co2_at_ph_free_7_5_alk_2': dic * a0}.items()}})
    return rows


if __name__ == '__main__':
    checks()
    OUT.write_text(json.dumps({'generated_by': 'chemcore/scripts/anchors_mpmath.py, mpmath ' + mp.__version__
                               + ', 50 digits', 'anchors': anchors()}, indent=1) + '\n', encoding='utf-8')
    sys.stdout.write(OUT.read_text(encoding='utf-8')[:400])
