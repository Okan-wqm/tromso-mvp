//! The water's equilibria: the carbonate, borate, water, ammonium and sulfide constants of a temperature and a
//! salinity on the free pH scale, the pH scales between them, the solver, and the gases (oxygen, CO₂ from the air).
//! A literal port of farm/water/chemistry.py as it was at golden v1 (chemcore/golden/v1): the same operations in the
//! same order, every transcendental from `libm`, and an error exactly where Python raised (crate::num).
//!
//! Every constant is per kg of solution on the scale of its source; a pH as a meter reads it (NBS) is converted to the
//! free scale with the same offset (the H⁺ activity coefficient of Zeebe & Wolf-Gladrow 2001, the molal-to-per-kg
//! factor and [H⁺]SWS/[H⁺]free). In fresh water (S ≤ 0) every scale factor is 1 (a limitation, I2 in
//! chemcore/findings/B1.md). Constants on the seawater (SWS) scale are divided by 1 + ST/KS + FT/KF, those on the
//! total scale by 1 + ST/KS.
//!
//! Validity ranges are stated beside each formula as information: the core does not refuse a water outside them
//! (Python never did); it refuses only where the mathematics fails.
use crate::num::{ChemError, R, div, exp, finite, ln, log10, pow, sqrt};

pub const KELVIN: f64 = 273.15;
/// Alkalinity: mg/L as CaCO₃ ÷ 50.04345 = meq/L (CaCO₃ 100.0869 / 2, IUPAC 2007 atomic weights).
pub const MG_CACO3_PER_MEQ: f64 = 50.04345;
/// CO₂, mg per mmol: C 12.0107 + 2 O 15.9994 (IUPAC 2007); decided over the source's 44.0096 (B1-01).
pub const MG_CO2_PER_MMOL: f64 = 44.0095;
/// Calcium, mg per mol (Ca 40.078).
pub const MG_CALCIUM_PER_MOL: f64 = 40078.0;
/// µg H₂S per µg S: total sulfide is reported as S, H₂S limits as H₂S (34.08088 / 32.065).
pub const H2S_PER_S: f64 = 34.08088 / 32.065;
/// The pH range the solvers search, NBS.
pub const SOLVER_PH: (f64, f64) = (0.0, 14.0);
/// The air's CO₂, mol/mol of dry air: 420 µmol/mol, outdoor air in 2024 (NOAA Global Monitoring Laboratory).
pub const AIR_CO2: f64 = 420e-6;

// ---- totals and ionic strength (from the salinity) -------------------------------------------------------------

/// Total sulfate, mol/kg: Morris & Riley (1966), 0.1400 g/kg per ‰ chlorinity (S / 1.80655). Sea water.
pub fn total_sulfate(salinity: f64) -> f64 {
    (0.1400 / 96.062) * (salinity / 1.80655)
}

/// Total fluoride, mol/kg: Riley (1965), 6.7e-5 g/kg per ‰ chlorinity. Sea water.
pub fn total_fluoride(salinity: f64) -> f64 {
    (0.000067 / 18.998) * (salinity / 1.80655)
}

/// Total boron, mol/kg: Uppström (1974), 2.32e-4 g/kg per ‰ chlorinity. Sea water.
pub fn total_boron(salinity: f64) -> f64 {
    0.000232 / 10.811 * (salinity / 1.80655)
}

/// Ionic strength of sea water from its salinity, I = 19.924 S / (1000 − 1.005 S) (DOE 1994, chapter 5).
/// Valid for sea water; it gives 0 in fresh water (I2).
pub fn ionic_strength(salinity: f64) -> R {
    div(19.924 * salinity, 1000.0 - 1.005 * salinity)
}

/// Bisulfate dissociation constant, free scale: Dickson (1990), J. Chem. Thermodyn. 22: 113. S 5–45, t 0–45 °C.
pub fn ks(temp_c: f64, salinity: f64) -> R {
    let t = temp_c + KELVIN;
    let i = ionic_strength(salinity)?;
    let root = sqrt(i)?;
    exp(div(-4276.1, t)? + 141.328 - 23.093 * ln(t)?
        + (div(-13856.0, t)? + 324.57 - 47.986 * ln(t)?) * root
        + (div(35474.0, t)? - 771.54 + 114.723 * ln(t)?) * i
        + div(-2698.0, t)? * i * root
        + div(1776.0, t)? * i * i
        + ln(1.0 - 0.001005 * salinity)?)
}

