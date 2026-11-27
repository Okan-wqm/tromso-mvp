//! Gas equilibration: what a gas sensor reads in air that has come to equilibrium with a water, and what that reading
//! says of the water. A small stream of air is brought into contact with a much larger stream of water until it takes
//! up no more; the partial pressure of a gas in that air is then the water's dissolved, un-ionised gas over its
//! solubility (Henry's law), whatever the pH: of the total sulfide only H₂S crosses, of the DIC only CO₂. So the
//! conversion of a reading (`h2s_from_gas`, `co2_from_gas`) takes the water's temperature, its salinity and the
//! pressure, and neither a pH nor a flow.
//!
//! The air takes a little CO₂ with it, the pH of the water it leaves rises, and a little H₂S becomes HS⁻:
//! `mixed_contact` says by how much the reading falls short for a ratio of air to water, and `ph_rise_bound` the most
//! the pH can rise without a pH or an alkalinity being known.
//!
//! Not part of the Deffeyes chart and of no formula version: nothing here changes a number the core returned before
//! (it is outside the core, which it only calls: the core's digest does not move; the crate's note). The carbonate and
//! sulfide equilibria are a water's own (`chemistry::Equilibria`, whatever formula made it).
//!
//! PROVISIONAL (not for a released instrument): the solubility of H₂S (`k0_h2s`) is NOT read from its source. Its
//! three numbers are round textbook values and may be 10 to 20 % off; every µg/L of `h2s_from_gas` moves with them.
//! To be replaced by a constant read in its paper before any use other than a prototype: Douabul & Riley (1979),
//! Deep-Sea Res. A 26: 259 (sea water); Sander (2023), Atmos. Chem. Phys. 23: 10901 (pure water, with its temperature).
use chemcore_core::chemistry::{Equilibria, KELVIN, MG_CO2_PER_MMOL, k0_co2, solve, vapour_pressure_atm};
use chemcore_core::num::{ChemError, R, div, exp, finite, log10, pow};

/// The gas constant, L atm / (mol K): 8.314462618 J/(mol K) (CODATA 2018) over 101.325 J per L atm.
pub const GAS_CONSTANT: f64 = 0.082057366;
/// Hydrogen sulfide, g per mol (the 34.08088 of `chemistry::H2S_PER_S`).
pub const G_H2S_PER_MOL: f64 = 34.08088;
/// PROVISIONAL: the solubility of H₂S in pure water at 25 °C, mol/(L atm). Not read from its source (module note).
pub const K0_H2S_25: f64 = 0.1013;
/// PROVISIONAL: its temperature coefficient, K: d ln K0 / d(1/T). Not read from its source.
pub const K0_H2S_TEMP: f64 = 2100.0;
/// PROVISIONAL: the share of that solubility sea water of 35 ‰ loses (salting out), taken as linear in the salinity.
/// Not read from its source.
pub const K0_H2S_SALTING: f64 = 0.10;

/// PROVISIONAL: the solubility of H₂S per litre, mol/(L atm), as `chemistry::k0_co2` is CO₂'s: the three constants
/// above, none read from its source (module note). The result is refused when it is not a finite number.
pub fn k0_h2s(temp_c: f64, salinity: f64) -> R {
    let t = finite(temp_c)? + KELVIN;
    let pure = K0_H2S_25 * exp(K0_H2S_TEMP * (div(1.0, t)? - 1.0 / 298.15))?;
    finite(pure * (1.0 - K0_H2S_SALTING * finite(salinity)? / 35.0))
}

/// A gas's concentration in air over its concentration in the water it is in equilibrium with (both per litre,
/// dimensionless): 1 / (K0 R T), for a solubility K0 in mol/(L atm). CO₂ about 1.0 and H₂S about 0.34 at 12 °C, 35 ‰.
pub fn gas_over_water(k0: f64, temp_c: f64) -> R {
    div(1.0, k0 * GAS_CONSTANT * (temp_c + KELVIN))
}

