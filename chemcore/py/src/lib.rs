//! The Python module `chemcore`: a thin skin over `chemcore_core`. Only `farm/water/native.py` imports it.
//! Errors become the exception Python's formulas raised at the same place (ValueError, ZeroDivisionError,
//! OverflowError); a non-finite input or result is `chemcore.NonFiniteError` (a ValueError): never a NaN as a number.
use chemcore_core::analysis as a;
use chemcore_core::chemistry as c;
use chemcore_core::dosing as d;
use chemcore_core::fresh as f;
use chemcore_core::geometry as g;
use chemcore_core::num::ChemError;
use chemcore_core::plots as pl;
use chemcore_core::scale as sc;
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
create_exception!(
    chemcore,
    ImpossibleWaterError,
    PyValueError,
    "A water that cannot be: its alkalinity at or below the floor of its pH, or a DIC below 0. Never worked out."
);
create_exception!(
    chemcore,
    SeawaterScaleError,
    PyValueError,
    "A pH on a seawater scale given for a water that is not sea water of 5 permil or more. Never converted."
);

fn err(error: ChemError) -> PyErr {
    match error {
        ChemError::Domain => PyValueError::new_err("math domain error"),
        ChemError::ZeroDivision => PyZeroDivisionError::new_err("float division by zero"),
        ChemError::Overflow => PyOverflowError::new_err("math range error"),
        ChemError::NonFinite => NonFiniteError::new_err("not a finite number"),
        ChemError::UnknownFormula => PyValueError::new_err("unknown formula version (the core has 1 and 3)"),
        ChemError::ImpossibleWater => ImpossibleWaterError::new_err(
            "no water has this pH and alkalinity: the hydroxide and the borate of the pH alone are at least the \
             alkalinity (or a DIC below 0 was given)",
        ),
        ChemError::SeawaterScale => SeawaterScaleError::new_err(
            "a pH on the total, the seawater or the free scale is taken for sea water of 5 permil or more only (the \n             sea path's constants alone): give the NBS pH",
        ),
        ChemError::OutOfRange => PyValueError::new_err(
            "ionic strength above 0.5: outside the range of the Davies equation (a conductivity in mS/cm, or a sea \
             water without its salinity?)",
        ),
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

/// The scale of a code ('nbs', 'total', 'sws', 'free'); ValueError for any other.
fn scale_of(code: &str) -> PyResult<sc::PhScale> {
    sc::PhScale::from_code(code).ok_or_else(|| PyValueError::new_err("unknown pH scale (nbs, total, sws, free)"))
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
    /// The formula version these equilibria were worked out by.
    #[getter]
    fn formula(&self) -> u32 {
        self.0.formula
    }
    /// The ionic strength (mol/L) they were worked out with.
    #[getter]
    fn ionic_strength(&self) -> f64 {
        self.0.ionic_strength
    }
    /// Where the ionic strength came from (a code: conductivity, hardness, salinity, alkalinity, seawater, none).
    #[getter]
    fn strength_source(&self) -> &'static str {
        self.0.source.code()
    }
    /// The seawater path's share of the constants, 0 to 1.
    #[getter]
    fn sea_weight(&self) -> f64 {
        self.0.sea_weight
    }
    /// Where its salt came from, as said ('', 'seawater', 'salt_added').
    #[getter]
    fn water_origin(&self) -> &'static str {
        self.0.origin.code()
    }
    /// The plausibility warnings of its inputs, as codes (cross review F5): 'conductivity_salinity',
    /// 'conductivity_above_ions', 'conductivity_below_ions', 'seawater_conductivity'; and 'nh3_past_guard', the water
    /// above 30 °C or 35 ‰, past the range the NH₃ judgement's guard holds over (the K_NH4 panel, 2026-11-10).
    #[getter]
    fn warnings(&self) -> Vec<&'static str> {
        [
            (f::CONDUCTIVITY_SALINITY, "conductivity_salinity"),
            (f::CONDUCTIVITY_ABOVE_IONS, "conductivity_above_ions"),
            (f::CONDUCTIVITY_BELOW_IONS, "conductivity_below_ions"),
            (f::SEAWATER_CONDUCTIVITY, "seawater_conductivity"),
            (f::NH3_PAST_GUARD, "nh3_past_guard"),
        ]
        .into_iter()
        .filter(|(bit, _code)| self.0.warnings & bit != 0)
        .map(|(_bit, code)| code)
        .collect()
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
    /// Whether a water of this pH can have this alkalinity (meq/L): the one rule of a water that cannot be.
    fn possible(&self, alkalinity: f64, ph: f64) -> PyResult<bool> {
        inputs(&[alkalinity, ph])?;
        self.0.possible(alkalinity, ph).map_err(err)
    }
    /// The DIC of a water; chemcore.ImpossibleWaterError when no water has this pH and alkalinity (formula 3).
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
    /// The judged share: the larger of the limits' basis and the activity-corrected (cross review F1).
    fn nh3_share(&self, ph: f64) -> PyResult<f64> {
        inputs(&[ph])?;
        ok(self.0.nh3_share(ph))
    }
    /// The share on the basis the limits were set on (formula 1: its own).
    fn nh3_share_limits(&self, ph: f64) -> PyResult<f64> {
        inputs(&[ph])?;
        ok(self.0.nh3_share_limits(ph))
    }
    /// The activity-corrected share (formula 3), information beside the judged one.
    fn nh3_share_corrected(&self, ph: f64) -> PyResult<f64> {
        inputs(&[ph])?;
        ok(self.0.nh3_share_corrected(ph))
    }
    /// Which share judges NH3: 'limits' (the basis the limits were set on) or 'corrected'.
    #[getter]
    fn nh3_basis(&self) -> PyResult<&'static str> {
        self.0.nh3_basis().map(|basis| basis.code()).map_err(err)
    }
    /// The NBS pH of a pH given on a scale ('nbs', 'total', 'sws', 'free'; chemcore.PH_SCALES): the pH itself for
    /// 'nbs'; chemcore.SeawaterScaleError where another scale is not taken (not sea water of 5 ‰ or more); ValueError
    /// for an unknown code.
    fn ph_nbs(&self, ph: f64, scale: &str) -> PyResult<f64> {
        inputs(&[ph])?;
        ok(sc::ph_nbs(&self.0, ph, scale_of(scale)?))
    }
    /// The pH on a scale of a water whose NBS pH is given (`ph_nbs` the other way).
    fn ph_on(&self, ph_nbs: f64, scale: &str) -> PyResult<f64> {
        inputs(&[ph_nbs])?;
        ok(sc::ph_on(&self.0, ph_nbs, scale_of(scale)?))
    }
    /// Whether a pH on this scale is taken for this water (every water takes 'nbs').
    fn takes_ph_scale(&self, scale: &str) -> PyResult<bool> {
        Ok(sc::converts(&self.0, scale_of(scale)?))
    }
    /// The equilibria of the basis the limits were set on (None for formula 1).
    fn limits_equilibria(&self) -> Option<Equilibria> {
        self.0.limits_equilibria().map(Equilibria)
    }
    /// (judged CO2 mmol/L, its basis code) of a water of this alkalinity (meq/L) and pH.
    fn co2_judged(&self, alkalinity: f64, ph: f64) -> PyResult<(f64, &'static str)> {
        inputs(&[alkalinity, ph])?;
        let own = self.0.co2_corrected(alkalinity, ph).map_err(err)?;
        let (co2, basis) = self.0.co2_judged(alkalinity, ph, own).map_err(err)?;
        Ok((ok(Ok(co2))?, basis.code()))
    }
    fn ph_where_nh3_corrected(&self, tan: f64, limit: f64) -> PyResult<Option<f64>> {
        inputs(&[tan, limit])?;
        ok_option(self.0.ph_where_nh3_corrected(tan, limit))
    }
    fn ph_where_co2_corrected(&self, alkalinity: f64, co2: f64) -> PyResult<Option<f64>> {
        inputs(&[alkalinity, co2])?;
        ok_option(self.0.ph_where_co2_corrected(alkalinity, co2))
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
    kw_sws,
    kw_free,
    kb_total,
    k_nh4_sws,
    pk_nh4,
    k_h2s_total,
    ksp_calcite,
    ksp_aragonite,
    k0_co2,
    seawater_density
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

// ---- formula 3, the application's: the fresh water's own ionic strength (chemcore/core/src/fresh.rs) ----------------

/// A water origin's code ('', 'seawater', 'salt_added'; cross review F3).
fn origin_of(code: &str) -> PyResult<c::Origin> {
    c::Origin::from_code(code).ok_or_else(|| PyValueError::new_err(format!("unknown water origin {code:?}")))
}

fn ions(conductivity_25_us_cm: Option<f64>, hardness_mg_l: Option<f64>, water_origin: &str) -> PyResult<f::Ions> {
    Ok(f::Ions {
        conductivity_25_us_cm,
        hardness_mg_l,
        origin: origin_of(water_origin)?,
    })
}

/// (ionic strength mol/L, its source's code) of a water by v3's rules.
#[pyfunction]
#[pyo3(signature = (salinity, alkalinity_mg_l=None, conductivity_25_us_cm=None, hardness_mg_l=None, water_origin=""))]
fn fresh_ionic_strength(
    salinity: f64,
    alkalinity_mg_l: Option<f64>,
    conductivity_25_us_cm: Option<f64>,
    hardness_mg_l: Option<f64>,
    water_origin: &str,
) -> PyResult<(f64, &'static str)> {
    let (strength, source) = f::ionic_strength(
        salinity,
        alkalinity_mg_l,
        ions(conductivity_25_us_cm, hardness_mg_l, water_origin)?,
    )
    .map_err(err)?;
    Ok((ok(Ok(strength))?, source.code()))
}

/// The practical salinity PSS-78 (with Hill et al. 1986) reads from a conductivity at 25 °C (µS/cm).
#[pyfunction]
fn practical_salinity(conductivity_25_us_cm: f64) -> PyResult<f64> {
    ok(f::practical_salinity(conductivity_25_us_cm))
}

/// The seawater path's share in a water's constants at a salinity (formula 3's band).
#[pyfunction]
fn sea_weight(salinity: f64) -> PyResult<f64> {
    inputs(&[salinity])?;
    Ok(f::sea_weight(salinity))
}

/// The dielectric constant of water at a temperature (Malmberg & Maryott 1956).
#[pyfunction]
fn dielectric_constant(temp_c: f64) -> PyResult<f64> {
    ok(f::dielectric_constant(temp_c))
}

/// The density of water at a temperature, g/cm3 (Kell 1975).
#[pyfunction]
fn water_density(temp_c: f64) -> PyResult<f64> {
    ok(f::water_density(temp_c))
}

/// The Debye-Hückel A of water at a temperature (formula 3).
#[pyfunction]
fn debye_huckel_a(temp_c: f64) -> PyResult<f64> {
    ok(f::debye_huckel_a(temp_c))
}

/// log10 of an ion's Davies activity coefficient.
#[pyfunction]
fn davies_log_gamma(temp_c: f64, ionic_strength: f64, charge: f64) -> PyResult<f64> {
    inputs(&[temp_c, ionic_strength, charge])?;
    ok(f::davies_log_gamma(temp_c, ionic_strength, charge))
}

/// The formula 3 equilibria of a water, its provenance with it (see `water_equilibria`).
#[pyfunction]
#[pyo3(signature = (temp_c, salinity, alkalinity_mg_l=None, conductivity_25_us_cm=None, hardness_mg_l=None, water_origin=""))]
fn equilibria_v3(
    temp_c: f64,
    salinity: f64,
    alkalinity_mg_l: Option<f64>,
    conductivity_25_us_cm: Option<f64>,
    hardness_mg_l: Option<f64>,
    water_origin: &str,
) -> PyResult<Equilibria> {
    f::equilibria_v3(
        temp_c,
        salinity,
        alkalinity_mg_l,
        ions(conductivity_25_us_cm, hardness_mg_l, water_origin)?,
    )
    .map(Equilibria)
    .map_err(err)
}

/// The equilibria of a water by a formula version (the application's by default): what every chemistry of a water
/// starts from. Formula 1 reads the temperature and the salinity only (golden v1).
#[pyfunction]
#[pyo3(signature = (temp_c, salinity, alkalinity_mg_l=None, conductivity_25_us_cm=None, hardness_mg_l=None, water_origin="",
                    formula=chemcore_core::FORMULA_VERSION))]
