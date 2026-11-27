//! The gas equilibration module against an independent implementation: the science review's of 2026-11-27
//! (reference/independent_check.py, written from the equations; it solves the vessel for its pH where the module solves
//! for its DIC), with the review's corrections C1 to C4, the second review's F3 and the cold-water decision applied as
//! reference/expected_values.py says, which printed every number here. Formula 1's equilibria (golden v1) unless a
//! test says formula 4 (golden v4's constants, the review's finding F1).
use chemcore_core::chemistry::{self as c, MG_CACO3_PER_MEQ};
use chemcore_core::fresh::{Ions, water_equilibria};
use chemcore_core::num::ChemError;
use chemcore_experimental::gas_exchange::{
    self as g,
    Validity::{Extrapolated, Measured},
};

fn close(got: Result<f64, ChemError>, want: f64) -> bool {
    got.is_ok_and(|x| (x - want).abs() <= 1e-7 * want.abs())
}

/// Douabul & Riley (1979), their 42 measurements as the IUPAC Solubility Data Series vol. 32 (1988), pp. 52–53,
/// tabulates them and the review lists them: T (K), S (g/kg), the solubility (mol/dm³ at an H₂S fugacity of 1 atm).
const DOUABUL_RILEY: [(f64, f64, f64); 42] = [
    (275.25, 9.972, 0.1910),
    (275.25, 20.014, 0.1878),
    (275.25, 24.958, 0.1862),
    (275.25, 29.993, 0.1846),
    (275.25, 34.994, 0.1831),
    (275.25, 40.028, 0.1816),
    (278.20, 9.972, 0.1741),
    (278.20, 20.014, 0.1714),
    (278.20, 24.958, 0.1701),
    (278.20, 29.993, 0.1688),
    (278.20, 34.994, 0.1675),
    (278.20, 40.028, 0.1662),
    (283.34, 9.972, 0.1496),
    (283.34, 20.014, 0.1476),
    (283.34, 24.958, 0.1466),
    (283.34, 29.993, 0.1456),
    (283.34, 34.994, 0.1447),
    (283.34, 40.028, 0.1437),
    (288.19, 9.972, 0.1299),
    (288.19, 20.014, 0.1284),
    (288.19, 24.958, 0.1276),
    (288.19, 29.993, 0.1269),
    (288.19, 34.994, 0.1262),
    (288.19, 40.028, 0.1255),
    (293.25, 9.972, 0.1143),
    (293.25, 20.014, 0.1131),
    (293.25, 24.958, 0.1126),
    (293.25, 29.993, 0.1120),
    (293.25, 34.994, 0.1114),
    (293.25, 40.028, 0.1108),
    (297.87, 9.972, 0.1013),
    (297.87, 20.014, 0.1004),
    (297.87, 24.958, 0.0999),
    (297.87, 29.993, 0.0995),
    (297.87, 34.994, 0.0990),
    (297.87, 40.028, 0.0986),
    (302.97, 9.972, 0.0907),
    (302.97, 20.014, 0.0898),
    (302.97, 24.958, 0.0894),
    (302.97, 29.993, 0.0891),
    (302.97, 34.994, 0.0887),
    (302.97, 40.028, 0.0884),
];

