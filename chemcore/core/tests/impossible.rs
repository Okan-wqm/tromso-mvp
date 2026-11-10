//! The core refuses a water that cannot be (owner-approved correction, 2026-11-10, after the independent check of
//! 2026-11-09, claim 9): a pH whose hydroxide and borate alone are more alkalinity than the water has, so its DIC, CO₂
//! and carbonate would be negative. Formula 3 answers `ChemError::ImpossibleWater`, never a negative concentration; one
//! rule (`Equilibria::possible`), which `analysis::why_impossible` asks too. Formula 1 refuses nothing, by name: golden
//! v1 holds what it returns below the floor.
use chemcore_core::analysis::{self as a, Limits, Medium, Target, Water};
use chemcore_core::chemistry::{self as c, Origin};
use chemcore_core::dosing;
use chemcore_core::fresh::{self as f, Ions};
use chemcore_core::geometry::{self as g, GeometryError, Layers};
use chemcore_core::num::ChemError;
use chemcore_core::plots;

fn water(temperature_c: f64, salinity_ppt: f64, ph: f64, alkalinity_mg_l: f64, formula: u32) -> Water {
    Water {
        temperature_c,
        salinity_ppt,
        ph,
        alkalinity_mg_l,
        tan_mg_l: Some(0.5),
        total_sulfide_ug_l: None,
        calcium_mg_l: Some(400.0),
        oxygen_mg_l: None,
        conductivity_25_us_cm: None,
        hardness_mg_l: None,
        origin: Origin::Unknown,
        formula,
    }
}

fn limits() -> Limits {
    Limits {
        nh3_n_mg_l: Some(0.0103),
        co2_mg_l: Some(15.0),
        h2s_ug_l: None,
        alkalinity_low_mg_l: Some(50.0),
        alkalinity_high_mg_l: Some(150.0),
    }
}

/// The independent check's water: 40 °C, S 40, an alkalinity of 0.5 meq/L, pH 9.
const ODD_MG_L: f64 = 0.5 * c::MG_CACO3_PER_MEQ;

#[test]
fn the_analysis_refuses_a_water_below_its_alkalinity_floor() {
    let odd = water(40.0, 40.0, 9.0, ODD_MG_L, 3);
    assert_eq!(
        a::analyse(&odd, &limits(), None, 1.0).err(),
        Some(ChemError::ImpossibleWater)
    );
    // The same water a little more alkaline is worked out, every concentration above 0.
    let fine = water(40.0, 40.0, 9.0, 200.0, 3);
    assert!(
        a::analyse(&fine, &limits(), None, 1.0)
            .is_ok_and(|found| found.dic > 0.0 && found.co2_mg_l > 0.0 && found.co2_corrected_mg_l > 0.0)
    );
}

#[test]
fn the_analysis_refuses_an_impossible_target() {
    let fine = water(12.0, 1.0, 7.0, 80.0, 3);
    let target = Target {
        ph: 11.5,
        alkalinity_mg_l: 20.0,
    };
    assert_eq!(
        a::analyse(&fine, &limits(), Some(&target), 1.0).err(),
        Some(ChemError::ImpossibleWater)
    );
    let reachable = Target {
        ph: 7.5,
        alkalinity_mg_l: 100.0,
    };
    assert!(a::analyse(&fine, &limits(), Some(&reachable), 1.0).is_ok_and(|found| {
        found.target_dic.is_some_and(|dic| dic > 0.0) && found.target_co2_mg_l.is_some_and(|co2| co2 > 0.0)
    }));
}

#[test]
fn the_equilibria_refuse_it_at_every_door() {
    let eq = f::equilibria_v3(40.0, 40.0, Some(ODD_MG_L), Ions::default());
    assert!(eq.is_ok());
    let Ok(eq) = eq else { return };
    assert_eq!(eq.possible(0.5, 9.0), Ok(false));
    assert_eq!(eq.dic(0.5, 9.0), Err(ChemError::ImpossibleWater));
    assert_eq!(eq.co2_corrected(0.5, 9.0), Err(ChemError::ImpossibleWater));
    // A negative DIC is no water's either: its CO₂ and carbonate are refused, not returned negative.
    assert_eq!(eq.co2(-0.0233, 9.0), Err(ChemError::ImpossibleWater));
    assert_eq!(eq.carbonate(-0.0233, 9.0), Err(ChemError::ImpossibleWater));
    assert_eq!(eq.ph_at(-0.0233, 0.5), Ok(None));
    // Above the floor all of them answer, above 0.
    assert_eq!(eq.possible(2.3, 8.1), Ok(true));
    assert!(eq.dic(2.3, 8.1).is_ok_and(|dic| dic > 0.0));
    assert!(eq.co2_corrected(2.3, 8.1).is_ok_and(|co2| co2 > 0.0));
    assert!(eq.co2(2.0, 8.1).is_ok_and(|co2| co2 > 0.0));
    assert_eq!(eq.co2(0.0, 8.1), Ok(0.0));
}

