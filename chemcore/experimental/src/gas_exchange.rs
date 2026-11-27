//! Gas equilibration: what a gas sensor reads in air that has come to equilibrium with a water, and what that reading
//! says of the water. A small stream of air is brought into contact with a much larger stream of water until it takes
//! up no more; the partial pressure of a gas in that air is then the water's dissolved, un-ionised gas over its
//! solubility (Henry's law), whatever the pH: of the total sulfide only H₂S crosses, of the DIC only CO₂. So the
//! conversion of a reading (`h2s_from_gas`, `co2_from_gas`) takes the water's temperature, its salinity and the
//! pressure, and neither a pH nor a flow.
//!
//! What a conversion takes (science review of 2026-11-27, C5): the temperature is the water's where it meets the gas;
//! `pressure` (atm) is where the gas last came to equilibrium with the water (an equilibrator's headspace, a bubble's
//! depth), not the sensor's nor the room's; a ppm or ppb is the mole fraction in the gas as it was there, moist
//! (`dried_gas_factor` when it is dried before the sensor).
//!
//! Every function refuses an input or a result that is not a finite number (`NonFinite`: never a NaN as a number), a
//! pressure at or below 0 and a negative flow of air (`Domain`). A reading below 0 (a sensor's zero offset and noise)
//! is kept signed and gives a concentration below 0, never refused and never held at 0 (decided after the second
//! science review, 2026-11-28): refusing loses the point and hides a drifting zero, clamping biases every average
//! upward. What to show is the display's: "< LOD" below the sensor's limit of detection, and a zero-fault (re-zero)
//! flag below −2 to −3 times its zero noise; the raw signed value is stored. Nothing of that is built yet.
//!
//! Where H₂S's solubility holds (`h2s_validity`, the one rule): measured from 2 to 30 °C and a salinity of 0 to 40;
//! extrapolated from the water's freezing point up to 2 °C (decided after the second review: good to about 1 %, its
//! pure-water part within 0.6 % of IUPAC's low-temperature equation at 0 and −1.9 °C); refused below freezing and
//! above 30 °C (`OutOfRange`). Every H₂S result says which (`Ranged`). CO₂'s side never waits on H₂S's: a contact
//! outside H₂S's range still gives its CO₂ (`Contact::h2s_ratio` is then None).
//!
//! The air takes a little CO₂ with it, the pH of the water it leaves rises, and a little H₂S becomes HS⁻:
//! `mixed_contact` says by how much the reading falls short for a ratio of air to water, and `ph_rise_bound` the most
//! the pH can rise without a pH or an alkalinity being known. That holds for a water holding more CO₂ than the entering
//! air would leave in it, as a fish tank's does (5 to 20 mg/L against 0.5 to 1.3 from outdoor air). A water holding
//! less (a high pH, a low alkalinity) takes CO₂ from the air instead: its pH falls and both readings lie above the
//! truth.
//!
//! The carbonate and sulfide equilibria are a water's own (`chemistry::Equilibria`, whatever formula made it). Formula
//! 4 against formula 1 (review F1; 12 °C, 35 ‰, 2 meq/L, pH 7.2): the H₂S reading ratio moves by under 1 ‰ (0.87 ‰ at
//! air 10 % of the water), the CO₂ ratio by up to 2.1 ‰ (1.1 ‰ at a CO₂ saturation of 0.9); a total sulfide worked out
//! from a free H₂S moves by 5.6 % (the pH's H₂S share). The tests hold these numbers.
//!
//! Not part of the Deffeyes chart and of no formula version: nothing here changes a number the core returned before
//! (it is outside the core, which it only calls: the core's digest does not move; the crate's note).
//!
//! Why it is not in the core yet (each must be settled before it moves there): the B coefficients of Douabul & Riley's
//! H₂S solubility are the review's reading of a garbled print, confirmed against the 42 measurements but not yet read
//! in the paper (`K0_H2S_B`); the diffusivity factor of `saturation_from_depths` is PROVISIONAL; the fugacity of H₂S is
//! taken as its partial pressure (no cross virial coefficient read; expected under 1 %).
use chemcore_core::chemistry::{Equilibria, KELVIN, MG_CO2_PER_MMOL, k0_co2, solve, vapour_pressure_atm};
use chemcore_core::num::{ChemError, R, div, exp, finite, ln, log10, pow, sqrt};