fn water_equilibria(
    temp_c: f64,
    salinity: f64,
    alkalinity_mg_l: Option<f64>,
    conductivity_25_us_cm: Option<f64>,
    hardness_mg_l: Option<f64>,
    water_origin: &str,
    formula: u32,
) -> PyResult<Equilibria> {
    f::water_equilibria(
        formula,
        temp_c,
        salinity,
        alkalinity_mg_l,
        ions(conductivity_25_us_cm, hardness_mg_l, water_origin)?,
    )
    .map(Equilibria)
    .map_err(err)
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
                    calcium_mg_l=None, oxygen_mg_l=None, conductivity_25_us_cm=None, hardness_mg_l=None, water_origin="",
                    formula=chemcore_core::FORMULA_VERSION, nh3_n_mg_l=None, co2_mg_l=None, h2s_ug_l=None,
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
    conductivity_25_us_cm: Option<f64>,
    hardness_mg_l: Option<f64>,
    water_origin: &str,
    formula: u32,
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
        conductivity_25_us_cm,
        hardness_mg_l,
        origin: origin_of(water_origin)?,
        formula,
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
        ("co2_corrected_mg_l", Some(result.co2_corrected_mg_l)),
        ("target_alkalinity_meq", result.target_alkalinity_meq),
        ("target_dic", result.target_dic),
        ("target_co2_mg_l", result.target_co2_mg_l),
        ("nh3_n_mg_l", result.nh3_n_mg_l),
        ("nh3_corrected_n_mg_l", result.nh3_corrected_n_mg_l),
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
    dict.set_item("co2_basis", result.co2_basis.code())?;
    dict.set_item("nh3_basis", result.nh3_basis.code())?;
    dict.set_item("co2", border(py, &result.co2)?)?;
    dict.set_item("nh3", border(py, &result.nh3)?)?;
    dict.set_item("h2s", border(py, &result.h2s)?)?;
    Ok(dict)
}

