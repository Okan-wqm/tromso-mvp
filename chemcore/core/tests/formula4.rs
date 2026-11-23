//! Formula 4 (chemcore/core/src/formula4.rs; the water-chemistry audit's consensus of 2026-11-19 and the owner's decision,
//! Rule S): the step against the papers it is fitted to, Clegg & Whitfield's constant, and the owner's MUST: the judged
//! NH₃ and CO₂ never below the best estimate, by the margin U = 0.03 pH gives from 5 ‰, over sea water (S 5 to 40) at
//! 0 to 30 °C and land water (fresh and brackish) at 8 to 30 °C; nothing steps at 1 or 5 ‰; fresh water (S ≤ 1) judged
//! as formula 3 judged it; and the moves against formula 3 in brackish water that the consensus states. Outside the
//! MUST ranges what holds is held too (`outside_the_must_ranges_the_judged_values_stay_above_the_best_estimate`).
use chemcore_core::chemistry::{self as c, Basis, Equilibria, Origin};
use chemcore_core::formula4 as f4;
use chemcore_core::fresh::{self as f, Ions};
use chemcore_core::num::ChemError;
use chemcore_core::scale::{self as sc, PhScale};

const U: f64 = 0.03;

fn ions(conductivity: Option<f64>, hardness: Option<f64>, origin: Origin) -> Ions {
    Ions {
        conductivity_25_us_cm: conductivity,
        hardness_mg_l: hardness,
        origin,
        phosphate_p_mg_l: None,
    }
}

fn v4(temp_c: f64, salinity: f64, alkalinity: f64, ions: Ions) -> Equilibria {
    f4::equilibria_v4(temp_c, salinity, Some(alkalinity), ions)
        .unwrap_or_else(|error| unreachable!("{temp_c} °C, S {salinity}: {error:?}"))
}

fn v3(temp_c: f64, salinity: f64, alkalinity: f64, ions: Ions) -> Equilibria {
    f::equilibria_v3(temp_c, salinity, Some(alkalinity), ions)
        .unwrap_or_else(|error| unreachable!("{temp_c} °C, S {salinity}: {error:?}"))
}

fn odds(share: f64) -> f64 {
    share / (1.0 - share)
}

/// (judged NH₃ share, best NH₃ share, (judged CO₂ mmol/L, best CO₂ mmol/L)), the CO₂ None where no water has them.
type Judged = (f64, f64, Option<(f64, f64)>);

/// The judged and best NH₃ and CO₂ of a water at a pH and an alkalinity (mg/L).
fn judged(eq: &Equilibria, ph: f64, alkalinity_mg_l: f64) -> Result<Judged, ChemError> {
    let meq = alkalinity_mg_l / c::MG_CACO3_PER_MEQ;
    let co2 = if eq.possible(meq, ph)? {
        let own = eq.co2_corrected(meq, ph)?;
        Some((eq.co2_judged(meq, ph, own)?.0, own))
    } else {
        None
    };
    Ok((eq.nh3_share(ph)?, eq.nh3_share_corrected(ph)?, co2))
}

fn phs() -> impl Iterator<Item = f64> {
    (0..=30).map(|step| 6.0 + 0.1 * f64::from(step))
}

#[test]
fn the_formula_is_four_and_three_is_kept() {
    assert_eq!(chemcore_core::FORMULA_VERSION, 4);
    assert_eq!(chemcore_core::FORMULAS, [1, 3, 4]);
    assert_eq!(f4::FORMULA, 4);
    let eq = f::water_equilibria(4, 12.0, 34.0, Some(100.0), Ions::default());
    assert!(eq.is_ok_and(|eq| eq.formula == 4 && eq.sea_weight == 1.0));
    let eq = f::water_equilibria(4, 12.0, 3.0, Some(100.0), Ions::default());
    assert!(eq.is_ok_and(|eq| eq.formula == 4 && eq.sea_weight == 0.5));
    let eq = f::water_equilibria(4, 12.0, 0.0, Some(100.0), Ions::default());
    assert!(eq.is_ok_and(|eq| eq.formula == 4 && eq.sea_weight == 0.0));
    assert_eq!(
        f::water_equilibria(3, 12.0, 34.0, Some(100.0), Ions::default()),
        f::equilibria_v3(12.0, 34.0, Some(100.0), Ions::default())
    );
    assert_eq!(
        f::water_equilibria(5, 12.0, 34.0, None, Ions::default()),
        Err(ChemError::UnknownFormula)
    );
    assert_eq!(f4::PH_UNCERTAINTY, U);
}

