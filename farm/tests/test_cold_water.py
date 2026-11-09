"""Cold water, 0 to 12 °C (Norwegian farms' range), against published values and an independent implementation: the
application's formula 3 (chemcore/core/src/fresh.rs) for the NH3 share, the carbonic acid and water constants, the CO2
solubility and the free CO2 of fresh waters with their own ionic strength.

The independent implementation below takes nothing from the core: the thermodynamic constants are the analytic
expressions of the USGS PHREEQC databases (phreeqc.dat and wateq4f.dat, Parkhurst & Appelo; public domain; the numbers
only are used here, conventionally attributed to Plummer & Busenberg 1982, GCA 46: 1011, for K1, K2 and KH, and Harned
& Hamer 1933 for Kw: the attribution in print was not checked), the activity coefficients are Davies (1962) with the
Debye-Hückel A tabulated by Hamer (1968, NSRDS-NBS 24, table 3), and the carbonate system is Stumm & Morgan's (1996). The
core's constants are Millero et al. (2006), Millero (1995), Weiss (1974): a disagreement is between two literatures."""
import math

from django.test import SimpleTestCase

from ..water import chemistry, native

# log K = a + b T + c / T + d log10 T + e / T² (T in K), as the PHREEQC databases write them.
HCO3_FORMATION = (107.8871, 0.03252849, -5151.79, -38.92561, 563713.9)       # H+ + CO3-2 = HCO3-: pK2
CO2_FORMATION = (464.1965, 0.09344813, -26986.16, -165.75951, 2248628.9)     # CO3-2 + 2 H+ = CO2 + H2O: pK1 + pK2
WATER = (-283.971, -0.05069842, 13323.0, 102.24447, -1119669.0)              # H2O = OH- + H+: −pKw (wateq4f.dat)
CO2_GAS = (108.3865, 0.01985076, -6919.53, -40.45154, 669365.0)              # CO2(g) = CO2: log KH (wateq4f.dat)
# Hamer (1968), NSRDS-NBS 24, table 3: the Debye-Hückel A (molal) by °C.
HAMER_A = {0: 0.4918, 5: 0.4953, 10: 0.4989, 15: 0.5027}
# Emerson, Russo, Lund & Thurston (1975), J. Fish. Res. Board Can. 32: 2379, the % un-ionised ammonia of their table
# as US EPA (1985), Ambient water quality criteria for ammonia, reprints it: {°C: (pH 7.0, 7.5, 8.0)}. A secondary
# check: the reprinted values lie 0.3 to 0.5 % above Emerson et al.'s own equation (below) at every point (cross review
# F7: 0.261 against 0.2597 at 0 °C, pH 7.5; 1.83 against 1.8221 at 10 °C, pH 8.0), more than the table's three digits
# explain (about 0.06 %): the reprint was probably made with slightly different pK values (EPA 1985 not checked in print).
EMERSON = {0: (0.0826, 0.261, 0.820), 5: (0.125, 0.394, 1.23), 10: (0.186, 0.586, 1.83), 12: (0.217, 0.684, 2.13)}
COLD = (0.0, 2.0, 5.0, 8.0, 10.0, 12.0)


def emerson_pka(temp_c):
    """Emerson et al. (1975), their primary equation: pKa = 0.09018 + 2729.92 / T (T in K), fresh water, 0 to 30 °C."""
    return 0.09018 + 2729.92 / (temp_c + 273.15)


def log_k(coefficients, temp_c):
    t = temp_c + 273.15
    a, b, c, d, e = coefficients
    return a + b * t + c / t + d * math.log10(t) + e / t ** 2


def hamer_a(temp_c):
    rows = sorted(HAMER_A.items())
    for (t0, a0), (t1, a1) in zip(rows, rows[1:]):
        if t0 <= temp_c <= t1:
            return a0 + (a1 - a0) * (temp_c - t0) / (t1 - t0)
    raise ValueError(temp_c)


