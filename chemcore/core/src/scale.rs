//! The scale of a pH that is given to the core (the K_NH4 panel's proposal of 2026-11-10, decision row 6, built by the
//! owner's decision of 2026-11-11; chemcore/findings/pH-scale.md).
//!
//! Every pH the core takes is on the NBS scale: what a meter calibrated with NBS/NIST buffers reads (`chemistry`). A
//! seawater pH is often measured on another scale: the total scale (a sensor or an indicator calibrated with TRIS
//! buffers), the seawater scale, or the free scale. Such a pH typed in as NBS reads 0.10 to 0.14 too low (total) from 5
//! to 35 ‰, and the NH₃ worked out from it 20 to 27 % too low at pH 8: the largest single hazard the panel found. So a
//! pH may say its scale, and is put on the NBS scale here, by the factors the core has always used, before anything is
//! worked out from it. `PhScale::Nbs`, the default, is the pH itself, bit for bit: nothing a caller gets today moves.
//!
//! The scales (Dickson, Sabine & Christian (eds.) 2007, Guide to Best Practices for Ocean CO₂ Measurements, PICES Spec.
//! Publ. 3, ch. 2, eq. 15, and SOP 6a, eq. 1, read: "[H⁺]T = [H⁺]F (1 + ST/KS)", ST the total sulfate and KS the
//! bisulfate constant; the seawater scale counts hydrogen fluoride too, [H⁺]SWS = [H⁺]F (1 + ST/KS + FT/KF), which the
//! Guide's ch. 5, footnote 5 names "the SWS pH scale (including HF)": Dickson & Riley 1979 and Zeebe & Wolf-Gladrow
//! 2001, ch. 1.3, were not read here):
//!
//!   pH free = pH total + log₁₀(1 + ST/KS)              (`chemistry::free_to_total`)
//!   pH free = pH SWS   + log₁₀(1 + ST/KS + FT/KF)      (`chemistry::free_to_sws`)
//!   pH NBS  = pH free − offset                          (`Equilibria::ph_offset`, the water's own: free − NBS)
//!
//! ST by Morris & Riley (1966), FT by Riley (1965), KS by Dickson (1990), KF by Dickson & Riley (1979), as `chemistry`
//! cites them. The first two lines are the published definitions and agree with PyCO2SYS 1.8.3.4 and seacarb 3.4.2 (the
//! comparison is in the finding). The third is the core's own NBS conversion, a Davies-type H⁺ activity coefficient with
//! the Debye–Hückel A of the temperature (`fresh`): an in-house variant, not a published method, ±0.08 pH against
//! CO2SYS's (Takahashi et al. 1982) fH from 5 ‰. That uncertainty does not reach what is worked out from a converted
//! pH with the water's own constants: the free [H⁺] the core then takes is 10^−(pH NBS + offset), the offset cancels,
//! and it is the given pH's own free [H⁺] exactly. It does reach the limits' basis, which takes the NBS pH as measured
//! (`fresh::limits_basis`), as it reaches every NBS pH a meter reads.
//!
//! Where a scale other than NBS is taken: sea water only, a salinity of `fresh::SEA_FROM` (5 ‰) or more whose constants
//! are the sea path's alone (`Equilibria::sea_weight` 1) and whose salt is not said to be added NaCl
//! (`Origin::SaltAdded`). The three are seawater scales: KS holds from S 5 (Dickson 1990), TRIS buffers are made for
//! S 20 to 40, and below 5 ‰ the offset is the fresh path's and depends on the ions measured. Fresh water salted with
//! NaCl has no sulfate and no fluoride at ANY salinity: inside the Davies range it is on the fresh path, and past it
//! (about 28.4 ‰ as NaCl) the core works its constants out by the sea path for want of another
//! (`fresh::ionic_strength`), which does not make it sea water (the independent review of 2026-11-16, R4: S 29, 30 and
//! 35 salt-added were converted with sea water's sulfate). In all of these the core refuses
//! (`ChemError::SeawaterScale`), never assuming a conversion: such a water's pH is given as NBS.
use crate::chemistry::{Equilibria, Origin, free_to_sws, free_to_total};
use crate::fresh::SEA_FROM;
use crate::num::{ChemError, R, finite, log10};

/// The scale a pH is given on.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum PhScale {
    /// As a meter calibrated with NBS/NIST buffers reads it: the core's own scale, and the default.
    #[default]
    Nbs,
    /// −log₁₀ of the free hydrogen ion concentration, mol per kg of sea water.
    Free,
    /// The total scale: the free hydrogen ion and bisulfate (TRIS buffers in synthetic sea water; Dickson 1993).
    Total,
    /// The seawater scale: bisulfate and hydrogen fluoride too.
    Seawater,
}

impl PhScale {
    /// Every scale, the default first.
    pub const ALL: [PhScale; 4] = [PhScale::Nbs, PhScale::Total, PhScale::Seawater, PhScale::Free];

    /// A stable code.
    pub fn code(self) -> &'static str {
        match self {
            PhScale::Nbs => "nbs",
            PhScale::Free => "free",
            PhScale::Total => "total",
            PhScale::Seawater => "sws",
        }
    }

    pub fn from_code(code: &str) -> Option<PhScale> {
        PhScale::ALL.into_iter().find(|scale| scale.code() == code)
    }
}

/// Whether a pH on a scale other than NBS can be put on the NBS scale for this water: sea water's constants alone, from
/// `SEA_FROM`, and never a water whose salt is added NaCl, whichever path works it out (the module's rule). The NBS
/// scale is taken for every water.
pub fn converts(eq: &Equilibria, scale: PhScale) -> bool {
    scale == PhScale::Nbs || (eq.salinity >= SEA_FROM && eq.sea_weight >= 1.0 && eq.origin != Origin::SaltAdded)
}

/// The NBS pH of a pH given on a scale, for a water with these equilibria (the module's rules): the pH itself when it is
/// NBS (bit for bit); else pH + log₁₀([H⁺]scale / [H⁺]free) − (pH free − pH NBS). Refused (`ChemError::SeawaterScale`)
/// where the scale is not taken (`converts`); a non-finite pH is refused.
pub fn ph_nbs(eq: &Equilibria, ph: f64, scale: PhScale) -> R {
    let ph = finite(ph)?;
    if scale == PhScale::Nbs {
        return Ok(ph);
    }
    if !converts(eq, scale) {
        return Err(ChemError::SeawaterScale);
    }
    let over_free = match scale {
        PhScale::Nbs | PhScale::Free => 1.0,
        PhScale::Total => free_to_total(eq.temp_c, eq.salinity)?,
        PhScale::Seawater => free_to_sws(eq.temp_c, eq.salinity)?,
    };
    finite(ph + log10(over_free)? - eq.ph_offset)
}

/// The pH on a scale of a water whose NBS pH is given: `ph_nbs` the other way (what a page says beside a converted pH).
pub fn ph_on(eq: &Equilibria, ph_nbs: f64, scale: PhScale) -> R {
    let ph = finite(ph_nbs)?;
    if scale == PhScale::Nbs {
        return Ok(ph);
    }
    if !converts(eq, scale) {
        return Err(ChemError::SeawaterScale);
    }
    let over_free = match scale {
        PhScale::Nbs | PhScale::Free => 1.0,
        PhScale::Total => free_to_total(eq.temp_c, eq.salinity)?,
        PhScale::Seawater => free_to_sws(eq.temp_c, eq.salinity)?,
    };
    finite(ph - log10(over_free)? + eq.ph_offset)
}
