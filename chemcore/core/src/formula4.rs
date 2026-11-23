//! Formula 4 (the water-chemistry audit of 2026-11-19 and its paper debate; the owner's decision of the same day, Rule S;
//! README.md, Water-chemistry core, formula 4): formula 3 (crate::fresh) with three changes, nothing else.
//!
//! 1. **The NBS step of the sea path** (pH free − pH NBS, `ph_offset`): from Millero (1986), Limnol. Oceanogr. 31: 839,
//!    table 7, the measured pH NBS − pH total (molal) of estuarine waters at 25 °C, a straight line through his S 5 to 35
//!    points by least squares, D(S) = 0.1306 + 0.00073 S (residuals ≤ 0.004 pH there; held at its S 35 value above 35,
//!    where his S 40 point lies 0.015 below the line), moved in temperature by 0.75 of the bisulfate and fluoride term's
//!    change, the share fitted to Takahashi, Williams & Bos (1982, GEOSECS Pacific vol. 3, p. 80)'s fH from 0 to 30 °C
//!    at S 30 to 36 (0.743; residual ≤ 0.004):
//!
//!      pH free − pH NBS = −D(S) − log₁₀(1 − 0.001005 S) + log₁₀ G(25, S) + 0.25 [log₁₀ F(t, S) − log₁₀ F(25, S)]
//!
//!    G = [H⁺]total / [H⁺]free and F = [H⁺]SWS / [H⁺]free (`chemistry::free_to_total`, `free_to_sws`: Morris & Riley's
//!    sulfate, Riley's fluoride, Dickson's 1990 KSO₄, Dickson & Riley's 1979 KF), 1 − 0.001005 S molal to per kg of
//!    solution (Millero 1995, eq. 62). Within 0.004 pH of Millero's points from S 5 to 35 at 25 °C and 0.006 of
//!    Takahashi's fit from 0 to 30 °C at S 30 to 35 (chemcore/core/tests/formula4.rs). Below 5 ‰, where only the band
//!    takes the sea path (blended with the fresh path's Davies offset), D runs between Millero's S 0 (0.053), S 2.5
//!    (0.094) and the line's S 5 points, straight between each. It replaces formula 3's Davies-type γH (Zeebe &
//!    Wolf-Gladrow 2001 with the temperature's A, an in-house variant): 0.024 pH off at 12 °C and 0.04 to 0.05 at 0 to
//!    4 °C in salt water (the audit, point 3 of its consensus). Nothing was measured below 25 °C under S 20; Millero's
//!    profile is one electrode pair.
//! 2. **K_NH4, the best estimate**: Clegg & Whitfield (1995) eq. 18 (`chemistry::k_nh4_cw95`), fresh water to the sea:
//!    their pure-water pK° on the fresh path, eq. 18 on the sea path (in formula 3 Yao & Millero's 1995 fit, 0.17 to
//!    8.8 % below it on the free scale from S 5).
//! 3. **Rule S, the judged NH₃ and CO₂** (`limits_basis`; the basis every judgement already takes the larger of, so
//!    `Equilibria::nh3_share`, `co2_judged` and the borders are unchanged): from `SEA_FROM` the water's own best estimate
//!    at its pH + `PH_UNCERTAINTY` for NH₃ and at its pH − `PH_UNCERTAINTY` for CO₂ (the electrode's ±0.03 pH, US EPA
//!    1989, EPA 440/5-88-004, p. 3, after Whitfield et al. 1985): +7.2 % on the NH₃ ([NH₃]/[NH₄⁺], 10^0.03) and +7.2 to
//!    +9 % on the CO₂ over the best estimate, at every temperature. Up to `FRESH_UP_TO` formula 3's basis unchanged, the
//!    ideal water (`fresh::ideal_water`: every activity 1, Yao & Millero's pure-water K_NH4 and formula 1's Kw, as
//!    Emerson et al. 1975 and Standard Methods 4500-CO₂ D), so a fresh water's judged NH₃ and CO₂ are formula 3's: the
//!    larger of it and the best estimate, which is the ideal wherever an ion is measured (the best estimate's K_NH4 lies
//!    up to 0.5 % above the ideal's at 0 °C: in a water with nothing measured, ionic strength 0, the best estimate judges
//!    there, by that much). Between, each basis constant and offset is blended with the band's sea weight, so nothing
//!    steps at 1 or 5 ‰. Salt-added water keeps formula 3's basis, the ideal water throughout (`fresh::limits_basis`).
//!    What the best estimate shows stays the best estimate; only the judged value carries the margin. It replaces "the
//!    larger of the classic tables' basis (Khoo et al. 1977, eq. 11, on the unconverted NBS pH) and the corrected value"
//!    in salt water: brackish judged NH₃ falls against formula 3 (S 5: 11 to 14 %, S 10: 8 to 12 %, S 20: 4 to 9 %, S 34:
//!    0 to 5 %), still 7 % above the best estimate; the judged CO₂ is never below the best estimate (formula 3's was, by
//!    up to 7.5 % in 11 of 48 cells from 12 °C and S 5).
//!
//! The safe-side and consistency range (the owner's MUST): sea sites 0 to 30 °C, land sites 8 to 30 °C; outside it what
//! the tests hold is said there. Nothing was computed below 0 °C or above 30 °C (`fresh::BELOW_FITTED_TEMP`,
//! `fresh::NH3_PAST_GUARD` stay said). Everything else, the fresh path's ionic strength, the Davies activities, the
//! band, the carbonate, borate, water, sulfide and phosphate constants, the scales and Ω, is formula 3's.
use crate::chemistry::{self as c, Equilibria, LimitsBasis, Origin};
use crate::fresh::{
    self as f, Ions, SEA_FROM, blend, checked, fresh_at, fresh_ionic_strength, ideal_water, ionic_strength,
    plausibility, sea_weight, with_phosphate,
};
use crate::num::{ChemError, R, finite, log10, pow};