#[test]
fn clegg_and_whitfield_on_the_free_scale_meets_pyco2sys() {
    // PyCO2SYS 1.8.3.4's ammonium constant on the free scale, mol per kg of solution (the K_NH4 panel's dump of
    // 2026-11-10, as chemcore/core/tests/nh3_guard.rs holds its own typing of the equation to it): (°C, S, free).
    for (temp_c, salinity, free) in [
        (0.0, 0.0, 8.270981103142548e-11),
        (0.0, 35.0, 6.339461138236505e-11),
        (10.0, 5.0, 1.7916674236860337e-10),
        (15.0, 0.5, 2.729047522613315e-10),
        (25.0, 0.0, 5.693705499509853e-10),
        (25.0, 35.0, 4.430297995529491e-10),
        (30.0, 20.0, 7.046154929368116e-10),
        (30.0, 35.0, 6.281348000036867e-10),
    ] {
        let found = c::k_nh4_cw95(temp_c, salinity).unwrap_or(f64::NAN);
        assert!(
            ((found - free) / free).abs() < 1e-12,
            "{temp_c} °C, S {salinity}: {found} against {free}"
        );
    }
    // Pure water: table 13's pK°, 9.2446 at 25 °C (Bates & Pinching 1949: 9.245), and eq. 18 at S 0 is it exactly.
    assert!((c::pk_nh4_cw95_pure(25.0).unwrap_or(f64::NAN) - 9.244605).abs() < 1e-12);
    for temp_c in [-2.0, 0.0, 12.0, 25.0, 40.0] {
        assert_eq!(c::pk_nh4_cw95_total(temp_c, 0.0), c::pk_nh4_cw95_pure(temp_c));
    }
    // Table 14 of the paper (total scale, molal; a sample of its printed cells): within its 0.00015 and the print's 0.001.
    for (kelvin, salinity, pk) in [
        (273.15, 10.0, 10.085),
        (273.15, 34.0, 10.139),
        (285.15, 20.0, 9.663),
        (285.15, 34.0, 9.687),
        (297.15, 10.0, 9.245),
        (297.15, 40.0, 9.272),
    ] {
        let found = c::pk_nh4_cw95_total(kelvin - 273.15, salinity).unwrap_or(f64::NAN);
        assert!(
            (found - pk).abs() < 0.0012,
            "{kelvin} K, S {salinity}: {found} against {pk}"
        );
    }
    assert_eq!(c::pk_nh4_cw95_total(12.0, -1.0), Err(ChemError::Domain));
}

/// Millero (1986), Limnol. Oceanogr. 31: 839, table 7: pH NBS − pH total (molal) at 25 °C.
const MILLERO: [(f64, f64); 10] = [
    (0.0, 0.053),
    (2.5, 0.094),
    (5.0, 0.134),
    (10.0, 0.135),
    (15.0, 0.142),
    (20.0, 0.149),
    (25.0, 0.150),
    (30.0, 0.152),
    (35.0, 0.154),
    (40.0, 0.141),
];

/// pH NBS − pH SWS (per kg of sea water) by Takahashi, Williams & Bos (1982), GEOSECS Pacific vol. 3, p. 80: the fit of
/// Culberson & Pytkowicz (1973), fH = 1.2948 − 0.002036 T + 4.607e-4 S² − 1.475e-6 S² T.
fn takahashi(temp_c: f64, salinity: f64) -> f64 {
    let t = temp_c + 273.15;
    -libm::log10(1.2948 - 0.002036 * t + 4.607e-4 * salinity * salinity - 1.475e-6 * salinity * salinity * t)
}

