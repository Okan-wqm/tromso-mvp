//! I2, fresh water's ionic strength (chemcore/findings/B1.md, I2; owner amendment B5), and I1, the Debye–Hückel A of the
//! water's temperature: formula 3 (golden v3; chemcore/findings/I2-comparison.md).
//!
//! v1 (crate::chemistry) takes the ionic strength from the salinity alone, so a fresh water (S 0) is ideal: every
//! activity coefficient 1, the NBS pH taken as the free pH. A fresh water is not ideal: a hard one has an ionic
//! strength near 0.01, where a monovalent ion's activity coefficient is about 0.9. Up to a salinity of `FRESH_UP_TO`
//! the v3 water takes its ionic strength from what is measured, and its constants are the fresh-water (thermodynamic,
//! infinite dilution) ones made concentration constants with Davies activity coefficients (`fresh_equilibria`); from
//! `SEA_FROM` on they are v1's seawater constants, the NBS pH converted with the temperature's A (I1, below) and the ion
//! product of water Millero's (1995) on his seawater scale (`sea_equilibria`; v1 keeps the 2007 Guide's); between
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
//! Concentrations per litre are taken as per kg (a fresh water's density is 1 within 0.3 %). Sea water is treated the
//! same way although its density is about 1.026 (the water-chemistry audit of 2026-11-19, F9): the alkalinity, the DIC
//! and the phosphate per litre against constants and totals per kg (boron, Kw / [H⁺]). Measured against PyCO2SYS given
//! the alkalinity as if per kg (the density taken as 1) instead of per kg by the EOS-80 density, its CO₂ moves by 0.000
//! to +0.143 % (the audit's grid: 4 to 16 °C, S 5 to 34, pH 6.8 to 8.0); the NH₃ not at all (its share is a ratio, TAN and NH₃-N both per
//! litre). Only Mucci's Ksp is put per litre (× ρ², for Ω).
//!
//! Davies (1962), Ion Association, p. 41: log γ = −A z² (√I / (1 + √I) − 0.3 I), valid to I ≈ 0.5. A is the
//! Debye–Hückel constant of the water's temperature (`debye_huckel_a`: its dielectric constant by Malmberg & Maryott
//! 1956 and its density by Kell 1975), I1 closed: formula 1's fixed ε = 79 made A 7.5 % too large at 12 °C and 15 % at
//! 2 °C. The seawater path's NBS conversion (Zeebe & Wolf-Gladrow 2001's Davies-type γH) takes the same A from formula 3
//! on: an in-house variant, not a published method (formula 1 codes ZWG with ε fixed at 79). Against CO2SYS's Takahashi et al. (1982) fH (fitted
//! for S 20 to 40) it is closer at 20 to 35 ‰ for t ≤ 15 °C and at 35 ‰ at every temperature, but not at 10 ‰ from 10
//! to 20 °C nor at 20 ‰, 20 °C, where formula 1 was closer (cross review F2; chemcore/findings/B1.md, the follow-up
//! formula 4: Takahashi's fH from 20 to 40 ‰).
//! The concentration constants (Stumm & Morgan 1996,
//! Aquatic Chemistry, 3rd ed., section 3.4; Plummer & Busenberg 1982), with γ₀ = 1 for CO₂, NH₃, H₂S, B(OH)₃:
//! pH free = pH NBS + log γ₁ (a meter reads the activity of H⁺); K1 = K1° / γ₁²; K2 = K2° / γ₂; Kw = Kw° / γ₁² (Kw°
//! pure water's: Millero's 1995 expression at S 0, `chemistry::kw_sws`);
//! KB = KB° / γ₁²; KH2S = KH2S° / γ₁²; KNH4 = KNH4° (H⁺ and NH₄⁺ both monovalent); Ksp as v1 (Ω is drawn only from 5 ‰).
pub use crate::chemistry::Source;
use crate::chemistry::{
    self as c, Equilibria, KELVIN, LimitsBasis, MG_CACO3_PER_MEQ, Origin, k_h2s_total, k_nh4_sws, k1_sws, k1p_sws,
    k2_sws, k2p_sws, k3p_sws, kb_total, kw_sws, kw_total, total_boron,
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
/// with the concentration (about 8.1e-6 at 0.001 mol/L, 9.4e-6 at 0.1): within ±12 % from 120 to 11 000 µS/cm; about
/// 1.07e-5 at 0.5 mol/L (near the Davies limit, 28 ‰), where it understates I by about 21 % (the corrected values a
/// little high, the conservative side; the judged one is the ideal anyway).
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

/// What is measured of a water besides its temperature, salinity and alkalinity (none: None): the ions its fresh-water
/// ionic strength is taken from, where its salt came from, and its phosphate.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Ions {
    /// µS/cm, compensated to 25 °C (specific conductance; a reading at the water's own temperature is not this value).
    pub conductivity_25_us_cm: Option<f64>,
    pub hardness_mg_l: Option<f64>,
    /// Where its salt came from (a unit's water origin, cross review F3): salt-added water takes the fresh path to the
    /// Davies limit with NaCl's ionic strength.
    pub origin: Origin,
    /// Orthophosphate, mg/L as P (PO₄-P): its part of the alkalinity is counted (`with_phosphate`). None, or 0: none
    /// given, and every result is what it was without the input. Formula 1 does not read it.
    pub phosphate_p_mg_l: Option<f64>,
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
    let bound = measured_bound(alkalinity, hardness)?;
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

// ---- plausibility of a water's inputs (cross review F5; the NH₃ guard): warnings said with the value, never a refusal --

/// The salinity's ionic strength outside what the conductivity allows (`PLAUSIBLE_PER_MICROSIEMENS`).
pub const CONDUCTIVITY_SALINITY: u8 = 1;
/// A conductivity (no salinity, the hardness measured) giving more than `ESTIMATE_OVER_BOUND` times the measured ions'
/// ionic strength.
pub const CONDUCTIVITY_ABOVE_IONS: u8 = 2;
/// A conductivity below the measured ions' ionic strength by more than `BOUND_OVER_ESTIMATE`: the bound is used.
pub const CONDUCTIVITY_BELOW_IONS: u8 = 4;
/// A salinity under `FRESH_UP_TO` with a conductivity PSS-78 reads as `SEA_FROM` or more (`practical_salinity`): past the
/// band, about 8 950 µS/cm, so a hard fresh RAS at 2000 to 3000 µS/cm (PSS-78 1 to 1.6) stays quiet (cross review round 2).
pub const SEAWATER_CONDUCTIVITY: u8 = 8;
/// The water is past the range the NH₃ judgement's guard holds over (`NH3_GUARD_MAX_TEMP_C`, `NH3_GUARD_MAX_SALINITY`):
/// its judged NH₃ may read below a Clegg & Whitfield (1995) based value. Said with every value worked out from the
/// water, never a refusal (the K_NH4 panel's decision of 2026-11-10, row 3).
pub const NH3_PAST_GUARD: u8 = 16;
/// The warmest water (°C) the NH₃ judgement's guard holds for; `NH3_GUARD_MAX_SALINITY` (‰) is the saltiest. Up to both,
/// the judged NH₃ (the larger of the limits' basis and the activity-corrected value, `Equilibria::nh3_share`) is never
/// below the core's own corrected value nor below one worked out with Clegg & Whitfield's (1995, Geochim. Cosmochim.
/// Acta 59: 2403, eq. 18) pK: tolerance 0 over 0 to 30 °C by S 0.5 to 35 (within 0.5 % at S 0), the smallest margin
/// +2.9 % at this very corner (chemcore/core/tests/nh3_guard.rs, where the equation is typed from Xu, Pierrot & Cai
/// 2017, Marine Chemistry, eq. 10; Clegg & Whitfield's paper itself was not read). Past either bound the judged value
/// does fall below it: from 33.55 °C at S 35 and from 30.10 °C at S 40; −1.3 % at 35 °C and −5.6 % at 40 °C, S 35 (the
/// panel's three independent computations; the guard's own tests). So `plausibility` says `NH3_PAST_GUARD` above 30 °C
/// or above 35 ‰, the bounds themselves quiet. No species in scope lives there (salmon's CTmax 28.5 °C, lumpfish
/// 20.6 °C, ballan wrasse 22.8 °C: second-hand, in the panel's report).
///
/// The two are validity bounds of cited constants, where what was checked against the sources ends, not limits a farm
/// sets: they are code on purpose, not user-editable reference data (the house rule "never hard-code a limit a farm
/// would want to change" is about a farm's own thresholds; editing these would only hide, or invent, a warning about
/// the chemistry). They move only with a guard held over a wider range.
pub const NH3_GUARD_MAX_TEMP_C: f64 = 30.0;
/// See `NH3_GUARD_MAX_TEMP_C`.
pub const NH3_GUARD_MAX_SALINITY: f64 = 35.0;
/// The water is colder than `FITTED_FROM_TEMP_C`: the constants are extrapolated there. Said with every value worked
/// out from the water, never a refusal (the water-chemistry audit of 2026-11-19, F10).
pub const BELOW_FITTED_TEMP: u8 = 32;
/// The coldest water (°C) the constants were fitted from: Millero et al. (2006)'s K1 and K2 and Dickson's (1990) KSO₄
/// and KB from 0 °C; the ammonium constants from warmer water still (Khoo et al. 1977's measurements and Yao & Millero's
/// 1995 fit of them from 5 °C; only Clegg & Whitfield 1995 reach −2 °C), Mucci's (1983) Ksp from 5 °C (Ω is said with
/// its own range). A
/// temperature is taken from −3 °C (farm/water/parameters.py: sea water at Tromsø goes below 0 °C), so below this one
/// `plausibility` says `BELOW_FITTED_TEMP`, the bound itself quiet. The judged values stay on the safe side there: at
/// −1.9 °C and S 30 to 34 the judged NH₃ is 11.7 to 14.4 % above Clegg & Whitfield (1995, fitted from −2 °C), the judged
/// CO₂ 18 to 21 % above PyCO2SYS (the audit's out/09_cold.txt): a missing sentence, not a wrong number. A validity bound
/// of cited constants, code on purpose (as `NH3_GUARD_MAX_TEMP_C`).
pub const FITTED_FROM_TEMP_C: f64 = 0.0;
/// The ionic strength per µS/cm a water may have: NaCl's `IONIC_PER_MICROSIEMENS_NACL` to Russell's
/// `IONIC_PER_MICROSIEMENS`, each widened by Russell's scatter of about ±30 % (as the cross review quotes it; the paper
/// itself was not read): 0.7 × 8.4e-6 and 1.3 × 1.6e-5.
pub const PLAUSIBLE_PER_MICROSIEMENS: (f64, f64) = (5.88e-6, 2.08e-5);
/// The conductivity's ionic strength over the hardness and alkalinity's bound beyond which a fresh water's conductivity is
/// suspect (salt added, or mS/cm read as µS/cm), checked only with the hardness measured (the alkalinity alone is too
/// low a reference): 30, an in-house threshold (cross review F5, round 2). World-average river water (Livingstone 1963,
/// USGS PP 440-G: Ca 15, Mg 4.1, Na 6.3, K 2.3, HCO₃ 58.4, SO₄ 11.2, Cl 7.8 mg/L) has about 1.3; an intensive RAS's
/// accumulated nitrate, chloride and sulfate (hundreds of mg/L, our reasoning, not a measured survey) take it to 10 to 20.
pub const ESTIMATE_OVER_BOUND: f64 = 30.0;
/// The measured ions' bound over the conductivity's ionic strength beyond which the conductivity is suspect (not
/// compensated to 25 °C, about 45 % low at 2 °C; or in the wrong unit): 1.5, about 1 / (1 − 0.3), Russell's scatter.
pub const BOUND_OVER_ESTIMATE: f64 = 1.5;

/// The practical salinity of a sea water of this conductivity at 25 °C (µS/cm): PSS-78 (UNESCO 1983, Tech. Pap. Mar.
/// Sci. 44; at 1 atm, t 25 °C, C(35, 15, 0) = 42.914 mS/cm, the r_t polynomial), extended below S 2 by Hill, Dauphinee &
/// Woods (1986), IEEE J. Oceanic Eng. OE-11: 109. Valid for sea water's ion composition: a fresh water's reads only
/// as "the sea water it would be".
pub fn practical_salinity(conductivity_25_us_cm: f64) -> R {
    let kappa = finite(conductivity_25_us_cm)?;
    if kappa < 0.0 {
        return Err(ChemError::Domain);
    }
    let t: f64 = 25.0;
    let r_t = 0.6766097 + 2.00564e-2 * t + 1.104259e-4 * t * t - 6.9698e-7 * pow(t, 3.0)? + 1.0031e-9 * pow(t, 4.0)?;
    let ratio = div(kappa / 1000.0, 42.914 * r_t)?;
    let root = sqrt(ratio)?;
    let a = [0.0080, -0.1692, 25.3851, 14.0941, -7.0261, 2.7081];
    let b = [0.0005, -0.0056, -0.0066, -0.0375, 0.0636, -0.0144];
    let (mut s, mut delta, mut power) = (0.0, 0.0, 1.0);
    for (a_i, b_i) in a.iter().zip(b.iter()) {
        s += a_i * power;
        delta += b_i * power;
        power *= root;
    }
    let f_t = div(t - 15.0, 1.0 + 0.0162 * (t - 15.0))?;
    let x = 400.0 * ratio;
    let y = 100.0 * ratio;
    let hill = div(0.0080, 1.0 + 1.5 * x + x * x)? + div(0.0005 * f_t, 1.0 + sqrt(y)? + y + pow(y, 1.5)?)?;
    Ok(s + f_t * delta - hill)
}

/// The warnings of a water's inputs (the constants above, or-ed): never a refusal, said beside every value worked out
/// from it (`Equilibria::warnings`). A water above `NH3_GUARD_MAX_TEMP_C` or `NH3_GUARD_MAX_SALINITY` is past the NH₃
/// guard (`NH3_PAST_GUARD`), one below `FITTED_FROM_TEMP_C` below the constants' fits (`BELOW_FITTED_TEMP`); of the
/// ionic inputs only a conductivity can disagree, so without one none of theirs.
pub fn plausibility(temp_c: f64, salinity: f64, alkalinity_mg_l: Option<f64>, ions: Ions) -> Result<u8, ChemError> {
    let salinity = finite(salinity)?;
    let temp_c = finite(temp_c)?;
    let mut warnings = 0;
    if temp_c > NH3_GUARD_MAX_TEMP_C || salinity > NH3_GUARD_MAX_SALINITY {
        warnings |= NH3_PAST_GUARD;
    }
    if temp_c < FITTED_FROM_TEMP_C {
        warnings |= BELOW_FITTED_TEMP;
    }
    let Some(kappa) = present(ions.conductivity_25_us_cm)? else {
        return Ok(warnings);
    };
    if salinity > 0.0 {
        let from_salinity = if ions.origin == Origin::SaltAdded {
            div(salinity / NACL_G_PER_MOL, 1.0 - salinity / 1000.0)?
        } else {
            c::ionic_strength(salinity)?
        };
        if from_salinity < PLAUSIBLE_PER_MICROSIEMENS.0 * kappa || from_salinity > PLAUSIBLE_PER_MICROSIEMENS.1 * kappa
        {
            warnings |= CONDUCTIVITY_SALINITY;
        }
    }
    if salinity < FRESH_UP_TO && practical_salinity(kappa)? >= SEA_FROM {
        warnings |= SEAWATER_CONDUCTIVITY;
    }
    let per = if ions.origin == Origin::SaltAdded {
        IONIC_PER_MICROSIEMENS_NACL
    } else {
        IONIC_PER_MICROSIEMENS
    };
    let estimate = per * kappa;
    if let Some(bound) = measured_bound(alkalinity_mg_l, ions.hardness_mg_l)? {
        if salinity == 0.0 && bound.1 == Source::Hardness && estimate > ESTIMATE_OVER_BOUND * bound.0 {
            warnings |= CONDUCTIVITY_ABOVE_IONS;
        }
        if bound.0 > BOUND_OVER_ESTIMATE * estimate {
            warnings |= CONDUCTIVITY_BELOW_IONS;
        }
    }
    Ok(warnings)
}

/// The least ionic strength the measured ions allow and its source (the module's rule): the hardness with the
/// alkalinity, else the alkalinity alone; None with neither.
fn measured_bound(
    alkalinity_mg_l: Option<f64>,
    hardness_mg_l: Option<f64>,
) -> Result<Option<(f64, Source)>, ChemError> {
    let alkalinity = present(alkalinity_mg_l)?;
    let bicarbonate = div(alkalinity.unwrap_or(0.0), MG_CACO3_PER_MEQ)?;
    Ok(match (present(hardness_mg_l)?, alkalinity) {
        (Some(hardness), _) => {
            let divalent = div(hardness, MG_CACO3_PER_MMOL)?;
            let balance = libm::fabs(2.0 * divalent - bicarbonate);
            Some((0.5e-3 * (4.0 * divalent + bicarbonate + balance), Source::Hardness))
        }
        (None, Some(_)) => Some((bicarbonate / 1000.0, Source::Alkalinity)),
        (None, None) => None,
    })
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
        limits_basis: Some(LimitsBasis::of(&ideal_water(temp_c, salinity, ions.origin)?)),
        ..eq
    })
}