/// The formula version of this module (crate::FORMULAS).
pub const FORMULA: u32 = 4;
/// The uncertainty of a pH reading (electrode and liquid junction): ±0.03 pH, US EPA (1989), Ambient Water Quality
/// Criteria for Ammonia (Saltwater), EPA 440/5-88-004, p. 3, after Whitfield et al. (1985). The judged NH₃ takes the pH
/// this much higher, the judged CO₂ this much lower (Rule S).
pub const PH_UNCERTAINTY: f64 = 0.03;
/// Millero (1986), table 7: pH NBS − pH total (molal) at 25 °C, the least-squares line through S 5 to 35 (0.130571 +
/// 0.00072857 S, as the owner's decision rounds it).
pub const NBS_STEP_INTERCEPT: f64 = 0.1306;
/// See `NBS_STEP_INTERCEPT`.
pub const NBS_STEP_SLOPE: f64 = 0.00073;
/// The line is held at its value here above (Millero's last point inside the fit; his S 40 point lies 0.015 below).
pub const NBS_STEP_HELD_FROM: f64 = 35.0;
/// Millero (1986), table 7, below the line: pH NBS − pH total (molal) at S 0 and at S 2.5, 25 °C (the band's sea side).
pub const NBS_STEP_BAND: [(f64, f64); 2] = [(0.0, 0.053), (2.5, 0.094)];
/// The share of the temperature change of log₁₀ [H⁺]SWS / [H⁺]free that the step follows (fitted to Takahashi et al.'s
/// fH from 0 to 30 °C at S 30 to 36: 0.743).
pub const BISULFATE_SHARE: f64 = 0.75;
/// The temperature (°C) Millero's table 7 was measured at.
pub const NBS_STEP_AT: f64 = 25.0;

/// pH NBS − pH total (molal) at 25 °C, D(S) (the module's step): the line from 5 ‰ (held above 35), Millero's points
/// joined below.
pub fn nbs_minus_total_25(salinity: f64) -> R {
    let s = finite(salinity)?;
    let line =
        |s: f64| NBS_STEP_INTERCEPT + NBS_STEP_SLOPE * if s < NBS_STEP_HELD_FROM { s } else { NBS_STEP_HELD_FROM };
    let [(s0, d0), (s1, d1)] = NBS_STEP_BAND;
    Ok(if s >= SEA_FROM {
        line(s)
    } else if s >= s1 {
        d1 + (line(SEA_FROM) - d1) * (s - s1) / (SEA_FROM - s1)
    } else {
        d0 + (d1 - d0) * (s - s0) / (s1 - s0)
    })
}

/// The sea path's pH free − pH NBS at a temperature (°C) and salinity (‰) (the module's step 1).
pub fn ph_offset(temp_c: f64, salinity: f64) -> R {
    let t = finite(temp_c)?;
    let s = finite(salinity)?;
    let swept = log10(c::free_to_sws(t, s)?)? - log10(c::free_to_sws(NBS_STEP_AT, s)?)?;
    finite(
        -nbs_minus_total_25(s)? - log10(1.0 - 0.001005 * s)?
            + log10(c::free_to_total(NBS_STEP_AT, s)?)?
            + (1.0 - BISULFATE_SHARE) * swept,
    )
}

/// The sea path's equilibria of formula 4: formula 3's (`fresh::sea_equilibria`) with the NBS step of this module and
/// Clegg & Whitfield's K_NH4.
pub fn sea_equilibria(temp_c: f64, salinity: f64) -> Result<Equilibria, ChemError> {
    let sea = f::sea_equilibria(temp_c, salinity)?;
    checked(Equilibria {
        ph_offset: ph_offset(temp_c, salinity)?,
        k_nh4: c::k_nh4_cw95(temp_c, salinity)?,
        formula: FORMULA,
        ..sea
    })
}

