//! The Water Quality Management Chart in its own units, DIC (mmol/L) across and alkalinity (meq/L) up (Deffeyes 1965,
//! Limnol. Oceanogr. 10: 412): the box, the pH isolines, the NH₃, CO₂ and H₂S regions and borders, the safe zone, the
//! calcite and aragonite Ω = 1 lines (Mucci 1983, S 5–44), the target, the dosing layer clipped to the box, the
//! simulator's steps. A literal port of farm/water/deffeyes.py's `geometry` at golden v1; words are codes (the notes),
//! the host says them (farm/water/messages.py).
use alloc::vec;
use alloc::vec::Vec;

use crate::analysis::{self as a, AxisError, ChartBox, Status};
use crate::chemistry::{self as c, Equilibria};
use crate::num::{ChemError, div};

/// A point (DIC, alkalinity).
pub type P = (f64, f64);

/// Points along a curve.
pub const SAMPLES: usize = 96;
/// Ω is drawn only for the salinities Mucci (1983) measured.
pub const OMEGA_SALINITY: (f64, f64) = (5.0, 44.0);

/// Why there is no geometry.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum GeometryError {
    Chem(ChemError),
    ChartTooLarge,
}

impl From<ChemError> for GeometryError {
    fn from(error: ChemError) -> Self {
        GeometryError::Chem(error)
    }
}

impl From<AxisError> for GeometryError {
    fn from(_: AxisError) -> Self {
        GeometryError::ChartTooLarge
    }
}

type G<T> = Result<T, GeometryError>;

// ---- clipping ---------------------------------------------------------------------------------------------------

/// Sutherland–Hodgman: the part of a polygon where the linear function `inside` is ≥ 0.
fn clip(polygon: &[P], inside: &dyn Fn(P) -> f64) -> Vec<P> {
    let mut kept = Vec::new();
    let count = polygon.len();
    for index in 0..count {
        let (Some(&current), Some(&previous)) = (polygon.get(index), polygon.get((index + count - 1) % count)) else {
            continue;
        };
        let (now, before) = (inside(current), inside(previous));
        if now >= 0.0 {
            if before < 0.0 {
                kept.push(cross(previous, current, before, now));
            }
            kept.push(current);
        } else if before >= 0.0 {
            kept.push(cross(previous, current, before, now));
        }
    }
    kept
}

fn cross(start: P, end: P, at_start: f64, at_end: f64) -> P {
    let share = at_start / (at_start - at_end);
    (start.0 + share * (end.0 - start.0), start.1 + share * (end.1 - start.1))
}

/// The part of a polygon inside the box; [] when fewer than 3 vertices are left.
pub fn clip_to_box(polygon: &[P], chart: &ChartBox) -> Vec<P> {
    let (dic, alkalinity) = (chart.dic, chart.alkalinity);
    let sides: [&dyn Fn(P) -> f64; 4] = [&|p: P| p.0, &move |p: P| dic - p.0, &|p: P| p.1, &move |p: P| {
        alkalinity - p.1
    }];
    let mut polygon = polygon.to_vec();
    for side in sides {
        if polygon.is_empty() {
            break;
        }
        polygon = clip(&polygon, side);
    }
    if polygon.len() >= 3 { polygon } else { Vec::new() }
}

/// Liang–Barsky: the part of a segment inside the box, or None.
pub fn clip_segment(start: P, end: P, chart: &ChartBox) -> Option<(P, P)> {
    let (mut low, mut high) = (0.0_f64, 1.0_f64);
    let (dx, dy) = (end.0 - start.0, end.1 - start.1);
    for (p, q) in [
        (-dx, start.0),
        (dx, chart.dic - start.0),
        (-dy, start.1),
        (dy, chart.alkalinity - start.1),
    ] {
        if p == 0.0 {
            if q < 0.0 {
                return None;
            }
            continue;
        }
        let ratio = q / p;
        if p < 0.0 {
            if ratio > low {
                low = ratio;
            }
        } else if ratio < high {
            high = ratio;
        }
        if low > high {
            return None;
        }
    }
    if high - low < 1e-12 {
        return None;
    }
    Some((
        (start.0 + low * dx, start.1 + low * dy),
        (start.0 + high * dx, start.1 + high * dy),
    ))
}