/// Hydrogen fluoride dissociation constant: Dickson & Riley (1979), Mar. Chem. 7: 89. Sea water.
pub fn kf(temp_c: f64, salinity: f64) -> R {
    let t = temp_c + KELVIN;
    let i = ionic_strength(salinity)?;
    exp(div(1590.2, t)? - 12.641 + 1.525 * sqrt(i)? + ln(1.0 - 0.001005 * salinity)?)
}

/// [H⁺]SWS / [H⁺]free = 1 + ST/KS + FT/KF; 1 in fresh water.
pub fn free_to_sws(temp_c: f64, salinity: f64) -> R {
    if salinity <= 0.0 {
        return Ok(1.0);
    }
    Ok(1.0
        + div(total_sulfate(salinity), ks(temp_c, salinity)?)?
        + div(total_fluoride(salinity), kf(temp_c, salinity)?)?)
}

/// [H⁺]total / [H⁺]free = 1 + ST/KS; 1 in fresh water.
pub fn free_to_total(temp_c: f64, salinity: f64) -> R {
    if salinity <= 0.0 {
        return Ok(1.0);
    }
    Ok(1.0 + div(total_sulfate(salinity), ks(temp_c, salinity)?)?)
}

/// The Debye–Hückel A of formula 1 (golden v1): 1.82e6 (ε T)^−1.5 with a fixed dielectric constant ε = 79, right only
/// near 25 °C (I1, chemcore/findings/B1.md). Kept so that formula 1 is reproduced bit for bit; formula 3 takes A from
/// the dielectric constant of its temperature (`fresh::debye_huckel_a`).
pub fn debye_huckel_a_v1(temp_c: f64) -> R {
    let t = temp_c + KELVIN;
    Ok(1820000.0 * pow(79.0 * t, -1.5)?)
}

/// The H⁺ activity coefficient for the NBS scale (Zeebe & Wolf-Gladrow 2001, a Davies-type equation with the
/// Debye–Hückel A of a fixed dielectric constant 79); 1 in fresh water. Valid to I ≈ 0.7 (sea water).
pub fn activity_coefficient_h(temp_c: f64, salinity: f64) -> R {
    activity_coefficient_h_with(temp_c, salinity, &debye_huckel_a_v1)
}

/// The H⁺ activity coefficient of `activity_coefficient_h` with the Debye–Hückel A of `a_of` (of the temperature, °C).
pub fn activity_coefficient_h_with(temp_c: f64, salinity: f64, a_of: &dyn Fn(f64) -> R) -> R {
    if salinity <= 0.0 {
        return Ok(1.0);
    }
    let i = ionic_strength(salinity)?;
    let root = sqrt(i)?;
    let a = a_of(temp_c)?;
    pow(10.0, -(a * (div(root, 1.0 + root)? - 0.2 * i)))
}

/// The SWS-to-NBS factor: the activity coefficient over the molal-to-per-kg factor 1 − 0.001005 S.
pub fn sws_to_nbs(temp_c: f64, salinity: f64) -> R {
    sws_to_nbs_with(temp_c, salinity, &debye_huckel_a_v1)
}

fn sws_to_nbs_with(temp_c: f64, salinity: f64, a_of: &dyn Fn(f64) -> R) -> R {
    div(
        activity_coefficient_h_with(temp_c, salinity, a_of)?,
        1.0 - 0.001005 * salinity,
    )
}

/// A pH read on the NBS scale (a meter or a kit), on the free scale.
pub fn ph_free(ph_nbs: f64, temp_c: f64, salinity: f64) -> R {
    Ok(ph_nbs + log10(sws_to_nbs(temp_c, salinity)?)? + log10(free_to_sws(temp_c, salinity)?)?)
}

// ---- the constants, each on the scale of its source -------------------------------------------------------------

/// First dissociation constant of carbonic acid, seawater scale, mol/kg: Millero, Graham, Huang, Bustos-Serrano &
/// Pierrot (2006), Mar. Chem. 100: 80. S 1–50, t 0–50 °C; the pure-water terms reproduce Harned's fresh-water K1.
pub fn k1_sws(temp_c: f64, salinity: f64) -> R {
    let t = temp_c + KELVIN;
    let root = sqrt(salinity)?;
    let pk = -126.34048 + div(6320.813, t)? + 19.568224 * ln(t)? + 13.4191 * root + 0.0331 * salinity
        - 5.33e-5 * pow(salinity, 2.0)?
        + div(-530.123 * root - 6.103 * salinity, t)?
        - 2.06950 * root * ln(t)?;
    pow(10.0, -pk)
}