/// The alkalinity floor of a pH in a medium (the formula; formula 3: the alkalinity and the ions measured).
#[pyfunction]
#[pyo3(signature = (temperature_c, salinity_ppt, ph, alkalinity_mg_l=None, conductivity_25_us_cm=None,
                    hardness_mg_l=None, water_origin="", formula=chemcore_core::FORMULA_VERSION))]
#[allow(clippy::too_many_arguments)]
fn alkalinity_floor(
    temperature_c: f64,
    salinity_ppt: f64,
    ph: f64,
    alkalinity_mg_l: Option<f64>,
    conductivity_25_us_cm: Option<f64>,
    hardness_mg_l: Option<f64>,
    water_origin: &str,
    formula: u32,
) -> PyResult<f64> {
    inputs(&[temperature_c, salinity_ppt, ph])?;
    let medium = a::Medium {
        formula,
        alkalinity_mg_l,
        ions: ions(conductivity_25_us_cm, hardness_mg_l, water_origin)?,
    };
    ok(a::alkalinity_floor(temperature_c, salinity_ppt, ph, &medium))
}

/// The alkalinity floor when a water of this pH and alkalinity cannot be, else None.
#[pyfunction]
#[pyo3(signature = (temperature_c, salinity_ppt, ph, alkalinity_mg_l, conductivity_25_us_cm=None, hardness_mg_l=None, water_origin="",
                    formula=chemcore_core::FORMULA_VERSION))]
