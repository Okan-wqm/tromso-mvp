//! The core's arithmetic refuses where CPython's math raised, the solver keeps Python's semantics, and the constants
//! meet their papers' check values (the full comparison with golden v1 is farm/tests/test_native_chemistry.py).
use chemcore_core::chemistry::{self as c, solve};
use chemcore_core::num::{self, ChemError};

#[test]
fn the_arithmetic_fails_where_python_raised() {
    assert_eq!(num::div(1.0, 0.0), Err(ChemError::ZeroDivision));
    assert_eq!(num::div(1.0, -0.0), Err(ChemError::ZeroDivision));
    assert_eq!(num::ln(0.0), Err(ChemError::Domain));
    assert_eq!(num::ln(-1.0), Err(ChemError::Domain));
    assert_eq!(num::log10(-0.0), Err(ChemError::Domain));
    assert_eq!(num::sqrt(-1e-300), Err(ChemError::Domain));
    assert_eq!(num::sqrt(-0.0).map(f64::to_bits), Ok((-0.0f64).to_bits()));
    assert_eq!(num::exp(710.0), Err(ChemError::Overflow));
    assert_eq!(num::exp(-1000.0), Ok(0.0));
    assert_eq!(num::pow(0.0, -1.5), Err(ChemError::Domain));
    assert_eq!(num::pow(-2.0, 0.5), Err(ChemError::Domain));
    assert_eq!(num::pow(-2.0, 2.0), Ok(4.0));
    assert_eq!(num::pow(10.0, 400.0), Err(ChemError::Overflow));
    assert!(num::ln(f64::NAN).is_ok_and(f64::is_nan));
}

#[test]
fn the_solver_keeps_its_ends_its_none_and_its_bracket() {
    let mut calls = 0;
    let root = solve::<()>(
        &mut |x| {
            calls += 1;
            Ok(x - 3.0)
        },
        0.0,
        14.0,
    );
    let root = root.ok().flatten().unwrap_or(f64::NAN);
    assert!((root - 3.0).abs() < 1e-10);
    assert_eq!(calls, 2 + 38); // the ends, then 38 halvings of [0, 14] to under 1e-10
    assert_eq!(solve::<()>(&mut |x| Ok(x), 0.0, 14.0), Ok(Some(0.0)));
    assert_eq!(solve::<()>(&mut |x| Ok(x - 14.0), 0.0, 14.0), Ok(Some(14.0)));
    assert_eq!(solve::<()>(&mut |x| Ok(x + 1.0), 0.0, 14.0), Ok(None));
    assert_eq!(solve::<()>(&mut |_x| Ok(f64::NAN), 0.0, 14.0), Ok(None));
    assert_eq!(solve(&mut |_x| Err("stop"), 0.0, 14.0), Err("stop"));
}

#[test]
fn a_water_is_refused_where_python_raised() {
    assert_eq!(c::equilibria(-273.15, 0.0), Err(ChemError::ZeroDivision));
    assert_eq!(c::equilibria(10.0, -1.0), Err(ChemError::Domain));
    assert_eq!(c::equilibria(10.0, 1000.0), Err(ChemError::Domain));
    assert_eq!(c::equilibria(f64::NAN, 0.0), Err(ChemError::NonFinite));
    assert_eq!(c::equilibria(10.0, f64::INFINITY), Err(ChemError::NonFinite));
    assert_eq!(c::pressure_atm(44331.0), Err(ChemError::Domain));
}

#[test]
fn the_constants_meet_their_papers() {
    let ln = |x: Result<f64, ChemError>| x.map(libm::log).unwrap_or(f64::NAN);
    assert!((ln(c::kb_total(25.0, 35.0)) - -19.7964).abs() < 5e-5); // Dickson 1990, DOE 1994
    assert!((ln(c::kw_total(25.0, 35.0)) - -30.434).abs() < 5e-4); // Millero 1995, DOE 1994
    assert!((ln(c::ks(25.0, 35.0)) - -2.30).abs() < 5e-3); // Dickson 1990, DOE 1994
    assert!((c::oxygen_solubility(25.0, 0.0, 1.0).unwrap_or(f64::NAN) - 8.26).abs() < 5e-3); // APHA 4500-O
    assert!((c::ksp_calcite(25.0, 35.0).unwrap_or(f64::NAN) * 1e7 - 4.27).abs() < 5e-3); // Mucci 1983
    let eq = c::equilibria(25.0, 0.0);
    assert!(eq.is_ok_and(|eq| (-libm::log10(eq.k1) - 6.352).abs() < 3e-3)); // Harned & Davis
}

#[test]
fn the_borders_of_a_water() {
    let eq = c::equilibria(12.0, 1.0);
    assert!(eq.is_ok());
    let Ok(eq) = eq else { return };
    assert_eq!(eq.ph_where_nh3(0.0103, 0.0103), Ok(None));
    assert_eq!(eq.ph_where_co2_at_dic(0.2, 0.3), Ok(None));
    assert_eq!(eq.ph_at(0.0, 1.0), Ok(None));
    let alkalinity = 80.0 / c::MG_CACO3_PER_MEQ;
    let dic = eq.dic(alkalinity, 7.0).unwrap_or(f64::NAN);
    let back = eq.ph_at(dic, alkalinity).ok().flatten().unwrap_or(f64::NAN);
    assert!((back - 7.0).abs() < 1e-9);
}