/// Second dissociation constant of carbonic acid, seawater scale, mol/kg: Millero et al. (2006). S 1–50, t 0–50 °C.
pub fn k2_sws(temp_c: f64, salinity: f64) -> R {
    let t = temp_c + KELVIN;
    let root = sqrt(salinity)?;
    let pk = -90.18333 + div(5143.692, t)? + 14.613358 * ln(t)? + 21.0894 * root + 0.1248 * salinity
        - 3.687e-4 * pow(salinity, 2.0)?
        + div(-772.483 * root - 20.051 * salinity, t)?
        - 3.3336 * root * ln(t)?;
    pow(10.0, -pk)
}

/// Ion product of water, total scale, (mol/kg)²: Millero (1995), Geochim. Cosmochim. Acta 59: 661. S 0–45, t 0–45 °C.
pub fn kw_total(temp_c: f64, salinity: f64) -> R {
    let t = temp_c + KELVIN;
    let root = sqrt(salinity)?;
    exp(
        148.9652 - div(13847.26, t)? - 23.6521 * ln(t)? + (-5.977 + div(118.67, t)? + 1.0495 * ln(t)?) * root
            - 0.01615 * salinity,
    )
}

/// Boric acid dissociation constant, total scale, mol/kg: Dickson (1990), Deep-Sea Res. 37: 755. S 5–45, t 0–45 °C.
pub fn kb_total(temp_c: f64, salinity: f64) -> R {
    let t = temp_c + KELVIN;
    let root = sqrt(salinity)?;
    exp(div(
        -8966.90 - 2890.53 * root - 77.942 * salinity + 1.728 * salinity * root - 0.0996 * pow(salinity, 2.0)?,
        t,
    )? + 148.0248
        + 137.1942 * root
        + 1.62142 * salinity
        + (-24.4344 - 25.085 * root - 0.2474 * salinity) * ln(t)?
        + 0.053105 * root * t)
}

/// Ammonium dissociation constant, seawater scale: Millero (1995). S 0–40, t 0–40 °C; in fresh water within 0.002 pK
/// of Emerson et al. (1975) up to 30 °C.
pub fn k_nh4_sws(temp_c: f64, salinity: f64) -> R {
    let t = temp_c + KELVIN;
    let root = sqrt(salinity)?;
    exp(div(-6285.33, t)? + 0.0001635 * t - 0.25444
        + (0.46532 - div(123.7184, t)?) * root
        + (-0.01992 + div(3.17556, t)?) * salinity)
}

/// pK of NH₄⁺ on the seawater scale (the free scale in fresh water).
pub fn pk_nh4(temp_c: f64, salinity: f64) -> R {
    Ok(-log10(k_nh4_sws(temp_c, salinity)?)?)
}

/// First dissociation constant of hydrogen sulfide, total scale: Millero, Plese & Fernandez (1988), Limnol. Oceanogr.
/// 33: 269 (as in Millero 1995): pK 6.98 in fresh water and 6.51 in sea water at 25 °C. Fresh to sea water.
pub fn k_h2s_total(temp_c: f64, salinity: f64) -> R {
    let t = temp_c + KELVIN;
    let root = sqrt(salinity)?;
    exp(225.838 - div(13275.3, t)? - 34.6435 * ln(t)? + 0.3449 * root - 0.0274 * salinity)
}

/// Stoichiometric solubility product of calcite, (mol/kg)²: Mucci (1983), Am. J. Sci. 283: 780. S 5–44, t 5–40 °C
/// (the chart draws Ω only there).
pub fn ksp_calcite(temp_c: f64, salinity: f64) -> R {
    let t = temp_c + KELVIN;
    let root = sqrt(salinity)?;
    pow(
        10.0,
        -171.9065 - 0.077993 * t
            + div(2839.319, t)?
            + 71.595 * log10(t)?
            + (-0.77712 + 0.0028426 * t + div(178.34, t)?) * root
            - 0.07711 * salinity
            + 0.0041249 * salinity * root,
    )
}

/// Stoichiometric solubility product of aragonite, (mol/kg)²: Mucci (1983). S 5–44, t 5–40 °C.
pub fn ksp_aragonite(temp_c: f64, salinity: f64) -> R {
    let t = temp_c + KELVIN;
    let root = sqrt(salinity)?;
    pow(
        10.0,
        -171.945 - 0.077993 * t
            + div(2903.293, t)?
            + 71.595 * log10(t)?
            + (-0.068393 + 0.0017276 * t + div(88.135, t)?) * root
            - 0.10018 * salinity
            + 0.0059415 * salinity * root,
    )
}

// ---- the solver -------------------------------------------------------------------------------------------------

