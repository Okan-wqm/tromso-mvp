//! I2 (golden v3): the fresh-water path meets the literature and leaves sea water as v1 (the corpus comparison is
//! farm/tests/test_golden_v3.py).
use chemcore_core::chemistry as c;
use chemcore_core::chemistry::Origin;
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
fn the_sources_in_order() {
    // The estimate (the conductivity, else a salinity above 0) is taken unless the measured ions' lower bound (the
    // hardness with the alkalinity, else the alkalinity alone) is above it; with nothing measured, 0.
    let both = Ions {
        conductivity_25_us_cm: Some(500.0),
        hardness_mg_l: Some(300.0),
        origin: Origin::Unknown,
    };
    let hardness = Ions {
        conductivity_25_us_cm: None,
        hardness_mg_l: Some(300.0),
        origin: Origin::Unknown,
    };
    let source = |salinity, alkalinity, ions| f::ionic_strength(salinity, alkalinity, ions).map(|(_i, source)| source);
    assert_eq!(source(0.0, Some(80.0), both), Ok(Source::Hardness)); // 0.008 against 0.0089
    assert_eq!(
        source(
            0.0,
            Some(80.0),
            Ions {
                conductivity_25_us_cm: Some(1000.0),
                ..both
            }
        ),
        Ok(Source::Conductivity)
    );
    assert_eq!(source(0.2, Some(80.0), hardness), Ok(Source::Hardness)); // 0.0040 against 0.0089
    assert_eq!(source(2.0, Some(80.0), hardness), Ok(Source::Salinity)); // 0.040 against 0.0089
    assert_eq!(source(2.0, Some(80.0), Ions::default()), Ok(Source::Salinity));
    assert_eq!(source(0.0, Some(80.0), Ions::default()), Ok(Source::Alkalinity));
    assert_eq!(source(0.01, Some(80.0), Ions::default()), Ok(Source::Alkalinity)); // 0.0002 against 0.0016
    assert_eq!(
        f::ionic_strength(0.0, None, Ions::default()),
        Ok((0.0, Source::Nothing))
    );
    assert_eq!(source(5.0, Some(80.0), both), Ok(Source::Seawater));
    assert!(f::ionic_strength(0.0, Some(-1.0), Ions::default()).is_err());
    assert!(f::ionic_strength(-0.1, Some(80.0), Ions::default()).is_err());
}

// ---- the boundary between the fresh and the sea path (chemcore/findings/I2-comparison.md) ------------------------

fn constants(eq: &c::Equilibria) -> [f64; 7] {
    [eq.ph_offset, eq.k1, eq.k2, eq.kw, eq.kb, eq.k_nh4, eq.k_h2s]
}

fn v3(temp_c: f64, salinity: f64, alkalinity: f64, ions: Ions) -> [f64; 7] {
    f::equilibria_v3(temp_c, salinity, Some(alkalinity), ions)
        .map(|eq| constants(&eq))
        .unwrap_or([f64::NAN; 7])
}

const WATERS: [(f64, Ions); 4] = [
    (
        120.0,
        Ions {
            conductivity_25_us_cm: None,
            hardness_mg_l: None,
            origin: Origin::Unknown,
        },
    ),
    (
        120.0,
        Ions {
            conductivity_25_us_cm: Some(3700.0),
            hardness_mg_l: None,
            origin: Origin::Unknown,
        },
    ),
    (
        120.0,
        Ions {
            conductivity_25_us_cm: None,
            hardness_mg_l: Some(300.0),
            origin: Origin::Unknown,
        },
    ),
    (
        20.0,
        Ions {
            conductivity_25_us_cm: None,
            hardness_mg_l: None,
            origin: Origin::Unknown,
        },
    ),
];

