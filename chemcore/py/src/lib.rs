//! The Python module `chemcore`: a thin skin over `chemcore_core`. Only `farm/water/native.py` imports it.
//! Errors become the exception Python's formulas raised at the same place (ValueError, ZeroDivisionError,
//! OverflowError); a non-finite input or result is `chemcore.NonFiniteError` (a ValueError): never a NaN as a number.
use chemcore_core::analysis as a;
use chemcore_core::chemistry as c;
use chemcore_core::dosing as d;
use chemcore_core::geometry as g;
use chemcore_core::num::ChemError;
use pyo3::create_exception;
use pyo3::exceptions::{PyOverflowError, PyValueError, PyZeroDivisionError};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyTuple};

create_exception!(
    chemcore,
    NonFiniteError,
    PyValueError,
    "A non-finite input or result: never shown as a number."
);

fn err(error: ChemError) -> PyErr {
    match error {
        ChemError::Domain => PyValueError::new_err("math domain error"),
        ChemError::ZeroDivision => PyZeroDivisionError::new_err("float division by zero"),
        ChemError::Overflow => PyOverflowError::new_err("math range error"),
        ChemError::NonFinite => NonFiniteError::new_err("not a finite number"),
    }
}

fn ok(value: Result<f64, ChemError>) -> PyResult<f64> {
    match value {
        Ok(number) if number.is_finite() => Ok(number),
        Ok(_) => Err(err(ChemError::NonFinite)),
        Err(error) => Err(err(error)),
    }
}

fn ok_option(value: Result<Option<f64>, ChemError>) -> PyResult<Option<f64>> {
    match value {
        Ok(Some(number)) => ok(Ok(number)).map(Some),
        Ok(None) => Ok(None),
        Err(error) => Err(err(error)),
    }
}

fn inputs(values: &[f64]) -> PyResult<()> {
    if values.iter().all(|value| value.is_finite()) {
        Ok(())
    } else {
        Err(err(ChemError::NonFinite))
    }
}

/// The crate's version.
#[pyfunction]
fn version() -> &'static str {
    chemcore_core::VERSION
}

/// The formula version (see chemcore_core::FORMULA_VERSION).
#[pyfunction]
fn formula_version() -> u32 {
    chemcore_core::FORMULA_VERSION
}

/// The source digest the server checks against chemcore/EXPECTED.
#[pyfunction]
fn core_hash() -> &'static str {
    chemcore_core::core_hash()
}

/// The equilibria of one water (frozen; equal and hashed by its values).
#[pyclass(frozen, name = "Equilibria", module = "chemcore")]
struct Equilibria(c::Equilibria);

#[pymethods]
impl Equilibria {
    #[getter]
    fn temp_c(&self) -> f64 {
        self.0.temp_c
    }
    #[getter]
    fn salinity(&self) -> f64 {
        self.0.salinity
    }
    #[getter]
    fn ph_offset(&self) -> f64 {
        self.0.ph_offset
    }
    #[getter]
    fn k1(&self) -> f64 {
        self.0.k1
    }
    #[getter]
    fn k2(&self) -> f64 {
        self.0.k2
    }
    #[getter]
    fn kw(&self) -> f64 {
        self.0.kw
    }
    #[getter]
    fn kb(&self) -> f64 {
        self.0.kb
    }
    #[getter]
    fn boron(&self) -> f64 {
        self.0.boron
    }
    #[getter]
    fn k_nh4(&self) -> f64 {
        self.0.k_nh4
    }
    #[getter]
    fn k_h2s(&self) -> f64 {
        self.0.k_h2s
    }
    #[getter]
    fn ksp_calcite(&self) -> f64 {
        self.0.ksp_calcite
    }
    #[getter]
    fn ksp_aragonite(&self) -> f64 {
        self.0.ksp_aragonite
    }

