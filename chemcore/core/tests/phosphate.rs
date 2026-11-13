//! The optional phosphate (PO₄-P) of a water (the independent check of 2026-11-09, hypothesis 12a; owner-approved
//! 2026-11-10; chemcore/findings/phosphate.md). Phosphate is part of the alkalinity a titration measures. Without it the
//! water's own CO₂ of a pH and an alkalinity is too high (the safe side), and what a dose or a stripping does is worked
//! out without the phosphate's buffer: the pH after it too high and the CO₂ after it far too low (the unsafe side).
//! With a PO₄-P given its alkalinity is counted: [HPO₄²⁻] + 2 [PO₄³⁻] − [H₃PO₄] (Dickson 1981, as Dickson, Sabine &
//! Christian 2007 give it, ch. 2), with Millero's (1995) constants. Without one nothing is read and nothing moves.
use chemcore_core::analysis::{self as a, Limits, Water};
use chemcore_core::chemistry::{self as c, Basis, Equilibria, Origin};
use chemcore_core::fresh::{self as f, Ions};
use chemcore_core::geometry as g;
use chemcore_core::num::ChemError;

fn ions(phosphate: Option<f64>, origin: Origin) -> Ions {
    Ions {
        phosphate_p_mg_l: phosphate,
        origin,
        ..Ions::default()
    }
}

fn water(temp_c: f64, salinity: f64, alkalinity_mg_l: f64, phosphate: Option<f64>) -> Result<Equilibria, ChemError> {
    f::equilibria_v3(
        temp_c,
        salinity,
        Some(alkalinity_mg_l),
        ions(phosphate, Origin::Unknown),
    )
}

#[test]
fn the_constants_meet_the_guides_check_values_and_pure_waters() {
    // Dickson, Sabine & Christian (2007), ch. 5, eq. 49, 52, 55: at S 35 and 25 °C, on the total scale, ln K1P = −3.71,
    // ln K2P = −13.727, ln K3P = −20.24. Ours are Millero's on his seawater scale (the Guide's with the 0.015 of its
    // footnote 5 put back): over [H⁺]SWS / [H⁺]total they are the Guide's within its approximate shift (0.006).
    let to_total = c::free_to_sws(25.0, 35.0).unwrap_or(f64::NAN) / c::free_to_total(25.0, 35.0).unwrap_or(f64::NAN);
    for (constant, wanted, within) in [
        (c::k1p_sws(25.0, 35.0), -3.71, 0.011),
        (c::k2p_sws(25.0, 35.0), -13.727, 0.0065),
        (c::k3p_sws(25.0, 35.0), -20.24, 0.011),
    ] {
        let total = constant.map_or(f64::NAN, |k| libm::log(k / to_total));
        assert!((total - wanted).abs() < within, "{total} against {wanted}");
        // And on the seawater scale itself, the Guide's value plus exactly its 0.015.
        let sws = constant.map_or(f64::NAN, libm::log);
        assert!((sws - 0.015 - wanted).abs() < within, "{sws}");
    }
    // At S 0 they are phosphoric acid's in pure water at 25 °C: pK 2.149, 7.200, 12.345 (handbooks: about 2.15, 7.20,
    // 12.3 to 12.4).
    for (constant, pk) in [
        (c::k1p_sws(25.0, 0.0), 2.1487),
        (c::k2p_sws(25.0, 0.0), 7.1998),
        (c::k3p_sws(25.0, 0.0), 12.3449),
    ] {
        let found = constant.map_or(f64::NAN, |k| -libm::log10(k));
        assert!((found - pk).abs() < 0.0005, "{found} against {pk}");
    }
}