#[test]
fn the_band_is_from_1_to_5_permil() {
    // Millero et al. (2006) measured K1, K2 from S 1; Dickson's (1990) KSO4 and KB hold from S 5.
    assert_eq!((f::FRESH_UP_TO, f::SEA_FROM), (1.0, 5.0));
    for (salinity, weight) in [
        (0.0, 0.0),
        (1.0, 0.0),
        (2.0, 0.25),
        (3.0, 0.5),
        (4.0, 0.75),
        (5.0, 1.0),
        (35.0, 1.0),
    ] {
        assert_eq!(f::sea_weight(salinity), weight);
    }
}

#[test]
fn no_jump_at_either_end_of_the_band() {
    // The old 5 ‰ boundary jumped up to 25 % in CO₂ (hardness) and 14.5 % in the NH₃ share; across the band every
    // constant is continuous: a step of 1e-9 ‰ moves none by more than 1e-7 of itself.
    for temp_c in [0.0, 2.0, 5.0, 12.0, 25.0] {
        for (alkalinity, ions) in WATERS {
            for edge in [f::FRESH_UP_TO, f::SEA_FROM] {
                let (below, above) = (
                    v3(temp_c, edge - 1e-9, alkalinity, ions),
                    v3(temp_c, edge + 1e-9, alkalinity, ions),
                );
                for (one, two) in below.iter().zip(above.iter()) {
                    assert!(
                        ((two - one) / one).abs() < 1e-7,
                        "{temp_c} °C, {edge} ‰: {one} against {two}"
                    );
                }
            }
        }
    }
}

#[test]
fn in_the_band_each_constant_is_the_geometric_blend_of_the_two_paths() {
    let ions = Ions::default();
    for salinity in [2.0, 3.5] {
        let weight = f::sea_weight(salinity);
        let blended = v3(12.0, salinity, 120.0, ions);
        let fresh = f::fresh_equilibria(12.0, salinity, Some(120.0), ions).map(|eq| constants(&eq));
        let sea = c::equilibria_with(12.0, salinity, &f::debye_huckel_a).map(|eq| constants(&eq));
        assert!(
            matches!((fresh, sea), (Ok(fresh), Ok(sea)) if blended.iter().zip(fresh.iter().zip(sea.iter()))
            .enumerate().all(|(index, (found, (fresh, sea)))| {
                let expected = if index == 0 {
                    (1.0 - weight) * fresh + weight * sea
                } else {
                    libm::exp((1.0 - weight) * libm::log(*fresh) + weight * libm::log(*sea))
                };
                ((found - expected) / expected).abs() < 1e-12
            }))
        );
    }
}

#[test]
fn a_salinity_near_0_does_not_drop_the_alkalinitys_ions() {
    // Formula 3 before the band: a salinity of 0.01 ‰ took I = 0.0002 over the alkalinity's 0.0016 (a 7.7 % step).
    for (one, two) in v3(12.0, 0.0, 300.0, Ions::default())
        .iter()
        .zip(v3(12.0, 0.01, 300.0, Ions::default()).iter())
    {
        assert!(((two - one) / one).abs() < 1e-12);
    }
}

#[test]
fn above_davies_range_it_is_refused() {
    let sea = Ions {
        conductivity_25_us_cm: Some(40000.0),
        hardness_mg_l: None,
        origin: Origin::Unknown,
    };
    assert_eq!(f::ionic_strength(0.0, Some(80.0), sea), Err(ChemError::OutOfRange));
    assert!(f::equilibria_v3(12.0, 0.0, Some(80.0), sea).is_err());
    assert!(f::equilibria_v3(12.0, 3.0, Some(80.0), sea).is_err()); // in the band the fresh path is half the answer
    assert_eq!(f::davies_log_gamma(12.0, 0.6, 1.0), Err(ChemError::OutOfRange));
    assert!(f::davies_log_gamma(12.0, f::DAVIES_MAX, 1.0).is_ok());
}

// ---- I1: the Debye–Hückel A of the water's temperature ----------------------------------------------------------

