"""The water's chemistry, worked out on read and never stored: the un-ionised ammonia of a TAN reading and
the oxygen saturation of a dissolved-oxygen reading (farm/water/read.py), and the carbonate and sulfide
systems the Deffeyes chart is drawn from (farm/water/deffeyes.py). Pure functions of floats, no database.
Ported from the source's engine (libs/aquaculture-engines/src/water-chemistry/water-quality.ts,
ammonia-calc.ts, co2-calc.ts, deffeyes-data.ts); where it was wrong the bug document says so (WQ-30 on).

The constants of one water (a temperature and a salinity) are worked out once (`equilibria`) on the free
pH scale; a pH as a meter reads it (NBS) is converted to the free scale with the same offset (the H⁺
activity coefficient of Zeebe & Wolf-Gladrow, the molal-to-per-kg factor and [H⁺]SWS/[H⁺]free). In fresh
water (S = 0) every scale factor is 1. Constants on the seawater (SWS) scale are divided by
1 + ST/KS + FT/KF, those on the total scale by 1 + ST/KS (KS Dickson 1990, KF Dickson & Riley 1979; ST
Morris & Riley 1966, FT Riley 1965).

- Carbonic acid: K1 and K2 of Millero, Graham, Huang, Bustos-Serrano & Pierrot (2006), Mar. Chem. 100:
  80, seawater scale, from fresh to sea water; the pure-water terms reproduce Harned's freshwater
  constants. (The source calls them Millero 2010; the coefficients are the 2006 ones, PyCO2SYS's
  kH2CO3_SWS_MGH06: WQ-39.)
- Water: Kw of Millero (1995), Geochim. Cosmochim. Acta 59: 661, total scale. Boric acid: KB of Dickson
  (1990), Deep-Sea Res. 37: 755, total scale, with total boron of Uppström (1974), 0.000232 g/kg per ‰
  chlorinity (S / 1.80655).
- Ammonium: K of Millero (1995), seawater scale; in fresh water pK equals Emerson et al. (1975),
  pK = 0.09018 + 2729.92 / T, within 0.002 up to 30 °C and 0.003 up to 40 °C (farm/tests/test_water.py
  pins both). NH₃ comes out as N, as
  TAN goes in.
- Hydrogen sulfide (H₂S ⇌ HS⁻ + H⁺): K of Millero, Plese & Fernandez (1988), Limnol. Oceanogr. 33: 269,
  total scale (as in Millero 1995): pK 6.98 in fresh water and 6.51 in sea water at 25 °C.
- Calcite and aragonite: the stoichiometric solubility products of Mucci (1983), Am. J. Sci. 283: 780,
  measured at S 5–44.

The carbonate system. With α0, α1, α2 the shares of DIC as CO₂, HCO₃⁻ and CO₃²⁻ at a pH, alkalinity =
DIC (α1 + 2 α2) + [OH⁻] − [H⁺] + [B(OH)₄⁻]: at a fixed pH a straight line in DIC, the pH's line on the
Deffeyes chart (Deffeyes 1965, Limnol. Oceanogr. 10: 412). So DIC = (alkalinity − intercept) / slope, and
CO₂ = DIC α0. Concentrations go in per litre and the constants are per kg of solution: in sea water the
[OH⁻] − [H⁺] + borate term (at most about 0.1 mmol) is off by the density, 2.7 %, below 0.003 meq/L.

Oxygen solubility. Benson & Krause (1984), the equation of Standard Methods 4500-O (APHA) and of the
USGS tables: ln C* = −139.34411 + 1.575701e5/T − 6.642308e7/T² + 1.243800e10/T³ − 8.621949e11/T⁴
− S (1.7674e−2 − 10.754/T + 2140.7/T²), C* in mg/L at 1 atm of moist air. At a barometric pressure P
(atm): Cp = C* P (1 − Pwv/P)(1 − θP) / ((1 − Pwv)(1 − θ)), with ln Pwv = 11.8571 − 3840.70/T − 216961/T²
and θ = 0.000975 − 1.426e−5 t + 6.436e−8 t². P follows from the site's altitude by the standard
atmosphere, P = (1 − 2.25577e−5 h)^5.25588. Saturation in % = 100 × mg/L ÷ Cp."""
import math
from dataclasses import dataclass
from functools import lru_cache