/// Where a monotone function crosses zero between `low` and `high`: bisection to a bracket under 1e-10, at most 200
/// halvings, the midpoint returned; an end where the function is exactly 0 there; None when it does not change sign
/// (NaN compares as Python's: never above 0). The function's own error stops the search.
pub fn solve<E>(function: &mut dyn FnMut(f64) -> Result<f64, E>, low: f64, high: f64) -> Result<Option<f64>, E> {
    let (mut low, mut high) = (low, high);
    let mut at_low = function(low)?;
    let at_high = function(high)?;
    if at_low == 0.0 {
        return Ok(Some(low));
    }
    if at_high == 0.0 {
        return Ok(Some(high));
    }
    if (at_low > 0.0) == (at_high > 0.0) {
        return Ok(None);
    }
    for _step in 0..200 {
        let middle = (low + high) / 2.0;
        let at_middle = function(middle)?;
        if (at_middle > 0.0) == (at_low > 0.0) {
            low = middle;
            at_low = at_middle;
        } else {
            high = middle;
        }
        if high - low < 1e-10 {
            break;
        }
    }
    Ok(Some((low + high) / 2.0))
}

// ---- one water --------------------------------------------------------------------------------------------------

/// Where a water's ionic strength came from (formula 3, crate::fresh; formula 1 takes the salinity's, `Seawater`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Source {
    Conductivity,
    Hardness,
    Salinity,
    Alkalinity,
    Seawater,
    /// Nothing measured: an ionic strength of 0 (formula 1's ideal fresh water).
    Nothing,
}

impl Source {
    /// A stable code.
    pub fn code(self) -> &'static str {
        match self {
            Source::Conductivity => "conductivity",
            Source::Hardness => "hardness",
            Source::Salinity => "salinity",
            Source::Alkalinity => "alkalinity",
            Source::Seawater => "seawater",
            Source::Nothing => "none",
        }
    }
}

/// The equilibria of a water at one temperature (°C) and salinity (‰), constants on the free scale, mol/kg.
/// Concentrations: alkalinity in meq/L, DIC and CO₂ in mmol/L; a pH is NBS. It says what it was worked out by (its
/// provenance): the formula version, the ionic strength and its source, and the seawater path's share of its constants.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Equilibria {
    pub temp_c: f64,
    pub salinity: f64,
    /// pH free − pH NBS.
    pub ph_offset: f64,
    pub k1: f64,
    pub k2: f64,
    pub kw: f64,
    pub kb: f64,
    /// Total boron, mol/kg.
    pub boron: f64,
    pub k_nh4: f64,
    pub k_h2s: f64,
    /// (mol/kg)².
    pub ksp_calcite: f64,
    pub ksp_aragonite: f64,
    /// The formula version (crate::FORMULA_VERSION; 1 or 3).
    pub formula: u32,
    /// mol/L; formula 1: the salinity's (DOE 1994), 0 at S ≤ 0.
    pub ionic_strength: f64,
    pub source: Source,
    /// The seawater path's share of the constants, 0 to 1 (formula 1: always 1).
    pub sea_weight: f64,
    /// The constants of the basis the NH₃ and CO₂ limits were set on (formula 3; `crate::fresh::limits_basis`), against
    /// which a judgement takes the larger value (`nh3_share`, `ph_where_nh3`, `co2_judged`, `ph_where_co2`); None for
    /// formula 1, which is that basis itself.
    pub limits_basis: Option<LimitsBasis>,
    /// Where its salt came from, as said (formula 1: `Origin::Unknown`).
    pub origin: Origin,
}

/// Where a water's salt came from (cross review F3, F4), as a unit says it: the band from 1 to 5 ‰ blends in the seawater
/// constants, which carry sea water's ions (sulfate and fluoride on the pH scales, Mg²⁺ and Ca²⁺ ion pairs in Millero's
/// K1 and K2, borate); fresh water salted with NaCl has none of them (`crate::fresh`).
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Origin {
    /// Not said: the band, its provenance saying it assumes sea water's ion composition.
    #[default]
    Unknown,
    /// Sea water or sea water diluted: the band.
    Seawater,
    /// Fresh water with salt (NaCl) added: the fresh path up to the Davies limit.
    SaltAdded,
}

impl Origin {
    /// A stable code (the unit's `water_origin`; '' not said).
    pub fn code(self) -> &'static str {
        match self {
            Origin::Unknown => "",
            Origin::Seawater => "seawater",
            Origin::SaltAdded => "salt_added",
        }
    }

    pub fn from_code(code: &str) -> Option<Origin> {
        [Origin::Unknown, Origin::Seawater, Origin::SaltAdded]
            .into_iter()
            .find(|origin| origin.code() == code)
    }
}

