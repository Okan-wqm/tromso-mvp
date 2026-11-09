//! I2, fresh water's ionic strength (chemcore/findings/B1.md, I2; owner amendment B5), and I1, the Debye–Hückel A of the
//! water's temperature: formula 3 (golden v3; chemcore/findings/I2-comparison.md).
//!
//! v1 (crate::chemistry) takes the ionic strength from the salinity alone, so a fresh water (S 0) is ideal: every
//! activity coefficient 1, the NBS pH taken as the free pH. A fresh water is not ideal: a hard one has an ionic
//! strength near 0.01, where a monovalent ion's activity coefficient is about 0.9. Up to a salinity of `FRESH_UP_TO`
//! the v3 water takes its ionic strength from what is measured, and its constants are the fresh-water (thermodynamic,
//! infinite dilution) ones made concentration constants with Davies activity coefficients (`fresh_equilibria`); from
//! `SEA_FROM` on they are v1's seawater constants, the NBS pH converted with the temperature's A (I1, below); between
//! the two, each constant is the geometric blend of the two paths, the sea path's weight going linearly from 0 at
//! `FRESH_UP_TO` to 1 at `SEA_FROM` (`sea_weight`), so nothing jumps at either end. Why 1 and 5 ‰: Millero et al.
//! (2006) measured their K1 and K2 from S 1 to 50 (below 1 ‰ a fresh water's ions are not sea water's in proportion);
//! Dickson's (1990) KSO₄ and KB, which the sea path's scales and borate need, hold from S 5; Davies holds to I ≈ 0.5
//! (S 5 is I 0.10). The measured jump of the old 5 ‰ boundary and the choice are in the comparison.
//!
//! The ionic strength of the fresh path: an estimate, the conductivity κ (µS/cm, at 25 °C: specific conductance),
//! I = 1.6e-5 κ (Russell 1976, J. Am. Water Works Assoc. 68: 2; as in Snoeyink & Jenkins 1980, Water Chemistry), else
//! the salinity's when one above 0 is given (as sea water's, DOE 1994, chemistry::ionic_strength); unless the measured
//! ions' lower bound is larger: the hardness (mg/L as CaCO₃, Ca²⁺ and Mg²⁺) with the alkalinity (meq/L, as HCO₃⁻),
//! their ions and the monovalent ions their charges need to balance, I = ½ (4 c₂ + A + |2 c₂ − A|), mmol/L to mol/L;
//! else the alkalinity alone, as sodium bicarbonate, I = A. A bound is the least ionic strength the measured ions allow
//! (an unmeasured ion only adds to it), so an estimate below it is taken as the bound: a salinity of 0.01 ‰ never drops
//! a water's bicarbonate. With nothing measured (S 0, no alkalinity) the ionic strength is 0, v1's ideal water.
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
pub use crate::chemistry::Source;
use crate::chemistry::{
    self as c, Equilibria, KELVIN, LimitsBasis, MG_CACO3_PER_MEQ, Origin, k_h2s_total, k_nh4_sws, k1_sws, k2_sws,
    kb_total, kw_total, total_boron,
};
use crate::num::{ChemError, R, div, exp, finite, ln, pow, sqrt};