KELVIN = 273.15

# Molar masses from the IUPAC standard atomic weights (C 12.0107, O 15.9994, H 1.00794, S 32.065, Ca 40.078).
MG_CACO3_PER_MEQ = 50.04345           # alkalinity: mg/L as CaCO₃ ÷ 50.04345 = meq/L (CaCO₃ 100.0869 / 2)
MG_CO2_PER_MMOL = 44.0095
MG_CALCIUM_PER_MOL = 40078.0
H2S_PER_S = 34.08088 / 32.065         # µg H₂S per µg S: total sulfide is reported as S, H₂S limits as H₂S

# The pH range the solvers search, NBS (the source's solver domain).
SOLVER_PH = (0.0, 14.0)


# ---- the scales (from the source's engine) -----------------------------------------------------------------
def _total_sulfate(salinity):
    return (0.1400 / 96.062) * (salinity / 1.80655)


def _total_fluoride(salinity):
    return (0.000067 / 18.998) * (salinity / 1.80655)


def _total_boron(salinity):
    """Uppström (1974), mol/kg."""
    return 0.000232 / 10.811 * (salinity / 1.80655)


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


def _free_to_total(temp_c, salinity):
    """[H⁺]total / [H⁺]free = 1 + ST/KS; 1 in fresh water."""
    if salinity <= 0:
        return 1.0
    return 1 + _total_sulfate(salinity) / _ks(temp_c, salinity)


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


# ---- the constants, each on the scale of its source ---------------------------------------------------------
def k1_sws(temp_c, salinity):
    """First dissociation constant of carbonic acid, Millero et al. (2006), seawater scale, mol/kg."""
    t, root = temp_c + KELVIN, math.sqrt(salinity)
    pk = (-126.34048 + 6320.813 / t + 19.568224 * math.log(t)
          + 13.4191 * root + 0.0331 * salinity - 5.33e-5 * salinity ** 2
          + (-530.123 * root - 6.103 * salinity) / t - 2.06950 * root * math.log(t))
    return math.pow(10, -pk)


def k2_sws(temp_c, salinity):
    """Second dissociation constant of carbonic acid, Millero et al. (2006), seawater scale, mol/kg."""
    t, root = temp_c + KELVIN, math.sqrt(salinity)
    pk = (-90.18333 + 5143.692 / t + 14.613358 * math.log(t)
          + 21.0894 * root + 0.1248 * salinity - 3.687e-4 * salinity ** 2
          + (-772.483 * root - 20.051 * salinity) / t - 3.3336 * root * math.log(t))
    return math.pow(10, -pk)


def kw_total(temp_c, salinity):
    """Ion product of water, Millero (1995), total scale, (mol/kg)²."""
    t, root = temp_c + KELVIN, math.sqrt(salinity)
    return math.exp(148.9652 - 13847.26 / t - 23.6521 * math.log(t)
                    + (-5.977 + 118.67 / t + 1.0495 * math.log(t)) * root - 0.01615 * salinity)


def kb_total(temp_c, salinity):
    """Boric acid dissociation constant, Dickson (1990), total scale, mol/kg."""
    t, root = temp_c + KELVIN, math.sqrt(salinity)
    return math.exp((-8966.90 - 2890.53 * root - 77.942 * salinity + 1.728 * salinity * root
                     - 0.0996 * salinity ** 2) / t
                    + 148.0248 + 137.1942 * root + 1.62142 * salinity
                    + (-24.4344 - 25.085 * root - 0.2474 * salinity) * math.log(t)
                    + 0.053105 * root * t)


def k_nh4_sws(temp_c, salinity):
    """The ammonium dissociation constant (Millero 1995), seawater scale."""
    t = temp_c + KELVIN
    root = math.sqrt(salinity)
    return math.exp(-6285.33 / t + 0.0001635 * t - 0.25444 + (0.46532 - 123.7184 / t) * root
                    + (-0.01992 + 3.17556 / t) * salinity)


def pk_nh4(temp_c, salinity):
    """pK of NH₄⁺ on the seawater scale (= the free scale in fresh water)."""
    return -math.log10(k_nh4_sws(temp_c, salinity))


