//! The guard of the NH₃ judgement (the K_NH4 panel's decision, 2026-11-10, row 2). The activity-corrected K_NH4 stays
//! Yao & Millero's (1995, as Millero 1995: `chemistry::k_nh4_sws`), which on the free scale lies 0.17 to 8.8 % below
//! Clegg & Whitfield's (1995) at S ≥ 5. No judgement rests on it: every NH₃ judged is the larger of the basis the limits
//! were set on and the corrected value (`Equilibria::nh3_share`). This test holds that rule to what it must cover. Over
//! 0 to 30 °C and S 0.5 to 35, the judged NH₃, as the ratio [NH₃]/[NH₄⁺], is never below the core's own corrected value
//! nor below a Clegg & Whitfield based one, tolerance 0; at S 0, where the two constants are both pure water's, within
//! 0.5 % (−0.46 % at 0 °C in ion-free water). Without the limits-basis rule it fails (shown by breaking the rule in a
//! copy of the core).
//!
//! Clegg & Whitfield's equation was not read in their paper (Geochim. Cosmochim. Acta 59: 2403, eq. 18 with table 13).
//! It is typed here from Xu, Pierrot & Cai (2017), "Ocean carbonate system computation for anoxic waters using an
//! updated CO2SYS program", Marine Chemistry, the accepted manuscript in the NOAA repository
//! (repository.library.noaa.gov/view/noaa/66365), eq. (10), which says it is that equation, for −2 to 40 °C and S 0 to
//! 40, "accuracy ... better than 5 %". Xu et al. print the T coefficient of the S^1.5 term as 0.0001471316; PyCO2SYS
//! 1.8.3.4's numbers need 0.0001471361 (0.06 % of K at S 35). Which the 1995 paper prints is not known, so the guard is
//! held against both. Scale and unit are the panel's reading (not stated beside eq. 10): the total scale, per kg of
//! water, which PyCO2SYS's free-scale numbers confirm below (numbers only were compared: its code is GPL, none copied).
use chemcore_core::chemistry::{self as c, Origin};
use chemcore_core::fresh::{self as f, Ions};
use chemcore_core::num::ChemError;

/// The T coefficient of the S^1.5 term as Xu et al. (2017) print it, and as PyCO2SYS's numbers need it.
const AS_PRINTED: f64 = 0.0001471316;
const AS_COMPUTED: f64 = 0.0001471361;

/// pK of NH₄⁺ by Clegg & Whitfield (1995), Xu et al.'s (2017) eq. (10): total scale, mol per kg of water.
fn cw95_pk(temp_c: f64, salinity: f64, s15_t: f64) -> f64 {
    let t = temp_c + 273.15;
    let root = libm::sqrt(t);
    9.244605 - 2729.33 * (1.0 / 298.15 - 1.0 / t)
        + (0.04203362 - 11.24742 / t) * libm::pow(salinity, 0.25)
        + (-13.6416 + 1.176949 * root - 0.02860785 * t + 545.4834 / t) * libm::sqrt(salinity)
        + (-0.1462507 + 0.0090226468 * root - s15_t * t + 10.5425 / t) * libm::pow(salinity, 1.5)
        + (0.004669309 - 0.0001691742 * root - 0.5677934 / t) * salinity * salinity
        + (-0.00002354039 + 0.009698623 / t) * libm::pow(salinity, 2.5)
}

/// The same per kg of solution (× 1 − 0.001005 S, the factor the core's constants carry), on the total scale.
fn cw95_total(temp_c: f64, salinity: f64, s15_t: f64) -> f64 {
    libm::pow(10.0, -cw95_pk(temp_c, salinity, s15_t)) * (1.0 - 0.001005 * salinity)
}

/// The same on the free scale, as the core holds its constants: over [H⁺]total / [H⁺]free (Dickson's 1990 KSO₄).
fn cw95_free(temp_c: f64, salinity: f64, s15_t: f64) -> f64 {
    cw95_total(temp_c, salinity, s15_t) / c::free_to_total(temp_c, salinity).unwrap_or(f64::NAN)
}