#[test]
fn the_h2s_solubility_is_douabul_and_rileys() {
    // every measurement within the authors' ±0.5 %, and within the 0.44 % the review found
    let mut worst = 0.0_f64;
    for (kelvin, salinity, measured) in DOUABUL_RILEY {
        let got = g::k0_h2s(kelvin - c::KELVIN, salinity);
        assert!(
            got.is_ok_and(|k0| ((k0.value - measured) / measured).abs() <= 0.005 && k0.validity == Measured),
            "{kelvin} K, S {salinity}: {got:?} against {measured}"
        );
        worst = worst.max(((value(got) - measured) / measured).abs());
    }
    assert!(worst <= 0.0044, "worst deviation {worst}");
    assert!(close(g::k0_h2s(12.0, 35.0).map(|x| x.value), 0.1372513877665758));
    assert!(close(g::k0_h2s(25.0, 0.0).map(|x| x.value), 0.1019504857840442));
    // the corners of the measured range
    for (temp_c, salinity, want) in [
        (2.0, 0.0, 0.19507990370865505),
        (2.0, 40.0, 0.18228729585575598),
        (30.0, 0.0, 0.09077570549507918),
        (30.0, 40.0, 0.0878610504504237),
    ] {
        let got = g::k0_h2s(temp_c, salinity);
        assert!(got.is_ok_and(|x| x.validity == Measured), "{got:?}");
        assert!(close(got.map(|x| x.value), want));
    }
    // refused above 30 °C, below the water's freezing point and outside the salinities measured
    for (temp_c, salinity) in [
        (30.01, 0.0),
        (-0.01, 0.0),
        (-1.93, 35.0),
        (12.0, -0.01),
        (12.0, 40.03),
        (-273.15, 0.0),
    ] {
        assert_eq!(
            g::k0_h2s(temp_c, salinity),
            Err(ChemError::OutOfRange),
            "{temp_c} °C, S {salinity}"
        );
    }
    assert_eq!(g::k0_h2s(f64::NAN, 35.0), Err(ChemError::NonFinite));
}

fn value(got: Result<g::Ranged, ChemError>) -> f64 {
    got.map_or(f64::NAN, |x| x.value)
}

/// Below 2 °C (decided after the second review): Douabul & Riley's equation down to the water's freezing point, said
/// as extrapolated; its pure-water part within 0.6 % of IUPAC's low-temperature equation (SDS-32 p. 1), as the review
/// found (−0.58 % at 0 °C, −0.54 % at −1.9 °C).
#[test]
fn below_2_c_the_h2s_solubility_is_extrapolated_to_freezing() {
    assert_eq!(g::freezing_point(0.0), Ok(0.0));
    assert!(close(g::freezing_point(35.0), -1.9223013411410586));
    assert!(close(g::freezing_point(40.0), -2.2120674663916646));
    assert_eq!(g::freezing_point(-1.0), Err(ChemError::Domain));
    for (temp_c, salinity, want) in [
        (0.0, 35.0, 0.19579976004897018),
        (-1.9, 35.0, 0.2081957355641334),
        (1.0, 35.0, 0.18968724530554448),
        (0.0, 0.0, 0.20849267180604414),
    ] {
        let got = g::k0_h2s(temp_c, salinity);
        assert!(
            got.is_ok_and(|x| x.validity == Extrapolated),
            "{temp_c} °C S {salinity}: {got:?}"
        );
        assert!(close(got.map(|x| x.value), want), "{temp_c} °C S {salinity}: {got:?}");
    }
    assert_eq!(g::h2s_validity(1.99, 35.0), Ok(Extrapolated));
    assert_eq!(g::h2s_validity(2.0, 35.0), Ok(Measured));
    assert_eq!(g::h2s_validity(30.0, 40.028), Ok(Measured));
    assert_eq!(g::h2s_validity(-1.92, 35.0), Ok(Extrapolated));
    assert_eq!(g::h2s_validity(-1.93, 35.0), Err(ChemError::OutOfRange));
    assert_eq!(g::h2s_validity(30.01, 35.0), Err(ChemError::OutOfRange));
    // the pure-water part against IUPAC: at 0 °C directly, at −1.9 °C (fresh water is ice there) through S 35 less its
    // salinity term
    let pure_0 = value(g::k0_h2s(0.0, 0.0)) / 0.20971382121903376 - 1.0;
    assert!((-0.0059..=-0.0057).contains(&pure_0), "{pure_0}");
    let x = (-1.9 + c::KELVIN) / 100.0;
    let [b1, b2, b3] = g::K0_H2S_B;
    let salting = (35.0 * (b1 + b2 * x + b3 * x * x)).exp();
    let pure_minus_1_9 = value(g::k0_h2s(-1.9, 35.0)) / salting / 0.22365983797444622 - 1.0;
    assert!((-0.0055..=-0.0053).contains(&pure_minus_1_9), "{pure_minus_1_9}");
    // every H₂S result says it
    assert!(g::h2s_from_gas(117.0, 1.0, 35.0, 1.0).is_ok_and(|x| x.validity == Extrapolated));
    assert!(g::h2s_from_gas(117.0, 12.0, 35.0, 1.0).is_ok_and(|x| x.validity == Measured));
}

