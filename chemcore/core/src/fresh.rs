//! I2, fresh water's ionic strength (chemcore/findings/B1.md, I2; owner amendment B5): golden v3, beside v1 and not
//! used by the application until the owner decides (chemcore/findings/I2-comparison.md).
//!
//! v1 (crate::chemistry) takes the ionic strength from the salinity alone, so a fresh water (S 0) is ideal: every
//! activity coefficient 1, the NBS pH taken as the free pH. A fresh water is not ideal: a hard one has an ionic
//! strength near 0.01, where a monovalent ion's activity coefficient is about 0.9. Below a salinity of `FRESH_BELOW`
//! the v3 water takes its ionic strength from what is measured, and its constants are the fresh-water (thermodynamic,
//! infinite dilution) ones made concentration constants with Davies activity coefficients; from `FRESH_BELOW` on it is
//! v1's seawater path, bit for bit.
//!
//! The ionic strength, the first source there is:
//! 1. the conductivity κ (µS/cm, at 25 °C): I = 1.6e-5 κ (Russell 1976, J. Am. Water Works Assoc. 68: 2; as in
//!    Snoeyink & Jenkins 1980, Water Chemistry, eq. 2-40);
//! 2. the hardness (mg/L as CaCO₃, Ca²⁺ and Mg²⁺) with the alkalinity (meq/L, as HCO₃⁻): their ions and the
//!    monovalent ions their charges need to balance, I = ½ (4 c₂ + A + |2 c₂ − A|), mmol/L to mol/L: the least ionic
//!    strength these measurements allow (an unmeasured ion only adds to it);
//! 3. the salinity, as sea water's (DOE 1994, chemistry::ionic_strength), when one above 0 is given;
//! 4. the alkalinity alone, as sodium bicarbonate, I = A: again the least it can be.
//!
//! Concentrations per litre are taken as per kg (a fresh water's density is 1 within 0.3 %).
//!
//! Davies (1962), Ion Association, p. 41: log γ = −A z² (√I / (1 + √I) − 0.3 I), valid to I ≈ 0.5; A is the
//! Debye–Hückel constant of the seawater path, 1.82e6 (ε T)^−1.5 with the same fixed dielectric constant 79 (I1, a
//! separate debt, kept so that v3 changes only the ionic strength). The concentration constants (Stumm & Morgan 1996,
//! Aquatic Chemistry, 3rd ed., section 3.4; Plummer & Busenberg 1982), with γ₀ = 1 for CO₂, NH₃, H₂S, B(OH)₃:
//! pH free = pH NBS + log γ₁ (a meter reads the activity of H⁺); K1 = K1° / γ₁²; K2 = K2° / γ₂; Kw = Kw° / γ₁²;
//! KB = KB° / γ₁²; KH2S = KH2S° / γ₁²; KNH4 = KNH4° (H⁺ and NH₄⁺ both monovalent); Ksp as v1 (Ω is drawn only from 5 ‰).
use crate::chemistry::{
    self as c, Equilibria, KELVIN, MG_CACO3_PER_MEQ, equilibria, k_h2s_total, k_nh4_sws, k1_sws, k2_sws, kb_total,
    kw_total, total_boron,
};
use crate::num::{ChemError, R, div, finite, pow, sqrt};

/// Below this salinity (‰) v3 takes the fresh-water path; from it on, v1's seawater path.
pub const FRESH_BELOW: f64 = 5.0;
/// Ionic strength per µS/cm of conductivity (Russell 1976).
pub const IONIC_PER_MICROSIEMENS: f64 = 1.6e-5;
/// Hardness: mg/L as CaCO₃ per mmol/L of Ca²⁺ and Mg²⁺ (CaCO₃ 100.0869, IUPAC 2007).
pub const MG_CACO3_PER_MMOL: f64 = 100.0869;
/// The Davies equation's linear term (Davies 1962).
pub const DAVIES: f64 = 0.3;

/// Where a v3 water's ionic strength came from.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Source {
    Conductivity,
    Hardness,
    Salinity,
    Alkalinity,
    Seawater,
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
        }
    }
}

/// What is measured of a fresh water's ions besides its alkalinity (none: None).
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Ions {
    pub conductivity_us_cm: Option<f64>,
    pub hardness_mg_l: Option<f64>,
}

