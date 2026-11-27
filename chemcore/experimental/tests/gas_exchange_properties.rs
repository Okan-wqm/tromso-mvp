//! Properties of the gas equilibration module over grids, beyond the point values of tests/gas_exchange.rs: what must
//! hold for every water, whatever a constant turns out to be once read in its source. Plain loops, no dependency. A
//! tolerance is the solvers' (`chemistry::solve`: a bracket under 1e-10, its midpoint returned), never a loosened
//! physics. Each test gathers every failure and reports them together.
use chemcore_core::chemistry::{AIR_CO2, Equilibria, KELVIN, MG_CACO3_PER_MEQ};
use chemcore_core::fresh::{Ions, water_equilibria};
use chemcore_core::num::ChemError;
use chemcore_experimental::gas_exchange as g;

/// The vessel's pH comes from a bisection whose bracket is under 1e-10 (its midpoint: under 5e-11 off); a share of the
/// pH moves by at most ln 10 times as much. 2e-10 holds every ratio and pH to that.
const SOLVED: f64 = 2e-10;

/// 0 °C: H₂S's solubility extrapolated (fresh water at its freezing point, sea water above its).
const TEMPS: [f64; 5] = [0.0, 2.0, 10.0, 20.0, 30.0];
/// The fresh path, the band between (1 to 5 ‰) and the sea path.
const SALINITIES: [f64; 7] = [0.0, 0.5, 3.0, 5.0, 20.0, 35.0, 40.0];
const PHS: [f64; 6] = [6.0, 6.5, 7.0, 7.5, 8.0, 8.5];
const ALKALINITIES: [f64; 4] = [0.5, 1.0, 2.0, 5.0];
/// Increasing.
const AIRS: [f64; 5] = [0.0, 0.001, 0.01, 0.1, 0.5];
/// (CO₂, H₂S): the same, and H₂S nearer (as it comes, `saturation_from_depths`).
const SATURATIONS: [(f64, f64); 5] = [(0.1, 0.1), (0.1, 1.0), (0.5, 0.5), (0.5, 1.0), (1.0, 1.0)];

fn report(failures: &[String], checked: usize) {
    let shown: Vec<&String> = failures.iter().take(20).collect();
    assert!(
        failures.is_empty(),
        "{} of {checked} failed, the first: {shown:#?}",
        failures.len()
    );
}

/// Every property of `mixed_contact` over the grid, by one formula's equilibria; the entering air without CO₂ and with
/// the outdoor air's.
fn the_contact_holds_by(formula: u32) {
    let (mut failures, mut checked) = (Vec::new(), 0_usize);
    for temp_c in TEMPS {
        for salinity in SALINITIES {
            for alkalinity in ALKALINITIES {
                let Ok(eq) = water_equilibria(
                    formula,
                    temp_c,
                    salinity,
                    Some(alkalinity * MG_CACO3_PER_MEQ),
                    Ions::default(),
                ) else {
                    failures.push(format!("formula {formula}: no equilibria at {temp_c} °C, S {salinity}"));
                    continue;
                };
                for ph in PHS {
                    for air_co2 in [0.0, AIR_CO2] {
                        for (saturation_co2, saturation_h2s) in SATURATIONS {
                            let water = Water {
                                eq: &eq,
                                alkalinity,
                                ph,
                                air_co2,
                                saturation_co2,
                                saturation_h2s,
                            };
                            checked += water.check(&mut failures);
                        }
                    }
                }
            }
        }
    }
    report(&failures, checked);
}

struct Water<'a> {
    eq: &'a Equilibria,
    alkalinity: f64,
    ph: f64,
    air_co2: f64,
    saturation_co2: f64,
    saturation_h2s: f64,
}