#[test]
fn the_solubilities_and_the_conversions() {
    let k0 = value(g::k0_h2s(12.0, 35.0));
    assert!(close(g::gas_over_water(k0, 12.0), 0.3113811419911722));
    let k0 = c::k0_co2(12.0, 35.0).unwrap_or(f64::NAN);
    assert!(close(g::gas_over_water(k0, 12.0), 1.0122273837161964));
    assert!(close(
        g::h2s_from_gas(117.0, 12.0, 35.0, 1.0).map(|x| x.value),
        0.5472848249278183
    )); // µg/L
    assert!(close(g::dried_gas_factor(12.0, 1.0), 0.9861608398007197));
    assert_eq!(g::h2s_from_gas(f64::NAN, 12.0, 35.0, 1.0), Err(ChemError::NonFinite));
}

#[test]
fn the_co2_conversion_takes_the_fugacity() {
    assert!(close(g::co2_fugacity_coefficient(5.0, 1.0), 0.9958898969240669));
    assert!(close(g::co2_fugacity_coefficient(12.0, 1.0), 0.9962480968397126));
    assert!(close(g::co2_fugacity_coefficient(20.0, 1.0), 0.9966083945861017));
    assert!(close(g::co2_fugacity_coefficient(12.0, 2.0), 0.9925102704567494));
    let with = g::co2_from_gas(3852.0, 12.0, 35.0, 1.0);
    assert!(close(with, 7.1306839373666)); // mg/L
    // the partial pressure alone gave 7.1575: 0.37 % more
    let effect = with.unwrap_or(f64::NAN) / 7.157538328039449 - 1.0;
    assert!((-0.0038..=-0.0037).contains(&effect), "{effect}");
}

#[test]
fn the_total_sulfide_needs_the_ph() {
    let eq = c::equilibria(12.0, 35.0);
    assert!(close(
        eq.and_then(|eq| g::total_sulfide(0.5, &eq, 7.2)),
        1.5765892793905285
    ));
    // formula 4 (F1): the H₂S share of pH 7.2 is 5.3 % less, the total sulfide 5.6 % more
    let eq = water_equilibria(4, 12.0, 35.0, Some(200.0), Ions::default());
    assert!(close(
        eq.and_then(|eq| g::total_sulfide(0.5, &eq, 7.2)),
        1.6653942428024509
    ));
}

fn contact_at(
    formula: u32,
    temp_c: f64,
    air_per_water: f64,
    saturation_co2: f64,
    saturation_h2s: f64,
) -> Option<g::Contact> {
    let eq = water_equilibria(formula, temp_c, 35.0, Some(200.0), Ions::default()).ok()?;
    g::mixed_contact(
        &eq,
        2.0,
        7.2,
        air_per_water,
        c::AIR_CO2,
        1.0,
        saturation_co2,
        saturation_h2s,
    )
    .ok()
    .flatten()
}

fn contact(formula: u32, air_per_water: f64, saturation_co2: f64, saturation_h2s: f64) -> Option<g::Contact> {
    contact_at(formula, 12.0, air_per_water, saturation_co2, saturation_h2s)
}

fn h2s(contact: &g::Contact) -> f64 {
    contact.h2s_ratio.map_or(f64::NAN, |x| x.value)
}

fn is_co2(got: Option<g::Contact>, ph: f64, co2_gas: f64, co2_ratio: f64) -> bool {
    got.is_some_and(|x| {
        (x.ph - ph).abs() < 1e-8
            && (x.co2_gas - co2_gas).abs() <= 1e-7 * co2_gas
            && (x.co2_ratio - co2_ratio).abs() <= 1e-7
    })
}

fn is(got: Option<g::Contact>, ph: f64, co2_gas: f64, co2_ratio: f64, h2s_ratio: f64) -> bool {
    is_co2(got, ph, co2_gas, co2_ratio)
        && got
            .is_some_and(|x| (h2s(&x) - h2s_ratio).abs() <= 1e-7 && x.h2s_ratio.is_some_and(|h| h.validity == Measured))
}