/// The fresh path's equilibria of formula 4 at an ionic strength: formula 3's (Davies, the water's own ions) with Clegg
/// & Whitfield's pure-water K_NH4.
fn fresh_path(temp_c: f64, salinity: f64, alkalinity_mg_l: Option<f64>, ions: Ions) -> Result<Equilibria, ChemError> {
    let (strength, source) = fresh_ionic_strength(salinity, alkalinity_mg_l, ions)?;
    let eq = fresh_at(temp_c, salinity, strength, source, ions.origin)?;
    checked(Equilibria {
        k_nh4: pow(10.0, -c::pk_nh4_cw95_pure(temp_c)?)?,
        formula: FORMULA,
        limits_basis: Some(LimitsBasis::of(&ideal_water(temp_c, salinity, ions.origin)?)),
        ..eq
    })
}

/// The basis a formula 4 judgement takes the larger of (the module's Rule S): up to `FRESH_UP_TO` (and for salt-added
/// water throughout) formula 3's ideal water; from `SEA_FROM` the sea path's own constants, the NH₃ at the pH +
/// `PH_UNCERTAINTY` (`nh3_ph_offset`) and the CO₂ at the pH − `PH_UNCERTAINTY` (`ph_offset`); between, each constant
/// blended geometrically and each offset linearly with `weight`, the sea path's share.
pub fn limits_basis(temp_c: f64, salinity: f64, weight: f64, origin: Origin) -> Result<LimitsBasis, ChemError> {
    let ideal = ideal_water(temp_c, salinity, origin)?;
    if weight <= 0.0 || origin == Origin::SaltAdded {
        return Ok(LimitsBasis::of(&ideal));
    }
    let sea = sea_equilibria(temp_c, salinity)?;
    let (co2_offset, nh3_offset) = (sea.ph_offset - PH_UNCERTAINTY, sea.ph_offset + PH_UNCERTAINTY);
    if weight >= 1.0 {
        return Ok(LimitsBasis {
            ph_offset: co2_offset,
            nh3_ph_offset: nh3_offset,
            ..LimitsBasis::of(&sea)
        });
    }
    let basis = LimitsBasis {
        ph_offset: (1.0 - weight) * ideal.ph_offset + weight * co2_offset,
        k1: blend(ideal.k1, sea.k1, weight)?,
        k2: blend(ideal.k2, sea.k2, weight)?,
        kw: blend(ideal.kw, sea.kw, weight)?,
        kb: blend(ideal.kb, sea.kb, weight)?,
        boron: sea.boron,
        k_nh4: blend(ideal.k_nh4, sea.k_nh4, weight)?,
        nh3_ph_offset: (1.0 - weight) * ideal.ph_offset + weight * nh3_offset,
    };
    for value in [basis.ph_offset, basis.nh3_ph_offset] {
        finite(value)?;
    }
    Ok(basis)
}

/// Formula 4's constants of a water, as `fresh::constants_v3` takes formula 3's: the fresh path up to `FRESH_UP_TO`, the
/// sea path from `SEA_FROM`, each constant blended between (the pH offset linearly, the rest geometrically); a salt-added
/// water on the fresh path to the Davies limit, then the sea path.
fn constants(temp_c: f64, salinity: f64, alkalinity_mg_l: Option<f64>, ions: Ions) -> Result<Equilibria, ChemError> {
    let weight = if ions.origin == Origin::SaltAdded {
        match fresh_path(temp_c, salinity, alkalinity_mg_l, ions) {
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
            ionic_strength: strength,
            source,
            limits_basis: Some(limits_basis(temp_c, salinity, 1.0, ions.origin)?),
            origin: ions.origin,
            ..sea
        });
    }
    let fresh = fresh_path(temp_c, salinity, alkalinity_mg_l, ions)?;
    if weight <= 0.0 {
        return Ok(fresh);
    }
    let sea = sea_equilibria(temp_c, salinity)?;
    checked(Equilibria {
        ph_offset: (1.0 - weight) * fresh.ph_offset + weight * sea.ph_offset,
        k1: blend(fresh.k1, sea.k1, weight)?,
        k2: blend(fresh.k2, sea.k2, weight)?,
        kw: blend(fresh.kw, sea.kw, weight)?,
        kb: blend(fresh.kb, sea.kb, weight)?,
        k_nh4: blend(fresh.k_nh4, sea.k_nh4, weight)?,
        k_h2s: blend(fresh.k_h2s, sea.k_h2s, weight)?,
        formula: FORMULA,
        ionic_strength: fresh.ionic_strength,
        source: fresh.source,
        sea_weight: weight,
        limits_basis: Some(limits_basis(temp_c, salinity, weight, ions.origin)?),
        origin: ions.origin,
        ..sea
    })
}

/// The formula 4 equilibria of a water (the module's rules), its provenance with it, its phosphate and its warnings as
/// formula 3's (`fresh::equilibria_v3`).
pub fn equilibria_v4(
    temp_c: f64,
    salinity: f64,
    alkalinity_mg_l: Option<f64>,
    ions: Ions,
) -> Result<Equilibria, ChemError> {
    let eq = with_phosphate(
        constants(temp_c, salinity, alkalinity_mg_l, ions)?,
        ions.phosphate_p_mg_l,
    )?;
    Ok(Equilibria {
        warnings: plausibility(temp_c, salinity, alkalinity_mg_l, ions)?,
        ..eq
    })
}