/// Formula 4's pH NBS − pH SWS (per kg of sea water).
fn step(temp_c: f64, salinity: f64) -> f64 {
    let to_sws = c::free_to_sws(temp_c, salinity).unwrap_or(f64::NAN);
    libm::log10(to_sws) - f4::ph_offset(temp_c, salinity).unwrap_or(f64::NAN)
}

#[test]
fn the_step_meets_millero_at_25_degrees_and_takahashi_from_0_to_30() {
    let mut worst: f64 = 0.0;
    for (salinity, measured) in MILLERO {
        let line = f4::nbs_minus_total_25(salinity).unwrap_or(f64::NAN);
        // The offset is the line's: −D − log₁₀ m + log₁₀ G at 25 °C.
        let implied = -f4::ph_offset(25.0, salinity).unwrap_or(f64::NAN) - libm::log10(1.0 - 0.001005 * salinity)
            + libm::log10(c::free_to_total(25.0, salinity).unwrap_or(f64::NAN));
        assert!((implied - line).abs() < 1e-12, "S {salinity}");
        if (5.0..=35.0).contains(&salinity) {
            worst = worst.max((line - measured).abs());
        } else if salinity < 5.0 {
            assert!(
                (line - measured).abs() < 1e-12,
                "the band's points are Millero's own: S {salinity}"
            );
        } else {
            // S 40, the line held at S 35: 0.015 above Millero's point (its NH₃ about 3.5 % low against it, under U).
            assert!((line - measured - 0.0152).abs() < 0.0005, "S 40: {}", line - measured);
        }
    }
    assert!(worst <= 0.0041, "against Millero, S 5 to 35: {worst}");
    let mut worst: f64 = 0.0;
    for temp_c in 0..=30 {
        for salinity in [30.0, 32.0, 34.0, 35.0] {
            worst = worst.max((step(f64::from(temp_c), salinity) - takahashi(f64::from(temp_c), salinity)).abs());
        }
    }
    // 0.0062 at 0 °C and S 35 (the prototype's least-squares line: 0.0061; the rounded line moves it by 0.0001).
    assert!(worst <= 0.0063, "against Takahashi, S 30 to 35, 0 to 30 °C: {worst}");
    // At S 20 it lies 0.010 to 0.014 below Takahashi's level (which is 0.009 above Millero's measurement there).
    for temp_c in [0.0, 4.0, 12.0, 25.0, 30.0] {
        let apart = step(temp_c, 20.0) - takahashi(temp_c, 20.0);
        assert!((-0.0145..=-0.0095).contains(&apart), "{temp_c} °C, S 20: {apart}");
    }
    // The line itself: 0.1306 + 0.00073 S from 5 ‰, held above 35, Millero's points joined below.
    assert_eq!(f4::nbs_minus_total_25(20.0), Ok(0.1306 + 0.00073 * 20.0));
    assert_eq!(f4::nbs_minus_total_25(38.0), f4::nbs_minus_total_25(35.0));
    let at = |s: f64| f4::nbs_minus_total_25(s).unwrap_or(f64::NAN);
    assert!((at(5.0 - 1e-9) - at(5.0)).abs() < 1e-10 && (at(2.5 - 1e-9) - at(2.5)).abs() < 1e-10);
}

