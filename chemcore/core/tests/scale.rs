//! The scale of a pH given to the core (`chemcore_core::scale`; the K_NH4 panel's proposal, the owner's decision of
//! 2026-11-11): a pH on the total, the seawater or the free scale is put on the NBS scale, the core's own, before
//! anything is worked out from it; the NBS scale, the default, is the pH itself, bit for bit.
use chemcore_core::chemistry::{self as c, Equilibria, Origin};
use chemcore_core::fresh::{self as f, Ions};
use chemcore_core::num::ChemError;
use chemcore_core::scale::{self as s, PhScale};

/// A sea water's equilibria by formula 3.
fn sea(temp_c: f64, salinity: f64) -> Result<Equilibria, ChemError> {
    f::equilibria_v3(temp_c, salinity, Some(115.0), Ions::default())
}

/// The NBS pH of a pH given on a scale in a sea water (NaN where refused: a comparison then fails).
fn nbs(temp_c: f64, salinity: f64, ph: f64, scale: PhScale) -> f64 {
    sea(temp_c, salinity)
        .and_then(|eq| s::ph_nbs(&eq, ph, scale))
        .unwrap_or(f64::NAN)
}

#[test]
fn the_codes_are_stable_and_nbs_is_the_default() {
    assert_eq!(PhScale::default(), PhScale::Nbs);
    let codes: Vec<&str> = PhScale::ALL.iter().map(|scale| scale.code()).collect();
    assert_eq!(codes, ["nbs", "total", "sws", "free"]);
    for scale in PhScale::ALL {
        assert_eq!(PhScale::from_code(scale.code()), Some(scale));
    }
    assert_eq!(PhScale::from_code("NBS"), None);
    assert_eq!(PhScale::from_code(""), None);
}

#[test]
fn an_nbs_ph_is_itself_bit_for_bit_in_every_water() {
    // The default changes nothing: fresh, brackish, salt-added and sea water, formula 1 and formula 3.
    let mut waters = 0;
    for temp_c in [0.0, 2.0, 12.0, 25.0, 30.0, 40.0] {
        for salinity in [0.0, 0.5, 1.0, 3.0, 4.99, 5.0, 20.0, 35.0, 40.0] {
            for origin in [Origin::Unknown, Origin::Seawater, Origin::SaltAdded] {
                let ions = Ions {
                    origin,
                    ..Ions::default()
                };
                for formula in [1, 3] {
                    let eq = f::water_equilibria(formula, temp_c, salinity, Some(80.0), ions);
                    assert!(eq.is_ok(), "{temp_c} °C, S {salinity}");
                    for ph in [4.0, 6.5, 7.0, 7.123456789, 8.0, 8.5, 12.0] {
                        let same = eq.and_then(|eq| s::ph_nbs(&eq, ph, PhScale::Nbs));
                        assert_eq!(same.map(f64::to_bits), Ok(ph.to_bits()));
                        let back = eq.and_then(|eq| s::ph_on(&eq, ph, PhScale::Nbs));
                        assert_eq!(back.map(f64::to_bits), Ok(ph.to_bits()));
                    }
                    waters += 1;
                }
            }
        }
    }
    assert_eq!(waters, 6 * 9 * 3 * 2);
}

#[test]
fn each_scale_by_its_definition() {
    // [H⁺]total = [H⁺]free (1 + ST/KS) (Dickson, Sabine & Christian 2007, ch. 2, eq. 15); the seawater scale counts HF
    // too; the NBS pH is the free pH less the water's own offset.
    for temp_c in [0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0] {
        for salinity in [5.0, 10.0, 20.0, 30.0, 35.0, 40.0] {
            let offset = sea(temp_c, salinity).map_or(f64::NAN, |eq| eq.ph_offset);
            let total = c::free_to_total(temp_c, salinity).map_or(f64::NAN, libm::log10);
            let sws = c::free_to_sws(temp_c, salinity).map_or(f64::NAN, libm::log10);
            for ph in [6.5, 7.0, 7.5, 8.0, 8.5] {
                assert_eq!(nbs(temp_c, salinity, ph, PhScale::Free), ph - offset);
                assert_eq!(nbs(temp_c, salinity, ph, PhScale::Total), ph + total - offset);
                assert_eq!(nbs(temp_c, salinity, ph, PhScale::Seawater), ph + sws - offset);
                // The seawater-scale pH is the lowest of the three and the free the highest; the NBS pH is above them
                // all from 5 ‰ (the hazard: typed as NBS they read low).
                assert!(
                    nbs(temp_c, salinity, ph, PhScale::Seawater) > nbs(temp_c, salinity, ph, PhScale::Total)
                        && nbs(temp_c, salinity, ph, PhScale::Total) > nbs(temp_c, salinity, ph, PhScale::Free)
                        && nbs(temp_c, salinity, ph, PhScale::Free) > ph,
                    "{temp_c} °C, S {salinity}"
                );
            }
        }
    }
}