/// The parts of a polyline inside the box, joined where a part starts within 1e-9 of where the last one ended.
pub fn clip_polyline(points: &[P], chart: &ChartBox) -> Vec<Vec<P>> {
    let mut lines: Vec<Vec<P>> = Vec::new();
    for pair in points.windows(2) {
        let (Some(&start), Some(&end)) = (pair.first(), pair.get(1)) else {
            continue;
        };
        let Some((first, second)) = clip_segment(start, end, chart) else {
            continue;
        };
        let joined = match lines.last_mut() {
            Some(line) => match line.last() {
                Some(&last) if libm::hypot(last.0 - first.0, last.1 - first.1) < 1e-9 => {
                    line.push(second);
                    true
                }
                _ => false,
            },
            None => false,
        };
        if !joined {
            lines.push(vec![first, second]);
        }
    }
    lines
}

fn corners(chart: &ChartBox) -> [P; 4] {
    [
        (0.0, 0.0),
        (chart.dic, 0.0),
        (chart.dic, chart.alkalinity),
        (0.0, chart.alkalinity),
    ]
}

// ---- the layers ---------------------------------------------------------------------------------------------------

/// A pH's isoline between its two ends inside the box.
pub fn isoline_segment(eq: &Equilibria, ph: f64, chart: &ChartBox) -> G<Option<(P, P)>> {
    let (slope, intercept) = eq.isoline(ph)?;
    Ok(clip_segment(
        (0.0, intercept),
        (chart.dic, slope * chart.dic + intercept),
        chart,
    ))
}

/// The part of the box above (higher pH) or below a pH's isoline.
pub fn half(eq: &Equilibria, ph: f64, chart: &ChartBox, above: bool) -> G<Vec<P>> {
    let (slope, intercept) = eq.isoline(ph)?;
    let sign = if above { 1.0 } else { -1.0 };
    let cut = clip(&corners(chart), &|p: P| sign * (p.1 - slope * p.0 - intercept));
    Ok(clip_to_box(&cut, chart))
}

/// The curve where CO₂ = `co2` (mmol/L) inside the box, from where it enters at alkalinity 0 to where it leaves at the
/// top or the right, and whether it leaves at the top; ([], false) when it does not cross the box.
pub fn co2_curve(eq: &Equilibria, co2: f64, chart: &ChartBox) -> G<(Vec<P>, bool)> {
    let alkalinity_at = |dic: f64| -> Result<f64, ChemError> {
        // Python passed None on to the alkalinity and raised; the core refuses the same inputs.
        let ph = eq.ph_where_co2_at_dic(dic, co2)?.ok_or(ChemError::Domain)?;
        eq.alkalinity(dic, ph)
    };
    if co2 >= chart.dic || alkalinity_at(chart.dic)? <= 0.0 {
        return Ok((Vec::new(), false));
    }
    let start = c::solve(&mut |dic| alkalinity_at(dic), co2 * (1.0 + 1e-9), chart.dic)?.ok_or(ChemError::Domain)?;
    let leaves_top = alkalinity_at(chart.dic)? > chart.alkalinity;
    let stop = if leaves_top {
        c::solve::<ChemError>(&mut |dic| Ok(alkalinity_at(dic)? - chart.alkalinity), start, chart.dic)?
            .ok_or(ChemError::Domain)?
    } else {
        chart.dic
    };
    let mut points = vec![(start, 0.0)];
    for step in 1..SAMPLES {
        let dic = start + (stop - start) * step as f64 / SAMPLES as f64;
        points.push((dic, alkalinity_at(dic)?));
    }
    points.push((
        stop,
        if leaves_top {
            chart.alkalinity
        } else {
            alkalinity_at(stop)?
        },
    ));
    Ok((points, leaves_top))
}

fn co2_region(curve: &[P], leaves_top: bool, chart: &ChartBox) -> Vec<P> {
    let mut region = curve.to_vec();
    if leaves_top {
        region.push((chart.dic, chart.alkalinity));
    }
    region.push((chart.dic, 0.0));
    region
}