    /// The field names, in order (the dataclass's).
    #[classattr]
    fn fields() -> Vec<&'static str> {
        vec![
            "temp_c",
            "salinity",
            "ph_offset",
            "k1",
            "k2",
            "kw",
            "kb",
            "boron",
            "k_nh4",
            "k_h2s",
            "ksp_calcite",
            "ksp_aragonite",
        ]
    }

    fn values(&self) -> Vec<f64> {
        let e = &self.0;
        vec![
            e.temp_c,
            e.salinity,
            e.ph_offset,
            e.k1,
            e.k2,
            e.kw,
            e.kb,
            e.boron,
            e.k_nh4,
            e.k_h2s,
            e.ksp_calcite,
            e.ksp_aragonite,
        ]
    }

    fn __eq__(&self, other: &Bound<'_, PyAny>) -> bool {
        other
            .cast::<Equilibria>()
            .map(|other| other.get().0 == self.0)
            .unwrap_or(false)
    }

    fn __hash__(&self) -> u64 {
        self.values().iter().fold(0xcbf2_9ce4_8422_2325_u64, |hash, value| {
            (hash ^ value.to_bits()).wrapping_mul(0x0000_0100_0000_01b3)
        })
    }

    fn __repr__(&self) -> String {
        let e = &self.0;
        format!(
            "Equilibria(temp_c={:?}, salinity={:?}, ph_offset={:?}, k1={:?}, k2={:?}, kw={:?}, kb={:?}, boron={:?}, \
             k_nh4={:?}, k_h2s={:?}, ksp_calcite={:?}, ksp_aragonite={:?})",
            e.temp_c,
            e.salinity,
            e.ph_offset,
            e.k1,
            e.k2,
            e.kw,
            e.kb,
            e.boron,
            e.k_nh4,
            e.k_h2s,
            e.ksp_calcite,
            e.ksp_aragonite
        )
    }

    fn hydrogen(&self, ph: f64) -> PyResult<f64> {
        inputs(&[ph])?;
        ok(self.0.hydrogen(ph))
    }
    fn ph_of(&self, hydrogen: f64) -> PyResult<f64> {
        inputs(&[hydrogen])?;
        ok(self.0.ph_of(hydrogen))
    }
    fn fractions(&self, ph: f64) -> PyResult<(f64, f64, f64)> {
        inputs(&[ph])?;
        let (a, b, d) = self.0.fractions(ph).map_err(err)?;
        Ok((ok(Ok(a))?, ok(Ok(b))?, ok(Ok(d))?))
    }
    fn isoline(&self, ph: f64) -> PyResult<(f64, f64)> {
        inputs(&[ph])?;
        let (slope, intercept) = self.0.isoline(ph).map_err(err)?;
        Ok((ok(Ok(slope))?, ok(Ok(intercept))?))
    }
    fn dic(&self, alkalinity: f64, ph: f64) -> PyResult<f64> {
        inputs(&[alkalinity, ph])?;
        ok(self.0.dic(alkalinity, ph))
    }
    fn alkalinity(&self, dic: f64, ph: f64) -> PyResult<f64> {
        inputs(&[dic, ph])?;
        ok(self.0.alkalinity(dic, ph))
    }
    fn ph_at(&self, dic: f64, alkalinity: f64) -> PyResult<Option<f64>> {
        inputs(&[dic, alkalinity])?;
        ok_option(self.0.ph_at(dic, alkalinity))
    }
    fn co2(&self, dic: f64, ph: f64) -> PyResult<f64> {
        inputs(&[dic, ph])?;
        ok(self.0.co2(dic, ph))
    }
    fn carbonate(&self, dic: f64, ph: f64) -> PyResult<f64> {
        inputs(&[dic, ph])?;
        ok(self.0.carbonate(dic, ph))
    }
    fn nh3_share(&self, ph: f64) -> PyResult<f64> {
        inputs(&[ph])?;
        ok(self.0.nh3_share(ph))
    }
    fn h2s_share(&self, ph: f64) -> PyResult<f64> {
        inputs(&[ph])?;
        ok(self.0.h2s_share(ph))
    }
    fn ph_where_nh3(&self, tan: f64, limit: f64) -> PyResult<Option<f64>> {
        inputs(&[tan, limit])?;
        ok_option(self.0.ph_where_nh3(tan, limit))
    }
    fn ph_where_h2s(&self, total: f64, limit: f64) -> PyResult<Option<f64>> {
        inputs(&[total, limit])?;
        ok_option(self.0.ph_where_h2s(total, limit))
    }
    fn ph_where_co2(&self, alkalinity: f64, co2: f64) -> PyResult<Option<f64>> {
        inputs(&[alkalinity, co2])?;
        ok_option(self.0.ph_where_co2(alkalinity, co2))
    }
    fn ph_where_co2_at_dic(&self, dic: f64, co2: f64) -> PyResult<Option<f64>> {
        inputs(&[dic, co2])?;
        ok_option(self.0.ph_where_co2_at_dic(dic, co2))
    }
    fn ph_where_carbonate(&self, dic: f64, carbonate: f64) -> PyResult<Option<f64>> {
        inputs(&[dic, carbonate])?;
        ok_option(self.0.ph_where_carbonate(dic, carbonate))
    }
}

#[pyfunction]
fn equilibria(temp_c: f64, salinity: f64) -> PyResult<Equilibria> {
    c::equilibria(temp_c, salinity).map(Equilibria).map_err(err)
}