impl Water<'_> {
    /// The properties along the increasing airs; how many contacts were checked.
    fn check(&self, failures: &mut Vec<String>) -> usize {
        let (eq, alkalinity, ph) = (self.eq, self.alkalinity, self.ph);
        let (temp_c, salinity) = (eq.temp_c, eq.salinity);
        let what = |air: f64| {
            format!(
                "formula {} {temp_c} °C S {salinity} pH {ph} alk {alkalinity} air {air} air CO₂ {} s {}/{}",
                eq.formula, self.air_co2, self.saturation_co2, self.saturation_h2s
            )
        };
        let (Ok(dic_in), Ok(per_atm), Ok(k0_h2s)) = (
            eq.dic(alkalinity, ph),
            g::co2_per_partial_pressure(temp_c, salinity, 1.0),
            g::k0_h2s(temp_c, salinity).map(|x| x.value),
        ) else {
            failures.push(format!("{}: not a water of the grid", what(0.0)));
            return 0;
        };
        let rt = g::GAS_CONSTANT * (temp_c + KELVIN);
        let (co2_over, h2s_over) = (1.0 / (per_atm * rt), 1.0 / (k0_h2s * rt));
        let co2_in = eq.co2(dic_in, ph).unwrap_or(f64::NAN);
        // the water holds more CO₂ than the entering air would leave in it: the air takes CO₂ (module note)
        let above_air = co2_over * co2_in > self.air_co2 * 1000.0 / rt;
        let mut last: Option<g::Contact> = None;
        let mut checked = 0;
        for air in AIRS {
            let got = g::mixed_contact(
                eq,
                alkalinity,
                ph,
                air,
                self.air_co2,
                1.0,
                self.saturation_co2,
                self.saturation_h2s,
            );
            let Ok(Some(contact)) = got else {
                failures.push(format!("{}: no contact, {got:?}", what(air)));
                continue;
            };
            checked += 1;
            let rise = contact.ph - ph;
            let bound = g::ph_rise_bound(temp_c, salinity, air, 1.0).unwrap_or(f64::NAN);
            let mut fail = |holds: bool, property: &str| {
                if !holds {
                    failures.push(format!("{}: {property}: {contact:?}", what(air)));
                }
            };
            fail(
                contact.h2s_ratio.map(|x| x.validity) == g::h2s_validity(temp_c, salinity).ok(),
                "the H₂S ratio without the validity of its water",
            );
            // every water
            fail(contact.co2_ratio > 0.0 && h2s(&contact) > 0.0, "a ratio at or below 0");
            fail(
                rise <= bound + SOLVED,
                &format!("the pH rose {rise}, over the bound {bound}"),
            );
            if self.saturation_co2 == 1.0 && self.saturation_h2s == 1.0 {
                let floor = 1.0 / ((1.0 + air * co2_over) * (1.0 + air * h2s_over));
                fail(
                    h2s(&contact) >= floor - SOLVED,
                    &format!("H₂S under its worst case {floor}"),
                );
            }
            // the mass balance: the DIC the water lost is the CO₂ the air carried away (mmol per litre of water)
            let lost = dic_in - eq.dic(alkalinity, contact.ph).unwrap_or(f64::NAN);
            let carried = air * (contact.co2_gas - self.air_co2) * 1000.0 / rt;
            fail(
                (lost - carried).abs() <= 1e-9 * dic_in,
                &format!("DIC lost {lost}, carried {carried}"),
            );
            if air == 0.0 && self.air_co2 == 0.0 {
                fail(
                    (contact.co2_ratio - self.saturation_co2).abs() <= SOLVED
                        && (h2s(&contact) - self.saturation_h2s).abs() <= SOLVED
                        && rise.abs() <= SOLVED,
                    "no air, yet not the saturations and the water's own pH",
                );
            }
            // a water the air takes CO₂ from: the readings fall short, more with more air, and the pH rises
            if above_air {
                fail(
                    contact.co2_ratio <= 1.0 + SOLVED && h2s(&contact) <= 1.0 + SOLVED,
                    "a ratio above 1",
                );
                fail(rise >= -SOLVED, "the pH fell");
                if let Some(before) = last {
                    fail(
                        contact.co2_ratio < before.co2_ratio && h2s(&contact) < h2s(&before),
                        &format!("a ratio did not fall with more air: before {before:?}"),
                    );
                }
            }
            last = Some(contact);
        }
        checked
    }
}

