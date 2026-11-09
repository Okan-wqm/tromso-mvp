//! The basis NH₃ and CO₂ are judged on (cross review F1; owner decision 2026-11-09): the larger of the basis the limits
//! were set on (formula 1: the ideal water in fresh water, every activity 1, as Emerson et al. 1975) and formula 3's
//! activity-corrected value, so formula 3 never understates NH₃ or CO₂ against how the limits were derived.
use chemcore_core::chemistry::{self as c, Basis, Origin};
use chemcore_core::fresh::{self as f, Ions};
use chemcore_core::num::ChemError;

fn conductivity(kappa: f64) -> Ions {
    Ions {
        conductivity_25_us_cm: Some(kappa),
        hardness_mg_l: None,
        origin: Origin::Unknown,
    }
}

fn at_least_the_ideal(kappa: f64) -> Result<(), ChemError> {
    let eq = f::equilibria_v3(12.0, 0.0, Some(80.0), conductivity(kappa))?;
    let ideal = c::equilibria(12.0, 0.0)?;
    let alkalinity = 80.0 / c::MG_CACO3_PER_MEQ;
    assert_eq!(eq.nh3_basis()?, Basis::Limits);
    for ph in [6.8, 7.0, 7.5, 8.0] {
        // NH₃: the judged share is the ideal one; the corrected one is lower.
        assert!(eq.nh3_share(ph)? >= ideal.nh3_share(ph)?);
        assert!(eq.nh3_share_corrected(ph)? < eq.nh3_share(ph)?);
        let (tan, limit) = (0.5, 0.0103);
        assert!(eq.ph_where_nh3(tan, limit)?.unwrap_or(f64::NAN) <= ideal.ph_where_nh3(tan, limit)?.unwrap_or(0.0));
        // CO₂ at the water's alkalinity and pH.
        let own = eq.co2_corrected(alkalinity, ph)?;
        let (judged, basis) = eq.co2_judged(alkalinity, ph, own)?;
        assert!(judged >= ideal.co2_corrected(alkalinity, ph)?);
        assert!(own < judged);
        assert_eq!(basis, Basis::Limits);
    }
    let co2 = 15.0 / c::MG_CO2_PER_MMOL;
    assert!(
        eq.ph_where_co2(alkalinity, co2)?.unwrap_or(f64::NAN) >= ideal.ph_where_co2(alkalinity, co2)?.unwrap_or(14.0)
    );
    Ok(())
}

#[test]
fn judged_nh3_and_co2_are_at_least_the_ideal_at_500_1000_and_3000_us_cm_and_12_degrees() {
    for kappa in [500.0, 1000.0, 3000.0] {
        assert_eq!(at_least_the_ideal(kappa), Ok(()));
    }
}

#[test]
fn formula_1_is_its_own_basis() {
    let one = c::equilibria(12.0, 35.0);
    assert!(one.is_ok_and(|eq| eq.limits_basis.is_none()
        && eq.nh3_share(8.0) == eq.nh3_share_corrected(8.0)
        && eq.nh3_basis() == Ok(Basis::Limits)));
}

#[test]
fn in_the_band_and_the_sea_the_larger_judges() {
    let check = |temp_c: f64, salinity: f64| -> Result<(), ChemError> {
        let eq = f::equilibria_v3(temp_c, salinity, Some(100.0), Ions::default())?;
        let basis = eq.limits_equilibria().ok_or(ChemError::Domain)?;
        for ph in [7.0, 7.5, 8.0, 8.5] {
            let judged = eq.nh3_share(ph)?;
            assert!(judged >= basis.nh3_share_corrected(ph)? && judged >= eq.nh3_share_corrected(ph)?);
        }
        Ok(())
    };
    for salinity in [0.5, 1.0, 2.0, 3.0, 4.99, 5.0, 10.0, 35.0] {
        for temp_c in [0.0, 2.0, 12.0, 25.0] {
            assert_eq!(check(temp_c, salinity), Ok(()));
        }
    }
}