/// Where a Python function crosses zero between two values (the core's solver, called back).
#[pyfunction]
fn solve(function: &Bound<'_, PyAny>, low: f64, high: f64) -> PyResult<Option<f64>> {
    inputs(&[low, high])?;
    c::solve(
        &mut |x: f64| -> PyResult<f64> { function.call1(PyTuple::new(function.py(), [x])?)?.extract::<f64>() },
        low,
        high,
    )
}

macro_rules! of_temperature_and_salinity {
    ($($name:ident),*) => {$(
        #[pyfunction]
        fn $name(temp_c: f64, salinity: f64) -> PyResult<f64> {
            inputs(&[temp_c, salinity])?;
            ok(c::$name(temp_c, salinity))
        }
    )*};
}
of_temperature_and_salinity!(
    ks,
    kf,
    free_to_sws,
    free_to_total,
    activity_coefficient_h,
    sws_to_nbs,
    k1_sws,
    k2_sws,
    kw_total,
    kb_total,
    k_nh4_sws,
    pk_nh4,
    k_h2s_total,
    ksp_calcite,
    ksp_aragonite,
    k0_co2
);

#[pyfunction]
fn ionic_strength(salinity: f64) -> PyResult<f64> {
    inputs(&[salinity])?;
    ok(c::ionic_strength(salinity))
}
#[pyfunction]
fn total_sulfate(salinity: f64) -> PyResult<f64> {
    inputs(&[salinity])?;
    ok(Ok(c::total_sulfate(salinity)))
}
#[pyfunction]
fn total_fluoride(salinity: f64) -> PyResult<f64> {
    inputs(&[salinity])?;
    ok(Ok(c::total_fluoride(salinity)))
}
#[pyfunction]
fn total_boron(salinity: f64) -> PyResult<f64> {
    inputs(&[salinity])?;
    ok(Ok(c::total_boron(salinity)))
}
#[pyfunction]
fn ph_free(ph_nbs: f64, temp_c: f64, salinity: f64) -> PyResult<f64> {
    inputs(&[ph_nbs, temp_c, salinity])?;
    ok(c::ph_free(ph_nbs, temp_c, salinity))
}
#[pyfunction]
fn nh3_fraction(ph_nbs: f64, temp_c: f64, salinity: f64) -> PyResult<f64> {
    inputs(&[ph_nbs, temp_c, salinity])?;
    ok(c::nh3_fraction(ph_nbs, temp_c, salinity))
}
#[pyfunction]
fn pressure_atm(altitude_m: f64) -> PyResult<f64> {
    inputs(&[altitude_m])?;
    ok(c::pressure_atm(altitude_m))
}
#[pyfunction]
fn vapour_pressure_atm(temp_c: f64) -> PyResult<f64> {
    inputs(&[temp_c])?;
    ok(c::vapour_pressure_atm(temp_c))
}
#[pyfunction]
#[pyo3(signature = (temp_c, salinity, pressure=1.0))]
fn oxygen_solubility(temp_c: f64, salinity: f64, pressure: f64) -> PyResult<f64> {
    inputs(&[temp_c, salinity, pressure])?;
    ok(c::oxygen_solubility(temp_c, salinity, pressure))
}
#[pyfunction]
#[pyo3(signature = (temp_c, salinity, pressure=1.0))]
fn co2_from_air(temp_c: f64, salinity: f64, pressure: f64) -> PyResult<f64> {
    inputs(&[temp_c, salinity, pressure])?;
    ok(c::co2_from_air(temp_c, salinity, pressure))
}

// ---- the analysis of a water (chemcore/core/src/analysis.rs) ---------------------------------------------------

create_exception!(
    chemcore,
    ChartTooLargeError,
    PyValueError,
    "The values need more than 12 ticks of 5e7 on an axis."
);

fn border<'py>(py: Python<'py>, border: &a::Border) -> PyResult<Bound<'py, PyDict>> {
    let dict = PyDict::new(py);
    dict.set_item("ph", border.ph)?;
    dict.set_item("toxic_above", border.toxic_above)?;
    dict.set_item("margin", border.margin)?;
    dict.set_item("status", border.status.code())?;
    dict.set_item("on_chart", border.on_chart())?;
    dict.set_item("everywhere", border.everywhere())?;
    dict.set_item("off_chart", border.off_chart())?;
    Ok(dict)
}

fn status(code: Option<&str>) -> PyResult<Option<a::Status>> {
    code.map(|code| a::Status::from_code(code).ok_or_else(|| PyValueError::new_err(format!("no status {code}"))))
        .transpose()
}