#[test]
fn the_sea_path_is_formula_3s_but_for_the_step_and_the_ammonium_constant() {
    for temp_c in [0.0, 12.0, 25.0] {
        for salinity in [5.0, 20.0, 34.0, 40.0] {
            let (four, three) = (
                v4(temp_c, salinity, 100.0, Ions::default()),
                v3(temp_c, salinity, 100.0, Ions::default()),
            );
            assert_eq!(four.ph_offset, f4::ph_offset(temp_c, salinity).unwrap_or(f64::NAN));
            assert_eq!(four.k_nh4, c::k_nh4_cw95(temp_c, salinity).unwrap_or(f64::NAN));
            let same = Equilibria {
                ph_offset: three.ph_offset,
                k_nh4: three.k_nh4,
                formula: 3,
                limits_basis: three.limits_basis,
                ..four
            };
            assert_eq!(same, three, "{temp_c} °C, S {salinity}");
        }
    }
}

#[test]
fn sea_water_0_to_30_degrees_judged_nh3_and_co2_carry_the_margin_over_the_best_estimate() {
    // The owner's MUST for sea sites: S 5 to 40, 0 to 30 °C, pH 6 to 9, three alkalinities, sea water's origin said or
    // not. NH₃: [NH₃]/[NH₄⁺] judged over best is 10^0.03 exactly (+7.15 %); CO₂: +7.15 % up to the borate's share.
    let margin = libm::pow(10.0, U) - 1.0;
    let (mut co2_least, mut co2_most, mut cells): (f64, f64, u32) = (1.0, 0.0, 0);
    for temp_c in 0..=30 {
        for salinity in [5.0, 7.5, 10.0, 15.0, 20.0, 25.0, 30.0, 34.0, 35.0, 40.0] {
            for origin in [Origin::Unknown, Origin::Seawater] {
                for alkalinity in [50.0, 100.0, 200.0] {
                    let eq = v4(f64::from(temp_c), salinity, alkalinity, ions(None, None, origin));
                    assert_eq!(eq.nh3_basis(), Ok(Basis::Limits));
                    for ph in phs() {
                        let found = judged(&eq, ph, alkalinity);
                        assert!(found.is_ok(), "{temp_c} °C, S {salinity}, pH {ph}");
                        let Ok((nh3, best, co2)) = found else { continue };
                        let over = odds(nh3) / odds(best) - 1.0;
                        assert!(
                            (over - margin).abs() < 1e-9,
                            "{temp_c} °C, S {salinity}, pH {ph}: {over}"
                        );
                        assert!(nh3 > best);
                        if let Some((judged_co2, best_co2)) = co2 {
                            let over = judged_co2 / best_co2 - 1.0;
                            co2_least = co2_least.min(over);
                            co2_most = co2_most.max(over);
                            assert!(over >= margin - 1e-9, "{temp_c} °C, S {salinity}, pH {ph}: CO₂ {over}");
                        }
                        cells += 1;
                    }
                }
            }
        }
    }
    assert_eq!(cells, 31 * 10 * 2 * 3 * 31);
    // +7.15 % at least; the most where the borate and the carbonate hold a large share (pH 9, little alkalinity).
    assert!(
        co2_least >= margin - 1e-9 && co2_most < 0.20,
        "{co2_least} to {co2_most}"
    );
}

