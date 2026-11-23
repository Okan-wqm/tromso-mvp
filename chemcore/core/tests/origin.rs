//! A water's origin (cross review F3, F4): salt-added fresh water takes the fresh path up to the Davies limit, its ionic
//! strength from NaCl, no seawater boron; sea-water-derived or unsaid keeps the band.
use chemcore_core::chemistry::Origin;
use chemcore_core::fresh::{self as f, Ions, Source};
use chemcore_core::num::ChemError;

fn salted(conductivity: Option<f64>) -> Ions {
    Ions {
        conductivity_25_us_cm: conductivity,
        hardness_mg_l: None,
        origin: Origin::SaltAdded,
        phosphate_p_mg_l: None,
    }
}

#[test]
fn salt_added_water_takes_the_fresh_path_with_nacls_ionic_strength() {
    let check = || -> Result<(), ChemError> {
        let eq = f::equilibria_v3(12.0, 3.0, Some(80.0), salted(None))?;
        assert_eq!(
            (eq.sea_weight, eq.origin, eq.source),
            (0.0, Origin::SaltAdded, Source::Salinity)
        );
        assert!((eq.ionic_strength - 3.0 / 58.443 / (1.0 - 0.003)).abs() < 1e-12);
        assert_eq!(eq.boron, 0.0);
        let by_kappa = f::equilibria_v3(12.0, 2.0, Some(80.0), salted(Some(5000.0)))?;
        assert_eq!(
            (by_kappa.ionic_strength, by_kappa.source),
            (8.4e-6 * 5000.0, Source::Conductivity)
        );
        // Up to the Davies limit, then the sea path.
        assert_eq!(f::equilibria_v3(12.0, 20.0, Some(80.0), salted(None))?.sea_weight, 0.0);
        let beyond = f::equilibria_v3(12.0, 35.0, Some(80.0), salted(None))?;
        assert_eq!((beyond.sea_weight, beyond.source), (1.0, Source::Seawater));
        Ok(())
    };
    assert_eq!(check(), Ok(()));
}

#[test]
fn unsaid_and_seawater_derived_keep_the_band() {
    let band = |origin| {
        f::equilibria_v3(
            12.0,
            3.0,
            Some(80.0),
            Ions {
                origin,
                ..Ions::default()
            },
        )
    };
    assert!(band(Origin::Unknown).is_ok_and(|eq| eq.sea_weight == 0.5));
    assert!(band(Origin::Seawater).is_ok_and(|eq| eq.sea_weight == 0.5 && eq.origin == Origin::Seawater));
    assert_eq!(Origin::from_code("salt_added"), Some(Origin::SaltAdded));
    assert_eq!(Origin::from_code(""), Some(Origin::Unknown));
    assert_eq!(Origin::from_code("rain"), None);
}