/// The border and the status of a pH against a border (see chemcore_core::analysis::judge), as a dict.
#[pyfunction]
#[pyo3(signature = (ph, border, toxic_above, missing=None))]
fn judge<'py>(
    py: Python<'py>,
    ph: f64,
    border: Option<f64>,
    toxic_above: bool,
    missing: Option<&str>,
) -> PyResult<Bound<'py, PyDict>> {
    inputs(&[ph])?;
    if let Some(border) = border {
        inputs(&[border])?;
    }
    self::border(py, &a::judge(ph, border, toxic_above, status(missing)?))
}

/// The values of a water against its limits, as a dict with the names of farm/water/deffeyes.py's Analysis (the
/// borders as dicts, statuses as codes) and `equilibria`.
#[pyfunction]
#[pyo3(signature = (temperature_c, salinity_ppt, ph, alkalinity_mg_l, tan_mg_l=None, total_sulfide_ug_l=None,
                    calcium_mg_l=None, oxygen_mg_l=None, nh3_n_mg_l=None, co2_mg_l=None, h2s_ug_l=None,
                    alkalinity_low_mg_l=None, alkalinity_high_mg_l=None, target_ph=None, target_alkalinity_mg_l=None,
                    pressure=1.0))]
#[allow(clippy::too_many_arguments)]
fn analyse<'py>(
    py: Python<'py>,
    temperature_c: f64,
    salinity_ppt: f64,
    ph: f64,
    alkalinity_mg_l: f64,
    tan_mg_l: Option<f64>,
    total_sulfide_ug_l: Option<f64>,
    calcium_mg_l: Option<f64>,
    oxygen_mg_l: Option<f64>,
    nh3_n_mg_l: Option<f64>,
    co2_mg_l: Option<f64>,
    h2s_ug_l: Option<f64>,
    alkalinity_low_mg_l: Option<f64>,
    alkalinity_high_mg_l: Option<f64>,
    target_ph: Option<f64>,
    target_alkalinity_mg_l: Option<f64>,
    pressure: f64,
) -> PyResult<Bound<'py, PyDict>> {
    let water = a::Water {
        temperature_c,
        salinity_ppt,
        ph,
        alkalinity_mg_l,
        tan_mg_l,
        total_sulfide_ug_l,
        calcium_mg_l,
        oxygen_mg_l,
    };
    let limits = a::Limits {
        nh3_n_mg_l,
        co2_mg_l,
        h2s_ug_l,
        alkalinity_low_mg_l,
        alkalinity_high_mg_l,
    };
    let target = match (target_ph, target_alkalinity_mg_l) {
        (Some(ph), Some(alkalinity_mg_l)) => Some(a::Target { ph, alkalinity_mg_l }),
        (None, None) => None,
        _ => return Err(PyValueError::new_err("a target is a pH and an alkalinity")),
    };
    let result = a::analyse(&water, &limits, target.as_ref(), pressure).map_err(err)?;
    let dict = PyDict::new(py);
    dict.set_item("equilibria", Equilibria(result.equilibria))?;
    for (name, value) in [
        ("alkalinity_meq", Some(result.alkalinity_meq)),
        ("dic", Some(result.dic)),
        ("co2_mg_l", Some(result.co2_mg_l)),
        ("target_alkalinity_meq", result.target_alkalinity_meq),
        ("target_dic", result.target_dic),
        ("target_co2_mg_l", result.target_co2_mg_l),
        ("nh3_n_mg_l", result.nh3_n_mg_l),
        ("safe_tan_mg_l", result.safe_tan_mg_l),
        ("nh3_share_at_border_pct", result.nh3_share_at_border_pct),
        ("h2s_ug_l", result.h2s_ug_l),
        ("safe_total_sulfide_ug_l", result.safe_total_sulfide_ug_l),
        ("oxygen_solubility_mg_l", Some(result.oxygen_solubility_mg_l)),
        ("oxygen_saturation_pct", result.oxygen_saturation_pct),
        ("pressure_atm", Some(result.pressure_atm)),
        ("nh3_share_pct", Some(result.nh3_share_pct)),
        ("h2s_share_pct", Some(result.h2s_share_pct)),
    ] {
        dict.set_item(name, value.map(|value| ok(Ok(value))).transpose()?)?;
    }
    dict.set_item("co2", border(py, &result.co2)?)?;
    dict.set_item("nh3", border(py, &result.nh3)?)?;
    dict.set_item("h2s", border(py, &result.h2s)?)?;
    Ok(dict)
}

#[pyfunction]
fn alkalinity_floor(temperature_c: f64, salinity_ppt: f64, ph: f64) -> PyResult<f64> {
    inputs(&[temperature_c, salinity_ppt, ph])?;
    ok(a::alkalinity_floor(temperature_c, salinity_ppt, ph))
}