#[test]
fn land_water_8_to_30_degrees_judged_nh3_and_co2_never_below_the_best_estimate() {
    // The owner's MUST for land sites: fresh and brackish water (S 0 to 5) of every kind of input, 8 to 30 °C.
    let waters = [
        ions(None, None, Origin::Unknown),
        ions(Some(50.0), None, Origin::Unknown),
        ions(Some(1000.0), None, Origin::Unknown),
        ions(Some(3000.0), Some(300.0), Origin::Unknown),
        ions(None, Some(150.0), Origin::Unknown),
        ions(None, None, Origin::Seawater),
        ions(None, None, Origin::SaltAdded),
        ions(Some(3000.0), None, Origin::SaltAdded),
    ];
    for temp_c in 8..=30 {
        for salinity in [0.0, 0.3, 0.5, 1.0, 1.5, 2.5, 3.0, 4.0, 4.99, 5.0, 8.0] {
            for water in waters {
                for alkalinity in [5.0, 50.0, 100.0, 200.0] {
                    let eq = v4(f64::from(temp_c), salinity, alkalinity, water);
                    for ph in phs() {
                        let found = judged(&eq, ph, alkalinity);
                        assert!(found.is_ok(), "{temp_c} °C, S {salinity}, pH {ph}");
                        let Ok((nh3, best, co2)) = found else { continue };
                        assert!(nh3 >= best, "{temp_c} °C, S {salinity}, {water:?}, pH {ph}");
                        if let Some((judged_co2, best_co2)) = co2 {
                            assert!(judged_co2 >= best_co2, "{temp_c} °C, S {salinity}, {water:?}, pH {ph}");
                        }
                    }
                }
            }
        }
    }
    // With nothing measured (ionic strength 0) the best estimate's K_NH4 judges where it is above the ideal water's
    // (Clegg & Whitfield's pure-water pK against Yao & Millero's: up to 0.5 % at 0 °C); with any ion measured the ideal.
    let bare = v4(12.0, 0.0, 0.0, Ions::default());
    assert_eq!(bare.ionic_strength, 0.0);
    let over = bare.nh3_share(7.6).unwrap_or(f64::NAN)
        / v3(12.0, 0.0, 0.0, Ions::default()).nh3_share(7.6).unwrap_or(f64::NAN)
        - 1.0;
    assert!((0.0..0.005).contains(&over), "{over}");
}

#[test]
fn fresh_water_is_judged_as_formula_3_judged_it() {
    // Up to 1 ‰ the basis is formula 3's ideal water, unchanged: the judged CO₂ and its borders bit for bit, the judged
    // NH₃ the larger of formula 3's and the best estimate, which is formula 3's wherever the ideal is the larger (every
    // water with an ion measured to an ionic strength of 1e-4 or more). Every constant but K_NH4 bit for bit.
    let waters = [
        ions(None, None, Origin::Unknown),
        ions(Some(300.0), None, Origin::Unknown),
        ions(Some(3000.0), Some(300.0), Origin::Unknown),
        ions(None, Some(150.0), Origin::Unknown),
        ions(None, None, Origin::SaltAdded),
        ions(Some(1000.0), None, Origin::Seawater),
    ];
    let mut same = 0;
    for temp_c in [-2.0, 0.0, 4.0, 8.0, 12.0, 20.0, 30.0, 40.0] {
        for salinity in [0.0, 0.2, 0.5, 0.99, 1.0] {
            for water in waters {
                for alkalinity in [0.0, 5.0, 100.0] {
                    let (four, three) = (
                        v4(temp_c, salinity, alkalinity, water),
                        v3(temp_c, salinity, alkalinity, water),
                    );
                    assert_eq!(four.limits_basis, three.limits_basis);
                    assert_eq!(
                        Equilibria {
                            k_nh4: three.k_nh4,
                            formula: 3,
                            ..four
                        },
                        three
                    );
                    let meq = alkalinity / c::MG_CACO3_PER_MEQ;
                    for ph in [6.0, 6.5, 7.0, 7.6, 8.0, 8.5, 9.0] {
                        let (n4, n3) = (four.nh3_share(ph), three.nh3_share(ph));
                        let best = four.nh3_share_corrected(ph);
                        assert_eq!(n4, Ok(n3.unwrap_or(f64::NAN).max(best.unwrap_or(f64::NAN))));
                        if four.ionic_strength >= 1e-4 {
                            assert_eq!(n4, n3, "{temp_c} °C, S {salinity}, {water:?}, pH {ph}");
                            same += 1;
                        }
                        if four.possible(meq, ph).unwrap_or(false) {
                            let own = four.co2_corrected(meq, ph);
                            assert_eq!(own, three.co2_corrected(meq, ph));
                            let own = own.unwrap_or(f64::NAN);
                            assert_eq!(four.co2_judged(meq, ph, own), three.co2_judged(meq, ph, own));
                        }
                        let co2 = 15.0 / c::MG_CO2_PER_MMOL;
                        assert_eq!(four.ph_where_co2(meq, co2), three.ph_where_co2(meq, co2));
                    }
                }
            }
        }
    }
    assert!(same > 3000, "{same}");
}