#[test]
fn the_chart_the_small_charts_and_the_simulator_refuse_it() {
    let odd = water(40.0, 40.0, 9.0, ODD_MG_L, 3);
    assert_eq!(
        g::geometry(&odd, &limits(), None, 1.0, Layers::default(), None, &[], &[]).err(),
        Some(GeometryError::Chem(ChemError::ImpossibleWater))
    );
    assert_eq!(
        plots::plots(&odd, &limits(), None, 1.0).err(),
        Some(ChemError::ImpossibleWater)
    );
    let eq = f::equilibria_v3(40.0, 40.0, Some(ODD_MG_L), Ions::default());
    assert!(eq.is_ok());
    let Ok(eq) = eq else { return };
    assert_eq!(
        dosing::simulate(&eq, (-0.0233, 0.5), 9.0, &[("naoh", 10.0)], 1.0, None).err(),
        Some(ChemError::ImpossibleWater)
    );
}

#[test]
fn a_dose_that_takes_more_than_there_is_stays_a_step_without_a_water() {
    // Not an error: the simulator says the step is no water (no pH, no CO₂), as before.
    let eq = f::equilibria_v3(12.0, 1.0, Some(80.0), Ions::default());
    assert!(eq.is_ok());
    let Ok(eq) = eq else { return };
    let alkalinity = 80.0 / c::MG_CACO3_PER_MEQ;
    let dic = eq.dic(alkalinity, 7.0).unwrap_or(f64::NAN);
    let steps = dosing::simulate(&eq, (dic, alkalinity), 7.0, &[("degas", 500.0)], 1.0, None);
    assert!(steps.is_ok_and(|steps| {
        steps.len() == 2
            && steps
                .first()
                .is_some_and(|step| step.co2_mg_l.is_some_and(|co2| co2 > 0.0))
            && steps
                .last()
                .is_some_and(|step| step.ph.is_none() && step.co2_mg_l.is_none())
    }));
}

#[test]
fn one_rule_decides_for_the_reason_the_analysis_and_the_equilibria() {
    // Over waters on both sides of the floor: `why_impossible` has a reason exactly where the analysis and the
    // equilibria refuse, and where they answer every concentration is above 0.
    let (mut refused, mut answered, mut apart) = (0, 0, 0);
    for temp_c in [0.0, 12.0, 25.0, 40.0] {
        for salinity in [0.0, 0.5, 3.0, 5.0, 35.0, 40.0] {
            for ph in [6.5, 8.0, 9.0, 9.5, 10.0, 11.0, 12.0] {
                for alkalinity_mg_l in [0.5, 5.0, ODD_MG_L, 80.0, 400.0, 2000.0] {
                    let reason = a::why_impossible(temp_c, salinity, ph, alkalinity_mg_l, 3, Ions::default());
                    let found = a::analyse(&water(temp_c, salinity, ph, alkalinity_mg_l, 3), &limits(), None, 1.0);
                    let dic = f::equilibria_v3(temp_c, salinity, Some(alkalinity_mg_l), Ions::default())
                        .and_then(|eq| eq.dic(alkalinity_mg_l / c::MG_CACO3_PER_MEQ, ph));
                    match (reason, found, dic) {
                        (Ok(None), Ok(found), Ok(dic))
                            if dic > 0.0
                                && found.dic == dic
                                && found.co2_mg_l > 0.0
                                && found.co2_corrected_mg_l > 0.0 =>
                        {
                            answered += 1;
                        }
                        (Ok(Some(_)), Err(ChemError::ImpossibleWater), Err(ChemError::ImpossibleWater)) => refused += 1,
                        _ => apart += 1,
                    }
                }
            }
        }
    }
    assert_eq!(apart, 0);
    assert!(
        refused > 100 && answered > 400,
        "{refused} refused, {answered} answered"
    );
}