/// The alkalinity floor when a water of this pH and alkalinity cannot be, else None.
#[pyfunction]
fn why_impossible(temperature_c: f64, salinity_ppt: f64, ph: f64, alkalinity_mg_l: f64) -> PyResult<Option<f64>> {
    inputs(&[temperature_c, salinity_ppt, ph, alkalinity_mg_l])?;
    ok_option(a::why_impossible(temperature_c, salinity_ppt, ph, alkalinity_mg_l))
}

/// The chart's box: (DIC end, alkalinity end, DIC step, alkalinity step).
#[pyfunction]
#[pyo3(signature = (dic, alkalinity_meq, target=None, alkalinity_high_mg_l=None, extra=Vec::new()))]
fn box_of(
    dic: f64,
    alkalinity_meq: f64,
    target: Option<(f64, f64)>,
    alkalinity_high_mg_l: Option<f64>,
    extra: Vec<(f64, f64)>,
) -> PyResult<(f64, f64, f64, f64)> {
    inputs(&[dic, alkalinity_meq])?;
    let chart = a::box_of(dic, alkalinity_meq, target, alkalinity_high_mg_l, &extra)
        .map_err(|_| ChartTooLargeError::new_err("the values need more than 12 ticks of 5e7 on an axis"))?;
    Ok((chart.dic, chart.alkalinity, chart.dic_step, chart.alkalinity_step))
}

// ---- the chart in its own units (chemcore/core/src/geometry.rs) ------------------------------------------------

type Point = (f64, f64);

fn optional(dict: &Bound<'_, PyDict>, key: &str) -> PyResult<Option<f64>> {
    match dict.get_item(key)? {
        Some(value) if !value.is_none() => Ok(Some(value.extract::<f64>()?)),
        _ => Ok(None),
    }
}

fn required(dict: &Bound<'_, PyDict>, key: &str) -> PyResult<f64> {
    optional(dict, key)?.ok_or_else(|| PyValueError::new_err(format!("{key} is required")))
}

fn water_of(water: &Bound<'_, PyDict>) -> PyResult<a::Water> {
    Ok(a::Water {
        temperature_c: required(water, "temperature_c")?,
        salinity_ppt: required(water, "salinity_ppt")?,
        ph: required(water, "ph")?,
        alkalinity_mg_l: required(water, "alkalinity_mg_l")?,
        tan_mg_l: optional(water, "tan_mg_l")?,
        total_sulfide_ug_l: optional(water, "total_sulfide_ug_l")?,
        calcium_mg_l: optional(water, "calcium_mg_l")?,
        oxygen_mg_l: optional(water, "oxygen_mg_l")?,
    })
}

fn limits_of(limits: &Bound<'_, PyDict>) -> PyResult<a::Limits> {
    Ok(a::Limits {
        nh3_n_mg_l: optional(limits, "nh3_n_mg_l")?,
        co2_mg_l: optional(limits, "co2_mg_l")?,
        h2s_ug_l: optional(limits, "h2s_ug_l")?,
        alkalinity_low_mg_l: optional(limits, "alkalinity_low_mg_l")?,
        alkalinity_high_mg_l: optional(limits, "alkalinity_high_mg_l")?,
    })
}

fn geometry_err(error: g::GeometryError) -> PyErr {
    match error {
        g::GeometryError::Chem(error) => err(error),
        g::GeometryError::ChartTooLarge => ChartTooLargeError::new_err("the values need more than 12 ticks of 5e7"),
    }
}

fn chart_box(chart: (f64, f64, f64, f64)) -> a::ChartBox {
    a::ChartBox {
        dic: chart.0,
        alkalinity: chart.1,
        dic_step: chart.2,
        alkalinity_step: chart.3,
    }
}

fn analysis_of(
    water: &Bound<'_, PyDict>,
    limits: &a::Limits,
    target: Option<Point>,
    pressure: f64,
) -> PyResult<a::Analysis> {
    let target = target.map(|(ph, alkalinity_mg_l)| a::Target { ph, alkalinity_mg_l });
    a::analyse(&water_of(water)?, limits, target.as_ref(), pressure).map_err(err)
}

/// Why there can be no safe zone, as codes (farm/water/messages.py says them).
#[pyfunction]
#[pyo3(signature = (water, limits, target=None, pressure=1.0))]
fn safe_zone_gaps(
    water: &Bound<'_, PyDict>,
    limits: &Bound<'_, PyDict>,
    target: Option<Point>,
    pressure: f64,
) -> PyResult<Vec<&'static str>> {
    let limits = limits_of(limits)?;
    Ok(g::safe_zone_gaps(
        &analysis_of(water, &limits, target, pressure)?,
        &limits,
    ))
}

