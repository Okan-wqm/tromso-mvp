//! The gas equilibration module against its reference: a Python mirror of the same operations in the same order over
//! formula 1's equilibria (golden v1), recorded 2026-11-27 with the PROVISIONAL solubility of H₂S (`k0_h2s`). The
//! numbers change when that constant is replaced by its source's; the relations do not.
use chemcore_core::chemistry as c;
use chemcore_core::num::ChemError;
use chemcore_experimental::gas_exchange as g;

fn close(got: Result<f64, ChemError>, want: f64) -> bool {
    got.is_ok_and(|x| (x - want).abs() <= 1e-7 * want.abs())
}

#[test]
fn the_solubilities_and_the_conversions() {
    assert!(close(g::k0_h2s(12.0, 35.0), 0.12569223744761449));
    assert!(close(g::k0_h2s(25.0, 0.0), 0.1013));
    let k0 = g::k0_h2s(12.0, 35.0).unwrap_or(f64::NAN);
    assert!(close(g::gas_over_water(k0, 12.0), 0.34001697138870374));
    let k0 = c::k0_co2(12.0, 35.0).unwrap_or(f64::NAN);
    assert!(close(g::gas_over_water(k0, 12.0), 1.0122273846962273));
    assert!(close(g::h2s_from_gas(117.0, 12.0, 35.0, 1.0), 0.5011931411818877)); // µg/L
    assert!(close(g::co2_from_gas(3852.0, 12.0, 35.0, 1.0), 7.157538328039449)); // mg/L
    assert!(close(g::dried_gas_factor(12.0, 1.0), 0.9861608398007197));
    assert_eq!(g::h2s_from_gas(f64::NAN, 12.0, 35.0, 1.0), Err(ChemError::NonFinite));
    assert_eq!(g::k0_h2s(-273.15, 0.0), Err(ChemError::ZeroDivision));
}

#[test]
fn the_total_sulfide_needs_the_ph() {
    let eq = c::equilibria(12.0, 35.0);
    assert!(close(
        eq.and_then(|eq| g::total_sulfide(0.5, &eq, 7.2)),
        1.5765892793905285
    ));
}

fn contact(air_per_water: f64, saturation: f64) -> Option<g::Contact> {
    let eq = c::equilibria(12.0, 35.0).ok()?;
    g::mixed_contact(&eq, 2.0, 7.2, air_per_water, c::AIR_CO2, 1.0, saturation)
        .ok()
        .flatten()
}

fn is(got: Option<g::Contact>, ph: f64, co2_gas: f64, co2_ratio: f64, h2s_ratio: f64) -> bool {
    got.is_some_and(|x| {
        (x.ph - ph).abs() < 1e-8
            && (x.co2_gas - co2_gas).abs() <= 1e-7 * co2_gas
            && (x.co2_ratio - co2_ratio).abs() <= 1e-7
            && (x.h2s_ratio - h2s_ratio).abs() <= 1e-7
    })
}

#[test]
fn a_mixed_vessel_reads_short_by_the_air_it_is_given() {
    // air 1 % of the water: the pH up 0.0034, the H₂S 0.6 % short
    assert!(is(
        contact(0.01, 1.0),
        7.2033679689666315,
        0.003851932145296956,
        0.9921289934110448,
        0.9936461112901878
    ));
    // air 10 % of the water: 5.9 % short
    assert!(is(
        contact(0.1, 1.0),
        7.232005364061479,
        0.0036014549240287338,
        0.9276144318779057,
        0.9407272232633087
    ));
    // bubbles 90 % saturated: the reading falls with them
    assert!(is(
        contact(0.01, 0.9),
        7.203032953362708,
        0.003511465154435521,
        0.9044360745870549,
        0.8948492208819272
    ));
    // no air: the water's own pH, and the reading the water's own
    assert!(is(contact(0.0, 1.0), 7.2, 0.0038824912593951088, 1.0, 1.0));
}

#[test]
fn a_contact_refuses_what_cannot_be() {
    let eq = c::equilibria(12.0, 35.0);
    let ask =
        |air: f64, saturation: f64| eq.and_then(|eq| g::mixed_contact(&eq, 2.0, 7.2, air, c::AIR_CO2, 1.0, saturation));
    assert_eq!(ask(-0.01, 1.0), Err(ChemError::Domain));
    assert_eq!(ask(0.01, 0.0), Err(ChemError::Domain));
    assert_eq!(ask(0.01, 1.1), Err(ChemError::Domain));
    assert_eq!(ask(f64::INFINITY, 1.0), Err(ChemError::NonFinite));
}

#[test]
fn the_bounds_need_no_ph() {
    assert!(close(g::ph_rise_bound(12.0, 35.0, 0.01), 0.0043739476864790815));
    // the vessel's own rise stays under the bound
    assert!(contact(0.01, 1.0).is_some_and(|x| x.ph - 7.2 < 0.0043739476864790815));
    let (co2, h2s) = g::saturation_from_depths(0.8, 12.0, 35.0).unwrap_or((f64::NAN, f64::NAN));
    assert!((co2 - 0.9375).abs() < 1e-12);
    assert!((h2s - 0.9997397768507817).abs() < 1e-9);
    assert_eq!(g::saturation_from_depths(1.0, 12.0, 35.0), Ok((1.0, 1.0)));
    assert_eq!(g::saturation_from_depths(0.4, 12.0, 35.0), Err(ChemError::Domain));
    assert_eq!(g::saturation_from_depths(1.01, 12.0, 35.0), Err(ChemError::Domain));
}