#[test]
fn clegg_and_whitfields_equation_meets_its_check_values() {
    // In pure water at 25 °C: 9.2446, against Bates & Pinching's (1949) 9.245 as Bell et al. (2007, Environ. Chem. 4:
    // 183) quote it (the panel's check; neither was opened here).
    assert!((cw95_pk(25.0, 0.0, AS_COMPUTED) - 9.245).abs() < 0.0006);
    assert_eq!(cw95_pk(25.0, 0.0, AS_COMPUTED), cw95_pk(25.0, 0.0, AS_PRINTED));
    // PyCO2SYS 1.8.3.4 (the panel's dump of 2026-11-10): its Clegg & Whitfield constant on the total scale and its
    // ammonium constant on the free scale, mol per kg of solution: (°C, S, total, free).
    for (temp_c, salinity, total, free) in [
        (0.0, 0.0, 8.270981103142548e-11, 8.270981103142548e-11),
        (0.0, 35.0, 6.963143415574797e-11, 6.339461138236505e-11),
        (10.0, 5.0, 1.906334164670896e-10, 1.7916674236860337e-10),
        (15.0, 0.5, 2.7794505915803263e-10, 2.729047522613315e-10),
        (25.0, 0.0, 5.693705499509853e-10, 5.693705499509853e-10),
        (25.0, 35.0, 5.677444598825593e-10, 4.430297995529491e-10),
        (30.0, 20.0, 8.745227717084991e-10, 7.046154929368116e-10),
        (30.0, 35.0, 8.384145890518309e-10, 6.281348000036867e-10),
    ] {
        let found = cw95_total(temp_c, salinity, AS_COMPUTED);
        assert!(
            ((found - total) / total).abs() < 1e-12,
            "{temp_c} °C, S {salinity}: {found} against {total}"
        );
        let found = cw95_free(temp_c, salinity, AS_COMPUTED);
        assert!(
            ((found - free) / free).abs() < 1e-12,
            "{temp_c} °C, S {salinity}: {found} against {free}"
        );
    }
    // The digit as printed lowers K by 0.064 % at S 35 and 25 °C, and less below.
    let apart = cw95_total(25.0, 35.0, AS_PRINTED) / cw95_total(25.0, 35.0, AS_COMPUTED) - 1.0;
    assert!((apart + 0.00064).abs() < 0.00002, "{apart}");
}

#[test]
fn the_corrected_constant_alone_would_not_cover_it() {
    // What the guard is for: on the free scale the core's own K_NH4 (Yao & Millero 1995) is 0.17 to 8.8 % below Clegg &
    // Whitfield's from S 5 (the independent check of 2026-11-09, claim 8; here to 30 °C and S 35: 0.17 to 6.3 %).
    let (mut least, mut most) = (f64::INFINITY, f64::NEG_INFINITY);
    for temp_c in [0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0] {
        for salinity in [5.0, 10.0, 20.0, 30.0, 35.0] {
            let own = f::equilibria_v3(temp_c, salinity, None, Ions::default()).map_or(f64::NAN, |eq| eq.k_nh4);
            let below = 1.0 - own / cw95_free(temp_c, salinity, AS_COMPUTED);
            least = least.min(below);
            most = most.max(below);
        }
    }
    assert!(least > 0.0016 && most < 0.088, "{least} to {most}");
    assert!(most > 0.05, "{most}");
}

/// [NH₃]/[NH₄⁺] of a share of the TAN.
fn ratio(share: f64) -> f64 {
    share / (1.0 - share)
}

/// The least of (judged ÷ corrected − 1) and of (judged ÷ Clegg & Whitfield based − 1) over a water's pHs, the latter
/// against the larger of the two readings of the equation: its K over the water's own free [H⁺].
fn margins(temp_c: f64, salinity: f64, alkalinity_mg_l: Option<f64>, ions: Ions) -> Result<(f64, f64), ChemError> {
    let eq = f::equilibria_v3(temp_c, salinity, alkalinity_mg_l, ions)?;
    let k = cw95_free(temp_c, salinity, AS_COMPUTED).max(cw95_free(temp_c, salinity, AS_PRINTED));
    let (mut over_corrected, mut over_cw95) = (f64::INFINITY, f64::INFINITY);
    for ph in [6.5, 7.0, 7.5, 8.0, 8.5, 9.0] {
        let judged = ratio(eq.nh3_share(ph)?);
        over_corrected = over_corrected.min(judged / ratio(eq.nh3_share_corrected(ph)?) - 1.0);
        over_cw95 = over_cw95.min(judged / (k / eq.hydrogen(ph)?) - 1.0);
    }
    Ok((over_corrected, over_cw95))
}