/// Why there can be no safe zone, as codes: a missing value is never taken for a safe one.
pub fn safe_zone_gaps(analysis: &a::Analysis, limits: &a::Limits) -> Vec<&'static str> {
    let mut gaps = Vec::new();
    match (limits.alkalinity_low_mg_l, limits.alkalinity_high_mg_l) {
        (Some(low), Some(high)) => {
            if low >= high {
                gaps.push("safe.empty_band");
            }
        }
        _ => gaps.push("safe.no_band"),
    }
    if analysis.nh3.status == Status::NotMeasured {
        gaps.push("safe.no_tan");
    } else if analysis.nh3.status == Status::NoLimit {
        gaps.push("safe.no_nh3_limit");
    }
    if analysis.co2.status == Status::NoLimit {
        gaps.push("safe.no_co2_limit");
    }
    if analysis.h2s.status == Status::NoLimit {
        gaps.push("safe.no_h2s_limit");
    }
    gaps
}

/// The safe region: the alkalinity band, from the NH₃ isoline (the chart's top pH when the TAN cannot reach its
/// limit) to the CO₂ curve or the H₂S isoline, whichever is the higher pH; [] when a gap or no safe pH.
pub fn safe_zone(analysis: &a::Analysis, limits: &a::Limits, chart: &ChartBox) -> G<Vec<P>> {
    if !safe_zone_gaps(analysis, limits).is_empty() {
        return Ok(Vec::new());
    }
    let (Some(low_mg), Some(high_mg), Some(co2_mg)) =
        (limits.alkalinity_low_mg_l, limits.alkalinity_high_mg_l, limits.co2_mg_l)
    else {
        return Ok(Vec::new());
    };
    let eq = &analysis.equilibria;
    let low = div(low_mg, c::MG_CACO3_PER_MEQ)?;
    let high = div(high_mg, c::MG_CACO3_PER_MEQ)?;
    let top = analysis.nh3.ph.unwrap_or(a::PH_RANGE.1);
    let co2 = div(co2_mg, c::MG_CO2_PER_MMOL)?;
    let h2s = analysis.h2s.ph;
    let co2_alkalinity = |ph: f64| -> Result<f64, ChemError> { eq.alkalinity_where_co2(co2, ph) };
    let floor = |alkalinity: f64| -> Result<f64, ChemError> {
        let mut most = a::PH_RANGE.0;
        if let Some(border) = eq.ph_where_co2(alkalinity, co2)? {
            if border > most {
                most = border;
            }
        }
        if let Some(h2s) = h2s {
            if h2s > most {
                most = h2s;
            }
        }
        Ok(most)
    };
    let half_count = SAMPLES / 2;
    let mut rows: Vec<f64> = (0..=half_count)
        .map(|step| low + (high - low) * step as f64 / half_count as f64)
        .collect();
    let closes = co2_alkalinity(top)?;
    let more = [Some(closes), h2s.map(co2_alkalinity).transpose()?];
    rows.extend(
        more.into_iter()
            .flatten()
            .filter(|alkalinity| low < *alkalinity && *alkalinity < high),
    );
    rows.sort_by(|one, two| one.partial_cmp(two).unwrap_or(core::cmp::Ordering::Equal));
    rows.dedup();
    let mut kept = Vec::new();
    for row in rows {
        if row <= closes && (floor(row)? < top || row == closes) {
            kept.push(row);
        }
    }
    if kept.len() < 2 {
        return Ok(Vec::new());
    }
    let mut polygon = Vec::with_capacity(2 * kept.len());
    for &row in &kept {
        polygon.push((eq.dic(row, top)?, row));
    }
    for &row in kept.iter().rev() {
        let ph = if row == closes { top } else { floor(row)? };
        polygon.push((eq.dic(row, ph)?, row));
    }
    Ok(clip_to_box(&polygon, chart))
}

/// The line Ω = 1 (calcium × carbonate = Ksp, all per litre: `Equilibria::ksp_per_litre`, as the small chart's
/// saturation index) inside the box, from just above that carbonate (the source's start) to the box's right edge.
pub fn omega_line(eq: &Equilibria, calcium_mg_l: f64, ksp: f64, chart: &ChartBox) -> G<Vec<Vec<P>>> {
    let carbonate = div(eq.ksp_per_litre(ksp)?, div(calcium_mg_l, c::MG_CALCIUM_PER_MOL)?)? * 1000.0;
    let start = if carbonate + 0.01 >= 0.05 {
        carbonate + 0.01
    } else {
        0.05
    };
    if start >= chart.dic {
        return Ok(Vec::new());
    }
    let mut points = Vec::with_capacity(SAMPLES + 1);
    for step in 0..=SAMPLES {
        let dic = start + (chart.dic - start) * step as f64 / SAMPLES as f64;
        if let Some(ph) = eq.ph_where_carbonate(dic, carbonate)? {
            points.push((dic, eq.alkalinity(dic, ph)?));
        }
    }
    Ok(clip_polyline(&points, chart))
}