/// The un-ionised H₂S (µg/L as H₂S) of the water an air is in equilibrium with, from that air's H₂S (ppb, nmol/mol,
/// as a sensor calibrated with dry gas reads the moist air itself) at a pressure (atm): ppb × pressure × K0 × M.
/// The temperature and the salinity are the water's. No pH: HS⁻ does not cross. PROVISIONAL as `k0_h2s` is.
pub fn h2s_from_gas(h2s_ppb: f64, temp_c: f64, salinity: f64, pressure: f64) -> R {
    finite(finite(h2s_ppb)? * 1e-9 * finite(pressure)? * k0_h2s(temp_c, salinity)? * G_H2S_PER_MOL * 1e6)
}

/// The dissolved CO₂ (mg/L) of the water an air is in equilibrium with, from that air's CO₂ (ppm, µmol/mol, read in
/// the moist air itself) at a pressure (atm): ppm × pressure × K0 (Weiss 1974, `chemistry::k0_co2`). No pH and no
/// alkalinity.
pub fn co2_from_gas(co2_ppm: f64, temp_c: f64, salinity: f64, pressure: f64) -> R {
    finite(finite(co2_ppm)? * 1e-6 * finite(pressure)? * k0_co2(temp_c, salinity)? * MG_CO2_PER_MMOL * 1000.0)
}

/// What a reading is multiplied by when the air is dried before the sensor (a mole fraction of dry air then, not of
/// the moist air the water saw): (pressure − the water's vapour pressure) / pressure. 0.986 at 12 °C and 1 atm.
pub fn dried_gas_factor(temp_c: f64, pressure: f64) -> R {
    div(pressure - vapour_pressure_atm(temp_c)?, pressure)
}

/// The total sulfide (in the unit of `free_h2s`, as H₂S) of a water whose un-ionised H₂S is `free_h2s`, at its pH
/// (NBS): free / the H₂S share. The one step of this module that needs a pH: 0.1 of a pH moves it by about 15 %.
pub fn total_sulfide(free_h2s: f64, eq: &Equilibria, ph: f64) -> R {
    div(free_h2s, eq.h2s_share(ph)?)
}

/// What a stream of air that has passed through a fully mixed vessel of flowing water carries, at steady state.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Contact {
    /// The pH (NBS) of the water in the vessel: the entering water's, risen by the CO₂ the air took.
    pub ph: f64,
    /// The CO₂ of the leaving air, mol/mol of moist air (× 1e6: ppm).
    pub co2_gas: f64,
    /// The CO₂ that `co2_from_gas` gives from the leaving air, over the entering water's CO₂.
    pub co2_ratio: f64,
    /// The H₂S that `h2s_from_gas` gives from the leaving air, over the entering water's un-ionised H₂S: below 1 by
    /// the H₂S that became HS⁻ as the pH rose, by the H₂S the air took, and by the air's saturation.
    pub h2s_ratio: f64,
}