def k_h2s_total(temp_c, salinity):
    """First dissociation constant of hydrogen sulfide, Millero, Plese & Fernandez (1988), total scale."""
    t, root = temp_c + KELVIN, math.sqrt(salinity)
    return math.exp(225.838 - 13275.3 / t - 34.6435 * math.log(t) + 0.3449 * root - 0.0274 * salinity)


def ksp_calcite(temp_c, salinity):
    """Stoichiometric solubility product of calcite, Mucci (1983), (mol/kg)²."""
    t, root = temp_c + KELVIN, math.sqrt(salinity)
    return math.pow(10, -171.9065 - 0.077993 * t + 2839.319 / t + 71.595 * math.log10(t)
                    + (-0.77712 + 0.0028426 * t + 178.34 / t) * root - 0.07711 * salinity
                    + 0.0041249 * salinity * root)


def ksp_aragonite(temp_c, salinity):
    """Stoichiometric solubility product of aragonite, Mucci (1983), (mol/kg)²."""
    t, root = temp_c + KELVIN, math.sqrt(salinity)
    return math.pow(10, -171.945 - 0.077993 * t + 2903.293 / t + 71.595 * math.log10(t)
                    + (-0.068393 + 0.0017276 * t + 88.135 / t) * root - 0.10018 * salinity
                    + 0.0059415 * salinity * root)


def solve(function, low, high):
    """Where a monotone function crosses zero between two values (a pH, a DIC), by bisection to 1e-10; None
    when it does not change sign there."""
    at_low, at_high = function(low), function(high)
    if at_low == 0:
        return low
    if at_high == 0:
        return high
    if (at_low > 0) == (at_high > 0):
        return None
    for _step in range(200):
        middle = (low + high) / 2
        at_middle = function(middle)
        if (at_middle > 0) == (at_low > 0):
            low, at_low = middle, at_middle
        else:
            high = middle
        if high - low < 1e-10:
            break
    return (low + high) / 2