/// The safe zone of a water in a given box, as a polygon (DIC, alkalinity).
#[pyfunction]
#[pyo3(signature = (water, limits, chart, target=None, pressure=1.0))]
fn safe_zone(
    water: &Bound<'_, PyDict>,
    limits: &Bound<'_, PyDict>,
    chart: (f64, f64, f64, f64),
    target: Option<Point>,
    pressure: f64,
) -> PyResult<Vec<Point>> {
    let limits = limits_of(limits)?;
    let analysis = analysis_of(water, &limits, target, pressure)?;
    g::safe_zone(&analysis, &limits, &chart_box(chart)).map_err(geometry_err)
}

/// The chart of a water in its own units, as a dict (see chemcore_core::geometry::Geometry; notes as codes).
#[pyfunction]
#[pyo3(signature = (water, limits, target=None, pressure=1.0, layers=Vec::new(), dosing=None, simulator=Vec::new(),
                    extent=Vec::new()))]
#[allow(clippy::too_many_arguments)]
fn geometry<'py>(
    py: Python<'py>,
    water: &Bound<'py, PyDict>,
    limits: &Bound<'py, PyDict>,
    target: Option<Point>,
    pressure: f64,
    layers: Vec<String>,
    dosing: Option<&Bound<'py, PyDict>>,
    simulator: Vec<Point>,
    extent: Vec<Point>,
) -> PyResult<Bound<'py, PyDict>> {
    let mut chosen = g::Layers::default();
    for layer in &layers {
        match layer.as_str() {
            "isolines" => chosen.isolines = true,
            "safe" => chosen.safe = true,
            "nh3" => chosen.nh3 = true,
            "co2" => chosen.co2 = true,
            "h2s" => chosen.h2s = true,
            "omega" => chosen.omega = true,
            "target" => chosen.target = true,
            "dosing" => chosen.dosing = true,
            "simulator" => chosen.simulator = true,
            other => return Err(PyValueError::new_err(format!("no layer {other}"))),
        }
    }
    let mut keys: Vec<String> = Vec::new();
    let mut lines: Vec<Vec<Point>> = Vec::new();
    let (mut wedge, mut path, mut waypoint) = (Vec::new(), Vec::new(), None);
    if let Some(dosing) = dosing {
        if let Some(found) = dosing.get_item("lines")? {
            for (key, line) in found.extract::<Vec<(String, Vec<Point>)>>()? {
                keys.push(key);
                lines.push(line);
            }
        }
        if let Some(found) = dosing.get_item("wedge")? {
            wedge = found.extract()?;
        }
        if let Some(found) = dosing.get_item("path")? {
            path = found.extract()?;
        }
        if let Some(found) = dosing.get_item("waypoint")? {
            waypoint = found.extract()?;
        }
    }
    let visual = dosing.map(|_| g::Dosing {
        lines: keys.iter().map(String::as_str).zip(lines.iter().cloned()).collect(),
        wedge: wedge.clone(),
        path: path.clone(),
        waypoint,
    });
    let target = target.map(|(ph, alkalinity_mg_l)| a::Target { ph, alkalinity_mg_l });
    let shape = g::geometry(
        &water_of(water)?,
        &limits_of(limits)?,
        target.as_ref(),
        pressure,
        chosen,
        visual.as_ref(),
        &simulator,
        &extent,
    )
    .map_err(geometry_err)?;
    let dict = PyDict::new(py);
    let chart = shape.chart.ok_or_else(|| ChartTooLargeError::new_err("no box"))?;
    dict.set_item(
        "box",
        (chart.dic, chart.alkalinity, chart.dic_step, chart.alkalinity_step),
    )?;
    dict.set_item("isolines", shape.isolines)?;
    let regions = PyDict::new(py);
    for (key, polygon) in shape.regions {
        regions.set_item(key, polygon)?;
    }
    dict.set_item("regions", regions)?;
    let boundaries = PyDict::new(py);
    for (key, found) in shape.boundaries {
        boundaries.set_item(key, found)?;
    }
    dict.set_item("boundaries", boundaries)?;
    let omega = PyDict::new(py);
    for (key, found) in shape.omega {
        omega.set_item(key, found)?;
    }
    dict.set_item("omega", omega)?;
    dict.set_item("point", shape.point)?;
    dict.set_item("target", shape.target)?;
    dict.set_item("reagent_lines", shape.reagent_lines)?;
    dict.set_item("wedge", shape.wedge)?;
    dict.set_item("dosing_path", shape.dosing_path)?;
    dict.set_item("waypoint", shape.waypoint)?;
    dict.set_item("simulator", shape.simulator)?;
    dict.set_item("notes", shape.notes)?;
    Ok(dict)
}

