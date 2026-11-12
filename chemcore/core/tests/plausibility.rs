//! Plausibility warnings on a water's ionic inputs (cross review F5): said with the value, never a refusal.
use chemcore_core::chemistry::Origin;
use chemcore_core::fresh::{self as f, Ions};

fn kappa(conductivity: f64, hardness: Option<f64>) -> Ions {
    Ions {
        conductivity_25_us_cm: Some(conductivity),
        hardness_mg_l: hardness,
        origin: Origin::Unknown,
    }
}

#[test]
fn pss78_reads_standard_sea_water_as_35() {
    let r25 = 0.6766097 + 2.00564e-2 * 25.0 + 1.104259e-4 * 625.0 - 6.9698e-7 * 15625.0 + 1.0031e-9 * 390625.0;
    assert!(f::practical_salinity(42914.0 * r25).is_ok_and(|s| (s - 35.0).abs() < 1e-4));
    assert!(f::practical_salinity(0.0).is_ok_and(|s| s.abs() < 1e-9));
}

#[test]
fn each_warning_where_its_inputs_disagree() {
    let bits = |salinity: f64, alkalinity: f64, ions: Ions| f::plausibility(12.0, salinity, Some(alkalinity), ions);
    assert_eq!(bits(0.0, 80.0, kappa(300.0, Some(100.0))), Ok(0));
    assert_eq!(bits(3.0, 80.0, kappa(500.0, None)), Ok(f::CONDUCTIVITY_SALINITY));
    assert_eq!(
        bits(0.0, 20.0, kappa(1500.0, Some(20.0))),
        Ok(f::CONDUCTIVITY_ABOVE_IONS)
    );
    assert_eq!(
        bits(0.0, 200.0, kappa(100.0, Some(300.0))),
        Ok(f::CONDUCTIVITY_BELOW_IONS)
    );
    assert!(bits(0.0, 80.0, kappa(20000.0, None)).is_ok_and(|w| w & f::SEAWATER_CONDUCTIVITY != 0));
    // Never a refusal: the water is still worked out, the warnings with it.
    assert!(
        f::equilibria_v3(12.0, 0.0, Some(80.0), kappa(20000.0, None))
            .is_ok_and(|eq| eq.warnings & f::SEAWATER_CONDUCTIVITY != 0)
    );
}

#[test]
fn the_nh3_judgement_past_its_guard_is_warned_never_refused() {
    // The K_NH4 panel's decision of 2026-11-10, row 3: above 30 °C or a salinity of 35 ‰ the judged NH₃ is outside what
    // its guard holds (chemcore/core/tests/nh3_guard.rs: 0 to 30 °C, S up to 35), so a warning is said, the bounds
    // themselves still inside.
    assert_eq!(f::NH3_PAST_GUARD, 16);
    assert_eq!((f::NH3_GUARD_MAX_TEMP_C, f::NH3_GUARD_MAX_SALINITY), (30.0, 35.0));
    let bits = |temp_c: f64, salinity: f64| f::plausibility(temp_c, salinity, None, Ions::default());
    for (temp_c, salinity) in [(0.0, 0.0), (12.0, 0.0), (30.0, 0.0), (0.0, 35.0), (30.0, 35.0)] {
        assert_eq!(bits(temp_c, salinity), Ok(0), "{temp_c} °C, S {salinity}");
    }
    for (temp_c, salinity) in [(30.5, 0.0), (31.0, 35.0), (12.0, 35.5), (40.0, 40.0)] {
        assert_eq!(
            bits(temp_c, salinity),
            Ok(f::NH3_PAST_GUARD),
            "{temp_c} °C, S {salinity}"
        );
    }
    // Whatever the unit's water origin, and beside a conductivity's own warning (or-ed, neither hides the other).
    for origin in [Origin::Unknown, Origin::Seawater, Origin::SaltAdded] {
        let ions = Ions {
            origin,
            ..Ions::default()
        };
        assert_eq!(f::plausibility(32.0, 10.0, Some(100.0), ions), Ok(f::NH3_PAST_GUARD));
        assert_eq!(f::plausibility(30.0, 10.0, Some(100.0), ions), Ok(0));
    }
    assert_eq!(
        f::plausibility(32.0, 3.0, Some(80.0), kappa(500.0, None)),
        Ok(f::CONDUCTIVITY_SALINITY | f::NH3_PAST_GUARD)
    );
    // Never a refusal: the water is worked out, its NH₃ judged, the warning with it.
    let warm = f::equilibria_v3(35.0, 35.0, Some(115.0), Ions::default());
    assert!(warm.is_ok_and(
        |eq| eq.warnings == f::NH3_PAST_GUARD && eq.nh3_share(8.0).is_ok_and(|share| share > 0.0 && share < 1.0)
    ));
    assert!(f::equilibria_v3(30.0, 35.0, Some(115.0), Ions::default()).is_ok_and(|eq| eq.warnings == 0));
    // Formula 1 says no warning (golden v1 holds none).
    assert!(f::water_equilibria(1, 35.0, 40.0, None, Ions::default()).is_ok_and(|eq| eq.warnings == 0));
}