#[test]
fn nothing_steps_at_1_or_5_permil_nor_anywhere_from_0_to_40() {
    // pH 7.6, alkalinity 100 mg/L, S 0 to 40 in steps of 0.05 ‰: the judged NH₃ and CO₂ change by less than 0.5 % a step
    // (the band's slope; the debate's prototype: 0.44 % at most), and across each edge by nothing that shows.
    let meq = 100.0 / c::MG_CACO3_PER_MEQ;
    let value = |temp_c: f64, salinity: f64| -> (f64, f64) {
        let eq = v4(temp_c, salinity, 100.0, Ions::default());
        let own = eq.co2_corrected(meq, 7.6).unwrap_or(f64::NAN);
        (
            eq.nh3_share(7.6).unwrap_or(f64::NAN),
            eq.co2_judged(meq, 7.6, own).map_or(f64::NAN, |found| found.0),
        )
    };
    for temp_c in [0.0, 4.0, 8.0, 12.0, 16.0, 20.0, 25.0, 30.0] {
        let mut before = value(temp_c, 0.0);
        let mut worst: f64 = 0.0;
        for step in 1..=800 {
            let now = value(temp_c, 0.05 * f64::from(step));
            worst = worst
                .max((now.0 / before.0 - 1.0).abs())
                .max((now.1 / before.1 - 1.0).abs());
            before = now;
        }
        assert!(worst < 0.005, "{temp_c} °C: {worst}");
        for edge in [f::FRESH_UP_TO, f::SEA_FROM] {
            let (below, above) = (value(temp_c, edge - 1e-9), value(temp_c, edge + 1e-9));
            assert!(
                (above.0 / below.0 - 1.0).abs() < 1e-7 && (above.1 / below.1 - 1.0).abs() < 1e-7,
                "{temp_c} °C, S {edge}"
            );
        }
    }
}

#[test]
fn brackish_and_sea_water_move_against_formula_3_as_the_consensus_says() {
    // Judged NH₃, formula 4 against formula 3, 0 to 30 °C, pH 6.8 to 8.2, alkalinity 100 mg/L (the consensus: S 5 −11 to
    // −14 %, S 10 −8 to −12 %, S 20 −4 to −9 %, S 34 0 to −5 %; the prototype's cells, b/out/09_final.txt, section 5).
    for (salinity, low, high) in [
        (5.0, -0.142, -0.112),
        (10.0, -0.120, -0.080),
        (20.0, -0.088, -0.039),
        (34.0, -0.051, 0.0),
    ] {
        for temp_c in [0.0, 4.0, 8.0, 12.0, 16.0, 20.0, 25.0, 30.0] {
            let (four, three) = (
                v4(temp_c, salinity, 100.0, Ions::default()),
                v3(temp_c, salinity, 100.0, Ions::default()),
            );
            for ph in [6.8, 7.2, 7.6, 8.0, 8.2] {
                let moved = four.nh3_share(ph).unwrap_or(f64::NAN) / three.nh3_share(ph).unwrap_or(f64::NAN) - 1.0;
                assert!(
                    (low..=high).contains(&moved),
                    "{temp_c} °C, S {salinity}, pH {ph}: {moved}"
                );
            }
        }
    }
    // The owner's example: 12 °C, S 34, pH 7.60, TAN 1 mg/L: formula 3 judged 0.006715; formula 4's best estimate
    // 0.006082 and judged 0.006515 (the consensus, with the least-squares line 0.130571 + 0.00072857 S; the decided
    // rounding, 0.1306 + 0.00073 S, is 0.00008 pH apart at S 34: 0.0060813 and 0.0065134, 0.02 % lower).
    let (four, three) = (
        v4(12.0, 34.0, 100.0, Ions::default()),
        v3(12.0, 34.0, 100.0, Ions::default()),
    );
    assert!((three.nh3_share(7.6).unwrap_or(f64::NAN) - 0.006715).abs() < 5e-7);
    assert!((four.nh3_share_corrected(7.6).unwrap_or(f64::NAN) - 0.006082).abs() < 1.5e-6);
    assert!((four.nh3_share(7.6).unwrap_or(f64::NAN) - 0.006515).abs() < 2e-6);
}