fn present(value: Option<f64>) -> Result<Option<f64>, ChemError> {
    match value {
        Some(number) => finite(number).map(Some),
        None => Ok(None),
    }
}

/// The ionic strength (mol/L) of a water and where it came from (the module's list). Refuses a non-finite input and
/// a negative conductivity, hardness or alkalinity.
pub fn ionic_strength(salinity: f64, alkalinity_mg_l: f64, ions: Ions) -> Result<(f64, Source), ChemError> {
    let salinity = finite(salinity)?;
    let alkalinity_mg_l = finite(alkalinity_mg_l)?;
    let conductivity = present(ions.conductivity_us_cm)?;
    let hardness = present(ions.hardness_mg_l)?;
    if salinity >= FRESH_BELOW {
        return Ok((c::ionic_strength(salinity)?, Source::Seawater));
    }
    if alkalinity_mg_l < 0.0 || conductivity.is_some_and(|k| k < 0.0) || hardness.is_some_and(|h| h < 0.0) {
        return Err(ChemError::Domain);
    }
    let bicarbonate = div(alkalinity_mg_l, MG_CACO3_PER_MEQ)?;
    if let Some(kappa) = conductivity {
        return Ok((IONIC_PER_MICROSIEMENS * kappa, Source::Conductivity));
    }
    if let Some(hardness) = hardness {
        let divalent = div(hardness, MG_CACO3_PER_MMOL)?;
        let balance = libm::fabs(2.0 * divalent - bicarbonate);
        return Ok((0.5e-3 * (4.0 * divalent + bicarbonate + balance), Source::Hardness));
    }
    if salinity > 0.0 {
        return Ok((c::ionic_strength(salinity)?, Source::Salinity));
    }
    Ok((bicarbonate / 1000.0, Source::Alkalinity))
}

/// log₁₀ of an ion's activity coefficient by Davies (1962) at a temperature (°C), an ionic strength (mol/L) and a
/// charge. Valid to I ≈ 0.5.
pub fn davies_log_gamma(temp_c: f64, ionic_strength: f64, charge: f64) -> R {
    let t = finite(temp_c)? + KELVIN;
    let i = finite(ionic_strength)?;
    let root = sqrt(i)?;
    let a = 1820000.0 * pow(79.0 * t, -1.5)?;
    Ok(-a * charge * charge * (div(root, 1.0 + root)? - DAVIES * i))
}

/// The v3 equilibria of a water (the module's rules) with its ionic strength and where it came from; from a salinity of
/// `FRESH_BELOW` on, `chemistry::equilibria` itself.
pub fn equilibria_v3(
    temp_c: f64,
    salinity: f64,
    alkalinity_mg_l: f64,
    ions: Ions,
) -> Result<(Equilibria, f64, Source), ChemError> {
    let (strength, source) = ionic_strength(salinity, alkalinity_mg_l, ions)?;
    if source == Source::Seawater {
        return Ok((equilibria(temp_c, salinity)?, strength, source));
    }
    let temp_c = finite(temp_c)?;
    let one = davies_log_gamma(temp_c, strength, 1.0)?;
    let gamma_one_squared = pow(10.0, 2.0 * one)?;
    let gamma_two = pow(10.0, davies_log_gamma(temp_c, strength, 2.0)?)?;
    let eq = Equilibria {
        temp_c,
        salinity,
        ph_offset: one,
        k1: div(k1_sws(temp_c, 0.0)?, gamma_one_squared)?,
        k2: div(k2_sws(temp_c, 0.0)?, gamma_two)?,
        kw: div(kw_total(temp_c, 0.0)?, gamma_one_squared)?,
        kb: div(kb_total(temp_c, 0.0)?, gamma_one_squared)?,
        boron: total_boron(salinity),
        k_nh4: k_nh4_sws(temp_c, 0.0)?,
        k_h2s: div(k_h2s_total(temp_c, 0.0)?, gamma_one_squared)?,
        ksp_calcite: c::ksp_calcite(temp_c, salinity)?,
        ksp_aragonite: c::ksp_aragonite(temp_c, salinity)?,
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
    Ok((eq, strength, source))
}