/// The parts of a polyline inside a box (DIC end, alkalinity end, steps): Liang-Barsky per segment, joined within
/// 1e-9 (the small plots' clipping too).
#[pyfunction]
fn clip_polyline(points: Vec<Point>, chart: (f64, f64, f64, f64)) -> PyResult<Vec<Vec<Point>>> {
    Ok(g::clip_polyline(&points, &chart_box(chart)))
}

// ---- dosing (chemcore/core/src/dosing.rs) ----------------------------------------------------------------------

fn reagent_of(key: &str) -> PyResult<d::Reagent> {
    d::by_key(key).ok_or_else(|| PyValueError::new_err(format!("no reagent {key}")))
}

/// The reagents in their order: (key, molar mass g/mol, DIC mmol, alkalinity meq per mmol).
#[pyfunction]
fn reagents() -> Vec<(&'static str, f64, f64, f64)> {
    d::reagents()
        .iter()
        .map(|reagent| (reagent.key, reagent.molar_mass, reagent.dic, reagent.alkalinity))
        .collect()
}

#[pyfunction]
fn at_target(start: Point, end: Point) -> bool {
    d::at_target(start, end)
}

/// (lower key, a, higher key, b) of two reagents from start to end, or None.
#[pyfunction]
fn split(
    start: Point,
    end: Point,
    first: &str,
    second: &str,
) -> PyResult<Option<(&'static str, f64, &'static str, f64)>> {
    Ok(d::split(start, end, reagent_of(first)?, reagent_of(second)?)
        .map(|(lower, a, higher, b)| (lower.key, a, higher.key, b)))
}

/// The recipes, practical first: [{'doses': [(key, concentration, grams or None, delta DIC, delta alkalinity)],
/// 'waypoint': (DIC, alkalinity), 'below_air': bool}]. `air`: (temperature, salinity, the air's CO2 mg/L) to flag a
/// stripping that ends below the air's whichever dose goes first.
#[pyfunction]
#[pyo3(signature = (start, end, chosen, volume=None, air=None))]
fn recipes<'py>(
    py: Python<'py>,
    start: Point,
    end: Point,
    chosen: Vec<String>,
    volume: Option<f64>,
    air: Option<(f64, f64, f64)>,
) -> PyResult<Vec<Bound<'py, PyDict>>> {
    let keys: Vec<&str> = chosen.iter().map(String::as_str).collect();
    let equilibria = air
        .map(|(temperature, salinity, _co2)| c::equilibria(temperature, salinity))
        .transpose()
        .map_err(err)?;
    let air = match (&equilibria, air) {
        (Some(equilibria), Some((_t, _s, co2_mg_l))) => Some(d::Air { equilibria, co2_mg_l }),
        _ => None,
    };
    let found = d::recipes(start, end, &keys, volume, air.as_ref()).map_err(err)?;
    let mut made = Vec::with_capacity(found.len());
    for recipe in found {
        let dict = PyDict::new(py);
        let doses: Vec<(&str, f64, Option<f64>, f64, f64)> = recipe
            .doses
            .iter()
            .map(|dose| {
                (
                    dose.reagent.key,
                    dose.concentration,
                    dose.grams,
                    dose.delta_dic,
                    dose.delta_alkalinity,
                )
            })
            .collect();
        dict.set_item("doses", doses)?;
        dict.set_item("waypoint", recipe.waypoint)?;
        dict.set_item("below_air", recipe.below_air)?;
        made.push(dict);
    }
    Ok(made)
}

/// The chart's dosing layer: {'lines': [(key, points)], 'wedge', 'path', 'waypoint', 'note': a code or None}.
#[pyfunction]
#[pyo3(signature = (start, end, chosen))]
fn visual<'py>(py: Python<'py>, start: Point, end: Option<Point>, chosen: Vec<String>) -> PyResult<Bound<'py, PyDict>> {
    let keys: Vec<&str> = chosen.iter().map(String::as_str).collect();
    let shown = d::visual(start, end, &keys).map_err(err)?;
    let dict = PyDict::new(py);
    dict.set_item("lines", shown.lines)?;
    dict.set_item("wedge", shown.wedge)?;
    dict.set_item("path", shown.path)?;
    dict.set_item("waypoint", shown.waypoint)?;
    dict.set_item("note", shown.note)?;
    Ok(dict)
}