// ---- the whole chart ----------------------------------------------------------------------------------------------

/// The layers a chart may draw.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Layers {
    pub isolines: bool,
    pub safe: bool,
    pub nh3: bool,
    pub co2: bool,
    pub h2s: bool,
    pub omega: bool,
    pub target: bool,
    pub dosing: bool,
    pub simulator: bool,
}

/// The dosing layer as the host's dosing module drew it (reagent lines, the wedge, the path through the waypoint).
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Dosing<'a> {
    pub lines: Vec<(&'a str, Vec<P>)>,
    pub wedge: Vec<P>,
    pub path: Vec<P>,
    pub waypoint: Option<P>,
}

/// The chart of an analysis in its own units. `notes` are codes, in the order the Python drew them.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Geometry<'a> {
    pub chart: Option<ChartBox>,
    /// (pH, labelled, the two ends inside the box)
    pub isolines: Vec<(f64, bool, (P, P))>,
    /// (layer, polygon) in the order drawn: nh3, co2, h2s, safe
    pub regions: Vec<(&'static str, Vec<P>)>,
    pub boundaries: Vec<(&'static str, Vec<Vec<P>>)>,
    pub omega: Vec<(&'static str, Vec<Vec<P>>)>,
    pub point: P,
    pub target: Option<P>,
    pub reagent_lines: Vec<(&'a str, Vec<Vec<P>>)>,
    pub wedge: Vec<P>,
    pub dosing_path: Vec<Vec<P>>,
    pub waypoint: Option<P>,
    pub simulator: Vec<P>,
    pub notes: Vec<&'static str>,
}

/// The pH isolines: every 0.25 from 4.25 to 12.5, labelled every 0.5 from 5.0 to 12.0 (k odd, 3 ≤ k ≤ 31).
pub fn isoline_phs() -> impl Iterator<Item = (f64, bool)> {
    (0..34_u32).map(|k| (4.25 + 0.25 * f64::from(k), k % 2 == 1 && (3..=31).contains(&k)))
}

fn toxic_region<'a>(
    shape: &mut Geometry<'a>,
    eq: &Equilibria,
    key: &'static str,
    border: &a::Border,
    above: bool,
    note: &'static str,
) -> G<()> {
    let chart = shape.chart.ok_or(GeometryError::ChartTooLarge)?;
    let region = match border.ph {
        Some(ph) => half(eq, ph, &chart, above)?,
        None => Vec::new(),
    };
    match border.ph {
        Some(ph) if !region.is_empty() => {
            shape.regions.push((key, region));
            let segment = isoline_segment(eq, ph, &chart)?;
            shape
                .boundaries
                .push((key, segment.map(|(one, two)| vec![vec![one, two]]).unwrap_or_default()));
        }
        _ => shape.notes.push(note),
    }
    Ok(())
}

fn nh3_note(analysis: &a::Analysis) -> &'static str {
    match (analysis.nh3.status, analysis.nh3.ph) {
        (Status::NotMeasured, _) => "nh3.no_tan",
        (Status::NoLimit, _) => "nh3.no_limit",
        (_, Some(_)) => "nh3.not_reached",
        (_, None) => "nh3.cannot_reach",
    }
}

fn h2s_note(analysis: &a::Analysis) -> &'static str {
    match (analysis.h2s.status, analysis.h2s.ph) {
        (Status::NotMeasured, _) => "h2s.no_sulfide",
        (Status::NoLimit, _) => "h2s.no_limit",
        (_, Some(_)) => "h2s.not_reached",
        (_, None) => "h2s.cannot_reach",
    }
}

