//! I2, fresh water's ionic strength (chemcore/findings/B1.md, I2; owner amendment B5): golden v3, beside v1 and not
//! used by the application until the owner decides (chemcore/findings/I2-comparison.md).
//!
//! v1 (crate::chemistry) takes the ionic strength from the salinity alone, so a fresh water (S 0) is ideal: every
//! activity coefficient 1, the NBS pH taken as the free pH. A fresh water is not ideal: a hard one has an ionic
//! strength near 0.01, where a monovalent ion's activity coefficient is about 0.9. Below a salinity of `FRESH_BELOW`
//! the v3 water takes its ionic strength from what is measured, and its constants are the fresh-water (thermodynamic,
//! infinite dilution) ones made concentration constants with Davies activity coefficients; from `FRESH_BELOW` on it is
//! v1's seawater path but for the NBS pH's conversion, whose Debye–Hückel A is the temperature's (I1, below).
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
//! Davies (1962), Ion Association, p. 41: log γ = −A z² (√I / (1 + √I) − 0.3 I), valid to I ≈ 0.5. A is the
//! Debye–Hückel constant of the water's temperature (`debye_huckel_a`: its dielectric constant by Malmberg & Maryott
//! 1956 and its density by Kell 1975), I1 closed: formula 1's fixed ε = 79 made A 7.5 % too large at 12 °C and 15 % at
//! 2 °C. The seawater path's NBS conversion (Zeebe & Wolf-Gladrow 2001) takes the same A from formula 3 on, which moves
//! it towards CO2SYS's Takahashi et al. (1982) at every temperature from 10 ‰ up (chemcore/findings/I2-comparison.md).
//! The concentration constants (Stumm & Morgan 1996,
//! Aquatic Chemistry, 3rd ed., section 3.4; Plummer & Busenberg 1982), with γ₀ = 1 for CO₂, NH₃, H₂S, B(OH)₃:
//! pH free = pH NBS + log γ₁ (a meter reads the activity of H⁺); K1 = K1° / γ₁²; K2 = K2° / γ₂; Kw = Kw° / γ₁²;
//! KB = KB° / γ₁²; KH2S = KH2S° / γ₁²; KNH4 = KNH4° (H⁺ and NH₄⁺ both monovalent); Ksp as v1 (Ω is drawn only from 5 ‰).
use crate::chemistry::{
    self as c, Equilibria, KELVIN, MG_CACO3_PER_MEQ, k_h2s_total, k_nh4_sws, k1_sws, k2_sws, kb_total, kw_total,
    total_boron,
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
/// The largest ionic strength the Davies equation is taken to (Stumm & Morgan 1996, table 3.3: "I < 0.5"); above it
/// the fresh-water path refuses (`ChemError::OutOfRange`), as when a sea water's conductivity comes without its salinity
/// or a conductivity in mS/cm is read as µS/cm.
pub const DAVIES_MAX: f64 = 0.5;

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

/// The ionic strength (mol/L) of a water and where it came from (the module's list). Refuses a non-finite input, a
/// negative conductivity, hardness or alkalinity, and on the fresh-water path an ionic strength above `DAVIES_MAX`.
pub fn ionic_strength(salinity: f64, alkalinity_mg_l: f64, ions: Ions) -> Result<(f64, Source), ChemError> {
    let (strength, source) = any_ionic_strength(salinity, alkalinity_mg_l, ions)?;
    if source != Source::Seawater && strength > DAVIES_MAX {
        return Err(ChemError::OutOfRange);
    }
    Ok((strength, source))
}

fn any_ionic_strength(salinity: f64, alkalinity_mg_l: f64, ions: Ions) -> Result<(f64, Source), ChemError> {
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

/// The dielectric constant (relative permittivity) of water at a temperature (°C): Malmberg & Maryott (1956), J. Res.
/// Natl. Bur. Stand. 56: 1, eq. (5) as their abstract prints it, ε = 87.740 − 0.40008 t + 9.398e-4 t² − 1.410e-6 t³,
/// fitted to their measurements from 0.1 to 99 °C within 0.01 (table 2: 87.740 at 0 °C, 83.832 at 10, 78.304 at 25).
pub fn dielectric_constant(temp_c: f64) -> R {
    let t = finite(temp_c)?;
    Ok(87.740 - 0.40008 * t + 9.398e-4 * t * t - 1.410e-6 * t * t * t)
}

/// The density of pure water at 1 atm, g/cm³: Kell (1975), J. Chem. Eng. Data 20: 97, the rational function of the
/// temperature (°C) for 0 to 150 °C, as reproduced in J. Res. NIST 97: 335 (1992) with its denominator's misprint
/// (16.897850e-3) corrected to 16.879850e-3 (0.99984 g/cm³ at 0 °C, the maximum 0.99997 at 3.98 °C, 0.99705 at 25 °C).
pub fn water_density(temp_c: f64) -> R {
    let t = finite(temp_c)?;
    let numerator = 999.83952 + 16.945176 * t - 7.9870401e-3 * t * t - 46.170461e-6 * pow(t, 3.0)?
        + 105.56302e-9 * pow(t, 4.0)?
        - 280.54253e-12 * pow(t, 5.0)?;
    Ok(div(numerator, 1.0 + 16.879850e-3 * t)? / 1000.0)
}

/// The Debye–Hückel constant: A = 1.824812e6 √ρ (ε T)^−3/2 (log₁₀, molal, kg^½ mol^−½, ρ in g/cm³), the limiting
/// law's (1/ln 10) √(2π N_A ρ) (e² / (4π ε₀ ε k T))^3/2 worked out with the CODATA 2018 constants; Hamer (1968),
/// NSRDS-NBS 24, prints 1.824829238e6 (older constants) and Nordstrom et al. (1984), USGS WRI 84-4186, 1.824814e6.
pub const DEBYE_HUCKEL: f64 = 1.824812e6;

/// The Debye–Hückel A of water at a temperature (°C) from its own dielectric constant and density (Malmberg & Maryott
/// 1956; Kell 1975): 0.4918 at 0 °C, 0.4989 at 10 °C, 0.5108 at 25 °C, Hamer's (1968) table 3 within 0.03 %, and
/// the USGS table of another ε (Nordstrom et al. 1984, table 1) within 0.3 % (chemcore/core/tests/fresh.rs). Formula 3; formula 1 kept ε = 79 (`chemistry::debye_huckel_a_v1`, I1).
pub fn debye_huckel_a(temp_c: f64) -> R {
    let t = finite(temp_c)? + KELVIN;
    Ok(DEBYE_HUCKEL * sqrt(water_density(temp_c)?)? * pow(dielectric_constant(temp_c)? * t, -1.5)?)
}

/// log₁₀ of an ion's activity coefficient by Davies (1962) at a temperature (°C), an ionic strength (mol/L) and a
/// charge, with the A of the temperature (`debye_huckel_a`); refused (`ChemError::OutOfRange`) above an ionic strength
/// of `DAVIES_MAX`.
pub fn davies_log_gamma(temp_c: f64, ionic_strength: f64, charge: f64) -> R {
    let a = debye_huckel_a(temp_c)?;
    let i = finite(ionic_strength)?;
    if i > DAVIES_MAX {
        return Err(ChemError::OutOfRange);
    }
    let root = sqrt(i)?;
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
        return Ok((c::equilibria_with(temp_c, salinity, &debye_huckel_a)?, strength, source));
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