#[test]
fn the_free_hydrogen_ion_of_a_converted_ph_is_the_given_phs_own() {
    // The core's NBS conversion is in-house (±0.08 pH against CO2SYS's); it cancels: what the water's own constants
    // work out from the converted pH takes exactly the free [H⁺] the given pH has by the published definition.
    for temp_c in [0.0, 10.0, 20.0, 30.0] {
        for salinity in [5.0, 20.0, 35.0] {
            for ph in [7.0, 8.0, 8.4] {
                let total = c::free_to_total(temp_c, salinity).unwrap_or(f64::NAN);
                let wanted = libm::pow(10.0, -ph) / total;
                let found = sea(temp_c, salinity)
                    .and_then(|eq| eq.hydrogen(s::ph_nbs(&eq, ph, PhScale::Total)?))
                    .unwrap_or(f64::NAN);
                assert!((found / wanted - 1.0).abs() < 1e-12, "{found} against {wanted}");
            }
        }
    }
}

/// PyCO2SYS 1.8.3.4 (numbers only; its code is GPL, none copied), opt_k_bisulfate 1 (Dickson 1990), opt_k_fluoride 1
/// (Dickson & Riley 1979), opt_total_borate 1, a pH of 8 given on the total scale: (°C, S, pH free, pH on the seawater
/// scale). Recorded 2026-11-12 (F:/dev/balik-notes/chem-v3/verify; the whole grid is in chemcore/findings/pH-scale.md).
const PYCO2SYS: [(f64, f64, f64, f64); 6] = [
    (0.0, 35.0, 8.04075299626232, 7.993046399913691),
    (10.0, 5.0, 8.026941633852406, 7.997230260485127),
    (15.0, 20.0, 8.05855610751629, 7.99297048337686),
    (25.0, 35.0, 8.107719965821587, 7.990319958615346),
    (30.0, 10.0, 8.066090505653367, 7.993998535443281),
    (30.0, 35.0, 8.125405971851398, 7.989857072746032),
];

#[test]
fn the_scales_agree_with_pyco2sys() {
    for (temp_c, salinity, free, sws) in PYCO2SYS {
        let found = sea(temp_c, salinity).and_then(|eq| {
            let nbs = s::ph_nbs(&eq, 8.0, PhScale::Total)?;
            Ok((
                s::ph_on(&eq, nbs, PhScale::Free)?,
                s::ph_on(&eq, nbs, PhScale::Seawater)?,
            ))
        });
        let (ours_free, ours_sws) = found.unwrap_or((f64::NAN, f64::NAN));
        assert!(
            (ours_free - free).abs() < 1e-12,
            "{temp_c} °C, S {salinity}: {ours_free} against {free}"
        );
        assert!(
            (ours_sws - sws).abs() < 1e-12,
            "{temp_c} °C, S {salinity}: {ours_sws} against {sws}"
        );
    }
}

#[test]
fn there_and_back() {
    for scale in PhScale::ALL {
        for temp_c in [2.0, 12.0, 25.0] {
            for ph in [7.2, 7.95, 8.31] {
                let back = sea(temp_c, 34.0).and_then(|eq| s::ph_on(&eq, s::ph_nbs(&eq, ph, scale)?, scale));
                assert!(back.is_ok_and(|back| (back - ph).abs() < 1e-12), "{scale:?} {back:?}");
            }
        }
    }
}

#[test]
fn only_sea_water_takes_another_scale() {
    // A seawater scale is taken from 5 ‰ where the constants are the sea path's alone; below it, and in fresh water
    // salted with NaCl inside the Davies range, it is refused, never assumed.
    let converted = |salinity: f64, origin: Origin, scale: PhScale| {
        let ions = Ions {
            origin,
            ..Ions::default()
        };
        f::equilibria_v3(12.0, salinity, Some(80.0), ions).and_then(|eq| s::ph_nbs(&eq, 8.0, scale))
    };
    for scale in [PhScale::Total, PhScale::Seawater, PhScale::Free] {
        for salinity in [0.0, 0.5, 1.0, 3.0, 4.99] {
            assert_eq!(
                converted(salinity, Origin::Unknown, scale),
                Err(ChemError::SeawaterScale)
            );
        }
        assert_eq!(converted(20.0, Origin::SaltAdded, scale), Err(ChemError::SeawaterScale));
        for (salinity, origin) in [(5.0, Origin::Unknown), (35.0, Origin::Seawater)] {
            assert!(converted(salinity, origin, scale).is_ok(), "S {salinity} {origin:?}");
        }
        assert_eq!(
            sea(12.0, 35.0).and_then(|eq| s::ph_nbs(&eq, f64::NAN, scale)),
            Err(ChemError::NonFinite)
        );
    }
    for (salinity, origin) in [(0.0, Origin::Unknown), (20.0, Origin::SaltAdded)] {
        assert_eq!(converted(salinity, origin, PhScale::Nbs), Ok(8.0));
    }
    let fresh = f::equilibria_v3(12.0, 0.0, Some(80.0), Ions::default());
    assert!(fresh.is_ok_and(|eq| !s::converts(&eq, PhScale::Total) && s::converts(&eq, PhScale::Nbs)));
    // Formula 1 (golden v1's, never the application's) takes them from 5 ‰ too, with its own offset.
    assert!(c::equilibria(12.0, 35.0).is_ok_and(|eq| s::converts(&eq, PhScale::Total)));
    assert!(c::equilibria(12.0, 3.0).is_ok_and(|eq| !s::converts(&eq, PhScale::Total)));
}