/// The chart of a water: the layers asked for; `simulator` the water after each step (the water first); `extent` more
/// points the box must hold, drawn as nothing (a replay page's).
#[allow(clippy::too_many_arguments)]
pub fn geometry<'a>(
    water: &a::Water,
    limits: &a::Limits,
    target: Option<&a::Target>,
    pressure: f64,
    layers: Layers,
    dosing: Option<&Dosing<'a>>,
    simulator: &[P],
    extent: &[P],
) -> G<Geometry<'a>> {
    let analysis = a::analyse(water, limits, target, pressure)?;
    let eq = analysis.equilibria;
    let show_target = layers.target && target.is_some();
    let path = layers.dosing && show_target && dosing.is_some_and(|dosing| !dosing.path.is_empty());
    let simulator: Vec<P> = if layers.simulator && simulator.len() > 1 {
        simulator.to_vec()
    } else {
        Vec::new()
    };
    let mut extra = simulator.clone();
    if path {
        if let Some(waypoint) = dosing.and_then(|dosing| dosing.waypoint) {
            extra.push(waypoint);
        }
    }
    extra.extend_from_slice(extent);
    let target_point = match (analysis.target_dic, analysis.target_alkalinity_meq) {
        (Some(dic), Some(alkalinity)) => Some((dic, alkalinity)),
        _ => None,
    };
    let chart = a::box_of(
        analysis.dic,
        analysis.alkalinity_meq,
        target_point,
        limits.alkalinity_high_mg_l,
        &extra,
    )?;
    let mut shape = Geometry {
        chart: Some(chart),
        point: (analysis.dic, analysis.alkalinity_meq),
        ..Geometry::default()
    };
    if layers.isolines {
        for (ph, labelled) in isoline_phs() {
            if let Some(segment) = isoline_segment(&eq, ph, &chart)? {
                shape.isolines.push((ph, labelled, segment));
            }
        }
    }
    if layers.nh3 {
        toxic_region(&mut shape, &eq, "nh3", &analysis.nh3, true, nh3_note(&analysis))?;
    }
    if layers.co2 {
        match limits.co2_mg_l {
            Some(limit) => {
                let (curve, leaves_top) =
                    co2_curve(&eq, div(analysis.co2_chart_limit(limit)?, c::MG_CO2_PER_MMOL)?, &chart)?;
                if !curve.is_empty() {
                    shape
                        .regions
                        .push(("co2", clip_to_box(&co2_region(&curve, leaves_top, &chart), &chart)));
                    shape.boundaries.push(("co2", vec![curve]));
                }
            }
            None => shape.notes.push("co2.no_limit"),
        }
    }
    if layers.h2s {
        toxic_region(&mut shape, &eq, "h2s", &analysis.h2s, false, h2s_note(&analysis))?;
    }
    if layers.safe {
        let gaps = safe_zone_gaps(&analysis, limits);
        let zone = safe_zone(&analysis, limits, &chart)?;
        if !gaps.is_empty() {
            shape.notes.extend(gaps);
        } else if !zone.is_empty() {
            shape.regions.push(("safe", zone));
            if analysis.h2s.status == Status::NotMeasured {
                shape.notes.push("safe.h2s_not_assessed");
            }
        } else {
            shape.notes.push("safe.no_safe_ph");
        }
    }
    if layers.omega {
        match water.calcium_mg_l {
            Some(calcium)
                if calcium != 0.0
                    && OMEGA_SALINITY.0 <= water.salinity_ppt
                    && water.salinity_ppt <= OMEGA_SALINITY.1 =>
            {
                shape
                    .omega
                    .push(("calcite", omega_line(&eq, calcium, eq.ksp_calcite, &chart)?));
                shape
                    .omega
                    .push(("aragonite", omega_line(&eq, calcium, eq.ksp_aragonite, &chart)?));
            }
            _ => shape.notes.push("omega.out_of_range"),
        }
    }
    if show_target {
        shape.target = target_point;
    }
    if layers.dosing {
        if let Some(dosing) = dosing {
            for (reagent, line) in &dosing.lines {
                shape.reagent_lines.push((reagent, clip_polyline(line, &chart)));
            }
            shape.wedge = if dosing.wedge.is_empty() {
                Vec::new()
            } else {
                clip_to_box(&dosing.wedge, &chart)
            };
            if path {
                shape.dosing_path = clip_polyline(&dosing.path, &chart);
                shape.waypoint = dosing.waypoint;
            }
        }
    }
    shape.simulator = simulator;
    Ok(shape)
}
