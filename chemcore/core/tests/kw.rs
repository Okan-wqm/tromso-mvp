//! The ion product of water (owner-approved correction, 2026-11-10, after the independent check of 2026-11-09). Formula 3
//! takes Millero's (1995) Kw on his seawater scale, converted to the free scale as K1, K2 and KNH4 are, in the sea path,
//! the band and the fresh path; formula 1 keeps, by name, the 2007 Guide's approximate total-scale value (golden v1), and
//! so does the basis the limits were set on, which is formula 1's.
use chemcore_core::chemistry::{self as c, Origin};
use chemcore_core::fresh::{self as f, Ions};
use chemcore_core::num::ChemError;

fn ln(value: Result<f64, ChemError>) -> f64 {
    value.map(libm::log).unwrap_or(f64::NAN)
}

fn pk(value: Result<f64, ChemError>) -> f64 {
    value.map(|k| -libm::log10(k)).unwrap_or(f64::NAN)
}

/// Kw on the free scale as formula 3 takes it: the seawater-scale value over [H⁺]SWS / [H⁺]free.
fn sws_over_free(temp_c: f64, salinity: f64) -> Result<f64, ChemError> {
    Ok(c::kw_sws(temp_c, salinity)? / c::free_to_sws(temp_c, salinity)?)
}

/// Kw on the free scale as formula 1 takes it: the Guide's total-scale value over [H⁺]total / [H⁺]free.
fn total_over_free(temp_c: f64, salinity: f64) -> Result<f64, ChemError> {
    Ok(c::kw_total(temp_c, salinity)? / c::free_to_total(temp_c, salinity)?)
}

#[test]
fn the_seawater_scale_kw_meets_the_guides_check_value() {
    // Dickson, Sabine & Christian (2007), Guide to Best Practices for Ocean CO2 Measurements, ch. 5, section 7.2.7, eq.
    // (62) with footnote 5: Millero's (1995) expression with 0.015 subtracted from its constant term (148.9802 becomes
    // 148.9652, "to convert, approximately, from the SWS pH scale used by Millero (1995) to the total hydrogen ion
    // scale") gives ln Kw = -30.434 at S 35 and 25 °C. Millero's own, on the seawater scale, is that plus 0.015.
    assert!((ln(c::kw_total(25.0, 35.0)) - -30.434).abs() < 5e-4);
    assert!((ln(c::kw_sws(25.0, 35.0)) - -30.419).abs() < 5e-4);
    for (temp_c, salinity) in [(0.0, 0.0), (12.0, 1.0), (25.0, 35.0), (40.0, 40.0)] {
        assert!((ln(c::kw_sws(temp_c, salinity)) - ln(c::kw_total(temp_c, salinity)) - 0.015).abs() < 1e-12);
    }
}

#[test]
fn at_a_salinity_of_0_it_is_pure_waters() {
    // pKw of pure water: 13.995 at 25 °C (the value the application's tests have held, farm/tests/test_deffeyes.py; the
    // tables in print were not opened for this change) and Harned & Owen's (1958) 13.9965 at 25 °C and 14.9435 at 0 °C
    // (as farm/tests/test_cold_water.py quotes them, with wateq4f's independent expression held there to 0.003 pK).
    // Millero's (1995) pure-water term gives 13.9946 and 14.9412: within 0.001 of the first and 0.003 of Harned & Owen.
    // The Guide's shifted constant leaves 14.0012 at 25 °C, 0.006 too high (-1.49 % in Kw): a sea-water approximation
    // taken into fresh water.
    assert!((pk(c::kw_sws(25.0, 0.0)) - 13.995).abs() < 0.001);
    assert!((pk(c::kw_sws(25.0, 0.0)) - 13.9965).abs() < 0.003);
    assert!((pk(c::kw_sws(0.0, 0.0)) - 14.9435).abs() < 0.003);
    assert!((pk(c::kw_total(25.0, 0.0)) - 14.0012).abs() < 0.0001);
}

#[test]
fn it_agrees_with_an_independent_implementation_of_millero_1995() {
    // PyCO2SYS 1.8.3.4 (Humphreys et al. 2022, Geosci. Model Dev. 15: 15), its seawater-scale Kw of Millero (1995) and
    // the same on the free scale: numbers only were compared (its code is GPL and was not copied): (°C, S, Kw on the
    // seawater scale, Kw on the free scale).
    for (temp_c, salinity, sws, free) in [
        (0.0, 0.0, 1.1450938414325627e-15, 1.1450938414325627e-15),
        (0.0, 35.0, 5.014193270915467e-15, 4.4925660760922815e-15),
        (10.0, 1.0, 4.1655632278895e-15, 4.051464743549687e-15),
        (10.0, 5.0, 6.150784033645522e-15, 5.744061815449534e-15),
        (25.0, 0.0, 1.0124026936165129e-14, 1.0124026936165129e-14),
        (25.0, 35.0, 6.155507249814314e-14, 4.6974681043988175e-14),
        (40.0, 40.0, 2.378816964913356e-13, 1.5745841610347962e-13),
    ] {
        let found = c::kw_sws(temp_c, salinity).unwrap_or(f64::NAN);
        assert!(
            ((found - sws) / sws).abs() < 1e-12,
            "{temp_c} °C, S {salinity}: {found} against {sws}"
        );
        let found = c::kw_free(temp_c, salinity).unwrap_or(f64::NAN);
        assert!(
            ((found - free) / free).abs() < 1e-12,
            "{temp_c} °C, S {salinity}: {found} against {free}"
        );
    }
}