/// Which value judged a water's NH₃ or CO₂ against its limits: the larger of the limits' basis and the
/// activity-corrected value (cross review F1; owner decision 2026-11-09, safety with live fish).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Basis {
    /// The basis the limits were set on (`crate::fresh::limits_basis`: up to 1 ‰ the ideal water, every activity 1, as
    /// Emerson et al. 1975 and Standard Methods 4500-CO₂ D; from 5 ‰ formula 1's seawater constants; blended between).
    Limits,
    /// The activity-corrected value of formula 3, the larger here.
    Corrected,
}

impl Basis {
    /// A stable code.
    pub fn code(self) -> &'static str {
        match self {
            Basis::Limits => "limits",
            Basis::Corrected => "corrected",
        }
    }
}

/// The constants of a water's limits basis that its NH₃ and CO₂ judgements need (`Equilibria::limits_basis`).
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct LimitsBasis {
    pub ph_offset: f64,
    pub k1: f64,
    pub k2: f64,
    pub kw: f64,
    pub kb: f64,
    pub boron: f64,
    pub k_nh4: f64,
}

impl LimitsBasis {
    /// The basis constants of equilibria worked out on it.
    pub fn of(eq: &Equilibria) -> LimitsBasis {
        LimitsBasis {
            ph_offset: eq.ph_offset,
            k1: eq.k1,
            k2: eq.k2,
            kw: eq.kw,
            kb: eq.kb,
            boron: eq.boron,
            k_nh4: eq.k_nh4,
        }
    }
}

/// The larger of two numbers, the first on a tie.
fn larger(one: f64, two: f64) -> f64 {
    if two > one { two } else { one }
}

/// The higher of two optional pHs (None when both are).
fn higher(one: Option<f64>, two: Option<f64>) -> Option<f64> {
    match (one, two) {
        (Some(one), Some(two)) => Some(larger(one, two)),
        (one, None) => one,
        (None, two) => two,
    }
}

/// The lower of two optional pHs (None when both are).
fn lower(one: Option<f64>, two: Option<f64>) -> Option<f64> {
    match (one, two) {
        (Some(one), Some(two)) => Some(if two < one { two } else { one }),
        (one, None) => one,
        (None, two) => two,
    }
}

/// The equilibria of a water by formula 1 (golden v1). Non-finite inputs are refused.
pub fn equilibria(temp_c: f64, salinity: f64) -> Result<Equilibria, ChemError> {
    equilibria_with(temp_c, salinity, &debye_huckel_a_v1)
}

/// The seawater equilibria of `equilibria` with the NBS pH converted by the Debye–Hückel A of `a_of` (formula 3
/// passes the A of the temperature's dielectric constant, `fresh::debye_huckel_a`). Non-finite inputs are refused.
pub fn equilibria_with(temp_c: f64, salinity: f64, a_of: &dyn Fn(f64) -> R) -> Result<Equilibria, ChemError> {
    let temp_c = finite(temp_c)?;
    let salinity = finite(salinity)?;
    let to_sws = free_to_sws(temp_c, salinity)?;
    let to_total = free_to_total(temp_c, salinity)?;
    let eq = Equilibria {
        temp_c,
        salinity,
        ph_offset: log10(sws_to_nbs_with(temp_c, salinity, a_of)?)? + log10(to_sws)?,
        k1: div(k1_sws(temp_c, salinity)?, to_sws)?,
        k2: div(k2_sws(temp_c, salinity)?, to_sws)?,
        kw: div(kw_total(temp_c, salinity)?, to_total)?,
        kb: div(kb_total(temp_c, salinity)?, to_total)?,
        boron: total_boron(salinity),
        k_nh4: div(k_nh4_sws(temp_c, salinity)?, to_sws)?,
        k_h2s: div(k_h2s_total(temp_c, salinity)?, to_total)?,
        ksp_calcite: ksp_calcite(temp_c, salinity)?,
        ksp_aragonite: ksp_aragonite(temp_c, salinity)?,
        formula: 1,
        ionic_strength: if salinity > 0.0 { ionic_strength(salinity)? } else { 0.0 },
        source: Source::Seawater,
        sea_weight: 1.0,
        limits_basis: None,
        origin: Origin::Unknown,
    };
    for value in [
        eq.ph_offset,
        eq.k1,
        eq.k2,
        eq.kw,
        eq.kb,
        eq.k_nh4,
        eq.k_h2s,
        eq.ksp_calcite,
        eq.ksp_aragonite,
    ] {
        finite(value)?;
    }
    Ok(eq)
}

impl Equilibria {
    /// [H⁺] on the free scale, mol/kg.
    pub fn hydrogen(&self, ph: f64) -> R {
        pow(10.0, -(ph + self.ph_offset))
    }

    /// The NBS pH of a free [H⁺].
    pub fn ph_of(&self, hydrogen: f64) -> R {
        Ok(-log10(hydrogen)? - self.ph_offset)
    }