#[allow(clippy::too_many_arguments)]
fn why_impossible(
    temperature_c: f64,
    salinity_ppt: f64,
    ph: f64,
    alkalinity_mg_l: f64,
    conductivity_25_us_cm: Option<f64>,
    hardness_mg_l: Option<f64>,
    water_origin: &str,
    formula: u32,
) -> PyResult<Option<f64>> {
    inputs(&[temperature_c, salinity_ppt, ph, alkalinity_mg_l])?;
    ok_option(a::why_impossible(
        temperature_c,
        salinity_ppt,
        ph,
        alkalinity_mg_l,
        formula,
        ions(conductivity_25_us_cm, hardness_mg_l, water_origin)?,
    ))
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
        conductivity_25_us_cm: optional(water, "conductivity_25_us_cm")?,
        hardness_mg_l: optional(water, "hardness_mg_l")?,
        origin: match water.get_item("water_origin")? {
            Some(value) if !value.is_none() => origin_of(&value.extract::<String>()?)?,
            _ => c::Origin::Unknown,
        },
        formula: match water.get_item("formula")? {
            Some(value) if !value.is_none() => value.extract::<u32>()?,
            _ => chemcore_core::FORMULA_VERSION,
        },
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

/// The reagents in their order: (key, molar mass g/mol, DIC mmol, alkalinity meq per mmol, angle).
#[pyfunction]
fn reagents() -> Vec<(&'static str, f64, f64, f64, f64)> {
    d::reagents()
        .iter()
        .map(|reagent| {
            (
                reagent.key,
                reagent.molar_mass,
                reagent.dic,
                reagent.alkalinity,
                reagent.angle(),
            )
        })
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
/// 'waypoint': (DIC, alkalinity), 'below_air': bool}]. `air`: (the water's Equilibria, the air's CO2 mg/L) to flag a
/// stripping that ends below the air's whichever dose goes first.
#[pyfunction]
#[pyo3(signature = (start, end, chosen, volume=None, air=None))]
fn recipes<'py>(
    py: Python<'py>,
    start: Point,
    end: Point,
    chosen: Vec<String>,
    volume: Option<f64>,
    air: Option<(PyRef<'py, Equilibria>, f64)>,
) -> PyResult<Vec<Bound<'py, PyDict>>> {
    let keys: Vec<&str> = chosen.iter().map(String::as_str).collect();
    let air = air.as_ref().map(|(equilibria, co2_mg_l)| d::Air {
        equilibria: &equilibria.0,
        co2_mg_l: *co2_mg_l,
    });
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
        dict.set_item("counter_productive", recipe.counter_productive())?;
        dict.set_item("priority", recipe.priority())?;
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
#[pyo3(signature = (equilibria, start, ph, amounts, volume, air_co2_mg_l=None))]
#[allow(clippy::type_complexity)]
fn simulate(
    equilibria: PyRef<'_, Equilibria>,
    start: Point,
    ph: f64,
    amounts: Vec<(String, f64)>,
    volume: f64,
    air_co2_mg_l: Option<f64>,
) -> PyResult<Vec<(Option<&'static str>, f64, f64, f64, Option<f64>, Option<f64>, bool)>> {
    let eq = equilibria.0;
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

// ---- the four small charts (chemcore/core/src/plots.rs) ------------------------------------------------------------

/// The four small charts by key ('nh3', 'h2s', 'carbonate', 'saturation'): None where one cannot be drawn, else
/// {'x', 'y', 'unit', 'series': [(key, points)], 'bands': [(kind, from, to)], 'verticals': [(key, pH)],
/// 'horizontals': [(key, value)], 'dots': [(key, pH, value)]}.
#[pyfunction]
#[pyo3(signature = (water, limits, target=None, pressure=1.0))]
fn plots<'py>(
    py: Python<'py>,
    water: &Bound<'py, PyDict>,
    limits: &Bound<'py, PyDict>,
    target: Option<Point>,
    pressure: f64,
) -> PyResult<Bound<'py, PyDict>> {
    let target = target.map(|(ph, alkalinity_mg_l)| a::Target { ph, alkalinity_mg_l });
    let found = pl::plots(&water_of(water)?, &limits_of(limits)?, target.as_ref(), pressure).map_err(err)?;
    let dict = PyDict::new(py);
    for (key, plot) in ["nh3", "h2s", "carbonate", "saturation"].into_iter().zip(found) {
        match plot {
            None => dict.set_item(key, py.None())?,
            Some(plot) => {
                let one = PyDict::new(py);
                one.set_item("x", plot.x)?;
                one.set_item("y", plot.y)?;
                one.set_item("unit", plot.unit)?;
                one.set_item("series", plot.series)?;
                one.set_item("bands", plot.bands)?;
                one.set_item("verticals", plot.verticals)?;
                one.set_item("horizontals", plot.horizontals)?;
                one.set_item("dots", plot.dots)?;
                dict.set_item(key, one)?;
            }
        }
    }
    Ok(dict)
}

// ---- a simulator step judged, the bands, the saturation index ------------------------------------------------------

/// A simulator step judged as its water: {'alkalinity_mg_l', 'alkalinity_status', 'co2', 'nh3_n_mg_l', 'nh3',
/// 'h2s_ug_l', 'h2s'} (borders as dicts).
#[pyfunction]
#[pyo3(signature = (water, limits, ph, alkalinity, target=None, pressure=1.0))]
fn judge_step<'py>(
    py: Python<'py>,
    water: &Bound<'py, PyDict>,
    limits: &Bound<'py, PyDict>,
    ph: f64,
    alkalinity: f64,
    target: Option<Point>,
    pressure: f64,
) -> PyResult<Bound<'py, PyDict>> {
    inputs(&[ph, alkalinity])?;
    let (water, limits) = (water_of(water)?, limits_of(limits)?);
    let target = target.map(|(ph, alkalinity_mg_l)| a::Target { ph, alkalinity_mg_l });
    let analysis = a::analyse(&water, &limits, target.as_ref(), pressure).map_err(err)?;
    let step = a::judge_step(&analysis, &water, &limits, ph, alkalinity).map_err(err)?;
    let dict = PyDict::new(py);
    dict.set_item("alkalinity_mg_l", step.alkalinity_mg_l)?;
    dict.set_item("alkalinity_status", step.alkalinity_status.code())?;
    dict.set_item("co2", border(py, &step.co2)?)?;
    dict.set_item("nh3_n_mg_l", step.nh3_n_mg_l)?;
    dict.set_item("nh3", border(py, &step.nh3)?)?;
    dict.set_item("h2s_ug_l", step.h2s_ug_l)?;
    dict.set_item("h2s", border(py, &step.h2s)?)?;
    Ok(dict)
}