#[test]
fn without_a_phosphate_nothing_is_read_and_nothing_moves() {
    // None and 0 are the water as it always was: the same equilibria (every field), the same pH lines bit for bit.
    for temp_c in [2.0, 12.0, 25.0] {
        for salinity in [0.0, 0.5, 3.0, 5.0, 35.0] {
            for origin in [Origin::Unknown, Origin::SaltAdded] {
                let bare = f::equilibria_v3(temp_c, salinity, Some(80.0), ions(None, origin));
                let zero = f::equilibria_v3(temp_c, salinity, Some(80.0), ions(Some(0.0), origin));
                assert!(bare.is_ok());
                assert_eq!(bare, zero);
                assert!(bare.is_ok_and(|eq| eq.phosphate == 0.0 && eq.k1p == 0.0 && eq.k2p == 0.0 && eq.k3p == 0.0));
                assert_eq!(bare.and_then(|eq| eq.phosphate_alkalinity(1e-7)), Ok(0.0));
            }
        }
    }
    // Formula 1 does not read it (golden v1).
    let one = f::water_equilibria(1, 12.0, 1.0, Some(80.0), ions(Some(10.0), Origin::Unknown));
    assert_eq!(one, c::equilibria(12.0, 1.0));
    // A negative or a non-finite phosphate is refused.
    assert_eq!(water(12.0, 0.0, 80.0, Some(-1.0)), Err(ChemError::Domain));
    assert_eq!(water(12.0, 0.0, 80.0, Some(f64::NAN)), Err(ChemError::NonFinite));
}

#[test]
fn the_phosphates_alkalinity_is_its_species_by_the_definition() {
    // 10 mg/L as P is 0.32285 mmol/L (P 30.973762). At each pH the alkalinity it holds is [HPO₄²⁻] + 2 [PO₄³⁻] −
    // [H₃PO₄], the species worked out here one by one from the water's constants.
    for (temp_c, salinity) in [(15.0, 0.0), (15.0, 3.0), (10.0, 35.0)] {
        let found = water(temp_c, salinity, 100.0, Some(10.0));
        assert!(found.is_ok_and(|eq| (eq.phosphate - 10.0 / 30.973762 / 1000.0).abs() < 1e-18));
        let Ok(eq) = found else { continue };
        for ph in [4.0, 6.5, 7.0, 7.2, 7.5, 8.0, 9.0] {
            let h = eq.hydrogen(ph).unwrap_or(f64::NAN);
            let (k1, k2, k3) = (eq.k1p, eq.k2p, eq.k3p);
            let whole = h * h * h + k1 * h * h + k1 * k2 * h + k1 * k2 * k3;
            let (h3po4, hpo4, po4) = (h * h * h / whole, k1 * k2 * h / whole, k1 * k2 * k3 / whole);
            let wanted = eq.phosphate * (hpo4 + 2.0 * po4 - h3po4);
            let held = eq.phosphate_alkalinity(h).unwrap_or(f64::NAN);
            assert!((held - wanted).abs() <= 1e-15 * eq.phosphate, "{held} against {wanted}");
            // It is the whole difference of the pH line's intercept (meq/L); the slope does not move.
            let bare = water(temp_c, salinity, 100.0, None).and_then(|bare| bare.isoline(ph));
            let with = eq.isoline(ph);
            let (slope, intercept) = with.unwrap_or((f64::NAN, f64::NAN));
            let (bare_slope, bare_intercept) = bare.unwrap_or((f64::NAN, f64::NAN));
            assert_eq!(slope, bare_slope);
            assert!((intercept - bare_intercept - 1000.0 * held).abs() < 1e-12);
        }
    }
    // In ion-free fresh water at 25 °C and pH 7.2 (pK2), half the phosphate is HPO₄²⁻: 0.5 of the total as alkalinity.
    let ideal = f::equilibria_v3(25.0, 0.0, None, ions(Some(10.0), Origin::Unknown));
    let share = ideal
        .and_then(|eq| Ok(eq.phosphate_alkalinity(eq.hydrogen(7.1998)?)? / eq.phosphate))
        .unwrap_or(f64::NAN);
    assert!((share - 0.5).abs() < 0.001, "{share}");
    // Below about pH 4.67, (pK1 + pK2) / 2, it is negative.
    let sign = |ph: f64| {
        ideal
            .and_then(|eq| eq.phosphate_alkalinity(eq.hydrogen(ph)?))
            .unwrap_or(f64::NAN)
    };
    assert!(sign(4.6) < 0.0 && sign(4.75) > 0.0);
}