#[test]
fn formula_3_takes_it_on_the_sea_path() {
    for (temp_c, salinity) in [(2.0, 5.0), (12.0, 10.0), (25.0, 35.0), (40.0, 40.0)] {
        let eq = f::equilibria_v3(temp_c, salinity, Some(100.0), Ions::default());
        let expected = sws_over_free(temp_c, salinity);
        assert!(
            matches!((eq, expected), (Ok(eq), Ok(expected)) if eq.kw == expected && eq.formula == 3),
            "{temp_c} °C, S {salinity}"
        );
        assert_eq!(c::kw_free(temp_c, salinity), expected);
    }
}

#[test]
fn formula_3_takes_it_on_the_fresh_path() {
    // Nothing measured: an ionic strength of 0, so Kw is pure water's own, 13.995 at 25 °C.
    let ideal = f::equilibria_v3(25.0, 0.0, None, Ions::default());
    assert!(ideal.is_ok_and(|eq| Ok(eq.kw) == c::kw_sws(25.0, 0.0) && (-libm::log10(eq.kw) - 13.995).abs() < 0.001));
    // With ions: Kw° / γ₁² (H⁺ and OH⁻ are both monovalent).
    let ions = Ions {
        conductivity_25_us_cm: Some(1000.0),
        hardness_mg_l: None,
        origin: Origin::Unknown,
        phosphate_p_mg_l: None,
    };
    for temp_c in [2.0, 12.0, 25.0] {
        let eq = f::equilibria_v3(temp_c, 0.0, Some(80.0), ions);
        let gamma = f::davies_log_gamma(temp_c, 1.6e-5 * 1000.0, 1.0).map(|log| libm::pow(10.0, 2.0 * log));
        let pure = c::kw_sws(temp_c, 0.0);
        assert!(
            matches!((eq, gamma, pure), (Ok(eq), Ok(gamma), Ok(pure)) if ((eq.kw - pure / gamma) / eq.kw).abs() < 1e-13)
        );
    }
}

#[test]
fn formula_3_takes_it_in_the_band() {
    // Between 1 and 5 ‰ each constant is the geometric blend of the two paths: both now hold Millero's Kw.
    for salinity in [2.0, 3.0, 4.5] {
        let weight = f::sea_weight(salinity);
        let band = f::equilibria_v3(12.0, salinity, Some(120.0), Ions::default());
        let fresh = f::fresh_equilibria(12.0, salinity, Some(120.0), Ions::default());
        let sea = sws_over_free(12.0, salinity);
        assert!(matches!((band, fresh, sea), (Ok(band), Ok(fresh), Ok(sea))
            if ((band.kw - libm::exp((1.0 - weight) * libm::log(fresh.kw) + weight * libm::log(sea))) / band.kw).abs()
                < 1e-12));
        let gamma = f::davies_log_gamma(12.0, fresh.map(|eq| eq.ionic_strength).unwrap_or(f64::NAN), 1.0)
            .map(|log| libm::pow(10.0, 2.0 * log));
        let pure = c::kw_sws(12.0, 0.0);
        assert!(matches!((fresh, gamma, pure), (Ok(fresh), Ok(gamma), Ok(pure))
            if ((fresh.kw - pure / gamma) / fresh.kw).abs() < 1e-13));
    }
}

#[test]
fn formula_1_keeps_the_guides_kw_bit_for_bit() {
    for (temp_c, salinity) in [(12.0, 0.0), (2.0, 0.5), (12.0, 3.0), (25.0, 35.0), (40.0, 40.0)] {
        let expected = total_over_free(temp_c, salinity);
        assert!(matches!((c::equilibria(temp_c, salinity), expected), (Ok(eq), Ok(expected)) if eq.kw == expected));
        let named = f::water_equilibria(1, temp_c, salinity, Some(80.0), Ions::default());
        assert!(matches!((named, expected), (Ok(eq), Ok(expected)) if eq.kw == expected && eq.formula == 1));
    }
}

#[test]
fn the_basis_the_limits_were_set_on_keeps_formula_1s_kw() {
    // The basis is formula 1's (the ideal water up to 1 ‰, its seawater constants from 5 ‰, blended between): a judged
    // CO₂ is the larger of it and the corrected one, so it never falls below formula 1's, bit for bit.
    for temp_c in [2.0, 12.0, 25.0] {
        let fresh = f::equilibria_v3(temp_c, 0.0, Some(80.0), Ions::default());
        let ideal = total_over_free(temp_c, 0.0);
        assert!(matches!((fresh.map(|eq| eq.limits_basis), ideal), (Ok(Some(basis)), Ok(ideal)) if basis.kw == ideal));
        let sea = f::equilibria_v3(temp_c, 35.0, Some(115.0), Ions::default());
        let one = total_over_free(temp_c, 35.0);
        assert!(matches!((sea.map(|eq| eq.limits_basis), one), (Ok(Some(basis)), Ok(one)) if basis.kw == one));
        let band = f::equilibria_v3(temp_c, 3.0, Some(115.0), Ions::default());
        let blended = total_over_free(temp_c, 3.0).map(|sea| libm::exp(0.5 * libm::log(sea)));
        assert!(
            matches!((band.map(|eq| eq.limits_basis), ideal, blended), (Ok(Some(basis)), Ok(ideal), Ok(blended))
            if ((basis.kw - libm::exp(0.5 * libm::log(ideal)) * blended) / basis.kw).abs() < 1e-12)
        );
    }
}