/// The simulator's steps: [(key or None, grams, DIC, alkalinity, pH or None, CO2 mg/L or None, below the air)].
#[pyfunction]
#[pyo3(signature = (temperature_c, salinity_ppt, start, ph, amounts, volume, air_co2_mg_l=None))]
#[allow(clippy::type_complexity)]
fn simulate(
    temperature_c: f64,
    salinity_ppt: f64,
    start: Point,
    ph: f64,
    amounts: Vec<(String, f64)>,
    volume: f64,
    air_co2_mg_l: Option<f64>,
) -> PyResult<Vec<(Option<&'static str>, f64, f64, f64, Option<f64>, Option<f64>, bool)>> {
    let eq = c::equilibria(temperature_c, salinity_ppt).map_err(err)?;
    let amounts: Vec<(&str, f64)> = amounts.iter().map(|(key, grams)| (key.as_str(), *grams)).collect();
    let steps = d::simulate(&eq, start, ph, &amounts, volume, air_co2_mg_l).map_err(err)?;
    Ok(steps
        .iter()
        .map(|step| {
            (
                step.reagent,
                step.grams,
                step.dic,
                step.alkalinity,
                step.ph,
                step.co2_mg_l,
                step.below_air,
            )
        })
        .collect())
}

#[pymodule]
fn chemcore(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add("NonFiniteError", module.py().get_type::<NonFiniteError>())?;
    module.add("ChartTooLargeError", module.py().get_type::<ChartTooLargeError>())?;
    module.add("PH_RANGE", a::PH_RANGE)?;
    module.add("ALERT_PH", a::ALERT_PH)?;
    module.add("AXIS", a::AXIS)?;
    module.add("KELVIN", c::KELVIN)?;
    module.add("MG_CACO3_PER_MEQ", c::MG_CACO3_PER_MEQ)?;
    module.add("MG_CO2_PER_MMOL", c::MG_CO2_PER_MMOL)?;
    module.add("MG_CALCIUM_PER_MOL", c::MG_CALCIUM_PER_MOL)?;
    module.add("H2S_PER_S", c::H2S_PER_S)?;
    module.add("SOLVER_PH", c::SOLVER_PH)?;
    module.add("AIR_CO2", c::AIR_CO2)?;
    module.add_class::<Equilibria>()?;
    module.add_function(wrap_pyfunction!(version, module)?)?;
    module.add_function(wrap_pyfunction!(formula_version, module)?)?;
    module.add_function(wrap_pyfunction!(core_hash, module)?)?;
    module.add_function(wrap_pyfunction!(equilibria, module)?)?;
    module.add_function(wrap_pyfunction!(solve, module)?)?;
    for function in [
        wrap_pyfunction!(ks, module)?,
        wrap_pyfunction!(kf, module)?,
        wrap_pyfunction!(free_to_sws, module)?,
        wrap_pyfunction!(free_to_total, module)?,
        wrap_pyfunction!(activity_coefficient_h, module)?,
        wrap_pyfunction!(sws_to_nbs, module)?,
        wrap_pyfunction!(k1_sws, module)?,
        wrap_pyfunction!(k2_sws, module)?,
        wrap_pyfunction!(kw_total, module)?,
        wrap_pyfunction!(kb_total, module)?,
        wrap_pyfunction!(k_nh4_sws, module)?,
        wrap_pyfunction!(pk_nh4, module)?,
        wrap_pyfunction!(k_h2s_total, module)?,
        wrap_pyfunction!(ksp_calcite, module)?,
        wrap_pyfunction!(ksp_aragonite, module)?,
        wrap_pyfunction!(k0_co2, module)?,
        wrap_pyfunction!(ionic_strength, module)?,
        wrap_pyfunction!(total_sulfate, module)?,
        wrap_pyfunction!(total_fluoride, module)?,
        wrap_pyfunction!(total_boron, module)?,
        wrap_pyfunction!(ph_free, module)?,
        wrap_pyfunction!(nh3_fraction, module)?,
        wrap_pyfunction!(pressure_atm, module)?,
        wrap_pyfunction!(vapour_pressure_atm, module)?,
        wrap_pyfunction!(oxygen_solubility, module)?,
        wrap_pyfunction!(co2_from_air, module)?,
        wrap_pyfunction!(judge, module)?,
        wrap_pyfunction!(analyse, module)?,
        wrap_pyfunction!(alkalinity_floor, module)?,
        wrap_pyfunction!(why_impossible, module)?,
        wrap_pyfunction!(box_of, module)?,
        wrap_pyfunction!(safe_zone_gaps, module)?,
        wrap_pyfunction!(safe_zone, module)?,
        wrap_pyfunction!(geometry, module)?,
        wrap_pyfunction!(clip_polyline, module)?,
        wrap_pyfunction!(reagents, module)?,
        wrap_pyfunction!(at_target, module)?,
        wrap_pyfunction!(split, module)?,
        wrap_pyfunction!(recipes, module)?,
        wrap_pyfunction!(visual, module)?,
        wrap_pyfunction!(simulate, module)?,
    ] {
        module.add_function(function)?;
    }
    Ok(())
}