#[test]
fn the_fresh_paths_constants_carry_the_davies_coefficients() {
    // K1P = K1P° / γ₁², K2P = K2P° / γ₂, K3P = K3P° γ₂ / (γ₁ γ₃), log γ_z = z² log γ₁: 10^(2, 4, 6 log γ₁) under them.
    let found = f::equilibria_v3(12.0, 0.0, Some(100.0), ions(Some(5.0), Origin::Unknown));
    assert!(found.is_ok());
    let Ok(eq) = found else { return };
    let one = f::davies_log_gamma(12.0, eq.ionic_strength, 1.0).unwrap_or(f64::NAN);
    assert!(one < 0.0);
    for (held, pure, power) in [
        (eq.k1p, c::k1p_sws(12.0, 0.0), 2.0),
        (eq.k2p, c::k2p_sws(12.0, 0.0), 4.0),
        (eq.k3p, c::k3p_sws(12.0, 0.0), 6.0),
    ] {
        let wanted = pure.unwrap_or(f64::NAN) / libm::pow(10.0, power * one);
        assert!((held / wanted - 1.0).abs() < 1e-14, "{held} against {wanted}");
    }
    // From 5 ‰ they are the seawater-scale constants over [H⁺]SWS / [H⁺]free; in the band between, in between.
    let sea = water(12.0, 35.0, 115.0, Some(5.0));
    let to_sws = c::free_to_sws(12.0, 35.0).unwrap_or(f64::NAN);
    assert!(sea.is_ok_and(|eq| (eq.k2p / (c::k2p_sws(12.0, 35.0).unwrap_or(f64::NAN) / to_sws) - 1.0).abs() < 1e-14));
    let k2 = |salinity: f64| water(12.0, salinity, 100.0, Some(5.0)).map_or(f64::NAN, |eq| eq.k2p);
    assert!(k2(1.0) < k2(3.0) && k2(3.0) < k2(5.0));
    assert!((k2(4.999999) / k2(5.0) - 1.0).abs() < 1e-5 && (k2(1.000001) / k2(1.0) - 1.0).abs() < 1e-5);
}

#[test]
fn the_waters_own_co2_is_lower_by_it_and_the_judged_co2_never_is() {
    // The independent check's typical water (15 °C, 2 meq/L, pH 7.0, 10 mg/L PO₄-P): without the phosphate the CO₂ of a
    // pH and an alkalinity was 6 % too high in fresh water and 17 % in sea water (PyCO2SYS). The water's own CO₂ now
    // counts it; every CO₂ judgement holds the value without it beside the limits' basis and takes the largest.
    let mut waters = 0;
    for temp_c in [5.0, 15.0, 25.0] {
        for salinity in [0.0, 0.5, 3.0, 5.0, 15.0, 35.0] {
            for alkalinity in [1.0, 2.0, 4.0] {
                for phosphate in [1.0, 3.0, 10.0, 30.0] {
                    let mg_l = alkalinity * c::MG_CACO3_PER_MEQ;
                    let (Ok(with), Ok(bare)) = (
                        water(temp_c, salinity, mg_l, Some(phosphate)),
                        water(temp_c, salinity, mg_l, None),
                    ) else {
                        assert!(water(temp_c, salinity, mg_l, None).is_ok());
                        continue;
                    };
                    for ph in [6.5, 7.0, 7.5, 8.0] {
                        let Ok(own) = with.co2_corrected(alkalinity, ph) else {
                            // The phosphate alone is that much alkalinity: refused, never a CO₂ below 0.
                            assert_eq!(with.possible(alkalinity, ph), Ok(false));
                            continue;
                        };
                        let before = bare.co2_corrected(alkalinity, ph).unwrap_or(f64::NAN);
                        assert!(own < before, "{temp_c} °C, S {salinity}, {alkalinity} meq/L, pH {ph}");
                        let judged = with.co2_judged(alkalinity, ph, own).map_or(f64::NAN, |found| found.0);
                        let judged_before = bare
                            .co2_judged(alkalinity, ph, before)
                            .map_or(f64::NAN, |found| found.0);
                        assert_eq!(judged.to_bits(), judged_before.to_bits());
                        assert_eq!(
                            with.co2_judged(alkalinity, ph, own).map(|found| found.1),
                            Ok(Basis::Limits)
                        );
                        // The borders: the pH below which the judged CO₂ passes a limit, and the alkalinity at which
                        // it is one, are the water's without the phosphate.
                        assert_eq!(with.ph_where_co2(alkalinity, 0.3), bare.ph_where_co2(alkalinity, 0.3));
                        assert_eq!(with.alkalinity_where_co2(0.3, ph), bare.alkalinity_where_co2(0.3, ph));
                        waters += 1;
                    }
                }
            }
        }
    }
    assert!(waters > 700, "{waters}");
    // The size, at the check's typical water (fresh, nothing but the alkalinity measured: the ionic strength its own).
    let size = |salinity: f64| {
        let alkalinity = 2.0;
        let mg_l = alkalinity * c::MG_CACO3_PER_MEQ;
        let with = water(15.0, salinity, mg_l, Some(10.0)).and_then(|eq| eq.co2_corrected(alkalinity, 7.0));
        let bare = water(15.0, salinity, mg_l, None).and_then(|eq| eq.co2_corrected(alkalinity, 7.0));
        bare.unwrap_or(f64::NAN) / with.unwrap_or(f64::NAN) - 1.0
    };
    assert!((size(0.0) - 0.06).abs() < 0.015, "{}", size(0.0));
    assert!((size(35.0) - 0.17).abs() < 0.02, "{}", size(35.0));
}