    /// α0, α1, α2: the shares of DIC as CO₂, HCO₃⁻ and CO₃²⁻ (Deffeyes 1965).
    pub fn fractions(&self, ph: f64) -> Result<(f64, f64, f64), ChemError> {
        let h = self.hydrogen(ph)?;
        let whole = h * h + h * self.k1 + self.k1 * self.k2;
        Ok((
            div(h * h, whole)?,
            div(h * self.k1, whole)?,
            div(self.k1 * self.k2, whole)?,
        ))
    }

    /// The pH's line on the Deffeyes chart, alkalinity = slope × DIC + intercept: slope α1 + 2 α2, intercept
    /// [OH⁻] − [H⁺] + [B(OH)₄⁻] in meq/L.
    pub fn isoline(&self, ph: f64) -> Result<(f64, f64), ChemError> {
        let (_co2, bicarbonate, carbonate) = self.fractions(ph)?;
        let h = self.hydrogen(ph)?;
        let borate = div(self.boron * self.kb, self.kb + h)?;
        Ok((bicarbonate + 2.0 * carbonate, (div(self.kw, h)? - h + borate) * 1000.0))
    }

    pub fn dic(&self, alkalinity: f64, ph: f64) -> R {
        let (slope, intercept) = self.isoline(ph)?;
        div(alkalinity - intercept, slope)
    }

    pub fn alkalinity(&self, dic: f64, ph: f64) -> R {
        let (slope, intercept) = self.isoline(ph)?;
        Ok(dic * slope + intercept)
    }

    /// The pH of a water with this DIC and alkalinity; None when no pH of the solver's range gives it.
    pub fn ph_at(&self, dic: f64, alkalinity: f64) -> Result<Option<f64>, ChemError> {
        if dic <= 0.0 {
            return Ok(None);
        }
        solve(
            &mut |ph| Ok(self.alkalinity(dic, ph)? - alkalinity),
            SOLVER_PH.0,
            SOLVER_PH.1,
        )
    }

    pub fn co2(&self, dic: f64, ph: f64) -> R {
        Ok(dic * self.fractions(ph)?.0)
    }

    pub fn carbonate(&self, dic: f64, ph: f64) -> R {
        Ok(dic * self.fractions(ph)?.2)
    }

    /// The equilibria of the basis the limits were set on (`limits_basis`), the same water otherwise; None for formula 1.
    pub fn limits_equilibria(&self) -> Option<Equilibria> {
        self.limits_basis.map(|basis| Equilibria {
            ph_offset: basis.ph_offset,
            k1: basis.k1,
            k2: basis.k2,
            kw: basis.kw,
            kb: basis.kb,
            boron: basis.boron,
            k_nh4: basis.k_nh4,
            limits_basis: None,
            ..*self
        })
    }

    /// The share of TAN that is un-ionised NH₃ as these constants give it, 0 to 1: K / (K + [H⁺]). Formula 3: the
    /// activity-corrected share, information beside the judged one (`nh3_share`).
    pub fn nh3_share_corrected(&self, ph: f64) -> R {
        div(self.k_nh4, self.k_nh4 + self.hydrogen(ph)?)
    }

    /// The share of TAN that is un-ionised NH₃ that every judgement, alarm, status, border and safe TAN takes, 0 to 1:
    /// the larger of the limits' basis and the activity-corrected share (cross review F1), so formula 3 never
    /// understates NH₃ against how its limits were set (Emerson et al. 1975's ideal fraction; Piper et al. 1982; US
    /// EPA 1985). Formula 1: its own share.
    pub fn nh3_share(&self, ph: f64) -> R {
        let corrected = self.nh3_share_corrected(ph)?;
        match self.limits_equilibria() {
            Some(basis) => Ok(larger(basis.nh3_share_corrected(ph)?, corrected)),
            None => Ok(corrected),
        }
    }

    /// Which share `nh3_share` takes: [NH₃]/[NH₄⁺] = K 10^(pH + offset), so the larger share is the larger K 10^offset
    /// at every pH; the limits' basis on a tie (and always for formula 1).
    pub fn nh3_basis(&self) -> Result<Basis, ChemError> {
        match self.limits_basis {
            Some(basis) if self.k_nh4 * pow(10.0, self.ph_offset)? > basis.k_nh4 * pow(10.0, basis.ph_offset)? => {
                Ok(Basis::Corrected)
            }
            _ => Ok(Basis::Limits),
        }
    }

    /// The share of the total sulfide that is H₂S, 0 to 1: [H⁺] / (K + [H⁺]).
    pub fn h2s_share(&self, ph: f64) -> R {
        let h = self.hydrogen(ph)?;
        div(h, self.k_h2s + h)
    }

