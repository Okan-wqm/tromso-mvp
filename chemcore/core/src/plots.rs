//! The four small charts beside the chart, each a value against the pH (farm/water/charts.py at golden v1, from the
//! source's SecondaryCharts.tsx with WQ-42 corrected): NH₃-N of the TAN, the shares of the total sulfide as H₂S and
//! HS⁻, the shares of the DIC as CO₂, HCO₃⁻ and CO₃²⁻, the calcite and aragonite saturation index (Mucci 1983, S 5–44)
//! at the water's DIC; with the NH₃ and H₂S bands (past the border danger, within 0.2 pH alert, else safe). Numbers and
//! keys only; the host names them.
use alloc::vec;
use alloc::vec::Vec;

use crate::analysis::{self as a, Status};
use crate::chemistry::{self as c, Equilibria};
use crate::geometry::{OMEGA_SALINITY, P};
use crate::num::{ChemError, div, log10};

/// pH between two points of a curve.
pub const STEP: f64 = 0.05;

/// One chart in its own units: pH across, the value up.
#[derive(Clone, Debug, PartialEq)]
pub struct Plot {
    pub key: &'static str,
    pub x: (f64, f64),
    pub y: (f64, f64),
    /// 'mg_l', 'percent' or 'index'
    pub unit: &'static str,
    pub series: Vec<(&'static str, Vec<P>)>,
    /// (kind, pH from, pH to): 'safe', 'alert', 'danger'
    pub bands: Vec<(&'static str, f64, f64)>,
    /// (key, pH): the water's, a border's
    pub verticals: Vec<(&'static str, f64)>,
    pub horizontals: Vec<(&'static str, f64)>,
    pub dots: Vec<(&'static str, f64, f64)>,
}

fn larger(one: f64, two: f64) -> f64 {
    // Python's max(one, two): one unless two is greater
    if two > one { two } else { one }
}

fn smaller(one: f64, two: f64) -> f64 {
    if two < one { two } else { one }
}

/// A pH axis that holds the water's pH, its ends on half units.
pub fn widen(span: (f64, f64), ph: f64, margin: f64) -> (f64, f64) {
    let (low, high) = span;
    (
        larger(a::PH_RANGE.0, smaller(low, libm::floor((ph - margin) * 2.0) / 2.0)),
        larger(high, libm::ceil((ph + margin) * 2.0) / 2.0),
    )
}

/// The pH of each point of a curve over a span, STEP apart (the count rounded half to even, as Python's round).
pub fn grid(span: (f64, f64)) -> Vec<f64> {
    let (low, high) = span;
    let count = libm::rint((high - low) / STEP);
    let steps = if count >= 0.0 { count as usize } else { 0 };
    (0..=steps)
        .map(|index| low + (high - low) * index as f64 / count)
        .collect()
}

/// The danger, alert and safe bands of a border on a pH axis, each cut to the axis; [] when the limit is not judged.
pub fn bands(border: &a::Border, low: f64, high: f64) -> Vec<(&'static str, f64, f64)> {
    if !matches!(border.status, Status::Ok | Status::Warning | Status::Critical) {
        return Vec::new();
    }
    let Some(edge) = border.ph else {
        return vec![("safe", low, high)];
    };
    let found = if border.toxic_above {
        [
            ("safe", low, edge - a::ALERT_PH),
            ("alert", edge - a::ALERT_PH, edge),
            ("danger", edge, high),
        ]
    } else {
        [
            ("danger", low, edge),
            ("alert", edge, edge + a::ALERT_PH),
            ("safe", edge + a::ALERT_PH, high),
        ]
    };
    found
        .into_iter()
        .map(|(kind, start, end)| (kind, larger(start, low), smaller(end, high)))
        .filter(|band| band.2 > band.1)
        .collect()
}

fn verticals(water_ph: f64, border: &a::Border, span: (f64, f64)) -> Vec<(&'static str, f64)> {
    let mut lines = vec![("water", water_ph)];
    if let Some(ph) = border.ph {
        if span.0 <= ph && ph <= span.1 {
            lines.push(("border", ph));
        }
    }
    lines
}

/// NH₃-N against pH; None without the TAN.
pub fn nh3_plot(analysis: &a::Analysis, water: &a::Water, limits: &a::Limits) -> Result<Option<Plot>, ChemError> {
    let Some(tan) = water.tan_mg_l else { return Ok(None) };
    let eq = &analysis.equilibria;
    let span = widen((6.0, 9.5), water.ph, 0.25);
    let mut curve = Vec::new();
    for ph in grid(span) {
        curve.push((ph, tan * eq.nh3_share(ph)?));
    }
    let limit = limits.nh3_n_mg_l.filter(|limit| *limit != 0.0);
    let mut top = match limit {
        Some(limit) => 2.5 * limit,
        None => curve.iter().map(|point| point.1).fold(f64::NEG_INFINITY, larger),
    };
    let nh3 = analysis.nh3_n_mg_l.unwrap_or(0.0);
    top = larger(top, 1.15 * nh3);
    if top == 0.0 {
        top = 1.0;
    }
    let mut plot = Plot {
        key: "nh3",
        x: span,
        y: (0.0, top),
        unit: "mg_l",
        series: vec![("nh3", curve)],
        bands: bands(&analysis.nh3, span.0, span.1),
        verticals: verticals(water.ph, &analysis.nh3, span),
        horizontals: Vec::new(),
        dots: vec![("water", water.ph, nh3)],
    };
    if let Some(limit) = limit {
        plot.horizontals.push(("limit", limit));
        if let Some(ph) = analysis.nh3.ph {
            if span.0 <= ph && ph <= span.1 {
                plot.dots.push(("border", ph, limit));
            }
        }
    }
    Ok(Some(plot))
}

/// The shares of the total sulfide as H₂S and HS⁻ against pH, in %.
pub fn h2s_plot(analysis: &a::Analysis, water: &a::Water) -> Result<Plot, ChemError> {
    let eq = &analysis.equilibria;
    let span = a::PH_RANGE;
    let mut shares = Vec::new();
    for ph in grid(span) {
        shares.push((ph, 100.0 * eq.h2s_share(ph)?));
    }
    let rest: Vec<P> = shares.iter().map(|&(ph, share)| (ph, 100.0 - share)).collect();
    Ok(Plot {
        key: "h2s",
        x: span,
        y: (0.0, 100.0),
        unit: "percent",
        series: vec![("h2s", shares), ("hs", rest)],
        bands: bands(&analysis.h2s, span.0, span.1),
        verticals: verticals(water.ph, &analysis.h2s, span),
        horizontals: Vec::new(),
        dots: vec![("water", water.ph, 100.0 * eq.h2s_share(water.ph)?)],
    })
}

/// The shares of the DIC as CO₂, HCO₃⁻ and CO₃²⁻ against pH, in %.
pub fn carbonate_plot(analysis: &a::Analysis, water: &a::Water) -> Result<Plot, ChemError> {
    let eq = &analysis.equilibria;
    let span = (a::PH_RANGE.0, 12.0);
    let (mut co2, mut hco3, mut co3) = (Vec::new(), Vec::new(), Vec::new());
    for ph in grid(span) {
        let (zero, one, two) = eq.fractions(ph)?;
        co2.push((ph, 100.0 * zero));
        hco3.push((ph, 100.0 * one));
        co3.push((ph, 100.0 * two));
    }
    Ok(Plot {
        key: "carbonate",
        x: span,
        y: (0.0, 100.0),
        unit: "percent",
        series: vec![("co2", co2), ("hco3", hco3), ("co3", co3)],
        bands: Vec::new(),
        verticals: vec![("water", water.ph)],
        horizontals: Vec::new(),
        dots: Vec::new(),
    })
}

/// log10 Ω of a water: Ω = [Ca²⁺] [CO₃²⁻] / Ksp, the concentrations per litre (WQ-32) and so the Ksp too
/// (`Equilibria::ksp_per_litre`: Mucci's per-kg² Ksp times the square of the sea water's density; formula 1 the per-kg
/// Ksp as it is).
pub fn saturation_index(eq: &Equilibria, dic: f64, ph: f64, calcium_mg_l: f64, ksp: f64) -> Result<f64, ChemError> {
    let product = div(calcium_mg_l, c::MG_CALCIUM_PER_MOL)? * eq.carbonate(dic, ph)? / 1000.0;
    log10(div(product, eq.ksp_per_litre(ksp)?)?)
}

/// The calcite and aragonite saturation index against pH at the water's DIC; None without the calcium or outside
/// Mucci's salinities.
pub fn saturation_plot(analysis: &a::Analysis, water: &a::Water) -> Result<Option<Plot>, ChemError> {
    let Some(calcium) = water.calcium_mg_l.filter(|calcium| *calcium != 0.0) else {
        return Ok(None);
    };
    if !(OMEGA_SALINITY.0 <= water.salinity_ppt && water.salinity_ppt <= OMEGA_SALINITY.1) {
        return Ok(None);
    }
    let eq = &analysis.equilibria;
    let span = widen((6.0, 9.5), water.ph, 0.25);
    let mut series = Vec::new();
    for (key, ksp) in [("calcite", eq.ksp_calcite), ("aragonite", eq.ksp_aragonite)] {
        let mut curve = Vec::new();
        for ph in grid(span) {
            curve.push((ph, saturation_index(eq, analysis.dic, ph, calcium, ksp)?));
        }
        series.push((key, curve));
    }
    let values: Vec<f64> = series
        .iter()
        .flat_map(|(_key, curve)| curve.iter().map(|point| point.1))
        .collect();
    let least = values.iter().copied().fold(f64::INFINITY, smaller);
    let most = values.iter().copied().fold(f64::NEG_INFINITY, larger);
    let low = libm::floor(smaller(least, 0.0) * 2.0) / 2.0;
    let mut high = libm::ceil(larger(most, 0.0) * 2.0) / 2.0;
    if high - low < 1.0 {
        high = low + 1.0;
    }
    Ok(Some(Plot {
        key: "saturation",
        x: span,
        y: (low, high),
        unit: "index",
        series,
        bands: Vec::new(),
        verticals: vec![("water", water.ph)],
        horizontals: vec![("zero", 0.0)],
        dots: Vec::new(),
    }))
}

/// The four charts of a water, in the order nh3, h2s, carbonate, saturation (None: cannot be drawn).
pub fn plots(
    water: &a::Water,
    limits: &a::Limits,
    target: Option<&a::Target>,
    pressure: f64,
) -> Result<[Option<Plot>; 4], ChemError> {
    let analysis = a::analyse(water, limits, target, pressure)?;
    Ok([
        nh3_plot(&analysis, water, limits)?,
        Some(h2s_plot(&analysis, water)?),
        Some(carbonate_plot(&analysis, water)?),
        saturation_plot(&analysis, water)?,
    ])
}
