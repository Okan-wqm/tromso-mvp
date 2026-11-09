//! I2 (golden v3): the fresh-water path meets the literature and leaves sea water as v1 (the corpus comparison is
//! farm/tests/test_golden_v3.py).
use chemcore_core::chemistry as c;
use chemcore_core::fresh::{self as f, Ions, Source};
use chemcore_core::num::ChemError;

#[test]
fn davies_meets_stumm_and_morgan() {
    // Stumm & Morgan (1996), table 3.3: by Davies at I = 0.01 and 25 °C, γ 0.90 for a monovalent ion, 0.66 divalent.
    let one = f::davies_log_gamma(25.0, 0.01, 1.0).map(|log| libm::pow(10.0, log));
    let two = f::davies_log_gamma(25.0, 0.01, 2.0).map(|log| libm::pow(10.0, log));
    assert!(one.is_ok_and(|gamma| (gamma - 0.90).abs() < 0.005));
    assert!(two.is_ok_and(|gamma| (gamma - 0.66).abs() < 0.01));
}

#[test]
fn sea_water_is_v1_bit_for_bit() {
    let ions = Ions {
        conductivity_us_cm: Some(500.0),
        hardness_mg_l: None,
    };
    for salinity in [5.0, 10.0, 35.0] {
        let v3 = f::equilibria_v3(12.0, salinity, 100.0, ions);
        let v1 = c::equilibria(12.0, salinity);
        assert_eq!(
            v3.map(|(eq, _i, source)| (eq, source)),
            v1.map(|eq| (eq, Source::Seawater))
        );
    }
}

#[test]
fn the_sources_in_order() {
    let both = Ions {
        conductivity_us_cm: Some(500.0),
        hardness_mg_l: Some(300.0),
    };
    let hardness = Ions {
        conductivity_us_cm: None,
        hardness_mg_l: Some(300.0),
    };
    let source = |salinity, ions| f::ionic_strength(salinity, 80.0, ions).map(|(_i, source)| source);
    assert_eq!(source(0.0, both), Ok(Source::Conductivity));
    assert_eq!(source(2.0, hardness), Ok(Source::Hardness));
    assert_eq!(source(2.0, Ions::default()), Ok(Source::Salinity));
    assert_eq!(source(0.0, Ions::default()), Ok(Source::Alkalinity));
    assert_eq!(source(5.0, both), Ok(Source::Seawater));
    assert!(f::ionic_strength(0.0, -1.0, Ions::default()).is_err());
}

#[test]
fn above_davies_range_it_is_refused() {
    let sea = Ions {
        conductivity_us_cm: Some(40000.0),
        hardness_mg_l: None,
    };
    assert_eq!(f::ionic_strength(0.0, 80.0, sea), Err(ChemError::OutOfRange));
    assert!(f::equilibria_v3(12.0, 0.0, 80.0, sea).is_err());
    assert_eq!(f::davies_log_gamma(12.0, 0.6, 1.0), Err(ChemError::OutOfRange));
    assert!(f::davies_log_gamma(12.0, f::DAVIES_MAX, 1.0).is_ok());
}