#[test]
fn a_dose_meets_the_phosphates_buffer() {
    // The unsafe side the input closes (the check: 10 mg/L, fresh water, 15 °C, 2 meq/L, pH 7.2; after 0.3 mmol/L of DIC
    // is stripped the pH was predicted 0.42 too high and the CO₂ 57 % too low; after 0.5 meq/L of base 0.55 and 71 %).
    let mg_l = 2.0 * c::MG_CACO3_PER_MEQ;
    let with = f::equilibria_v3(15.0, 0.0, None, ions(Some(10.0), Origin::Unknown));
    let bare = f::equilibria_v3(15.0, 0.0, None, ions(None, Origin::Unknown));
    assert!(with.is_ok() && bare.is_ok() && mg_l > 0.0);
    let (Ok(with), Ok(bare)) = (with, bare) else { return };
    let after = |eq: &Equilibria, strip: f64, base: f64| {
        let dic = eq.dic(2.0, 7.2).unwrap_or(f64::NAN) - strip;
        let ph = eq.ph_at(dic, 2.0 + base).ok().flatten().unwrap_or(f64::NAN);
        (ph, eq.co2(dic, ph).unwrap_or(f64::NAN))
    };
    for (strip, base, ph_high, co2_low) in [(0.3, 0.0, 0.42, 0.57), (0.0, 0.5, 0.55, 0.71)] {
        let (ph, co2) = after(&with, strip, base);
        let (blind_ph, blind_co2) = after(&bare, strip, base);
        assert!((blind_ph - ph - ph_high).abs() < 0.03, "{}", blind_ph - ph);
        assert!(
            (1.0 - blind_co2 / co2 - co2_low).abs() < 0.03,
            "{}",
            1.0 - blind_co2 / co2
        );
        // There and back: the pH found gives the alkalinity it was found for.
        assert!(
            with.alkalinity(with.dic(2.0, 7.2).unwrap_or(f64::NAN) - strip, ph)
                .is_ok_and(|alk| (alk - 2.0 - base).abs() < 1e-8)
        );
    }
}

