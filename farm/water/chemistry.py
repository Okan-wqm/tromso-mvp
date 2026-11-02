"""The two values a sample's own readings give without a new measurement, computed on read and never
stored (farm/water/read.py): the un-ionised ammonia of a TAN reading, and the oxygen saturation of a
dissolved-oxygen reading (or the other way round). Pure functions of floats, no database.

Un-ionised ammonia (NH₃-N). NH₄⁺ ⇌ NH₃ + H⁺, so the share of TAN that is NH₃ is K / (K + [H⁺]). K is
Millero (1995)'s ammonium constant on the seawater scale, converted to the free scale, and the pH (NBS,
as a meter reads it) is converted to the free scale too; ported as it stands from the source's engine
(libs/aquaculture-engines/src/water-chemistry/water-quality.ts: totalSulfate, totalFluoride, calcKS,
calcKF, getKNH4, calcIonicStrength, molalToMolin, ahSwsToNbsFactor, phNbsToFree,
calcActivityCoefficientH, ahFreeToSwsFactor, swsToFree; ammonia-calc.ts: fractionNH3). In fresh water
(S = 0) every scale factor is 1 and pK equals Emerson et al. (1975), pK = 0.09018 + 2729.92 / T, within
0.002 (farm/tests/test_water.py pins both). NH₃ comes out as N, as TAN goes in.

Oxygen solubility. Benson & Krause (1984), the equation of Standard Methods 4500-O (APHA) and of the
USGS tables: ln C* = −139.34411 + 1.575701e5/T − 6.642308e7/T² + 1.243800e10/T³ − 8.621949e11/T⁴
− S (1.7674e−2 − 10.754/T + 2140.7/T²), C* in mg/L at 1 atm of moist air. At a barometric pressure P
(atm): Cp = C* P (1 − Pwv/P)(1 − θP) / ((1 − Pwv)(1 − θ)), with ln Pwv = 11.8571 − 3840.70/T − 216961/T²
and θ = 0.000975 − 1.426e−5 t + 6.436e−8 t². P follows from the site's altitude by the standard
atmosphere, P = (1 − 2.25577e−5 h)^5.25588. Saturation in % = 100 × mg/L ÷ Cp."""
import math

KELVIN = 273.15


# ---- un-ionised ammonia (Millero 1995, from the source's engine) --------------------------------------
def _total_sulfate(salinity):
    return (0.1400 / 96.062) * (salinity / 1.80655)


def _total_fluoride(salinity):
    return (0.000067 / 18.998) * (salinity / 1.80655)


def _ionic_strength(salinity):
    return 19.924 * salinity / (1000 - 1.005 * salinity)


def _ks(temp_c, salinity):
    """Bisulfate dissociation constant (Dickson 1990), free scale."""
    t = temp_c + KELVIN
    i = _ionic_strength(salinity)
    root = math.sqrt(i)
    return math.exp(-4276.1 / t + 141.328 - 23.093 * math.log(t)
                    + (-13856.0 / t + 324.57 - 47.986 * math.log(t)) * root
                    + (35474.0 / t - 771.54 + 114.723 * math.log(t)) * i
                    + (-2698.0 / t) * i * root + (1776.0 / t) * i * i
                    + math.log(1 - 0.001005 * salinity))


def _kf(temp_c, salinity):
    """Hydrogen fluoride dissociation constant (Dickson & Riley 1979)."""
    t = temp_c + KELVIN
    i = _ionic_strength(salinity)
    return math.exp(1590.2 / t - 12.641 + 1.525 * math.sqrt(i) + math.log(1 - 0.001005 * salinity))


def _free_to_sws(temp_c, salinity):
    """[H⁺]SWS / [H⁺]free = 1 + ST/KS + FT/KF; 1 in fresh water."""
    if salinity <= 0:
        return 1.0
    return 1 + _total_sulfate(salinity) / _ks(temp_c, salinity) + _total_fluoride(salinity) / _kf(temp_c, salinity)


def _activity_coefficient_h(temp_c, salinity):
    """The H⁺ activity coefficient (Zeebe & Wolf-Gladrow), for the NBS scale; 1 in fresh water."""
    if salinity <= 0:
        return 1.0
    t = temp_c + KELVIN
    i = _ionic_strength(salinity)
    root = math.sqrt(i)
    a = 1820000.0 * math.pow(79 * t, -1.5)
    return math.pow(10, -(a * (root / (1 + root) - 0.2 * i)))


def _sws_to_nbs(temp_c, salinity):
    return _activity_coefficient_h(temp_c, salinity) / (1.0 - 0.001005 * salinity)


def ph_free(ph_nbs, temp_c, salinity):
    """A pH read on the NBS scale (a meter or a kit), on the free scale."""
    return ph_nbs + math.log10(_sws_to_nbs(temp_c, salinity)) + math.log10(_free_to_sws(temp_c, salinity))


def k_nh4_sws(temp_c, salinity):
    """The ammonium dissociation constant (Millero 1995), seawater scale."""
    t = temp_c + KELVIN
    root = math.sqrt(salinity)
    return math.exp(-6285.33 / t + 0.0001635 * t - 0.25444 + (0.46532 - 123.7184 / t) * root
                    + (-0.01992 + 3.17556 / t) * salinity)


def pk_nh4(temp_c, salinity):
    """pK of NH₄⁺ on the seawater scale (= the free scale in fresh water)."""
    return -math.log10(k_nh4_sws(temp_c, salinity))


def nh3_fraction(ph_nbs, temp_c, salinity):
    """The share of TAN that is un-ionised NH₃, 0 to 1."""
    k_free = k_nh4_sws(temp_c, salinity) / _free_to_sws(temp_c, salinity)
    h = math.pow(10, -ph_free(ph_nbs, temp_c, salinity))
    return k_free / (k_free + h)


# ---- oxygen (Benson & Krause 1984; APHA 4500-O) --------------------------------------------------------
def pressure_atm(altitude_m):
    """The standard atmosphere's barometric pressure at an altitude, in atm (1 at sea level)."""
    return math.pow(1 - 2.25577e-5 * altitude_m, 5.25588)


def oxygen_solubility(temp_c, salinity, pressure=1.0):
    """The oxygen water holds in equilibrium with moist air, in mg/L, at a barometric pressure in atm."""
    t = temp_c + KELVIN
    ln_c = (-139.34411 + 1.575701e5 / t - 6.642308e7 / t ** 2 + 1.243800e10 / t ** 3 - 8.621949e11 / t ** 4
            - salinity * (1.7674e-2 - 10.754 / t + 2140.7 / t ** 2))
    c = math.exp(ln_c)
    if pressure == 1.0:
        return c
    vapour = math.exp(11.8571 - 3840.70 / t - 216961 / t ** 2)
    theta = 0.000975 - 1.426e-5 * temp_c + 6.436e-8 * temp_c ** 2
    return c * pressure * (1 - vapour / pressure) * (1 - theta * pressure) / ((1 - vapour) * (1 - theta))
