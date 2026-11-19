//! The calcite and aragonite saturation Ω of formula 3 (owner-approved correction, 2026-11-10, after the independent
//! check of 2026-11-09, claim 12b): Ω = [Ca²⁺] [CO₃²⁻] / Ksp with the calcium (mg/L) and the carbonate (of a per-litre
//! alkalinity) per litre and Mucci's (1983) Ksp per kg², so the Ksp is taken per litre, times the square of the sea
//! water's density (EOS-80). One definition (`Equilibria::ksp_per_litre`) for the small chart's saturation index and the
//! chart's Ω = 1 line. Formula 1 keeps the per-kg Ksp by name (golden v1: Ω too high by ρ²).
use chemcore_core::analysis::ChartBox;
use chemcore_core::chemistry as c;
use chemcore_core::fresh::{self as f, Ions};
use chemcore_core::geometry::omega_line;
use chemcore_core::num::ChemError;
use chemcore_core::plots::saturation_index;

#[test]
fn the_density_of_sea_water_meets_its_check_values() {
    // The one-atmosphere International Equation of State of Seawater, 1980 (Millero & Poisson 1981, Deep-Sea Res. 28A:
    // 625): (°C on IPTS-68, S, kg/m³, the digits printed).
    for (temp_c, salinity, expected, digits) in [
        // UNESCO (1983), Fofonoff & Millard, Algorithms for computation of fundamental properties of seawater, Tech.
        // Pap. Mar. Sci. 44: the check values of its density algorithm at p = 0.
        (5.0, 35.0, 1027.67547, 1e-5),
        (25.0, 35.0, 1023.34306, 1e-5),
        // The same report's table at 0 and 30 °C, as the documentation of python-seawater quotes it (p. 22).
        (0.0, 0.0, 999.842594, 1e-6),
        (30.0, 0.0, 995.65113374, 1e-7),
        (0.0, 35.0, 1028.10633141, 1e-7),
        (30.0, 35.0, 1021.72863949, 1e-7),
        // Dickson, Sabine & Christian (2007), Guide to Best Practices for Ocean CO2 Measurements, ch. 5, section 4.2,
        // eq. (6) to (10): "At 25 °C (IPTS 68) and S = 35, ρSW = 1023.343 kg m⁻³".
        (25.0, 35.0, 1023.343, 1e-3),
    ] {
        let found = c::seawater_density(temp_c, salinity).map_or(f64::NAN, |kg_per_litre| 1000.0 * kg_per_litre);
        assert!(
            (found - expected).abs() < digits,
            "{temp_c} °C, S {salinity}: {found} against {expected}"
        );
    }
    assert_eq!(c::seawater_density(10.0, -1.0), Err(ChemError::Domain));
    assert_eq!(c::seawater_density(f64::NAN, 35.0), Err(ChemError::NonFinite));
    assert_eq!(c::seawater_density(10.0, f64::INFINITY), Err(ChemError::NonFinite));
}

/// A sea water's DIC (mmol/L) at an alkalinity of 115 mg/L as CaCO₃ and a pH, and its calcium (mg/L, sea water's 412
/// at S 35 in proportion).
fn sea_water(eq: &c::Equilibria, ph: f64) -> (f64, f64) {
    let dic = eq.dic(115.0 / c::MG_CACO3_PER_MEQ, ph).unwrap_or(f64::NAN);
    (dic, 412.0 * eq.salinity / 35.0)
}