/// The gas constant, L atm / (mol K): 8.314462618 J/(mol K) (CODATA 2018) over 101.325 J per L atm.
pub const GAS_CONSTANT: f64 = 0.082057366;
/// Hydrogen sulfide, g per mol (the 34.08088 of `chemistry::H2S_PER_S`).
pub const G_H2S_PER_MOL: f64 = 34.08088;
/// The solubility of H₂S, ln K0 = A1 + A2 (100/T) + A3 ln(T/100) + S [B1 + B2 (T/100) + B3 (T/100)²], K0 in mol/dm³
/// at an H₂S fugacity of 1 atm, T in K, S in g/kg: Douabul & Riley (1979), Deep-Sea Res. 26A: 259–268, their fit to
/// their 42 measurements in sea water (S 10 to 40) and their distilled water, within ±0.5 %, as the IUPAC Solubility
/// Data Series vol. 32 (Fogg & Young 1988), pp. 52–53, prints it. A1, A2, A3 as printed there.
pub const K0_H2S_A: [f64; 3] = [-41.0563, 66.4005, 15.1060];
/// B1, B2, B3 of `K0_H2S_A`'s equation. The IUPAC page as extracted reads −0.60583, 0.379753, −0.602340, which misses
/// the tabulated measurements by up to 100 %; these, the same digits a decimal place over (science review of
/// 2026-11-27), reproduce all 42 within 0.44 % (tests/gas_exchange.rs). To confirm in the original paper: until then
/// this module stays out of the core.
pub const K0_H2S_B: [f64; 3] = [-0.060583, 0.0379753, -0.0060234];
/// The temperatures (°C) of Douabul & Riley's measurements, 275.25 to 302.97 K: `Validity::Measured` between, and
/// extrapolated from the water's freezing point up to the first (`h2s_validity`).
pub const K0_H2S_TEMP_C: (f64, f64) = (2.0, 30.0);
/// The salinities (g/kg) it holds for: their distilled water and sea water of 9.972 to 40.028 (their largest, kept
/// so that every measurement is inside).
pub const K0_H2S_SALINITY: (f64, f64) = (0.0, 40.028);
/// PROVISIONAL: the diffusivity of H₂S in water over CO₂'s, 1.36 / 1.91 (1e-9 m²/s at 25 °C, CRC-derived tables as the
/// review read them; the tables it read span 0.71 to 0.80). The least: the least H₂S saturation follows, the larger
/// correction of a reading, the safe side.
pub const H2S_OVER_CO2_DIFFUSIVITY: f64 = 0.712;
/// PROVISIONAL: the power of the diffusivity in a liquid-film coefficient: 1/2 for a mobile bubble surface
/// (penetration, surface renewal), 2/3 for the rigid surface of a small, contaminated bubble, as in farm water; 2/3
/// gives the smaller factor, the safe side.
pub const FILM_EXPONENT: f64 = 2.0 / 3.0;

/// A pressure (atm) a gas can have: finite (`NonFinite`) and above 0 (`Domain`).
fn gas_pressure(pressure: f64) -> R {
    if finite(pressure)? > 0.0 {
        Ok(pressure)
    } else {
        Err(ChemError::Domain)
    }
}

/// How far an H₂S result stands on Douabul & Riley's measurements.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Validity {
    /// Inside their measurements: 2 to 30 °C, a salinity of 0 to 40.
    Measured,
    /// Their equation taken below 2 °C, down to the water's freezing point (said with the value).
    Extrapolated,
}

impl Validity {
    /// A stable code.
    pub fn code(self) -> &'static str {
        match self {
            Validity::Measured => "measured",
            Validity::Extrapolated => "extrapolated",
        }
    }
}

/// An H₂S result and how far it stands on the measurements behind it.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Ranged {
    pub value: f64,
    pub validity: Validity,
}