#[test]
fn a_salt_added_water_never_takes_another_scale() {
    // The independent review of 2026-11-16, R4. Fresh water salted with NaCl has no sulfate and no fluoride, at any
    // salinity (the module's rule). Past the Davies limit (about 28.4 ‰ as NaCl) its constants are worked out by the
    // sea path, for want of another, and `converts` took that for sea water: S 29, 30 and 35 were converted with sea
    // water's sulfate (12 °C, total 8.00 -> 8.1372 at S 30). It is refused at every salinity, both ways; the NBS pH,
    // the default, is the pH itself as before.
    let salted = |salinity: f64| {
        let ions = Ions {
            origin: Origin::SaltAdded,
            ..Ions::default()
        };
        f::equilibria_v3(12.0, salinity, Some(80.0), ions)
    };
    for salinity in [5.0, 20.0, 28.0, 28.4, 28.5, 29.0, 30.0, 35.0, 40.0] {
        let eq = salted(salinity);
        assert!(eq.is_ok(), "S {salinity}");
        for scale in [PhScale::Total, PhScale::Seawater, PhScale::Free] {
            assert!(eq.is_ok_and(|eq| !s::converts(&eq, scale)), "S {salinity} {scale:?}");
            assert_eq!(
                eq.and_then(|eq| s::ph_nbs(&eq, 8.0, scale)),
                Err(ChemError::SeawaterScale),
                "S {salinity} {scale:?}"
            );
            assert_eq!(
                eq.and_then(|eq| s::ph_on(&eq, 8.0, scale)),
                Err(ChemError::SeawaterScale),
                "S {salinity} {scale:?}"
            );
        }
        assert!(eq.is_ok_and(|eq| s::converts(&eq, PhScale::Nbs)));
        assert_eq!(eq.and_then(|eq| s::ph_nbs(&eq, 8.0, PhScale::Nbs)), Ok(8.0));
    }
    // The water the review measured is one the sea path works out (past the Davies limit): the refusal is the
    // origin's, not the path's.
    assert!(salted(30.0).is_ok_and(|eq| eq.sea_weight >= 1.0 && eq.origin == Origin::SaltAdded));
    assert!(salted(20.0).is_ok_and(|eq| eq.sea_weight <= 0.0));
    // Sea water, said or not, is converted as before.
    for origin in [Origin::Unknown, Origin::Seawater] {
        let ions = Ions {
            origin,
            ..Ions::default()
        };
        for salinity in [29.0, 30.0, 35.0] {
            let eq = f::equilibria_v3(12.0, salinity, Some(80.0), ions);
            assert!(
                eq.is_ok_and(|eq| s::converts(&eq, PhScale::Total)),
                "S {salinity} {origin:?}"
            );
        }
    }
}

#[test]
fn the_hazard_and_its_size() {
    // What the selector is for: over 5 to 35 ‰ and 0 to 30 °C a total-scale pH is 0.10 to 0.14 below the NBS pH, and
    // typed as NBS it makes the judged NH₃ at pH 8 20 to 27 % too low.
    let (mut least, mut most) = (f64::INFINITY, f64::NEG_INFINITY);
    let (mut low_least, mut low_most) = (f64::INFINITY, f64::NEG_INFINITY);
    for temp_c in [0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0] {
        for salinity in [5.0, 10.0, 20.0, 30.0, 35.0] {
            let as_nbs = nbs(temp_c, salinity, 8.0, PhScale::Total);
            least = least.min(as_nbs - 8.0);
            most = most.max(as_nbs - 8.0);
            let low = sea(temp_c, salinity)
                .and_then(|eq| Ok(1.0 - eq.nh3_share(8.0)? / eq.nh3_share(as_nbs)?))
                .unwrap_or(f64::NAN);
            low_least = low_least.min(low);
            low_most = low_most.max(low);
        }
    }
    assert!(
        least > 0.10 && least < 0.105 && most > 0.14 && most < 0.145,
        "{least} to {most}"
    );
    assert!(
        low_least > 0.20 && low_least < 0.21 && low_most > 0.26 && low_most < 0.27,
        "{low_least} to {low_most}"
    );
}