/// The danger, alert and safe bands of a border (pH, toxic above, status code) on a pH axis from low to high.
#[pyfunction]
fn bands(
    ph: Option<f64>,
    toxic_above: bool,
    status: &str,
    low: f64,
    high: f64,
) -> PyResult<Vec<(&'static str, f64, f64)>> {
    let status = a::Status::from_code(status).ok_or_else(|| PyValueError::new_err(format!("no status {status}")))?;
    Ok(pl::bands(
        &a::Border {
            ph,
            toxic_above,
            margin: None,
            status,
        },
        low,
        high,
    ))
}

/// log10 Omega of a water (its Equilibria) with this DIC and pH, calcium (mg/L) and Ksp.
#[pyfunction]
fn saturation_index(
    equilibria: PyRef<'_, Equilibria>,
    dic: f64,
    ph: f64,
    calcium_mg_l: f64,
    ksp: f64,
) -> PyResult<f64> {
    inputs(&[dic, ph, calcium_mg_l, ksp])?;
    ok(pl::saturation_index(&equilibria.0, dic, ph, calcium_mg_l, ksp))
}

#[pymodule]
fn chemcore(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add("NonFiniteError", module.py().get_type::<NonFiniteError>())?;
    module.add("ImpossibleWaterError", module.py().get_type::<ImpossibleWaterError>())?;
    module.add("ChartTooLargeError", module.py().get_type::<ChartTooLargeError>())?;
    module.add("SeawaterScaleError", module.py().get_type::<SeawaterScaleError>())?;
    module.add(
        "PH_SCALES",
        sc::PhScale::ALL.iter().map(|scale| scale.code()).collect::<Vec<_>>(),
    )?;
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
    module.add("FRESH_UP_TO", f::FRESH_UP_TO)?;
    module.add("SEA_FROM", f::SEA_FROM)?;
    module.add("DAVIES_MAX", f::DAVIES_MAX)?;
    module.add("IONIC_PER_MICROSIEMENS", f::IONIC_PER_MICROSIEMENS)?;
    module.add("IONIC_PER_MICROSIEMENS_NACL", f::IONIC_PER_MICROSIEMENS_NACL)?;
    module.add("FORMULAS", chemcore_core::FORMULAS.to_vec())?;
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
        wrap_pyfunction!(kw_sws, module)?,
        wrap_pyfunction!(kw_free, module)?,
        wrap_pyfunction!(kb_total, module)?,
        wrap_pyfunction!(k_nh4_sws, module)?,
        wrap_pyfunction!(pk_nh4, module)?,
        wrap_pyfunction!(k_h2s_total, module)?,
        wrap_pyfunction!(ksp_calcite, module)?,
        wrap_pyfunction!(ksp_aragonite, module)?,
        wrap_pyfunction!(k0_co2, module)?,
        wrap_pyfunction!(seawater_density, module)?,
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
        wrap_pyfunction!(plots, module)?,
        wrap_pyfunction!(judge_step, module)?,
        wrap_pyfunction!(bands, module)?,
        wrap_pyfunction!(saturation_index, module)?,
        wrap_pyfunction!(fresh_ionic_strength, module)?,
        wrap_pyfunction!(davies_log_gamma, module)?,
        wrap_pyfunction!(sea_weight, module)?,
        wrap_pyfunction!(practical_salinity, module)?,
        wrap_pyfunction!(dielectric_constant, module)?,
        wrap_pyfunction!(water_density, module)?,
        wrap_pyfunction!(debye_huckel_a, module)?,
        wrap_pyfunction!(equilibria_v3, module)?,
        wrap_pyfunction!(water_equilibria, module)?,
    ] {
        module.add_function(function)?;
    }
    Ok(())
}