/// The freezing point of sea water at one atmosphere, °C: −0.0575 S + 1.710523e-3 S^1.5 − 2.154996e-4 S², UNESCO
/// (1983), Tech. Pap. Mar. Sci. 44 (Fofonoff & Millard), as the second science review gives it. 0 for fresh water,
/// −1.92 °C at 35 ‰. A salinity below 0 is refused (`Domain`).
pub fn freezing_point(salinity: f64) -> R {
    let s = finite(salinity)?;
    if s < 0.0 {
        return Err(ChemError::Domain);
    }
    finite(-0.0575 * s + 1.710523e-3 * s * sqrt(s)? - 2.154996e-4 * s * s)
}

/// Where Douabul & Riley's H₂S solubility holds for a water (THE rule; every H₂S result carries it): `Measured` from
/// 2 to 30 °C, `Extrapolated` from the water's freezing point (`freezing_point`) up to 2 °C; refused (`OutOfRange`)
/// below freezing, above 30 °C or outside a salinity of 0 to 40.028 (their largest), `NonFinite` for what is not a
/// number.
pub fn h2s_validity(temp_c: f64, salinity: f64) -> Result<Validity, ChemError> {
    let (temp_c, salinity) = (finite(temp_c)?, finite(salinity)?);
    if !(K0_H2S_SALINITY.0..=K0_H2S_SALINITY.1).contains(&salinity) || temp_c > K0_H2S_TEMP_C.1 {
        return Err(ChemError::OutOfRange);
    }
    if temp_c >= K0_H2S_TEMP_C.0 {
        Ok(Validity::Measured)
    } else if temp_c >= freezing_point(salinity)? {
        Ok(Validity::Extrapolated)
    } else {
        Err(ChemError::OutOfRange)
    }
}

/// The solubility of H₂S per litre, mol/(L atm), at a fugacity of 1 atm: Douabul & Riley (1979), `K0_H2S_A` and
/// `K0_H2S_B` (B to be confirmed in the paper), with its validity (`h2s_validity`: refused where that refuses).
pub fn k0_h2s(temp_c: f64, salinity: f64) -> Result<Ranged, ChemError> {
    let validity = h2s_validity(temp_c, salinity)?;
    let x = (temp_c + KELVIN) / 100.0;
    let [a1, a2, a3] = K0_H2S_A;
    let [b1, b2, b3] = K0_H2S_B;
    let value = finite(exp(a1
        + div(a2, x)?
        + a3 * ln(x)?
        + salinity * (b1 + b2 * x + b3 * x * x))?)?;
    Ok(Ranged { value, validity })
}

/// A gas's concentration in air over its concentration in the water it is in equilibrium with (both per litre,
/// dimensionless): 1 / (K0 R T), for a solubility K0 in mol/(L atm). CO₂ about 1.0 and H₂S about 0.31 at 12 °C, 35 ‰.
pub fn gas_over_water(k0: f64, temp_c: f64) -> R {
    finite(div(1.0, finite(k0)? * GAS_CONSTANT * (finite(temp_c)? + KELVIN))?)
}

/// The fugacity of CO₂ in air over its partial pressure, exp[(B + 2δ) P / (R T)]: Weiss (1974), Mar. Chem. 2: 203,
/// B = −1636.75 + 12.0408 T − 3.27957e-2 T² + 3.16528e-5 T³ and δ = 57.7 − 0.118 T (cm³/mol, T in K), R in
/// cm³ atm/(mol K), P in atm. 0.99625 at 12 °C and 1 atm.
pub fn co2_fugacity_coefficient(temp_c: f64, pressure: f64) -> R {
    let t = finite(temp_c)? + KELVIN;
    let virial = -1636.75 + 12.0408 * t - 3.27957e-2 * t * t + 3.16528e-5 * t * t * t;
    let cross = 57.7 - 0.118 * t;
    finite(exp(div(
        (virial + 2.0 * cross) * gas_pressure(pressure)?,
        GAS_CONSTANT * 1000.0 * t,
    )?)?)
}

/// The CO₂ a litre of water holds per atm of CO₂'s partial pressure in air, mol/(L atm): Weiss's K0, which is per
/// fugacity (`chemistry::k0_co2`), times the fugacity coefficient (`co2_fugacity_coefficient`).
pub fn co2_per_partial_pressure(temp_c: f64, salinity: f64, pressure: f64) -> R {
    finite(k0_co2(finite(temp_c)?, finite(salinity)?)? * co2_fugacity_coefficient(temp_c, pressure)?)
}