/// The Debye–Hückel A (log₁₀, molal, kg^½ mol^−½) as tabulated by Hamer (1968), Theoretical mean activity coefficients
/// of strong electrolytes in aqueous solutions from 0 to 100 °C, NSRDS-NBS 24, table 3 (from Malmberg & Maryott's ε and
/// the density of water): (°C, A).
const A_TABLE: [(f64, f64); 7] = [
    (0.0, 0.4918),
    (5.0, 0.4953),
    (10.0, 0.4989),
    (15.0, 0.5027),
    (20.0, 0.5067),
    (25.0, 0.5108),
    (30.0, 0.5151),
];

/// An independent table: Nordstrom, Valentine, Ball, Plummer & Jones (1984), USGS WRI 84-4186, table 1, A from the
/// dielectric constant of Uematsu & Franck (1980), which differs from Malmberg & Maryott's by up to 0.3 % in A: (°C, A).
const A_USGS: [(f64, f64); 4] = [(0.0, 0.4912), (10.0, 0.4976), (20.0, 0.5052), (30.0, 0.5139)];

/// The table's A at a temperature between two of its rows, linearly.
fn tabulated_a(temp_c: f64) -> f64 {
    let mut found = f64::NAN;
    for pair in A_TABLE.windows(2) {
        if let [(t0, a0), (t1, a1)] = pair {
            if *t0 <= temp_c && temp_c <= *t1 {
                found = a0 + (a1 - a0) * (temp_c - t0) / (t1 - t0);
            }
        }
    }
    found
}

#[test]
fn the_dielectric_constant_meets_malmberg_and_maryott() {
    // Malmberg & Maryott (1956), J. Res. Natl. Bur. Stand. 56: 1, table 2, ε of their eq. (5) (the abstract's
    // coefficients; p. 5 misprints the linear one as 0.4008).
    for (temp_c, epsilon) in [
        (0.0, 87.740),
        (5.0, 85.763),
        (10.0, 83.832),
        (15.0, 81.946),
        (20.0, 80.103),
        (25.0, 78.304),
        (30.0, 76.546),
    ] {
        assert!(f::dielectric_constant(temp_c).is_ok_and(|found| (found - epsilon).abs() < 0.001));
    }
}

#[test]
fn the_density_meets_kell() {
    // Kell (1975), J. Chem. Eng. Data 20: 97, as reproduced in J. Res. NIST 97: 335 (1992), whose denominator misprints
    // 16.897850e-3 (that puts the density's maximum at 4 °C below 0.99991): 0.99984 g/cm³ at 0 °C, the maximum 0.99997 at
    // 4 °C, 0.99705 at 25 °C (the CRC values of pure water; Kell's own table was not read).
    for (temp_c, density) in [(0.0, 0.99984), (4.0, 0.99997), (25.0, 0.99705)] {
        assert!(f::water_density(temp_c).is_ok_and(|found| (found - density).abs() < 1e-5));
    }
}

#[test]
fn debye_huckel_a_meets_the_tables_from_0_to_30_degrees() {
    for (temp_c, a) in A_TABLE {
        let found = f::debye_huckel_a(temp_c);
        assert!(
            found.is_ok_and(|found| ((found - a) / a).abs() < 0.0003),
            "{temp_c} °C: {found:?} against {a}"
        );
    }
    for (temp_c, a) in A_USGS {
        let found = f::debye_huckel_a(temp_c);
        assert!(
            found.is_ok_and(|found| ((found - a) / a).abs() < 0.003),
            "{temp_c} °C: {found:?} against {a}"
        );
    }
    // Formula 1's fixed ε = 79 was 7.5 % too large at 12 °C and 15 % at 2 °C (I1; cross review F2).
    for (temp_c, excess) in [(12.0, 0.075), (2.0, 0.15)] {
        let v1 = c::debye_huckel_a_v1(temp_c).unwrap_or(f64::NAN);
        assert!(((v1 / tabulated_a(temp_c) - 1.0) - excess).abs() < 0.01);
    }
}