/// The ideal water the limits were set on (`limits_basis`): the fresh path at an ionic strength of 0 with formula 1's ion
/// product of water (`chemistry::kw_total` at S 0, the 2007 Guide's), so that it stays formula 1's fresh water at S 0
/// bit for bit and a judged CO₂, the larger of the basis's and the water's own, never falls below formula 1's. The water's
/// own constants take Millero's Kw (`fresh_at`).
fn ideal_water(temp_c: f64, salinity: f64, origin: Origin) -> Result<Equilibria, ChemError> {
    let ideal = fresh_at(temp_c, salinity, 0.0, Source::Nothing, origin)?;
    checked(Equilibria {
        kw: kw_total(temp_c, 0.0)?,
        ..ideal
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
        // Kw° is pure water's: Millero's (1995) seawater-scale expression at S 0, where every pH scale is the free one
        // (pKw 13.995 at 25 °C; the Guide's total-scale constant of formula 1 leaves 14.0012 there).
        kw: div(kw_sws(temp_c, 0.0)?, gamma_one_squared)?,
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
        warnings: 0,
        phosphate: 0.0,
        k1p: 0.0,
        k2p: 0.0,
        k3p: 0.0,
    };
    checked(eq)
}

/// The basis the NH₃ and CO₂ limits were set on, for a water of formula 3 (cross review F1; owner decision 2026-11-09;
/// the sea side's NH₃, cross review round 2, S1). Up to `FRESH_UP_TO` the ideal water (the fresh path at an ionic
/// strength of 0, formula 1's fresh water at S 0: every activity 1, the NBS pH taken as −log [H⁺], as Emerson et al.
/// 1975's fraction, on which Piper et al. 1982 and US EPA 1985 set the NH₃ limits, and Standard Methods 4500-CO₂ D's free
/// CO₂). From `SEA_FROM`: for NH₃ the free-scale, molal pKa of Khoo, Culberson & Bates (1977), eq. 11 (with Emerson's
/// pure-water term), applied to the NBS pH as measured, not converted: the safe side (`pk_nh4_seawater`, which says
/// what it is and is not: neither Bower & Bidwell 1978's tables nor the US EPA 1989 criteria's own), for CO₂ formula 1's seawater constants (the salinity's; its NBS
/// conversion with ε = 79: CO₂ limits are applied to measured true concentrations, which Millero's apparent constants
/// estimate). Between, the same blend as the water's own (the module's rules) with the same weight. Up to 1 ‰ this is
/// the ideal water even where formula 1 took seawater constants (0 < S ≤ 1): at the calculator's example (12 °C, 1 ‰,
/// pH 7, 80 mg/L) the NH₃ border is 7.986, against formula 3's corrected 8.045 and formula 1's 8.040; the CO₂ 19.62
/// mg/L, against 17.12 and 16.94. A salt-added water's basis is the ideal water throughout, past the Davies limit too
/// (its constants jump there, S 28.39 ‰ as NaCl, its judged NH₃ and CO₂ never drop). Judgements take the larger of this
/// and the activity-corrected value.
pub fn limits_basis(temp_c: f64, salinity: f64, weight: f64, origin: Origin) -> Result<LimitsBasis, ChemError> {
    let ideal = ideal_water(temp_c, salinity, origin)?;
    if weight <= 0.0 || origin == Origin::SaltAdded {
        return Ok(LimitsBasis::of(&ideal));
    }
    let sea = c::equilibria(temp_c, salinity)?;
    let k_khoo = pow(10.0, -pk_nh4_seawater(temp_c, salinity)?)?;
    if weight >= 1.0 {
        return Ok(LimitsBasis {
            k_nh4: k_khoo,
            nh3_ph_offset: 0.0,
            ..LimitsBasis::of(&sea)
        });
    }
    Ok(LimitsBasis {
        ph_offset: (1.0 - weight) * ideal.ph_offset + weight * sea.ph_offset,
        k1: blend(ideal.k1, sea.k1, weight)?,
        k2: blend(ideal.k2, sea.k2, weight)?,
        kw: blend(ideal.kw, sea.kw, weight)?,
        kb: blend(ideal.kb, sea.kb, weight)?,
        boron: sea.boron,
        k_nh4: blend(ideal.k_nh4, k_khoo, weight)?,
        nh3_ph_offset: 0.0,
    })
}

/// The pKa of NH₄⁺ in sea water of the NH₃ limits' basis: Khoo, Culberson & Bates (1977), J. Solution Chem. 6: 281,
/// eq. 11 (p. 285), pK = pK° + (0.1552 − 0.0003142 t) I_f, with pK° the pure-water value (here Emerson et al. 1975's
/// fit of the same Bates & Pinching values, 0.09018 + 2729.92 / T) and I_f the formal ionic strength of their sea water
/// (Table I, p. 284), which I = 19.9273 S / (1000 − 1.005109 S) reproduces (0.4132, 0.7229, 0.9294 at S 20.31, 35.00,
/// 44.55):
/// pKa^s = 0.09018 + 2729.92 / T + (0.1552 − 0.0003142 t) I, T in K, t in °C.
///
/// What it is (the water-chemistry audit of 2026-11-19, F5, checked against the paper): a constant on the FREE hydrogen
/// ion scale (their eq. 7, p. 283, writes the total as m_H (1 + β_HSO₄ m_SO₄), so m_H is the free ion) and MOLAL
/// (Table III, p. 288, "Molality Scale"). Measured from 5 to 40 °C at S 20.31 to 44.55; against its 24 values this form
/// is −0.009 to +0.011 (rms 0.0070; the paper's standard deviation 0.0065). The application applies it to the meter's
/// NBS pH WITHOUT converting that pH to the free scale: in sea water an NBS pH reads above the free pH, so the NH₃ is
/// read higher than with a converted pH (6 to 20 % at S 20 to 35), the safe side, on purpose. No paper says that a
/// sea-water table takes an NBS pH; that ammonia toxicity tests calibrate with NBS buffers is US EPA 1989's statement
/// (p. 2), after Millero 1986 (p. 846). Below 5 °C and below S 20 it is extrapolated; against Clegg & Whitfield's (1995)
/// free-basis equation (−2 to 40 °C, S 0 to 40) it is −0.002 to +0.011 pK over S 5 to 35 and −2 to 16 °C.
///
/// What it is not. Not Bower & Bidwell's (1978, J. Fish. Res. Board Can. 35: 1012) tables: they never cite Khoo; they
/// take Whitfield's (1974) mean values at 25 °C per salinity band (9.29, 9.32, 9.33, 9.35; Table 1, p. 1012) with a
/// linear term, pK(T) = pK(298 K) + 0.0324 (298 − T) (p. 1015). At S 34 this form gives the same NH₃ as their Table 5
/// at 12 °C (0.6715 against 0.670 % at pH 7.6) and less below it: −1.5 % at 8 °C, −4.0 % at 4 °C, −7.5 % at 0 °C (−7.1
/// and −10.3 % at 4 and 0 °C at S 20), their linear term being the one that departs from the measurements (the audit's
/// F12). Nor the speciation of the US EPA (1989) saltwater ammonia criteria (EPA 440/5-88-004): those used Hampson's
/// (1977) program for Whitfield's model, %UIA = 100 / (1 + 10^(X + 0.0324 (298 − T) + 0.0415 P / T − pH)) with X the
/// model's pKa^s at 25 °C (its pp. 1–2 and 27–28, eq. 4; Khoo et al. are cited there only as having substantiated
/// Whitfield); against this form EPA's printed table gives 6.7 to 14.3 % more NH₃ at 0 to 5 °C (its linear temperature
/// term, 8.1 % wrong in pure water at 0 °C) and agrees within 2 to 6 % at 10 to 25 °C (the K_NH4 panel, 2026-11-10,
/// rows 4 and 5). So a limit taken from those tables at low temperature was set with more NH₃ than this basis gives
/// (documented, not copied).
///
/// Bell et al. (2007, Environ. Chem. 4: 183) read eq. 11 with pK° held at 25 °C and reported large errors; their
/// corrigendum (Environ. Chem. 2008, 5: 258) withdraws that ("we misinterpreted the method presented by Khoo et al."):
/// with a temperature-dependent pK°, as here, the equation "gave reasonable predictions … between 5 and 40 °C".
pub fn pk_nh4_seawater(temp_c: f64, salinity: f64) -> R {
    let t = finite(temp_c)?;
    let s = finite(salinity)?;
    let strength = div(19.9273 * s, 1000.0 - 1.005109 * s)?;
    Ok(0.09018 + div(2729.92, t + KELVIN)? + (0.1552 - 0.0003142 * t) * strength)
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

/// The sea path's equilibria of formula 3: formula 1's seawater constants with two differences, the NBS pH converted by
/// the temperature's A (I1) and the ion product of water Millero's (1995) on his seawater scale over [H⁺]SWS / [H⁺]free,
/// as K1, K2 and KNH4 are converted (`chemistry::kw_free`; the correction of 2026-11-10 after the independent check:
/// formula 1 keeps the 2007 Guide's approximate total-scale value, `chemistry::kw_total`).
pub fn sea_equilibria(temp_c: f64, salinity: f64) -> Result<Equilibria, ChemError> {
    let sea = c::equilibria_with(temp_c, salinity, &debye_huckel_a)?;
    checked(Equilibria {
        kw: c::kw_free(temp_c, salinity)?,
        ..sea
    })
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
    let eq = with_phosphate(
        constants_v3(temp_c, salinity, alkalinity_mg_l, ions)?,
        ions.phosphate_p_mg_l,
    )?;
    Ok(Equilibria {
        warnings: plausibility(temp_c, salinity, alkalinity_mg_l, ions)?,
        ..eq
    })
}

/// A water's equilibria with its phosphate (the optional PO₄-P input: the independent check of 2026-11-09, hypothesis
/// 12a; owner-approved 2026-11-10): the total, mg/L as P ÷ `chemistry::MG_P_PER_MMOL` as mmol/L, and the three constants
/// of phosphoric acid (Millero 1995: `chemistry::k1p_sws`, `k2p_sws`, `k3p_sws`) made the water's as its other constants
/// are. On the sea path, over [H⁺]SWS / [H⁺]free. On the fresh path, the S 0 (pure water) values made concentration
/// constants with the Davies activity coefficients of the water's ionic strength (the module's rules): K1P = K1P° /
/// γ₁² (H₃PO₄⁰ ⇌ H⁺ + H₂PO₄⁻), K2P = K2P° / γ₂ (the γ₁ of H₂PO₄⁻ and of H⁺ cancel), K3P = K3P° γ₂ / (γ₁ γ₃), with
/// log γ_z = z² log γ₁, so 10^(2, 4, 6 log γ₁) under the three. In the band, the geometric blend with the sea path's
/// weight. The phosphate is not added to the ionic strength (a conductivity already counts it; 10 mg/L as P is about
/// 0.0005 mol/L). None, or 0: the equilibria as they are, nothing computed; a negative one is refused.
fn with_phosphate(eq: Equilibria, phosphate_p_mg_l: Option<f64>) -> Result<Equilibria, ChemError> {
    let Some(given) = present(phosphate_p_mg_l)? else {
        return Ok(eq);
    };
    if given < 0.0 {
        return Err(ChemError::Domain);
    }
    if given == 0.0 {
        return Ok(eq);
    }
    let (temp_c, salinity, weight) = (eq.temp_c, eq.salinity, eq.sea_weight);
    let fresh = || -> Result<(f64, f64, f64), ChemError> {
        let one = davies_log_gamma(temp_c, eq.ionic_strength, 1.0)?;
        Ok((
            div(k1p_sws(temp_c, 0.0)?, pow(10.0, 2.0 * one)?)?,
            div(k2p_sws(temp_c, 0.0)?, pow(10.0, 4.0 * one)?)?,
            div(k3p_sws(temp_c, 0.0)?, pow(10.0, 6.0 * one)?)?,
        ))
    };
    let sea = || -> Result<(f64, f64, f64), ChemError> {
        let to_sws = c::free_to_sws(temp_c, salinity)?;
        Ok((
            div(k1p_sws(temp_c, salinity)?, to_sws)?,
            div(k2p_sws(temp_c, salinity)?, to_sws)?,
            div(k3p_sws(temp_c, salinity)?, to_sws)?,
        ))
    };
    let (k1p, k2p, k3p) = if weight <= 0.0 {
        fresh()?
    } else if weight >= 1.0 {
        sea()?
    } else {
        let (fresh, sea) = (fresh()?, sea()?);
        (
            blend(fresh.0, sea.0, weight)?,
            blend(fresh.1, sea.1, weight)?,
            blend(fresh.2, sea.2, weight)?,
        )
    };
    for value in [k1p, k2p, k3p] {
        finite(value)?;
    }
    Ok(Equilibria {
        phosphate: given / c::MG_P_PER_MMOL / 1000.0,
        k1p,
        k2p,
        k3p,
        ..eq
    })
}

fn constants_v3(temp_c: f64, salinity: f64, alkalinity_mg_l: Option<f64>, ions: Ions) -> Result<Equilibria, ChemError> {
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
        let sea = sea_equilibria(temp_c, salinity)?;
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
    let sea = sea_equilibria(temp_c, salinity)?;
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

/// The equilibria of a water by a formula version: 1 (golden v1: the salinity alone, ε = 79; the ions and the phosphate
/// are not read) or
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