#[test]
fn omega_takes_the_ksp_per_litre() {
    for (temp_c, salinity) in [(25.0, 35.0), (5.0, 35.0), (10.0, 5.0), (40.0, 40.0), (5.0, 44.0)] {
        let eq = f::equilibria_v3(temp_c, salinity, Some(115.0), Ions::default());
        assert!(eq.is_ok(), "{temp_c} °C, S {salinity}");
        let Ok(eq) = eq else { continue };
        let density = c::seawater_density(temp_c, salinity).unwrap_or(f64::NAN);
        for ph in [7.6, 8.1] {
            let (dic, calcium) = sea_water(&eq, ph);
            let carbonate = eq.carbonate(dic, ph).unwrap_or(f64::NAN);
            for ksp in [eq.ksp_calcite, eq.ksp_aragonite] {
                // mol/L of calcium times mol/L of carbonate, over (mol/kg)² times (kg/L)²
                let expected =
                    libm::log10(calcium / c::MG_CALCIUM_PER_MOL * (carbonate / 1000.0) / (ksp * density * density));
                let found = saturation_index(&eq, dic, ph, calcium, ksp).unwrap_or(f64::NAN);
                assert!(
                    (found - expected).abs() < 1e-12,
                    "{temp_c} °C, S {salinity}, pH {ph}: {found} against {expected}"
                );
                assert_eq!(eq.ksp_per_litre(ksp), Ok(ksp * density * density));
            }
        }
    }
}

#[test]
fn omega_was_too_high_by_the_density_squared() {
    // The independent check: +4.7 % at S 35 and 25 °C, +3.6 to +6.4 % at S 35, up to +7.6 % at S 40 and below 1 % at S 5.
    let excess = |temp_c: f64, salinity: f64| {
        c::seawater_density(temp_c, salinity).map_or(f64::NAN, |density| 100.0 * (density * density - 1.0))
    };
    assert!((excess(25.0, 35.0) - 4.72).abs() < 0.01);
    assert!((excess(5.0, 35.0) - 5.61).abs() < 0.01);
    assert!(excess(40.0, 35.0) > 3.6 && excess(0.0, 35.0) < 6.4);
    assert!(excess(0.0, 40.0) < 7.6 && excess(40.0, 40.0) > 4.3);
    assert!(excess(10.0, 5.0).abs() < 1.0 && excess(40.0, 5.0).abs() < 1.0);
}

#[test]
fn formula_1_keeps_the_ksp_per_kg_bit_for_bit() {
    let eq = c::equilibria(25.0, 35.0);
    assert!(eq.is_ok());
    let Ok(eq) = eq else { return };
    let (dic, calcium) = sea_water(&eq, 8.1);
    let carbonate = eq.carbonate(dic, 8.1).unwrap_or(f64::NAN);
    for ksp in [eq.ksp_calcite, eq.ksp_aragonite] {
        // golden v1's arithmetic, in its order
        let expected = libm::log10(calcium / c::MG_CALCIUM_PER_MOL * carbonate / 1000.0 / ksp);
        assert_eq!(saturation_index(&eq, dic, 8.1, calcium, ksp), Ok(expected));
        assert_eq!(eq.ksp_per_litre(ksp), Ok(ksp));
    }
}

#[test]
fn on_the_charts_omega_line_the_saturation_index_is_0() {
    // The chart's Ω = 1 line and the small chart's index are one definition: along the line the index is 0 (within the
    // line's 96 straight pieces and the solver's 1e-10 pH), by either formula. A density in one of the two only would
    // leave 0.02 at S 35.
    let chart = ChartBox {
        dic: 6.0,
        alkalinity: 6.0,
        dic_step: 1.0,
        alkalinity_step: 1.0,
    };
    for formula in [1, 3, 4] {
        for (temp_c, salinity) in [(25.0, 35.0), (8.0, 20.0)] {
            let eq = f::water_equilibria(formula, temp_c, salinity, Some(115.0), Ions::default());
            assert!(eq.is_ok());
            let Ok(eq) = eq else { continue };
            let calcium = 412.0 * salinity / 35.0;
            for ksp in [eq.ksp_calcite, eq.ksp_aragonite] {
                let lines = omega_line(&eq, calcium, ksp, &chart).unwrap_or_default();
                let points: Vec<(f64, f64)> = lines.into_iter().flatten().collect();
                assert!(points.len() > 10, "formula {formula}, {temp_c} °C, S {salinity}");
                for (dic, alkalinity) in points {
                    let ph = eq.ph_at(dic, alkalinity).ok().flatten().unwrap_or(f64::NAN);
                    let index = saturation_index(&eq, dic, ph, calcium, ksp).unwrap_or(f64::NAN);
                    assert!(index.abs() < 1e-3, "formula {formula}: {index} at DIC {dic}");
                }
            }
        }
    }
}