#[test]
fn on_the_floor_and_one_step_either_side_the_three_agree() {
    // On the floor (where the DIC is 0) and a last digit beside it the decision may fall either way, but the reason, the
    // analysis and the equilibria decide alike, and once a water is possible it stays so going up.
    let sea = Medium {
        formula: 3,
        alkalinity_mg_l: None,
        ions: Ions::default(),
    };
    for (temp_c, salinity, ph) in [
        (25.0, 35.0, 9.0),
        (10.0, 5.0, 10.0),
        (40.0, 40.0, 9.0),
        (30.0, 15.0, 11.5),
    ] {
        let floor = a::alkalinity_floor(temp_c, salinity, ph, &sea).unwrap_or(f64::NAN);
        assert!(floor > 0.0);
        let mut decided = [false; 6];
        for (slot, alkalinity_mg_l) in decided.iter_mut().zip([
            floor - 1e-9,
            floor.next_down(),
            floor,
            floor.next_up(),
            floor.next_up().next_up().next_up(),
            floor + 1e-9,
        ]) {
            let reason = a::why_impossible(temp_c, salinity, ph, alkalinity_mg_l, 3, Ions::default());
            let found = a::analyse(&water(temp_c, salinity, ph, alkalinity_mg_l, 3), &limits(), None, 1.0);
            *slot = matches!(reason, Ok(None));
            assert_eq!(
                found.is_ok(),
                *slot,
                "{temp_c} °C, S {salinity}, pH {ph}, {alkalinity_mg_l} mg/L"
            );
            assert!(found.is_ok() || found.err() == Some(ChemError::ImpossibleWater));
            assert!(found.is_ok_and(|found| found.dic > 0.0) || !*slot);
        }
        // Far enough below it is refused, far enough above it is answered, and once possible it stays so going up.
        assert!(!decided.first().copied().unwrap_or(true) && decided.last().copied().unwrap_or(false));
        assert!(
            decided
                .windows(2)
                .all(|pair| matches!(pair, [below, above] if !*below || *above))
        );
    }
}

#[test]
fn formula_1_still_returns_what_golden_v1_holds_below_the_floor() {
    // Formula 1 is kept so that a recorded value can be worked out again: it refuses nothing (the independent check's
    // numbers: DIC −0.0233 mmol/L, CO₂ and carbonate below 0), while its `why_impossible` says the water cannot be.
    let odd = water(40.0, 40.0, 9.0, ODD_MG_L, 1);
    assert!(
        a::analyse(&odd, &limits(), None, 1.0)
            .is_ok_and(|found| (found.dic - -0.0233).abs() < 1e-4 && found.co2_mg_l < 0.0)
    );
    assert!(matches!(
        a::why_impossible(40.0, 40.0, 9.0, ODD_MG_L, 1, Ions::default()),
        Ok(Some(floor)) if floor > ODD_MG_L
    ));
    let one = c::equilibria(40.0, 40.0);
    assert!(one.is_ok_and(|eq| eq.dic(0.5, 9.0).is_ok_and(|dic| dic < 0.0) && eq.possible(0.5, 9.0) == Ok(false)));
}

#[test]
fn the_safe_zone_is_still_drawn_where_its_edge_runs_along_a_ph_the_band_cannot_have() {
    // A TAN that cannot reach its limit: the zone's upper edge is the chart's top pH (12.5), whose floor lies far above
    // the alkalinity band, so its corner points have a DIC below 0 and are cut at the box. That is the chart's
    // geometry, not a water: it is not refused.
    let calm = Water {
        tan_mg_l: Some(0.005),
        ..water(12.0, 0.0, 7.2, 90.0, 3)
    };
    let layers = Layers {
        safe: true,
        ..Layers::default()
    };
    let shape = g::geometry(&calm, &limits(), None, 1.0, layers, None, &[], &[]);
    assert!(shape.is_ok_and(|shape| {
        shape
            .regions
            .iter()
            .any(|(key, polygon)| *key == "safe" && polygon.len() >= 3)
    }));
}