/// Up to this salinity (‰) formula 3 takes the fresh-water path alone: Millero et al. (2006) measured K1, K2 from S 1.
pub const FRESH_UP_TO: f64 = 1.0;
/// From this salinity (‰) formula 3 takes the seawater path alone: Dickson's (1990) KSO₄ and KB hold from S 5.
pub const SEA_FROM: f64 = 5.0;
/// Ionic strength per µS/cm of conductivity (Russell 1976, J. Am. Water Works Assoc. 68: 2, as Snoeyink & Jenkins 1980
/// give it; Russell's paper itself was not read): fitted to natural, bicarbonate-type waters (1 mM Ca(HCO₃)₂: I 3 mM at
/// about 200 µS/cm, 1.5e-5), with a scatter of about ±20 to 30 % (Griffin & Jurinak 1973 give 1.3e-5). It overstates a
/// NaCl water's ionic strength about 1.9 times (cross review F4), so a salt-added water takes
/// `IONIC_PER_MICROSIEMENS_NACL`.
pub const IONIC_PER_MICROSIEMENS: f64 = 1.6e-5;
/// Ionic strength per µS/cm of a NaCl solution at 25 °C: 0.01 mol/L NaCl has a molar conductivity of about 118.5 S cm²/mol
/// (CRC Handbook of Chemistry and Physics, molar conductivity of aqueous electrolytes; Robinson & Stokes 1959, Electrolyte
/// Solutions, appendix 6.2; neither printed table was opened here: the value agrees with Kohlrausch's law from NaCl's
/// limiting 126.4 and with the 0.01 mol/L KCl standard's 1413 µS/cm), so κ ≈ 1185 µS/cm and I / κ = 8.4e-6. It rises
/// with the concentration (about 8.1e-6 at 0.001 mol/L, 9.4e-6 at 0.1): within ±12 % from 120 to 11 000 µS/cm.
pub const IONIC_PER_MICROSIEMENS_NACL: f64 = 8.4e-6;
/// NaCl, g/mol (IUPAC 2007: Na 22.98977, Cl 35.453): a salt-added water's salinity as NaCl's molality.
pub const NACL_G_PER_MOL: f64 = 58.443;
/// Hardness: mg/L as CaCO₃ per mmol/L of Ca²⁺ and Mg²⁺ (CaCO₃ 100.0869, IUPAC 2007).
pub const MG_CACO3_PER_MMOL: f64 = 100.0869;
/// The Davies equation's linear term (Davies 1962).
pub const DAVIES: f64 = 0.3;
/// The largest ionic strength the Davies equation is taken to (Stumm & Morgan 1996, table 3.3: "I < 0.5"); above it
/// the fresh-water path refuses (`ChemError::OutOfRange`), as when a sea water's conductivity comes without its salinity
/// or a conductivity in mS/cm is read as µS/cm.
pub const DAVIES_MAX: f64 = 0.5;

/// What is measured of a fresh water's ions besides its alkalinity (none: None).
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Ions {
    /// µS/cm, compensated to 25 °C (specific conductance; a reading at the water's own temperature is not this value).
    pub conductivity_25_us_cm: Option<f64>,
    pub hardness_mg_l: Option<f64>,
    /// Where its salt came from (a unit's water origin, cross review F3): salt-added water takes the fresh path to the
    /// Davies limit with NaCl's ionic strength.
    pub origin: Origin,
}

fn present(value: Option<f64>) -> Result<Option<f64>, ChemError> {
    match value {
        Some(number) => finite(number).map(Some),
        None => Ok(None),
    }
}

/// The share of the seawater path in a water's constants: 0 up to `FRESH_UP_TO`, 1 from `SEA_FROM`, linear between.
pub fn sea_weight(salinity: f64) -> f64 {
    if salinity <= FRESH_UP_TO {
        0.0
    } else if salinity >= SEA_FROM {
        1.0
    } else {
        (salinity - FRESH_UP_TO) / (SEA_FROM - FRESH_UP_TO)
    }
}

/// The ionic strength (mol/L) of a water and where it came from: the sea's from `SEA_FROM` (DOE 1994), else the fresh
/// path's (`fresh_ionic_strength`). Refuses a non-finite input, a negative salinity, conductivity, hardness or
/// alkalinity, and on the fresh path an ionic strength above `DAVIES_MAX`.
pub fn ionic_strength(salinity: f64, alkalinity_mg_l: Option<f64>, ions: Ions) -> Result<(f64, Source), ChemError> {
    if ions.origin == Origin::SaltAdded {
        return match fresh_ionic_strength(salinity, alkalinity_mg_l, ions) {
            Err(ChemError::OutOfRange) if salinity >= SEA_FROM => Ok((c::ionic_strength(salinity)?, Source::Seawater)),
            found => found,
        };
    }
    if finite(salinity)? >= SEA_FROM {
        return Ok((c::ionic_strength(salinity)?, Source::Seawater));
    }
    fresh_ionic_strength(salinity, alkalinity_mg_l, ions)
}

