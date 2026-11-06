//! The Python module `chemcore`: a thin skin over `chemcore_core`. Only `farm/water/native.py` imports it.
//! Errors become the exception Python's formulas raised at the same place (ValueError, ZeroDivisionError,
//! OverflowError); a non-finite input or result is `chemcore.NonFiniteError` (a ValueError): never a NaN as a number.
use chemcore_core::chemistry as c;
use chemcore_core::num::ChemError;
use pyo3::create_exception;
use pyo3::exceptions::{PyOverflowError, PyValueError, PyZeroDivisionError};
use pyo3::prelude::*;
use pyo3::types::PyTuple;

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

#[pymodule]
fn chemcore(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add("NonFiniteError", module.py().get_type::<NonFiniteError>())?;
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
    ] {
        module.add_function(function)?;
    }
    Ok(())
}