/// The un-ionised H₂S (µg/L as H₂S) of the water an air is in equilibrium with, from that air's H₂S (ppb, nmol/mol,
/// as a sensor calibrated with dry gas reads the moist air itself) at a pressure (atm, where the gas last met the
/// water): ppb × pressure × K0 × M, with K0's validity (`h2s_validity`). The temperature and the salinity are the
/// water's. No pH: HS⁻ does not cross. The fugacity of H₂S is taken as its partial pressure (module note).
pub fn h2s_from_gas(h2s_ppb: f64, temp_c: f64, salinity: f64, pressure: f64) -> Result<Ranged, ChemError> {
    let k0 = k0_h2s(temp_c, salinity)?;
    let value = finite(finite(h2s_ppb)? * 1e-9 * gas_pressure(pressure)? * k0.value * G_H2S_PER_MOL * 1e6)?;
    Ok(Ranged { value, ..k0 })
}

/// The dissolved CO₂ (mg/L) of the water an air is in equilibrium with, from that air's CO₂ (ppm, µmol/mol, read in
/// the moist air itself) at a pressure (atm, where the gas last met the water): ppm × pressure × K0 × the fugacity
/// coefficient (`co2_per_partial_pressure`; 0.37 % less at 12 °C than the partial pressure alone gives). No pH and no
/// alkalinity.
pub fn co2_from_gas(co2_ppm: f64, temp_c: f64, salinity: f64, pressure: f64) -> R {
    let per_atm = co2_per_partial_pressure(temp_c, salinity, pressure)?;
    finite(finite(co2_ppm)? * 1e-6 * gas_pressure(pressure)? * per_atm * MG_CO2_PER_MMOL * 1000.0)
}

/// What a reading is multiplied by when the air is dried before the sensor (a mole fraction of dry air then, not of
/// the moist air the water saw): (pressure − the water's vapour pressure) / pressure, the pressure where the gas met
/// the water. 0.986 at 12 °C and 1 atm. Dried to a known dew point instead of fully: (P − p_w(water)) / (P − p_w(dew)).
/// A pressure at or below the water's vapour pressure (no air could be there) is refused (`Domain`).
pub fn dried_gas_factor(temp_c: f64, pressure: f64) -> R {
    let pressure = gas_pressure(pressure)?;
    let dry = pressure - vapour_pressure_atm(finite(temp_c)?)?;
    if dry <= 0.0 {
        return Err(ChemError::Domain);
    }
    finite(div(dry, pressure)?)
}

/// The total sulfide (in the unit of `free_h2s`, as H₂S) of a water whose un-ionised H₂S is `free_h2s`, at its pH
/// (NBS): free / the H₂S share. The one step of this module that needs a pH: 0.1 of a pH moves it by
/// 10^(0.1 (1 − share)) − 1, nothing where the share is near 1 (a low pH), about 15 % where it is 0.3, up to 26 % at a
/// high pH.
pub fn total_sulfide(free_h2s: f64, eq: &Equilibria, ph: f64) -> R {
    finite(div(finite(free_h2s)?, eq.h2s_share(finite(ph)?)?)?)
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
    /// The H₂S that `h2s_from_gas` gives from the leaving air, over the entering water's un-ionised H₂S, with its
    /// validity: below 1 by the H₂S that became HS⁻ as the pH rose, by the H₂S the air took, and by the air's
    /// saturation. None where H₂S's solubility does not hold (`h2s_validity`); the CO₂ above is given all the same.
    pub h2s_ratio: Option<Ranged>,
}