/// The fresh path's ionic strength (the module's rule: the estimate unless the measured ions' bound is larger).
pub fn fresh_ionic_strength(
    salinity: f64,
    alkalinity_mg_l: Option<f64>,
    ions: Ions,
) -> Result<(f64, Source), ChemError> {
    let salinity = finite(salinity)?;
    let alkalinity = present(alkalinity_mg_l)?;
    let conductivity = present(ions.conductivity_25_us_cm)?;
    let hardness = present(ions.hardness_mg_l)?;
    if salinity < 0.0
        || [alkalinity, conductivity, hardness]
            .iter()
            .any(|value| value.is_some_and(|v| v < 0.0))
    {
        return Err(ChemError::Domain);
    }
    let bicarbonate = div(alkalinity.unwrap_or(0.0), MG_CACO3_PER_MEQ)?;
    let bound = match (hardness, alkalinity) {
        (Some(hardness), _) => {
            let divalent = div(hardness, MG_CACO3_PER_MMOL)?;
            let balance = libm::fabs(2.0 * divalent - bicarbonate);
            Some((0.5e-3 * (4.0 * divalent + bicarbonate + balance), Source::Hardness))
        }
        (None, Some(_)) => Some((bicarbonate / 1000.0, Source::Alkalinity)),
        (None, None) => None,
    };
    let estimate = match conductivity {
        Some(kappa) if ions.origin == Origin::SaltAdded => {
            Some((IONIC_PER_MICROSIEMENS_NACL * kappa, Source::Conductivity))
        }
        Some(kappa) => Some((IONIC_PER_MICROSIEMENS * kappa, Source::Conductivity)),
        // NaCl's molality: S g per kg of solution, (S / 58.443) / (1 − S / 1000) mol per kg of water.
        None if salinity > 0.0 && ions.origin == Origin::SaltAdded => Some((
            div(salinity / NACL_G_PER_MOL, 1.0 - salinity / 1000.0)?,
            Source::Salinity,
        )),
        None if salinity > 0.0 => Some((c::ionic_strength(salinity)?, Source::Salinity)),
        None => None,
    };
    let (strength, source) = match (estimate, bound) {
        (Some(estimate), Some(bound)) if bound.0 > estimate.0 => bound,
        (Some(estimate), _) => estimate,
        (None, Some(bound)) => bound,
        (None, None) => (0.0, Source::Nothing),
    };
    if strength > DAVIES_MAX {
        return Err(ChemError::OutOfRange);
    }
    Ok((strength, source))
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

/// The fresh path's equilibria of a water with its ionic strength and where it came from: the thermodynamic constants
/// made concentration constants with Davies activity coefficients (the module's rules), at any salinity below
/// `SEA_FROM` (`equilibria_v3` blends them with the sea's from `FRESH_UP_TO`).
pub fn fresh_equilibria(
    temp_c: f64,
    salinity: f64,
    alkalinity_mg_l: Option<f64>,
    ions: Ions,
) -> Result<Equilibria, ChemError> {
    let (strength, source) = fresh_ionic_strength(salinity, alkalinity_mg_l, ions)?;
    let eq = fresh_at(temp_c, salinity, strength, source, ions.origin)?;
    Ok(Equilibria {
        limits_basis: Some(LimitsBasis::of(&fresh_at(
            temp_c,
            salinity,
            0.0,
            Source::Nothing,
            ions.origin,
        )?)),
        ..eq
    })
}

/// The fresh path's equilibria at an ionic strength (mol/L; 0: every activity 1, the ideal water). A salt-added water
/// holds no seawater boron (NaCl carries none).
fn fresh_at(
    temp_c: f64,
    salinity: f64,
    strength: f64,
    source: Source,
    origin: Origin,
) -> Result<Equilibria, ChemError> {
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
        boron: if origin == Origin::SaltAdded {
            0.0
        } else {
            total_boron(salinity)
        },
        k_nh4: k_nh4_sws(temp_c, 0.0)?,
        k_h2s: div(k_h2s_total(temp_c, 0.0)?, gamma_one_squared)?,
        ksp_calcite: c::ksp_calcite(temp_c, salinity)?,
        ksp_aragonite: c::ksp_aragonite(temp_c, salinity)?,
        formula: 3,
        ionic_strength: strength,
        source,
        sea_weight: 0.0,
        limits_basis: None,
        origin,
    };
    checked(eq)
}

/// The basis the NH₃ and CO₂ limits were set on, for a water of formula 3 (cross review F1; owner decision 2026-11-09):
/// up to `FRESH_UP_TO` the ideal water (the fresh path at an ionic strength of 0, formula 1's fresh water at S 0: every
/// activity 1, the NBS pH taken as −log [H⁺], as Emerson et al. 1975's fraction, on which Piper et al. 1982 and US EPA
/// 1985 set the NH₃ limits, and Standard Methods 4500-CO₂ D's free CO₂), from `SEA_FROM` formula 1's seawater
/// constants (the salinity's; its NBS conversion with ε = 79), and between the same blend as the water's own (the
/// module's rules) with the same weight. Up to 1 ‰ this is the ideal water even where formula 1 took seawater constants
/// (0 < S ≤ 1): at the calculator's example (12 °C, 1 ‰, pH 7, 80 mg/L) the NH₃ border is 7.986, against formula 3's
/// corrected 8.045 and formula 1's 8.040; the CO₂ 19.62 mg/L, against 17.12 and 16.94. Judgements take the larger of this and the activity-corrected value.
pub fn limits_basis(temp_c: f64, salinity: f64, weight: f64, origin: Origin) -> Result<LimitsBasis, ChemError> {
    if weight >= 1.0 {
        return Ok(LimitsBasis::of(&c::equilibria(temp_c, salinity)?));
    }
    let ideal = fresh_at(temp_c, salinity, 0.0, Source::Nothing, origin)?;
    if weight <= 0.0 {
        return Ok(LimitsBasis::of(&ideal));
    }
    let sea = c::equilibria(temp_c, salinity)?;
    Ok(LimitsBasis {
        ph_offset: (1.0 - weight) * ideal.ph_offset + weight * sea.ph_offset,
        k1: blend(ideal.k1, sea.k1, weight)?,
        k2: blend(ideal.k2, sea.k2, weight)?,
        kw: blend(ideal.kw, sea.kw, weight)?,
        kb: blend(ideal.kb, sea.kb, weight)?,
        boron: sea.boron,
        k_nh4: blend(ideal.k_nh4, sea.k_nh4, weight)?,
    })
}