#[test]
fn a_mixed_vessel_reads_short_by_the_air_it_is_given() {
    // air 1 % of the water: the pH up 0.0034, the H₂S 0.6 % short
    assert!(is(
        contact(1, 0.01, 1.0, 1.0),
        7.2033821212367215,
        0.0038663102567234615,
        0.9920960480067164,
        0.9937136394922534
    ));
    // air 10 % of the water: 5.9 % short
    assert!(is(
        contact(1, 0.1, 1.0, 1.0),
        7.232134322060043,
        0.003613923053279545,
        0.9273334370215407,
        0.9413381162281969
    ));
    // bubbles 90 % saturated with CO₂ and H₂S given the same: the conservative choice, H₂S's reading 10.5 % short
    assert!(is(
        contact(1, 0.01, 0.9, 0.9),
        7.203045704103651,
        0.0035244270846338703,
        0.9043687521125877,
        0.8949039824038976
    ));
    // the same bubbles with H₂S as near as the bubble model brings it (0.9975): the CO₂ side unchanged
    assert!(is(
        contact(1, 0.01, 0.9, 0.9975),
        7.203045704103651,
        0.0035244270846338703,
        0.9043687521125877,
        0.9917569654532955
    ));
    // no air: the water's own pH, and the reading the water's own
    assert!(is(contact(1, 0.0, 1.0, 1.0), 7.2, 0.003897112849599101, 1.0, 1.0));
}

#[test]
fn formula_4_moves_the_co2_ratio_by_up_to_two_permil() {
    assert!(is(
        contact(4, 0.01, 1.0, 1.0),
        7.2032769551952605,
        0.0035669734905498,
        0.9923294656417763,
        0.9938037074528514
    ));
    let (one, four) = (contact(1, 0.1, 1.0, 1.0), contact(4, 0.1, 1.0, 1.0));
    assert!(is(
        four,
        7.231123629311229,
        0.0033408895614940007,
        0.9294330788016392,
        0.9422067598709907
    ));
    assert!(is(
        contact(4, 0.01, 0.9, 0.9),
        7.20295101179881,
        0.0032547359764031397,
        0.9054652132475948,
        0.8949769647372665
    ));
    // F1: the author expected under 1 ‰ for both ratios; the CO₂ ratio moves 2.1 ‰, the H₂S ratio 0.87 ‰
    let moved = |pick: fn(&g::Contact) -> f64| match (one, four) {
        (Some(one), Some(four)) => pick(&four) - pick(&one),
        _ => f64::NAN,
    };
    assert!((0.0020..=0.0022).contains(&moved(|x| x.co2_ratio)));
    assert!((0.0008..=0.0010).contains(&moved(h2s)));
    // a fresh water of 200 mg/L as CaCO₃ by formula 4
    let fresh = water_equilibria(4, 12.0, 0.0, Some(200.0), Ions::default()).ok();
    let got = fresh.and_then(|eq| {
        g::mixed_contact(&eq, 200.0 / MG_CACO3_PER_MEQ, 7.2, 0.01, c::AIR_CO2, 1.0, 1.0, 1.0)
            .ok()
            .flatten()
    });
    assert!(is(
        got,
        7.203559109920308,
        0.013037458687274833,
        0.9918272399850134,
        0.9943135982147704
    ));
}

/// The CO₂ half never waits on H₂S's constants (second review, F2): at 0 °C, S 35 both, the H₂S said as extrapolated;
/// at 32 °C and below the water's freezing point the CO₂ alone.
#[test]
fn the_co2_side_never_waits_on_h2s() {
    let cold = contact_at(1, 0.0, 0.01, 1.0, 1.0);
    assert!(is_co2(
        cold,
        7.202471687057345,
        0.0036364044889449936,
        0.9942572524632886
    ));
    assert!(cold.is_some_and(|x| {
        x.h2s_ratio
            .is_some_and(|h| (h.value - 0.9958685257815352).abs() <= 1e-7 && h.validity == Extrapolated)
    }));
    let warm = contact_at(1, 32.0, 0.01, 1.0, 1.0);
    assert!(is_co2(
        warm,
        7.204235380116378,
        0.004067955419458513,
        0.9899172253638129
    ));
    assert!(warm.is_some_and(|x| x.h2s_ratio.is_none()));
    let ice = contact_at(1, -2.5, 0.01, 1.0, 1.0);
    assert!(
        ice.is_some_and(|x| x.h2s_ratio.is_none() && x.co2_ratio < 1.0),
        "{ice:?}"
    );
}

