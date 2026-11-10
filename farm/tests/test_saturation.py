"""The calcite and aragonite saturation Ω of formula 3 (owner-approved correction, 2026-11-10; the independent check of
2026-11-09, claim 12b): Ω = [Ca²⁺] [CO₃²⁻] / Ksp takes the calcium (mg/L) and the carbonate (of a per-litre alkalinity)
per litre, and Mucci's (1983) Ksp is per kg², so the Ksp is taken per litre: times the square of the sea water's density
(EOS-80, Millero & Poisson 1981). Before, Ω was too high by ρ²: +4.7 % at S 35 and 25 °C, up to +7.6 % at S 40. One
definition in the core (Equilibria::ksp_per_litre) for the small chart's index and the chart's Ω = 1 line; formula 1
keeps the per-kg Ksp by name (golden v1)."""
import math

from django.test import SimpleTestCase

from ..water import charts, deffeyes, native


def eos80(temp_c, salinity):
    """The density of sea water at one atmosphere, kg/m³, typed here from Dickson, Sabine & Christian (2007), Guide to
    Best Practices for Ocean CO2 Measurements, ch. 5, section 4.2, eq. (6) to (10) (Millero & Poisson 1981): independent
    of the core's."""
    t, s = temp_c, salinity
    smow = (999.842594 + 6.793952e-2 * t - 9.095290e-3 * t ** 2 + 1.001685e-4 * t ** 3 - 1.120083e-6 * t ** 4
            + 6.536332e-9 * t ** 5)
    a = 8.24493e-1 - 4.0899e-3 * t + 7.6438e-5 * t ** 2 - 8.2467e-7 * t ** 3 + 5.3875e-9 * t ** 4
    b = -5.72466e-3 + 1.0227e-4 * t - 1.6546e-6 * t ** 2
    return smow + a * s + b * s ** 1.5 + 4.8314e-4 * s ** 2


def sea_water(temp_c, salinity, ph=8.1, formula=native.FORMULA_VERSION):
    return deffeyes.Water(temp_c, salinity, ph, 115.0, calcium_mg_l=412.0 * salinity / 35.0, formula=formula)


class DensityTests(SimpleTestCase):
    def test_the_check_values(self):
        # The Guide (as above): 1023.343 kg/m³ at 25 °C and S 35. UNESCO (1983), Fofonoff & Millard, Tech. Pap. Mar. Sci.
        # 44, the check values of its density algorithm at p = 0: 1027.67547 at 5 °C and 1023.34306 at 25 °C, S 35.
        self.assertAlmostEqual(1000 * native.seawater_density(25.0, 35.0), 1023.343, delta=1e-3)
        self.assertAlmostEqual(1000 * native.seawater_density(25.0, 35.0), 1023.34306, delta=1e-5)
        self.assertAlmostEqual(1000 * native.seawater_density(5.0, 35.0), 1027.67547, delta=1e-5)

    def test_the_core_is_the_equation_as_printed(self):
        for temp_c in (0.0, 2.0, 5.0, 12.0, 25.0, 40.0):
            for salinity in (0.0, 5.0, 20.0, 35.0, 42.0, 44.0):
                with self.subTest(temp_c=temp_c, salinity=salinity):
                    self.assertTrue(math.isclose(1000 * native.seawater_density(temp_c, salinity),
                                                 eos80(temp_c, salinity), rel_tol=1e-14))

    def test_what_is_not_a_water_is_refused(self):
        with self.assertRaises(ValueError):
            native.seawater_density(10.0, -1.0)
        with self.assertRaises(native.NonFiniteError):
            native.seawater_density(float('nan'), 35.0)


class SaturationTests(SimpleTestCase):
    def test_the_small_charts_index_takes_the_ksp_per_litre(self):
        for temp_c, salinity in ((25.0, 35.0), (5.0, 35.0), (10.0, 5.0), (40.0, 40.0), (5.0, 44.0)):
            analysis = deffeyes.analyse(sea_water(temp_c, salinity))
            eq, density = analysis.equilibria, eos80(temp_c, salinity) / 1000
            plot = charts.plots(analysis)['saturation']
            self.assertIsNotNone(plot)
            for (name, _label, points), ksp in zip(plot.series, (eq.ksp_calcite, eq.ksp_aragonite)):
                for ph, index in points:
                    carbonate = eq.carbonate(analysis.dic, ph) / 1000                     # mol/L
                    expected = math.log10(analysis.water.calcium_mg_l / native.MG_CALCIUM_PER_MOL * carbonate
                                          / (ksp * density ** 2))
                    with self.subTest(temp_c=temp_c, salinity=salinity, mineral=name, ph=ph):
                        self.assertAlmostEqual(index, expected, delta=1e-11)

    def test_omega_is_lower_than_formula_1s_arithmetic_by_the_density_squared(self):
        """What the pages showed before: +4.7 % in Ω at S 35 and 25 °C (0.020 in the index), +5.6 % at 5 °C."""
        for temp_c, percent in ((25.0, 4.72), (5.0, 5.61)):
            analysis = deffeyes.analyse(sea_water(temp_c, 35.0))
            eq = analysis.equilibria
            carbonate = eq.carbonate(analysis.dic, 8.1) / 1000
            before = math.log10(analysis.water.calcium_mg_l / native.MG_CALCIUM_PER_MOL * carbonate / eq.ksp_calcite)
            now = native.saturation_index(eq, analysis.dic, 8.1, analysis.water.calcium_mg_l, eq.ksp_calcite)
            with self.subTest(temp_c=temp_c):
                self.assertAlmostEqual(100 * (10 ** (before - now) - 1), percent, delta=0.01)

    def test_on_the_charts_omega_line_the_index_is_0(self):
        """The chart's Ω = 1 line and the small chart's index are one definition: along the line the index is 0, by
        either formula (a density in one of the two only would leave 0.02 at S 35)."""
        for formula in native.FORMULAS:
            analysis = deffeyes.analyse(sea_water(25.0, 35.0, formula=formula))
            eq = analysis.equilibria
            shape = deffeyes.geometry(analysis, layers=frozenset({'omega'}))
            for name, ksp in (('calcite', eq.ksp_calcite), ('aragonite', eq.ksp_aragonite)):
                points = [point for line in shape.omega[name] for point in line]
                self.assertGreater(len(points), 10)
                for dic, alkalinity in points:
                    ph = eq.ph_at(dic, alkalinity)
                    index = native.saturation_index(eq, dic, ph, analysis.water.calcium_mg_l, ksp)
                    with self.subTest(formula=formula, mineral=name, dic=dic):
                        self.assertAlmostEqual(index, 0.0, delta=1e-3)

    def test_formula_1_keeps_the_ksp_per_kg(self):
        analysis = deffeyes.analyse(sea_water(25.0, 35.0, formula=1))
        eq = analysis.equilibria
        carbonate = eq.carbonate(analysis.dic, 8.1)
        expected = math.log10(analysis.water.calcium_mg_l / native.MG_CALCIUM_PER_MOL * carbonate / 1000.0
                              / eq.ksp_calcite)
        self.assertAlmostEqual(native.saturation_index(eq, analysis.dic, 8.1, analysis.water.calcium_mg_l,
                                                       eq.ksp_calcite), expected, delta=1e-13)