#[test]
fn outside_the_must_ranges_the_judged_values_stay_above_the_best_estimate() {
    // Sea water above 30 °C (to 40) and below 0 (to −2), land water below 8 °C: the margin is the rule's, so it holds;
    // what is not known there is the best estimate itself (nothing was computed below 0 or above 30 °C: the warnings
    // `fresh::BELOW_FITTED_TEMP` and `fresh::NH3_PAST_GUARD` stay said).
    let margin = libm::pow(10.0, U) - 1.0;
    for temp_c in [-2.0, -1.0, 31.0, 35.0, 40.0] {
        for salinity in [5.0, 20.0, 35.0, 40.0] {
            let eq = v4(temp_c, salinity, 100.0, Ions::default());
            for ph in phs() {
                let Ok((nh3, best, co2)) = judged(&eq, ph, 100.0) else {
                    continue;
                };
                assert!((odds(nh3) / odds(best) - 1.0 - margin).abs() < 1e-9);
                if let Some((judged_co2, best_co2)) = co2 {
                    assert!(judged_co2 / best_co2 - 1.0 >= margin - 1e-9);
                }
            }
            let expected = if temp_c < 0.0 {
                f::BELOW_FITTED_TEMP
            } else {
                f::NH3_PAST_GUARD
            };
            assert!(eq.warnings & expected != 0, "{temp_c} °C, S {salinity}");
        }
    }
    for temp_c in [-2.0, 0.0, 4.0, 7.9] {
        for salinity in [0.0, 1.0, 3.0] {
            let eq = v4(temp_c, salinity, 100.0, ions(Some(500.0), None, Origin::Unknown));
            for ph in phs() {
                let Ok((nh3, best, co2)) = judged(&eq, ph, 100.0) else {
                    continue;
                };
                assert!(nh3 >= best);
                if let Some((judged_co2, best_co2)) = co2 {
                    assert!(judged_co2 >= best_co2);
                }
            }
        }
    }
}

#[test]
fn a_ph_on_another_scale_takes_the_new_step_and_the_same_refusals() {
    for temp_c in [0.0, 12.0, 30.0] {
        for salinity in [5.0, 20.0, 34.0] {
            let eq = v4(temp_c, salinity, 100.0, Ions::default());
            // A total-scale pH is put on the NBS scale by the step: pH NBS = pH total + log₁₀ G − offset.
            let expected = 7.9 + libm::log10(c::free_to_total(temp_c, salinity).unwrap_or(f64::NAN)) - eq.ph_offset;
            assert_eq!(sc::ph_nbs(&eq, 7.9, PhScale::Total), Ok(expected));
            let back = sc::ph_nbs(&eq, 7.9, PhScale::Total).and_then(|nbs| sc::ph_on(&eq, nbs, PhScale::Total));
            assert!(back.is_ok_and(|ph| (ph - 7.9).abs() < 1e-12));
            // pH NBS − pH total, 0.09 to 0.16 (at 25 °C Millero's 0.134 to 0.154 less the per-kg term).
            let apart = expected - 7.9;
            assert!((0.09..=0.16).contains(&apart), "{temp_c} °C, S {salinity}: {apart}");
        }
    }
    for (salinity, origin) in [
        (4.99, Origin::Unknown),
        (1.0, Origin::Unknown),
        (30.0, Origin::SaltAdded),
    ] {
        let eq = v4(12.0, salinity, 100.0, ions(None, None, origin));
        assert_eq!(sc::ph_nbs(&eq, 7.9, PhScale::Total), Err(ChemError::SeawaterScale));
    }
}