/// The H₂S reading ratio of a contact, NaN where it has none.
fn h2s(contact: &g::Contact) -> f64 {
    contact.h2s_ratio.map_or(f64::NAN, |x| x.value)
}

#[test]
fn the_contact_holds_by_formula_1() {
    the_contact_holds_by(1);
}

#[test]
fn the_contact_holds_by_formula_3() {
    the_contact_holds_by(3);
}

#[test]
fn the_contact_holds_by_formula_4() {
    the_contact_holds_by(4);
}

/// A water holding less CO₂ than the entering air would leave (pH 8.5, 0.5 meq/L, 2 °C, fresh, formula 4): the air
/// gives CO₂, the pH falls and both readings lie above the truth (module note). Not a fault: what the model says.
#[test]
fn a_water_below_the_air_takes_co2_from_it() {
    let eq = water_equilibria(4, 2.0, 0.0, Some(0.5 * MG_CACO3_PER_MEQ), Ions::default());
    let got = eq.and_then(|eq| g::mixed_contact(&eq, 0.5, 8.5, 0.5, AIR_CO2, 1.0, 1.0, 1.0));
    assert!(
        got.is_ok_and(|x| x.is_some_and(|x| x.ph < 8.5 && x.co2_ratio > 1.0 && h2s(&x) > 1.0)),
        "{got:?}"
    );
}

const READINGS: [f64; 6] = [0.5, 1.0, 117.0, 1000.0, 3852.0, 1e5];
const PRESSURES: [f64; 5] = [0.5, 0.8, 1.0, 1.2, 2.0];

/// h2s_from_gas is linear in the reading and in the pressure; co2_from_gas in the reading, and in the pressure but for
/// the fugacity coefficient (which moves with the pressure).
#[test]
fn the_conversions_are_linear() {
    let (mut failures, mut checked) = (Vec::new(), 0_usize);
    let near = |a: f64, b: f64| (a - b).abs() <= 1e-14 * b.abs();
    for temp_c in [0.0, 2.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0] {
        for salinity in [0.0, 5.0, 20.0, 35.0, 40.0] {
            let h2s_unit = g::h2s_from_gas(1.0, temp_c, salinity, 1.0).map_or(f64::NAN, |x| x.value);
            let co2_unit = g::co2_from_gas(1.0, temp_c, salinity, 1.0).unwrap_or(f64::NAN)
                / g::co2_fugacity_coefficient(temp_c, 1.0).unwrap_or(f64::NAN);
            for reading in READINGS {
                for pressure in PRESSURES {
                    checked += 1;
                    let h2s = g::h2s_from_gas(reading, temp_c, salinity, pressure).map_or(f64::NAN, |x| x.value);
                    let co2 = g::co2_from_gas(reading, temp_c, salinity, pressure).unwrap_or(f64::NAN);
                    let fugacity = g::co2_fugacity_coefficient(temp_c, pressure).unwrap_or(f64::NAN);
                    let twice_h2s =
                        g::h2s_from_gas(2.0 * reading, temp_c, salinity, pressure).map_or(f64::NAN, |x| x.value);
                    let twice_co2 = g::co2_from_gas(2.0 * reading, temp_c, salinity, pressure).unwrap_or(f64::NAN);
                    if !(near(h2s, reading * pressure * h2s_unit)
                        && near(co2, reading * pressure * fugacity * co2_unit)
                        && twice_h2s == 2.0 * h2s
                        && twice_co2 == 2.0 * co2)
                    {
                        failures.push(format!(
                            "{temp_c} °C S {salinity} reading {reading} P {pressure}: {h2s} {co2}"
                        ));
                    }
                }
            }
            if g::h2s_from_gas(0.0, temp_c, salinity, 1.0).map(|x| x.value) != Ok(0.0)
                || g::co2_from_gas(0.0, temp_c, salinity, 1.0) != Ok(0.0)
            {
                failures.push(format!("{temp_c} °C S {salinity}: no gas, yet not 0"));
            }
        }
    }
    report(&failures, checked);
}