    /// The pH above which NH₃-N as these constants give it exceeds `limit` (mg/L as TAN): [H⁺] = K (1 − f) / f,
    /// f = limit / TAN; None when the TAN cannot give that much.
    pub fn ph_where_nh3_corrected(&self, tan: f64, limit: f64) -> Result<Option<f64>, ChemError> {
        if tan <= 0.0 || limit <= 0.0 || limit >= tan {
            return Ok(None);
        }
        let share = div(limit, tan)?;
        Ok(Some(self.ph_of(div(self.k_nh4 * (1.0 - share), share)?)?))
    }

    /// The pH above which the judged NH₃-N (`nh3_share`) exceeds `limit`: the lower of the two borders.
    pub fn ph_where_nh3(&self, tan: f64, limit: f64) -> Result<Option<f64>, ChemError> {
        let corrected = self.ph_where_nh3_corrected(tan, limit)?;
        match self.limits_equilibria() {
            Some(basis) => Ok(lower(basis.ph_where_nh3_corrected(tan, limit)?, corrected)),
            None => Ok(corrected),
        }
    }

    /// The pH below which H₂S exceeds `limit`: [H⁺] = K f / (1 − f), f = limit / total; None when the total cannot.
    pub fn ph_where_h2s(&self, total: f64, limit: f64) -> Result<Option<f64>, ChemError> {
        if total <= 0.0 || limit <= 0.0 || limit >= total {
            return Ok(None);
        }
        let share = div(limit, total)?;
        Ok(Some(self.ph_of(div(self.k_h2s * share, 1.0 - share)?)?))
    }

    /// The pH below which CO₂ (mmol/L) as these constants give it exceeds `co2` at a fixed alkalinity (meq/L); None
    /// when not in range.
    pub fn ph_where_co2_corrected(&self, alkalinity: f64, co2: f64) -> Result<Option<f64>, ChemError> {
        solve(
            &mut |ph| Ok(self.co2(self.dic(alkalinity, ph)?, ph)? - co2),
            SOLVER_PH.0,
            SOLVER_PH.1,
        )
    }

    /// The pH below which the judged CO₂ (`co2_judged`) exceeds `co2` at a fixed alkalinity: the higher of the two
    /// borders (CO₂ falls as the pH rises at a fixed alkalinity).
    pub fn ph_where_co2(&self, alkalinity: f64, co2: f64) -> Result<Option<f64>, ChemError> {
        let corrected = self.ph_where_co2_corrected(alkalinity, co2)?;
        match self.limits_equilibria() {
            Some(basis) => Ok(higher(basis.ph_where_co2_corrected(alkalinity, co2)?, corrected)),
            None => Ok(corrected),
        }
    }

    /// The CO₂ (mmol/L) of a water of this alkalinity (meq/L) and pH (NBS) as these constants give it.
    pub fn co2_corrected(&self, alkalinity: f64, ph: f64) -> R {
        self.co2(self.dic(alkalinity, ph)?, ph)
    }

    /// The CO₂ (mmol/L) every CO₂ judgement takes, of a water of this alkalinity (meq/L) and pH, and its basis: the
    /// larger of the limits' basis and the activity-corrected CO₂ (cross review F1, as `nh3_share`); `own` is this
    /// water's own CO₂ as these constants give it (a state's `co2(dic, ph)`, passed so a simulator step keeps its own).
    pub fn co2_judged(&self, alkalinity: f64, ph: f64, own: f64) -> Result<(f64, Basis), ChemError> {
        match self.limits_equilibria() {
            Some(basis) => {
                let limits = basis.co2_corrected(alkalinity, ph)?;
                Ok(if own > limits {
                    (own, Basis::Corrected)
                } else {
                    (limits, Basis::Limits)
                })
            }
            None => Ok((own, Basis::Limits)),
        }
    }

    /// The alkalinity (meq/L) at which the judged CO₂ is `co2` (mmol/L) at a pH: the lower of the two (CO₂ rises with
    /// the alkalinity at a fixed pH).
    pub fn alkalinity_where_co2(&self, co2: f64, ph: f64) -> R {
        let corrected = self.alkalinity(div(co2, self.fractions(ph)?.0)?, ph)?;
        match self.limits_equilibria() {
            Some(basis) => {
                let limits = basis.alkalinity(div(co2, basis.fractions(ph)?.0)?, ph)?;
                Ok(if limits < corrected { limits } else { corrected })
            }
            None => Ok(corrected),
        }
    }