/// The steady state of a fully mixed vessel through which a water (its equilibria, its alkalinity in meq/L and its pH,
/// NBS) and air flow: `air_per_water` is the air's flow over the water's, both by volume at the vessel's temperature
/// and pressure (0.01 for 100 mL of air a minute to 10 L of water; a mass-flow controller's standard litres differ by
/// 1 to 5 %); `air_co2` the entering air's CO₂ as a mole fraction at that pressure (dry compressed air:
/// `chemistry::AIR_CO2`, a dry-air value, as it is; humid outdoor air: AIR_CO2 × (1 − its vapour pressure / P), about
/// 1 % less and negligible on the ratios); `pressure` in atm; `saturation_co2` and `saturation_h2s` how far the leaving
/// air has come to equilibrium with the vessel's water for each gas (above 0, up to 1). H₂S, three times as soluble,
/// comes nearer than CO₂ (`saturation_from_depths`); H₂S given CO₂'s saturation is the conservative choice (its
/// reading corrected upward more).
///
/// The balance of the DIC per litre of water: DIC in − DIC = air per water × CO₂'s saturation × (CO₂ of the vessel's
/// water × its gas over water − the entering air's CO₂), the alkalinity unchanged; the total sulfide likewise with
/// H₂S's saturation, its H₂S share at the vessel's pH. CO₂'s gas over water takes its fugacity
/// (`co2_per_partial_pressure`), so a reading of air in equilibrium is the water's own. None when no DIC between
/// nothing and the entering water's balances or no pH gives the alkalinity at an end of that search (a water that
/// cannot be). The CO₂ side needs nothing of H₂S's: where H₂S's solubility does not hold (below the water's freezing
/// point, above 30 °C, a salinity above 40) only `h2s_ratio` is None. The worst case of a contact: a counter-current
/// column or a closed headspace falls short by less.
#[allow(clippy::too_many_arguments)]
pub fn mixed_contact(
    eq: &Equilibria,
    alkalinity: f64,
    ph: f64,
    air_per_water: f64,
    air_co2: f64,
    pressure: f64,
    saturation_co2: f64,
    saturation_h2s: f64,
) -> Result<Option<Contact>, ChemError> {
    for value in [
        alkalinity,
        ph,
        air_per_water,
        air_co2,
        pressure,
        saturation_co2,
        saturation_h2s,
    ] {
        finite(value)?;
    }
    let saturation = |s: f64| 0.0 < s && s <= 1.0;
    if air_per_water < 0.0
        || air_co2 < 0.0
        || pressure <= 0.0
        || !saturation(saturation_co2)
        || !saturation(saturation_h2s)
    {
        return Err(ChemError::Domain);
    }
    let rt = GAS_CONSTANT * (eq.temp_c + KELVIN);
    let co2_over = gas_over_water(co2_per_partial_pressure(eq.temp_c, eq.salinity, pressure)?, eq.temp_c)?;
    let h2s_k0 = match k0_h2s(eq.temp_c, eq.salinity) {
        Ok(k0) => Some(k0),
        Err(ChemError::OutOfRange) => None,
        Err(other) => return Err(other),
    };
    let dic_in = eq.dic(alkalinity, ph)?;
    let co2_in = eq.co2(dic_in, ph)?;
    // the entering air's CO₂, mmol per litre of air
    let air = div(air_co2 * pressure * 1000.0, rt)?;
    let reach = air_per_water * saturation_co2;
    let (low, high) = (dic_in * 1e-9, dic_in + reach * air);
    if eq.ph_at(low, alkalinity)?.is_none() || eq.ph_at(high, alkalinity)?.is_none() {
        return Ok(None);
    }
    let mut balance = |dic: f64| -> R {
        let Some(ph_here) = eq.ph_at(dic, alkalinity)? else {
            return Err(ChemError::ImpossibleWater);
        };
        Ok(dic_in - dic - reach * (co2_over * eq.co2(dic, ph_here)? - air))
    };
    let Some(dic) = solve(&mut balance, low, high)? else {
        return Ok(None);
    };
    let Some(ph_here) = eq.ph_at(dic, alkalinity)? else {
        return Ok(None);
    };
    let leaving = air + saturation_co2 * (co2_over * eq.co2(dic, ph_here)? - air);
    let h2s_ratio = match h2s_k0 {
        Some(k0) => {
            let h2s_over = gas_over_water(k0.value, eq.temp_c)?;
            let share = eq.h2s_share(ph_here)?;
            // the vessel's total sulfide for an entering un-ionised H₂S of 1
            let sulfide = div(
                div(1.0, eq.h2s_share(ph)?)?,
                1.0 + air_per_water * saturation_h2s * h2s_over * share,
            )?;
            Some(Ranged {
                value: finite(saturation_h2s * sulfide * share)?,
                ..k0
            })
        }
        None => None,
    };
    Ok(Some(Contact {
        ph: ph_here,
        co2_gas: div(leaving * rt, 1000.0 * pressure)?,
        co2_ratio: div(div(leaving, co2_over)?, co2_in)?,
        h2s_ratio,
    }))
}