/// The steady state of a fully mixed vessel through which a water (its equilibria, its alkalinity in meq/L and its pH,
/// NBS) and air flow: `air_per_water` is the air's flow over the water's (both by volume, 0.01 for 100 mL of air a
/// minute to 10 L of water), `air_co2` the entering air's CO₂ (mol/mol, `chemistry::AIR_CO2` outdoors), `pressure` in
/// atm, and `saturation` how far the leaving air has come to equilibrium with the vessel's water (above 0, up to 1;
/// the same for both gases).
///
/// The balance of the DIC per litre of water: DIC in − DIC = air per water × saturation × (CO₂ of the vessel's water
/// × its gas over water − the entering air's CO₂), the alkalinity unchanged; the total sulfide likewise, its H₂S
/// share at the vessel's pH. None when no DIC between nothing and the entering water's balances (a water that cannot
/// be). The worst case of a contact: a counter-current column or a closed headspace falls short by less.
pub fn mixed_contact(
    eq: &Equilibria,
    alkalinity: f64,
    ph: f64,
    air_per_water: f64,
    air_co2: f64,
    pressure: f64,
    saturation: f64,
) -> Result<Option<Contact>, ChemError> {
    for value in [alkalinity, ph, air_per_water, air_co2, pressure, saturation] {
        finite(value)?;
    }
    if air_per_water < 0.0 || air_co2 < 0.0 || pressure <= 0.0 || saturation <= 0.0 || saturation > 1.0 {
        return Err(ChemError::Domain);
    }
    let rt = GAS_CONSTANT * (eq.temp_c + KELVIN);
    let co2_over = div(1.0, k0_co2(eq.temp_c, eq.salinity)? * rt)?;
    let h2s_over = div(1.0, k0_h2s(eq.temp_c, eq.salinity)? * rt)?;
    let dic_in = eq.dic(alkalinity, ph)?;
    let co2_in = eq.co2(dic_in, ph)?;
    // the entering air's CO₂, mmol per litre of air
    let air = div(air_co2 * pressure * 1000.0, rt)?;
    let reach = air_per_water * saturation;
    let mut balance = |dic: f64| -> R {
        let Some(ph_here) = eq.ph_at(dic, alkalinity)? else {
            return Err(ChemError::ImpossibleWater);
        };
        Ok(dic_in - dic - reach * (co2_over * eq.co2(dic, ph_here)? - air))
    };
    let Some(dic) = solve(&mut balance, dic_in * 1e-9, dic_in + reach * air)? else {
        return Ok(None);
    };
    let Some(ph_here) = eq.ph_at(dic, alkalinity)? else {
        return Ok(None);
    };
    let leaving = air + saturation * (co2_over * eq.co2(dic, ph_here)? - air);
    let share = eq.h2s_share(ph_here)?;
    // the vessel's total sulfide for an entering un-ionised H₂S of 1
    let sulfide = div(div(1.0, eq.h2s_share(ph)?)?, 1.0 + reach * h2s_over * share)?;
    Ok(Some(Contact {
        ph: ph_here,
        co2_gas: div(leaving * rt, 1000.0 * pressure)?,
        co2_ratio: div(div(leaving, co2_over)?, co2_in)?,
        h2s_ratio: saturation * sulfide * share,
    }))
}

/// The most a contact with air can raise the pH of the water it leaves, whatever that water's pH and alkalinity:
/// log10(1 + CO₂'s gas over water × air per water), the air taking all the CO₂ it can hold (entering with none) and
/// the bicarbonate unchanged. 0.0044 at 12 °C, 35 ‰ and an air of 1 % of the water. The H₂S share falls by at most
/// ln 10 times that.
pub fn ph_rise_bound(temp_c: f64, salinity: f64, air_per_water: f64) -> R {
    let over = gas_over_water(k0_co2(temp_c, salinity)?, temp_c)?;
    log10(1.0 + over * finite(air_per_water)?)
}

/// How far bubbles have come to equilibrium at the full depth of a vessel, for CO₂ and for H₂S (0 to 1 each), from the
/// CO₂ read with the air let in at half the depth over the CO₂ read with it let in at the full depth (each less the
/// entering air's CO₂; the same flows of air and water): with x = 1/ratio − 1 the CO₂ is 1 − x² short of nothing and
/// the H₂S 1 − x^(2 K0 H₂S / K0 CO₂), a bubble filling with each gas at a rate in proportion to that gas's
/// solubility (the same diffusivity taken for both, an assumption). A ratio outside 0.5 to 1 is refused (`Domain`):
/// no bubble reads less at the full depth. PROVISIONAL as `k0_h2s` is.
pub fn saturation_from_depths(ratio: f64, temp_c: f64, salinity: f64) -> Result<(f64, f64), ChemError> {
    if !(0.5..=1.0).contains(&finite(ratio)?) {
        return Err(ChemError::Domain);
    }
    let short = div(1.0, ratio)? - 1.0;
    let harder = div(k0_h2s(temp_c, salinity)?, k0_co2(temp_c, salinity)?)?;
    Ok((1.0 - short * short, 1.0 - pow(short, 2.0 * harder)?))
}