# ---- one water: its constants on the free scale, and what follows from a pH (NBS) --------------------------
@dataclass(frozen=True)
class Equilibria:
    """The equilibria of a water at one temperature and salinity. Concentrations: alkalinity in meq/L, DIC
    and CO₂ in mmol/L; a pH is as a meter reads it (NBS)."""
    temp_c: float
    salinity: float
    ph_offset: float        # pH free − pH NBS
    k1: float               # the constants on the free scale, mol/kg
    k2: float
    kw: float
    kb: float
    boron: float            # total boron, mol/kg
    k_nh4: float
    k_h2s: float
    ksp_calcite: float      # (mol/kg)²
    ksp_aragonite: float

    def hydrogen(self, ph):
        """[H⁺] on the free scale, mol/kg."""
        return math.pow(10, -(ph + self.ph_offset))

    def ph_of(self, hydrogen):
        """The NBS pH of a free [H⁺]."""
        return -math.log10(hydrogen) - self.ph_offset

    def fractions(self, ph):
        """α0, α1, α2: the shares of DIC as CO₂, HCO₃⁻ and CO₃²⁻."""
        h = self.hydrogen(ph)
        whole = h * h + h * self.k1 + self.k1 * self.k2
        return h * h / whole, h * self.k1 / whole, self.k1 * self.k2 / whole

    def isoline(self, ph):
        """The pH's line on the Deffeyes chart, alkalinity = slope × DIC + intercept: (slope, intercept in
        meq/L), slope α1 + 2 α2, intercept [OH⁻] − [H⁺] + [B(OH)₄⁻]."""
        _co2, bicarbonate, carbonate = self.fractions(ph)
        h = self.hydrogen(ph)
        borate = self.boron * self.kb / (self.kb + h)
        return bicarbonate + 2 * carbonate, (self.kw / h - h + borate) * 1000

    def dic(self, alkalinity, ph):
        slope, intercept = self.isoline(ph)
        return (alkalinity - intercept) / slope

    def alkalinity(self, dic, ph):
        slope, intercept = self.isoline(ph)
        return dic * slope + intercept

    def ph_at(self, dic, alkalinity):
        """The pH of a water with this DIC and alkalinity: the pH whose line passes through the point (the
        alkalinity of a DIC rises with the pH). None when no pH in the solver's range gives it."""
        if dic <= 0:
            return None
        return solve(lambda ph: self.alkalinity(dic, ph) - alkalinity, *SOLVER_PH)

    def co2(self, dic, ph):
        return dic * self.fractions(ph)[0]

    def carbonate(self, dic, ph):
        return dic * self.fractions(ph)[2]

    def nh3_share(self, ph):
        """The share of TAN that is un-ionised NH₃, 0 to 1: K / (K + [H⁺])."""
        return self.k_nh4 / (self.k_nh4 + self.hydrogen(ph))

    def h2s_share(self, ph):
        """The share of the total sulfide that is H₂S, 0 to 1: [H⁺] / (K + [H⁺])."""
        h = self.hydrogen(ph)
        return h / (self.k_h2s + h)

    # -- the pH at which a limit is reached --
    def ph_where_nh3(self, tan, limit):
        """The pH above which NH₃-N exceeds `limit` (mg/L, as TAN): [H⁺] = K (1 − f) / f with f = limit / TAN.
        None when TAN cannot give that much (limit ≥ TAN)."""
        if tan <= 0 or limit <= 0 or limit >= tan:
            return None
        share = limit / tan
        return self.ph_of(self.k_nh4 * (1 - share) / share)

    def ph_where_h2s(self, total, limit):
        """The pH below which H₂S exceeds `limit`, both in the same basis: [H⁺] = K f / (1 − f) with
        f = limit / total. None when the total cannot give that much (limit ≥ total)."""
        if total <= 0 or limit <= 0 or limit >= total:
            return None
        share = limit / total
        return self.ph_of(self.k_h2s * share / (1 - share))

    def ph_where_co2(self, alkalinity, co2):
        """The pH below which CO₂ (mmol/L) exceeds `co2` at a fixed alkalinity (meq/L): CO₂ falls as the pH
        rises along the alkalinity, so one root; None when it is not reached in the solver's range."""
        return solve(lambda ph: self.co2(self.dic(alkalinity, ph), ph) - co2, *SOLVER_PH)

    def ph_where_co2_at_dic(self, dic, co2):
        """The pH at which a DIC (mmol/L) holds `co2` (mmol/L) as CO₂: α0 = c / DIC solved for [H⁺]. None when
        the DIC cannot hold that much (c ≥ DIC)."""
        if dic <= 0 or co2 <= 0 or co2 >= dic:
            return None
        share = co2 / dic
        k1, k2 = self.k1, self.k2
        h = (share * k1 + math.sqrt((share * k1) ** 2 + 4 * (1 - share) * share * k1 * k2)) / (2 * (1 - share))
        return self.ph_of(h)

    def ph_where_carbonate(self, dic, carbonate):
        """The pH at which a DIC (mmol/L) holds `carbonate` (mmol/L) as CO₃²⁻: α2 = c / DIC solved for [H⁺].
        None when the DIC cannot hold that much."""
        if dic <= 0 or carbonate <= 0 or carbonate >= dic:
            return None
        share = carbonate / dic
        k1, k2 = self.k1, self.k2
        h = (-share * k1 + math.sqrt((share * k1) ** 2 + 4 * share * (1 - share) * k1 * k2)) / (2 * share)
        return self.ph_of(h)


@lru_cache(maxsize=256)
def equilibria(temp_c, salinity):
    """The equilibria of a water at a temperature (°C) and salinity (‰)."""
    temp_c, salinity = float(temp_c), float(salinity)
    to_sws, to_total = _free_to_sws(temp_c, salinity), _free_to_total(temp_c, salinity)
    return Equilibria(
        temp_c=temp_c, salinity=salinity,
        ph_offset=math.log10(_sws_to_nbs(temp_c, salinity)) + math.log10(to_sws),
        k1=k1_sws(temp_c, salinity) / to_sws, k2=k2_sws(temp_c, salinity) / to_sws,
        kw=kw_total(temp_c, salinity) / to_total, kb=kb_total(temp_c, salinity) / to_total,
        boron=_total_boron(salinity),
        k_nh4=k_nh4_sws(temp_c, salinity) / to_sws, k_h2s=k_h2s_total(temp_c, salinity) / to_total,
        ksp_calcite=ksp_calcite(temp_c, salinity), ksp_aragonite=ksp_aragonite(temp_c, salinity))


def nh3_fraction(ph_nbs, temp_c, salinity):
    """The share of TAN that is un-ionised NH₃, 0 to 1."""
    return equilibria(temp_c, salinity).nh3_share(ph_nbs)


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