def davies(temp_c, strength, charge):
    root = math.sqrt(strength)
    return -hamer_a(temp_c) * charge ** 2 * (root / (1 + root) - 0.3 * strength)


def free_co2(temp_c, ph, alkalinity_mg_l, strength):
    """Free CO2 (mg/L) of a fresh water from its NBS pH, its alkalinity and its ionic strength, by the independent
    constants: [H+] = 10^−pH / γ1; K1 = K1° / γ1², K2 = K2° / γ2, Kw = Kw° / γ1² (Stumm & Morgan 1996, section 3.4)."""
    pk2 = log_k(HCO3_FORMATION, temp_c)
    pk1 = log_k(CO2_FORMATION, temp_c) - pk2
    one, two = 10 ** davies(temp_c, strength, 1), 10 ** davies(temp_c, strength, 2)
    k1, k2, kw = 10 ** -pk1 / one ** 2, 10 ** -pk2 / two, 10 ** log_k(WATER, temp_c) / one ** 2
    h = 10 ** -ph / one
    alkalinity = alkalinity_mg_l / 50.04345 / 1000                                   # eq/L
    a1, a2 = h * k1 / (h * h + h * k1 + k1 * k2), k1 * k2 / (h * h + h * k1 + k1 * k2)
    dic = (alkalinity - kw / h + h) / (a1 + 2 * a2)
    return dic * h * h / (h * h + h * k1 + k1 * k2) * 44.0095 * 1000


class ConstantsTests(SimpleTestCase):
    def test_the_carbonic_acid_and_water_constants_at_0_to_12_degrees(self):
        # Millero et al. (2006) at S 0 against Plummer & Busenberg (1982): within 0.002 pK; Millero (1995) against
        # Harned & Hamer (1933): within 0.007 pK (the core is 0.005 to 0.006 above it from 0 to 12 °C).
        for temp_c in COLD:
            pk2 = log_k(HCO3_FORMATION, temp_c)
            pk1 = log_k(CO2_FORMATION, temp_c) - pk2
            with self.subTest(temp_c=temp_c):
                self.assertAlmostEqual(-math.log10(chemistry.k1_sws(temp_c, 0)), pk1, delta=0.002)
                self.assertAlmostEqual(-math.log10(chemistry.k2_sws(temp_c, 0)), pk2, delta=0.002)
                # Why 0.007 for Kw: the core's is Millero (1995)'s seawater fit on the total scale (DOE 1994, its ln
                # constant 148.9652) at S = 0, which lies 0.004 to 0.006 pK above Harned & Owen's pure-water Kw (14.9435
                # at 0 °C, 13.9965 at 25 °C) and wateq4f's Harned & Hamer expression; Millero's own pure-water constant
                # 148.9802 would lie 0.002 below (cross review F8). It moves neither CO2 nor NH3 measurably below pH 9,
                # where OH- is under 0.1 % of the alkalinity.
                self.assertAlmostEqual(-math.log10(chemistry.kw_total(temp_c, 0)), -log_k(WATER, temp_c), delta=0.007)

    def test_the_co2_solubility(self):
        # Weiss (1974), per litre, against the PHREEQC database's KH, per kg: within 0.002 in log K (0.5 %).
        for temp_c in COLD:
            with self.subTest(temp_c=temp_c):
                self.assertAlmostEqual(math.log10(chemistry.k0_co2(temp_c, 0)), log_k(CO2_GAS, temp_c), delta=0.002)