/// The waters the guard is held over at each temperature and salinity: nothing but the salinity known, an alkalinity,
/// a conductivity in the fresh range, and the unit's origin said to be sea water.
fn waters() -> [(Option<f64>, Ions); 4] {
    [
        (None, Ions::default()),
        (Some(100.0), Ions::default()),
        (
            Some(100.0),
            Ions {
                conductivity_25_us_cm: Some(1500.0),
                hardness_mg_l: None,
                origin: Origin::Unknown,
            },
        ),
        (
            None,
            Ions {
                origin: Origin::Seawater,
                ..Ions::default()
            },
        ),
    ]
}

#[test]
fn the_judged_nh3_is_never_below_the_corrected_nor_clegg_and_whitfields_from_0_to_30_degrees_and_s_05_to_35() {
    // 31 temperatures by 70 salinities (every °C, every 0.5 ‰) by four waters by six pH: tolerance 0.
    let (mut cells, mut least, mut at) = (0, f64::INFINITY, (f64::NAN, f64::NAN));
    for degree in 0..=30_u32 {
        for half in 1..=70_u32 {
            let (temp_c, salinity) = (f64::from(degree), 0.5 * f64::from(half));
            for (alkalinity, ions) in waters() {
                let found = margins(temp_c, salinity, alkalinity, ions);
                assert!(found.is_ok(), "{temp_c} °C, S {salinity}: {found:?}");
                let (over_corrected, over_cw95) = found.unwrap_or((f64::NAN, f64::NAN));
                assert!(
                    over_corrected >= 0.0,
                    "{temp_c} °C, S {salinity}: {over_corrected} below the corrected"
                );
                assert!(
                    over_cw95 >= 0.0,
                    "{temp_c} °C, S {salinity}: {over_cw95} below Clegg & Whitfield"
                );
                cells += 1;
                if over_cw95 < least {
                    (least, at) = (over_cw95, (temp_c, salinity));
                }
            }
        }
    }
    assert_eq!(cells, 31 * 70 * 4);
    // The smallest margin is at the warm, salty corner (the panel: +2.9 % at 30 °C, S 35); beyond it the judged value
    // does fall below (the warning of `fresh::NH3_PAST_GUARD`).
    assert_eq!(at, (30.0, 35.0));
    assert!(least > 0.02 && least < 0.035, "{least}");
}

#[test]
fn at_a_salinity_of_0_it_is_within_half_a_percent() {
    // Both constants are pure water's there (Yao & Millero's S → 0 limit against Clegg & Whitfield's): the judged NH₃ of
    // ion-free water is 0.03 to 0.46 % below, the most at 0 °C; with ions measured the corrected side only falls.
    let mut least = f64::INFINITY;
    for degree in 0..=30_u32 {
        let temp_c = f64::from(degree);
        for (alkalinity, ions) in waters() {
            let found = margins(temp_c, 0.0, alkalinity, ions);
            assert!(found.is_ok_and(|(over_corrected, over_cw95)| over_corrected >= 0.0 && over_cw95 >= -0.005));
            least = least.min(found.map_or(f64::NAN, |(_, over_cw95)| over_cw95));
        }
    }
    assert!((least - -0.0046).abs() < 0.0003, "{least}");
}

#[test]
fn past_30_degrees_or_s_35_the_judged_nh3_can_fall_below_it() {
    // Why a warning is said there, never a refusal (the panel's row 3): −1.3 % at 35 °C and −5.6 % at 40 °C, S 35; at S
    // 40 from just above 30 °C.
    let below = |temp_c: f64, salinity: f64| {
        margins(temp_c, salinity, None, Ions::default()).map_or(f64::NAN, |(_, over_cw95)| 100.0 * over_cw95)
    };
    assert!((below(35.0, 35.0) - -1.3).abs() < 0.15, "{}", below(35.0, 35.0));
    assert!((below(40.0, 35.0) - -5.6).abs() < 0.15, "{}", below(40.0, 35.0));
    assert!(below(31.0, 40.0) < 0.0 && below(30.0, 40.0) > 0.0);
}