#[test]
fn a_water_whose_phosphate_alone_is_its_alkalinity_cannot_be() {
    // 10 mg/L as P holds 0.2 meq/L at pH 7.5 in fresh water; a water of 0.2 meq/L (10 mg/L as CaCO₃) at that pH has
    // no carbonate left: refused by the one rule, with its floor as the reason, never worked out below 0.
    let found = water(15.0, 0.0, 10.0, Some(10.0));
    assert!(found.is_ok());
    let Ok(eq) = found else { return };
    let alkalinity = 10.0 / c::MG_CACO3_PER_MEQ;
    assert_eq!(eq.possible(alkalinity, 7.5), Ok(false));
    assert_eq!(eq.dic(alkalinity, 7.5), Err(ChemError::ImpossibleWater));
    let why = a::why_impossible(15.0, 0.0, 7.5, 10.0, 3, ions(Some(10.0), Origin::Unknown));
    assert!(why.is_ok_and(|floor| floor.is_some_and(|floor| floor > 10.0)));
    assert_eq!(
        a::why_impossible(15.0, 0.0, 7.5, 10.0, 3, ions(None, Origin::Unknown)),
        Ok(None)
    );
    let sample = Water {
        temperature_c: 15.0,
        salinity_ppt: 0.0,
        ph: 7.5,
        alkalinity_mg_l: 10.0,
        tan_mg_l: None,
        total_sulfide_ug_l: None,
        calcium_mg_l: None,
        oxygen_mg_l: None,
        conductivity_25_us_cm: None,
        hardness_mg_l: None,
        origin: Origin::Unknown,
        formula: 3,
        phosphate_p_mg_l: Some(10.0),
    };
    assert_eq!(
        a::analyse(&sample, &Limits::default(), None, 1.0).map(|_| ()),
        Err(ChemError::ImpossibleWater)
    );
    let fine = Water {
        alkalinity_mg_l: 100.0,
        ..sample
    };
    let analysis = a::analyse(&fine, &Limits::default(), None, 1.0);
    let plain = a::analyse(
        &Water {
            phosphate_p_mg_l: None,
            ..fine
        },
        &Limits::default(),
        None,
        1.0,
    );
    assert!(analysis.is_ok() && plain.is_ok());
    let (Ok(analysis), Ok(plain)) = (analysis, plain) else {
        return;
    };
    // The judged CO₂ is the water's without the phosphate; the DIC and the corrected CO₂ are lower by it.
    assert_eq!(analysis.co2_mg_l.to_bits(), plain.co2_mg_l.to_bits());
    assert!(analysis.co2_corrected_mg_l < plain.co2_corrected_mg_l && analysis.dic < plain.dic);
    assert_eq!(analysis.nh3_share_pct.to_bits(), plain.nh3_share_pct.to_bits());
}

#[test]
fn the_charts_co2_curve_is_the_judged_one() {
    // With a phosphate the limits' basis and the water's own CO₂ are not in one ratio, so the chart draws the judged
    // curve itself: at every point of it the judged CO₂ is the limit, and it is the curve of the water without the
    // phosphate seen in the water's own (DIC, alkalinity).
    let chart = a::ChartBox {
        dic: 6.0,
        alkalinity: 6.0,
        dic_step: 1.0,
        alkalinity_step: 1.0,
    };
    let limit = 15.0 / c::MG_CO2_PER_MMOL;
    for salinity in [0.0, 3.0, 35.0] {
        let found = water(12.0, salinity, 100.0, Some(10.0));
        assert!(found.is_ok());
        let Ok(eq) = found else { continue };
        let curve = g::co2_curve_judged(&eq, limit, &chart);
        assert!(curve.is_ok());
        let Ok((points, _leaves_top)) = curve else { continue };
        assert_eq!(points.len(), g::SAMPLES + 1);
        let mut before = (f64::NEG_INFINITY, f64::NEG_INFINITY);
        for &(dic, alkalinity) in points.iter().skip(1).take(g::SAMPLES - 1) {
            assert!(dic > before.0 && alkalinity > before.1, "S {salinity}: not rising");
            before = (dic, alkalinity);
            let ph = eq.ph_at(dic, alkalinity).ok().flatten().unwrap_or(f64::NAN);
            let own = eq.co2(dic, ph).unwrap_or(f64::NAN);
            let judged = eq.co2_judged(alkalinity, ph, own).map_or(f64::NAN, |found| found.0);
            assert!(
                (judged / limit - 1.0).abs() < 1e-6,
                "S {salinity}: {judged} against {limit}"
            );
            assert!(own < limit);
        }
    }
}