/// The most a contact with air can raise the pH of the water it leaves, whatever that water's pH and alkalinity:
/// log10(1 + H × air per water), H CO₂'s gas over water at the pressure (as `mixed_contact` takes it), the air taking
/// all the CO₂ it can hold (entering with none) and the bicarbonate unchanged; proved for every possible water, every
/// saturation and every entering CO₂ (science review, 2(d)). 0.0044 at 12 °C, 35 ‰, 1 atm and an air of 1 % of the
/// water. It bounds the H₂S share only, which falls by at most H r / (1 + H r) (r the air per water). The H₂S reading
/// also falls by the H₂S the air takes: at saturations of 1 the whole worst case is
/// h2s_ratio ≥ 1 / ((1 + H r)(1 + H_H₂S r)), H_H₂S H₂S's gas over water.
pub fn ph_rise_bound(temp_c: f64, salinity: f64, air_per_water: f64, pressure: f64) -> R {
    if finite(air_per_water)? < 0.0 {
        return Err(ChemError::Domain);
    }
    let over = gas_over_water(co2_per_partial_pressure(temp_c, salinity, pressure)?, temp_c)?;
    finite(log10(1.0 + over * air_per_water)?)
}

/// How far bubbles have come to equilibrium at the full depth of a vessel, for CO₂ and for H₂S (0 to 1 each), from the
/// CO₂ read with the air let in at half the depth over the CO₂ read with it let in at the full depth (each less the
/// entering air's CO₂; the same flows of air and water). With x = 1/ratio − 1 the CO₂ is 1 − x² short of nothing and
/// the H₂S 1 − x^(2 k), k = (K0 H₂S / K0 CO₂) (D H₂S / D CO₂)^n, CO₂'s per partial pressure at `pressure` (atm) as
/// everywhere in this module (`co2_per_partial_pressure`; second review, F3): a bubble fills with each gas at a rate in
/// proportion to its solubility times its liquid-film coefficient (science review, 2(e)). PROVISIONAL
/// (`H2S_OVER_CO2_DIFFUSIVITY`, `FILM_EXPONENT`), and the model leaves out H₂S's ionisation in the film (a faster H₂S),
/// the bubble's formation and the surface (not in proportion to the depth) and the hydrostatic pressure. What holds
/// whatever those turn out to be: the H₂S saturation is never below the CO₂'s, for which k ≥ 1 suffices (1 − x^(2k) ≥
/// 1 − x² for x in [0, 1]); k is 2.17 to 3.13 from 2 to 30 °C and 0 to 40 ‰ over the factor's stated range (a
/// property test). So taking CO₂'s for H₂S is the conservative choice. The CO₂ saturation needs no constant: where
/// H₂S's solubility does not hold the H₂S one is None. A ratio outside 0.5 to 1 is refused (`Domain`): no bubble reads
/// less at the full depth.
pub fn saturation_from_depths(
    ratio: f64,
    temp_c: f64,
    salinity: f64,
    pressure: f64,
) -> Result<(f64, Option<Ranged>), ChemError> {
    if !(0.5..=1.0).contains(&finite(ratio)?) {
        return Err(ChemError::Domain);
    }
    let short = div(1.0, ratio)? - 1.0;
    let per_atm = co2_per_partial_pressure(temp_c, salinity, pressure)?;
    let h2s = match k0_h2s(temp_c, salinity) {
        Ok(k0) => {
            let faster = div(k0.value, per_atm)? * pow(H2S_OVER_CO2_DIFFUSIVITY, FILM_EXPONENT)?;
            Some(Ranged {
                value: 1.0 - pow(short, 2.0 * faster)?,
                ..k0
            })
        }
        Err(ChemError::OutOfRange) => None,
        Err(other) => return Err(other),
    };
    Ok((1.0 - short * short, h2s))
}
