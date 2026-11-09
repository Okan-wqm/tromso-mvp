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
    let bits = |salinity: f64, alkalinity: f64, ions: Ions| f::plausibility(salinity, Some(alkalinity), ions);
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