/// The dried-gas factor and the fugacity coefficient lie in (0, 1); the factor falls as the water warms (its vapour
/// pressure rises) and rises with the pressure; the coefficient falls with the pressure.
#[test]
fn the_factors_lie_between_0_and_1() {
    let (mut failures, mut checked) = (Vec::new(), 0_usize);
    for step in 0..=30 {
        let temp_c = f64::from(step);
        let mut last: Option<(f64, f64)> = None;
        for pressure in PRESSURES {
            checked += 1;
            let dried = g::dried_gas_factor(temp_c, pressure).unwrap_or(f64::NAN);
            let fugacity = g::co2_fugacity_coefficient(temp_c, pressure).unwrap_or(f64::NAN);
            let warmer = g::dried_gas_factor(temp_c + 1.0, pressure).unwrap_or(f64::NAN);
            let inside = |x: f64| 0.0 < x && x < 1.0;
            let ordered = last.is_none_or(|(d, f)| dried > d && fugacity < f);
            if !(inside(dried) && inside(fugacity) && warmer < dried && ordered) {
                failures.push(format!(
                    "{temp_c} °C, {pressure} atm: dried {dried}, fugacity {fugacity}"
                ));
            }
            last = Some((dried, fugacity));
        }
    }
    report(&failures, checked);
}

/// The depth test: both saturations in [0, 1], rising with the ratio, H₂S's never below CO₂'s (its exponent over 2,
/// whatever the provisional diffusivity factor within its stated range).
#[test]
fn the_depth_test_saturations_are_ordered() {
    let (mut failures, mut checked) = (Vec::new(), 0_usize);
    let (mut least, mut most) = (f64::INFINITY, 0.0_f64);
    for step in 2..=30 {
        let temp_c = f64::from(step);
        for salinity in [0.0, 5.0, 10.0, 20.0, 30.0, 35.0, 40.0] {
            let solubility = g::k0_h2s(temp_c, salinity).map_or(f64::NAN, |x| x.value)
                / g::co2_per_partial_pressure(temp_c, salinity, 1.0).unwrap_or(f64::NAN);
            // the stated ranges: D ratio 0.71 to 0.80, n 1/2 to 2/3
            for factor in [0.71_f64.powf(2.0 / 3.0), 0.80_f64.powf(0.5)] {
                let exponent = solubility * factor;
                least = least.min(exponent);
                most = most.max(exponent);
                if exponent.is_nan() || exponent <= 2.0 {
                    failures.push(format!("{temp_c} °C S {salinity}: exponent {exponent}"));
                }
            }
            let mut last = (-1.0, -1.0);
            for tenth in 0..=50 {
                checked += 1;
                let ratio = 0.5 + f64::from(tenth) / 100.0;
                let got = g::saturation_from_depths(ratio, temp_c, salinity, 1.0);
                let Ok((co2, Some(g::Ranged { value: h2s, .. }))) = got else {
                    failures.push(format!("{temp_c} °C S {salinity} ratio {ratio}: {got:?}"));
                    continue;
                };
                if !((0.0..=1.0).contains(&co2)
                    && (0.0..=1.0).contains(&h2s)
                    && h2s >= co2
                    && co2 > last.0
                    && h2s >= last.1)
                {
                    failures.push(format!(
                        "{temp_c} °C S {salinity} ratio {ratio}: {co2} {h2s} after {last:?}"
                    ));
                }
                last = (co2, h2s);
            }
        }
    }
    eprintln!("depth test: k = (K0 H2S / K0 CO2) (D ratio)^n from {least} to {most}");
    report(&failures, checked);
}