#[test]
fn a_contact_refuses_what_cannot_be() {
    let eq = c::equilibria(12.0, 35.0);
    let ask = |air: f64, co2: f64, h2s: f64| {
        eq.and_then(|eq| g::mixed_contact(&eq, 2.0, 7.2, air, c::AIR_CO2, 1.0, co2, h2s))
    };
    assert_eq!(ask(-0.01, 1.0, 1.0), Err(ChemError::Domain));
    assert_eq!(ask(0.01, 0.0, 1.0), Err(ChemError::Domain));
    assert_eq!(ask(0.01, 1.1, 1.0), Err(ChemError::Domain));
    assert_eq!(ask(0.01, 1.0, 0.0), Err(ChemError::Domain));
    assert_eq!(ask(0.01, 1.0, 1.1), Err(ChemError::Domain));
    assert_eq!(ask(f64::INFINITY, 1.0, 1.0), Err(ChemError::NonFinite));
    // no pH gives 2000 meq/L at the lower end of the DIC searched (it would take over pH 14): None, as documented, not
    // an error (the review's minor finding)
    assert_eq!(
        eq.and_then(|eq| g::mixed_contact(&eq, 2000.0, 7.2, 0.01, c::AIR_CO2, 1.0, 1.0, 1.0)),
        Ok(None)
    );
}

#[test]
fn the_bounds_need_no_ph() {
    assert!(close(g::ph_rise_bound(12.0, 35.0, 0.01, 1.0), 0.004390337131769065));
    // the vessel's own rise stays under the bound
    assert!(contact(1, 0.01, 1.0, 1.0).is_some_and(|x| x.ph - 7.2 < 0.004390337131769065));
    // the whole worst case of the H₂S reading at saturations of 1, air 10 % of the water
    assert!(contact(1, 0.1, 1.0, 1.0).is_some_and(|x| h2s(&x) >= 0.8803546789606475));
}

#[test]
fn the_depths_give_the_saturations() {
    let h2s_of = |got: Result<(f64, Option<g::Ranged>), ChemError>| match got {
        Ok((co2, Some(h2s))) => (co2, h2s.value, Some(h2s.validity)),
        Ok((co2, None)) => (co2, f64::NAN, None),
        Err(_) => (f64::NAN, f64::NAN, None),
    };
    // the CO₂ solubility per partial pressure in the exponent (F3)
    let (co2, h2s, validity) = h2s_of(g::saturation_from_depths(0.8, 12.0, 35.0, 1.0));
    assert!((co2 - 0.9375).abs() < 1e-12 && (h2s - 0.9992635601293581).abs() < 1e-9 && validity == Some(Measured));
    let (co2, h2s, _) = h2s_of(g::saturation_from_depths(0.55, 12.0, 35.0, 1.0));
    assert!((co2 - 0.33057851239669434).abs() < 1e-12 && (h2s - 0.6480282902733643).abs() < 1e-9);
    assert_eq!(
        h2s_of(g::saturation_from_depths(1.0, 12.0, 35.0, 1.0)),
        (1.0, 1.0, Some(Measured))
    );
    assert_eq!(
        h2s_of(g::saturation_from_depths(0.8, 1.0, 35.0, 1.0)).2,
        Some(Extrapolated)
    );
    let (co2, _, validity) = h2s_of(g::saturation_from_depths(0.8, 31.0, 35.0, 1.0));
    assert!((co2 - 0.9375).abs() < 1e-12 && validity.is_none());
    assert_eq!(g::saturation_from_depths(0.4, 12.0, 35.0, 1.0), Err(ChemError::Domain));
    assert_eq!(g::saturation_from_depths(1.01, 12.0, 35.0, 1.0), Err(ChemError::Domain));
    assert_eq!(g::saturation_from_depths(0.8, 12.0, 35.0, 0.0), Err(ChemError::Domain));
}