    /// The pH at which a DIC holds `co2` as CO₂: α0 = c / DIC solved for [H⁺]; None when c ≥ DIC (B1-02).
    pub fn ph_where_co2_at_dic(&self, dic: f64, co2: f64) -> Result<Option<f64>, ChemError> {
        if dic <= 0.0 || co2 <= 0.0 || co2 >= dic {
            return Ok(None);
        }
        let share = div(co2, dic)?;
        let (k1, k2) = (self.k1, self.k2);
        let h = div(
            share * k1 + sqrt(pow(share * k1, 2.0)? + 4.0 * (1.0 - share) * share * k1 * k2)?,
            2.0 * (1.0 - share),
        )?;
        Ok(Some(self.ph_of(h)?))
    }

    /// The pH at which a DIC holds `carbonate` as CO₃²⁻: α2 = c / DIC solved for [H⁺]; None when c ≥ DIC.
    pub fn ph_where_carbonate(&self, dic: f64, carbonate: f64) -> Result<Option<f64>, ChemError> {
        if dic <= 0.0 || carbonate <= 0.0 || carbonate >= dic {
            return Ok(None);
        }
        let share = div(carbonate, dic)?;
        let (k1, k2) = (self.k1, self.k2);
        let h = div(
            -share * k1 + sqrt(pow(share * k1, 2.0)? + 4.0 * share * (1.0 - share) * k1 * k2)?,
            2.0 * share,
        )?;
        Ok(Some(self.ph_of(h)?))
    }
}

/// The share of TAN that is un-ionised NH₃ at a pH (NBS), 0 to 1.
pub fn nh3_fraction(ph_nbs: f64, temp_c: f64, salinity: f64) -> R {
    equilibria(temp_c, salinity)?.nh3_share(ph_nbs)
}

// ---- oxygen (Benson & Krause 1984; APHA 4500-O) ---------------------------------------------------------------

/// The standard atmosphere's pressure at an altitude (m), atm: (1 − 2.25577e-5 h)^5.25588. 0 to 11 km.
pub fn pressure_atm(altitude_m: f64) -> R {
    pow(1.0 - 2.25577e-5 * altitude_m, 5.25588)
}

/// The vapour pressure of water, atm: Benson & Krause (1984) as APHA 4500-O gives it. t 0–40 °C.
pub fn vapour_pressure_atm(temp_c: f64) -> R {
    let t = temp_c + KELVIN;
    exp(11.8571 - div(3840.70, t)? - div(216961.0, pow(t, 2.0)?)?)
}

/// The oxygen water holds in equilibrium with moist air, mg/L, at a pressure in atm: Benson & Krause (1984),
/// Limnol. Oceanogr. 29: 620, the equation of APHA 4500-O and the USGS tables. t 0–40 °C, S 0–40.
pub fn oxygen_solubility(temp_c: f64, salinity: f64, pressure: f64) -> R {
    let t = temp_c + KELVIN;
    let ln_c = -139.34411 + div(1.575701e5, t)? - div(6.642308e7, pow(t, 2.0)?)? + div(1.243800e10, pow(t, 3.0)?)?
        - div(8.621949e11, pow(t, 4.0)?)?
        - salinity * (1.7674e-2 - div(10.754, t)? + div(2140.7, pow(t, 2.0)?)?);
    let c = exp(ln_c)?;
    if pressure == 1.0 {
        return Ok(c);
    }
    let vapour = vapour_pressure_atm(temp_c)?;
    let theta = 0.000975 - 1.426e-5 * temp_c + 6.436e-8 * pow(temp_c, 2.0)?;
    div(
        c * pressure * (1.0 - div(vapour, pressure)?) * (1.0 - theta * pressure),
        (1.0 - vapour) * (1.0 - theta),
    )
}

// ---- carbon dioxide from the air (Weiss 1974) --------------------------------------------------------------------

/// The solubility of CO₂ per litre, mol/(L atm): Weiss (1974), Mar. Chem. 2: 203. t −1–40 °C, S 0–40.
pub fn k0_co2(temp_c: f64, salinity: f64) -> R {
    let t = (temp_c + KELVIN) / 100.0;
    exp(-58.0931 + div(90.5069, t)? + 22.2940 * ln(t)? + salinity * (0.027766 - 0.025888 * t + 0.0050578 * t * t))
}

/// The CO₂ (mg/L) of a water in equilibrium with the air at a pressure (atm): the least stripping can leave.
pub fn co2_from_air(temp_c: f64, salinity: f64, pressure: f64) -> R {
    let partial = AIR_CO2 * (pressure - vapour_pressure_atm(temp_c)?);
    Ok(k0_co2(temp_c, salinity)? * partial * MG_CO2_PER_MMOL * 1000.0)
}