/// Every function refuses NaN and ±∞ in every argument, and the inputs out of its domain.
#[test]
fn the_functions_refuse_what_is_not_a_number_or_out_of_domain() {
    let mut failures = Vec::new();
    let Ok(eq) = water_equilibria(4, 12.0, 35.0, Some(200.0), Ions::default()) else {
        report(&["no equilibria".into()], 0);
        return;
    };
    let mut refused = |what: String, got: Result<f64, ChemError>| {
        if got.is_ok() {
            failures.push(format!("{what}: {got:?}"));
        }
    };
    for bad in [f64::NAN, f64::INFINITY, f64::NEG_INFINITY] {
        refused(
            format!("saturation_from_depths ratio {bad}"),
            g::saturation_from_depths(bad, 12.0, 35.0, 1.0).map(|x| x.0),
        );
        let args = |i: usize, n: usize| -> Vec<f64> {
            let good = [12.0, 35.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0];
            (0..n)
                .map(|j| {
                    if j == i {
                        bad
                    } else {
                        good.get(j).copied().unwrap_or(1.0)
                    }
                })
                .collect()
        };
        for i in 0..2 {
            let a = args(i, 2);
            let (x, y) = (a.first().copied().unwrap_or(1.0), a.get(1).copied().unwrap_or(1.0));
            refused(format!("k0_h2s {a:?}"), g::k0_h2s(x, y).map(|x| x.value));
            refused(format!("h2s_validity {a:?}"), g::h2s_validity(x, y).map(|_| 0.0));
            if i == 1 {
                refused(format!("freezing_point {a:?}"), g::freezing_point(y));
            }
            refused(format!("gas_over_water {a:?}"), g::gas_over_water(y, x));
            refused(
                format!("co2_fugacity_coefficient {a:?}"),
                g::co2_fugacity_coefficient(x, y),
            );
            refused(format!("dried_gas_factor {a:?}"), g::dried_gas_factor(x, y));
            refused(
                format!("total_sulfide {a:?}"),
                g::total_sulfide(if i == 0 { bad } else { 1.0 }, &eq, if i == 1 { bad } else { 7.2 }),
            );
            refused(
                format!("saturation_from_depths (t, S) {a:?}"),
                g::saturation_from_depths(0.8, x, y, 1.0).map(|x| x.0),
            );
        }
        for i in 0..3 {
            let a = args(i, 3);
            let at = |j: usize| a.get(j).copied().unwrap_or(1.0);
            refused(
                format!("co2_per_partial_pressure {a:?}"),
                g::co2_per_partial_pressure(at(0), at(1), at(2)),
            );
        }
        for i in 0..4 {
            let a = args(i, 4);
            let at = |j: usize| a.get(j).copied().unwrap_or(1.0);
            // (reading, temperature, salinity, pressure)
            let reading = [at(2), at(0), at(1), at(3)];
            let [r, t, s, p] = reading;
            refused(
                format!("h2s_from_gas {reading:?}"),
                g::h2s_from_gas(r, t, s, p).map(|x| x.value),
            );
            if i == 3 {
                refused(
                    format!("saturation_from_depths (P) {a:?}"),
                    g::saturation_from_depths(0.8, t, s, p).map(|x| x.0),
                );
            }
            refused(format!("co2_from_gas {reading:?}"), g::co2_from_gas(r, t, s, p));
            refused(
                format!("ph_rise_bound {a:?}"),
                g::ph_rise_bound(at(0), at(1), at(2) * 0.01, at(3)),
            );
        }
        for i in 0..7 {
            let mut a = [2.0, 7.2, 0.01, AIR_CO2, 1.0, 1.0, 1.0];
            if let Some(x) = a.get_mut(i) {
                *x = bad;
            }
            let [alkalinity, ph, air, air_co2, pressure, s_co2, s_h2s] = a;
            let got = g::mixed_contact(&eq, alkalinity, ph, air, air_co2, pressure, s_co2, s_h2s);
            refused(
                format!("mixed_contact {a:?}"),
                got.map(|x| x.map_or(f64::NAN, |x| x.ph)),
            );
        }
    }
    // out of domain
    for (what, got) in [
        (
            "k0_h2s below fresh water's freezing point",
            g::k0_h2s(-0.1, 0.0).map(|x| x.value),
        ),
        (
            "k0_h2s below sea water's freezing point",
            g::k0_h2s(-2.0, 35.0).map(|x| x.value),
        ),
        ("k0_h2s above 30 °C", g::k0_h2s(30.1, 0.0).map(|x| x.value)),
        ("k0_h2s salinity below 0", g::k0_h2s(12.0, -1.0).map(|x| x.value)),
        (
            "k0_h2s salinity above its range",
            g::k0_h2s(12.0, 41.0).map(|x| x.value),
        ),
        ("freezing_point salinity below 0", g::freezing_point(-1.0)),
        (
            "h2s_from_gas at no pressure",
            g::h2s_from_gas(117.0, 12.0, 35.0, 0.0).map(|x| x.value),
        ),
        (
            "h2s_from_gas below 0 atm",
            g::h2s_from_gas(117.0, 12.0, 35.0, -1.0).map(|x| x.value),
        ),
        (
            "saturation_from_depths at no pressure",
            g::saturation_from_depths(0.8, 12.0, 35.0, 0.0).map(|x| x.0),
        ),
        ("co2_from_gas at no pressure", g::co2_from_gas(3852.0, 12.0, 35.0, 0.0)),
        ("co2_from_gas below 0 atm", g::co2_from_gas(3852.0, 12.0, 35.0, -1.0)),
        ("dried_gas_factor below 0 atm", g::dried_gas_factor(12.0, -1.0)),
        (
            "dried_gas_factor under the vapour pressure",
            g::dried_gas_factor(12.0, 0.01),
        ),
        ("ph_rise_bound a negative air", g::ph_rise_bound(12.0, 35.0, -0.01, 1.0)),
        ("ph_rise_bound at no pressure", g::ph_rise_bound(12.0, 35.0, 0.01, 0.0)),
        (
            "saturation_from_depths below 0.5",
            g::saturation_from_depths(0.49, 12.0, 35.0, 1.0).map(|x| x.0),
        ),
        (
            "saturation_from_depths above 1",
            g::saturation_from_depths(1.01, 12.0, 35.0, 1.0).map(|x| x.0),
        ),
        (
            "mixed_contact at no pressure",
            contact_of(&eq, [2.0, 0.01, AIR_CO2, 0.0, 1.0, 1.0]),
        ),
        (
            "mixed_contact a negative air",
            contact_of(&eq, [2.0, -0.01, AIR_CO2, 1.0, 1.0, 1.0]),
        ),
        (
            "mixed_contact a negative air CO₂",
            contact_of(&eq, [2.0, 0.01, -AIR_CO2, 1.0, 1.0, 1.0]),
        ),
        (
            "mixed_contact a CO₂ saturation of 0",
            contact_of(&eq, [2.0, 0.01, AIR_CO2, 1.0, 0.0, 1.0]),
        ),
        (
            "mixed_contact an H₂S saturation over 1",
            contact_of(&eq, [2.0, 0.01, AIR_CO2, 1.0, 1.0, 1.01]),
        ),
        (
            "mixed_contact no alkalinity",
            contact_of(&eq, [0.0, 0.01, AIR_CO2, 1.0, 1.0, 1.0]),
        ),
    ] {
        refused(what.into(), got);
    }
    report(&failures, 0);
}

fn contact_of(eq: &Equilibria, [alkalinity, air, air_co2, pressure, s_co2, s_h2s]: [f64; 6]) -> Result<f64, ChemError> {
    g::mixed_contact(eq, alkalinity, 7.2, air, air_co2, pressure, s_co2, s_h2s).map(|x| x.map_or(f64::NAN, |x| x.ph))
}

/// Decided after the second review (module note): a reading below 0 is kept signed, never refused or held at 0, and
/// gives a concentration below 0; a free H₂S below 0 a total sulfide below 0. The display says "< LOD" and flags a
/// zero fault; the chemistry does not.
#[test]
fn a_reading_below_0_stays_signed() {
    assert!(g::h2s_from_gas(-1.0, 12.0, 35.0, 1.0).is_ok_and(|x| x.value < 0.0));
    assert!(g::co2_from_gas(-1.0, 12.0, 35.0, 1.0).is_ok_and(|x| x < 0.0));
    let eq = water_equilibria(4, 12.0, 35.0, Some(200.0), Ions::default());
    assert!(
        eq.and_then(|eq| g::total_sulfide(-1.0, &eq, 7.2))
            .is_ok_and(|x| x < 0.0)
    );
}