class AmmoniaTests(SimpleTestCase):
    def test_the_nh3_share_meets_emersons_table(self):
        """With nothing measured the ionic strength is 0 and the share is the thermodynamic one: Emerson's table within
        0.6 % of itself (the table's three digits; Millero 1995 against Emerson's pK, under 0.002 pK)."""
        for temp_c, row in EMERSON.items():
            for ph, published in zip((7.0, 7.5, 8.0), row):
                with self.subTest(temp_c=temp_c, ph=ph):
                    found = 100 * chemistry.water_equilibria(float(temp_c), 0.0).nh3_share(ph)
                    self.assertAlmostEqual(found / published, 1, delta=0.006)

    def test_the_nh3_share_meets_emersons_equation(self):
        """With nothing measured the share's pK (pH + log10((1 − f) / f)) is Emerson et al.'s primary equation within
        0.002 pK from 0 to 25 °C (cross review F7: the core is within 0.0016, 0.0008 at 12 °C); the table above is the
        secondary check, with its +0.4 % bias."""
        for temp_c in (0.0, 2.0, 5.0, 8.0, 10.0, 12.0, 15.0, 20.0, 25.0):
            for ph in (7.0, 7.5, 8.0):
                share = chemistry.water_equilibria(temp_c, 0.0).nh3_share(ph)
                with self.subTest(temp_c=temp_c, ph=ph):
                    self.assertAlmostEqual(ph + math.log10((1 - share) / share), emerson_pka(temp_c), delta=0.002)

    def test_an_ion_rich_water_has_less_nh3_by_its_activities(self):
        """NH4+ and H+ are both monovalent, so KNH4 needs no activity: the share moves only by the meter's pH,
        [H+] = 10^−pH / γ1, so the corrected NH3% ≈ Emerson's at pH + log γ1. It is information: the judged share is
        the larger, the ideal one the limits were set on (cross review F1; test_limits_basis)."""
        for temp_c in (2.0, 5.0, 8.0, 12.0):
            for conductivity in (100.0, 500.0, 1000.0):
                eq = chemistry.water_equilibria(temp_c, 0.0, 80.0, conductivity_25_us_cm=conductivity)
                gamma = 10 ** davies(temp_c, 1.6e-5 * conductivity, 1)
                k = chemistry.k_nh4_sws(temp_c, 0)
                expected = k / (k + 10 ** -7.5 / gamma)
                with self.subTest(temp_c=temp_c, conductivity=conductivity):
                    self.assertAlmostEqual(eq.nh3_share_corrected(7.5) / expected, 1, delta=0.001)
                    self.assertAlmostEqual(eq.nh3_share(7.5) / (k / (k + 10 ** -7.5)), 1, delta=1e-12)


class CarbonDioxideTests(SimpleTestCase):
    def test_free_co2_of_cold_fresh_waters_against_an_independent_implementation(self):
        """Typical Norwegian fresh and RAS waters at 2, 5, 8 and 12 °C: the core's CO2 against the independent
        implementation within 0.5 %."""
        for temp_c in (2.0, 5.0, 8.0, 12.0):
            for ph, alkalinity, conductivity in ((6.8, 10.0, 30.0), (7.0, 40.0, 120.0), (7.2, 120.0, 500.0),
                                                 (7.5, 200.0, 1000.0)):
                eq = chemistry.water_equilibria(temp_c, 0.0, alkalinity, conductivity_25_us_cm=conductivity)
                meq = alkalinity / chemistry.MG_CACO3_PER_MEQ
                ours = eq.co2(eq.dic(meq, ph), ph) * chemistry.MG_CO2_PER_MMOL
                theirs = free_co2(temp_c, ph, alkalinity, 1.6e-5 * conductivity)
                with self.subTest(temp_c=temp_c, ph=ph, alkalinity=alkalinity):
                    self.assertAlmostEqual(ours / theirs, 1, delta=0.005)

    def test_the_ph_scale_offset_is_daviess_gamma_h(self):
        for temp_c in COLD:
            eq = native.water_equilibria(temp_c, 0.0, 120.0, conductivity_25_us_cm=500.0)
            with self.subTest(temp_c=temp_c):
                self.assertAlmostEqual(eq.ph_offset / davies(temp_c, 0.008, 1), 1, delta=0.002)