fn checked(eq: Equilibria) -> Result<Equilibria, ChemError> {
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

/// A constant of the band: the geometric blend of the fresh and the sea path's, `weight` the sea's.
fn blend(fresh: f64, sea: f64, weight: f64) -> R {
    exp((1.0 - weight) * ln(fresh)? + weight * ln(sea)?)
}

/// The formula 3 equilibria of a water (the module's rules), its provenance with it: the fresh path up to
/// `FRESH_UP_TO`, the sea path from `SEA_FROM` (v1's constants, the NBS conversion with the temperature's A), each
/// constant blended between (the pH offset, a logarithm, linearly; the rest geometrically). In the band the ionic
/// strength and its source are the fresh path's.
pub fn equilibria_v3(
    temp_c: f64,
    salinity: f64,
    alkalinity_mg_l: Option<f64>,
    ions: Ions,
) -> Result<Equilibria, ChemError> {
    let weight = if ions.origin == Origin::SaltAdded {
        // Salt-added fresh water (cross review F3): the fresh path up to the Davies limit, then the sea path.
        match fresh_equilibria(temp_c, salinity, alkalinity_mg_l, ions) {
            Err(ChemError::OutOfRange) if salinity >= SEA_FROM => 1.0,
            found => return found,
        }
    } else {
        sea_weight(finite(salinity)?)
    };
    if weight >= 1.0 {
        let (strength, source) = ionic_strength(salinity, alkalinity_mg_l, ions)?;
        let sea = c::equilibria_with(temp_c, salinity, &debye_huckel_a)?;
        return Ok(Equilibria {
            formula: 3,
            ionic_strength: strength,
            source,
            limits_basis: Some(limits_basis(temp_c, salinity, 1.0, ions.origin)?),
            origin: ions.origin,
            ..sea
        });
    }
    let fresh = fresh_equilibria(temp_c, salinity, alkalinity_mg_l, ions)?;
    if weight <= 0.0 {
        return Ok(fresh);
    }
    let sea = c::equilibria_with(temp_c, salinity, &debye_huckel_a)?;
    let eq = Equilibria {
        ph_offset: (1.0 - weight) * fresh.ph_offset + weight * sea.ph_offset,
        k1: blend(fresh.k1, sea.k1, weight)?,
        k2: blend(fresh.k2, sea.k2, weight)?,
        kw: blend(fresh.kw, sea.kw, weight)?,
        kb: blend(fresh.kb, sea.kb, weight)?,
        k_nh4: blend(fresh.k_nh4, sea.k_nh4, weight)?,
        k_h2s: blend(fresh.k_h2s, sea.k_h2s, weight)?,
        formula: 3,
        ionic_strength: fresh.ionic_strength,
        source: fresh.source,
        sea_weight: weight,
        limits_basis: Some(limits_basis(temp_c, salinity, weight, ions.origin)?),
        origin: ions.origin,
        ..sea
    };
    checked(eq)
}

/// The equilibria of a water by a formula version: 1 (golden v1: the salinity alone, ε = 79; the ions are not read) or
/// 3 (`equilibria_v3`); any other is refused (`ChemError::UnknownFormula`).
pub fn water_equilibria(
    formula: u32,
    temp_c: f64,
    salinity: f64,
    alkalinity_mg_l: Option<f64>,
    ions: Ions,
) -> Result<Equilibria, ChemError> {
    match formula {
        1 => c::equilibria(temp_c, salinity),
        3 => equilibria_v3(temp_c, salinity, alkalinity_mg_l, ions),
        _ => Err(ChemError::UnknownFormula),
    }
}