#[test]
fn davies_at_2_5_and_12_degrees_meets_the_tabulated_a() {
    // Davies (1962): log γ = −A z² (√I / (1 + √I) − 0.3 I), with the table's A at the temperature.
    for temp_c in [2.0, 5.0, 12.0] {
        for strength in [0.001, 0.01, 0.05, 0.1] {
            for charge in [1.0, 2.0] {
                let root = libm::sqrt(strength);
                let expected = -tabulated_a(temp_c) * charge * charge * (root / (1.0 + root) - 0.3 * strength);
                let found = f::davies_log_gamma(temp_c, strength, charge).unwrap_or(f64::NAN);
                // γ itself within 0.1 %
                assert!(
                    (libm::pow(10.0, found - expected) - 1.0).abs() < 1e-3,
                    "{temp_c} °C, I {strength}, z {charge}"
                );
            }
        }
    }
}

#[test]
fn sea_water_keeps_v1s_constants_and_converts_the_nbs_ph_with_the_temperatures_a() {
    let ions = Ions {
        conductivity_25_us_cm: Some(500.0),
        hardness_mg_l: None,
        origin: Origin::Unknown,
    };
    for temp_c in [2.0, 12.0, 25.0] {
        for salinity in [5.0, 10.0, 35.0] {
            let v3 = f::equilibria_v3(temp_c, salinity, Some(100.0), ions);
            let v1 = c::equilibria(temp_c, salinity);
            assert!(
                matches!((v3, v1), (Ok(v3), Ok(v1)) if v3.k1 == v1.k1 && v3.k2 == v1.k2 && v3.kw == v1.kw
                && v3.kb == v1.kb && v3.k_nh4 == v1.k_nh4 && v3.k_h2s == v1.k_h2s && v3.boron == v1.boron)
            );
            let gamma = |a_of: &dyn Fn(f64) -> chemcore_core::num::R| {
                c::activity_coefficient_h_with(temp_c, salinity, a_of).map(libm::log10)
            };
            let shift = gamma(&f::debye_huckel_a).and_then(|t| gamma(&c::debye_huckel_a_v1).map(|v| t - v));
            assert!(matches!((v3, v1, shift), (Ok(v3), Ok(v1), Ok(shift))
                if (v3.ph_offset - v1.ph_offset - shift).abs() < 1e-12));
        }
    }
}

// ---- the switch: formula 3 is the application's, formula 1 is still worked out exactly -------------------------------

#[test]
fn every_equilibria_says_its_formula_its_ionic_strength_and_where_it_came_from() {
    let ions = Ions {
        conductivity_25_us_cm: Some(300.0),
        hardness_mg_l: None,
        origin: Origin::Unknown,
    };
    let fresh = f::water_equilibria(3, 12.0, 0.0, Some(80.0), ions);
    assert!(fresh.is_ok_and(|eq| eq.formula == 3
        && eq.ionic_strength == 1.6e-5 * 300.0
        && eq.source == Source::Conductivity
        && eq.sea_weight == 0.0));
    let band = f::water_equilibria(3, 12.0, 3.0, Some(80.0), Ions::default());
    assert!(band.is_ok_and(|eq| eq.formula == 3 && eq.source == Source::Salinity && eq.sea_weight == 0.5));
    let sea = f::water_equilibria(3, 12.0, 35.0, Some(80.0), ions);
    assert!(sea.is_ok_and(|eq| eq.formula == 3 && eq.source == Source::Seawater && eq.sea_weight == 1.0));
    // formula 1 is golden v1's equilibria exactly, whatever is measured
    assert_eq!(
        f::water_equilibria(1, 12.0, 0.0, Some(80.0), ions),
        c::equilibria(12.0, 0.0)
    );
    assert!(c::equilibria(12.0, 0.0).is_ok_and(|eq| eq.formula == 1 && eq.ionic_strength == 0.0));
    assert_eq!(
        f::water_equilibria(2, 12.0, 0.0, None, Ions::default()),
        Err(ChemError::UnknownFormula)
    );
    assert_eq!(chemcore_core::FORMULA_VERSION, 3);
}
