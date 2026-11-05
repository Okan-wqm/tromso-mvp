//! The Python module `chemcore`: a thin skin over `chemcore_core`. Only `farm/water/native.py` imports it.
use pyo3::prelude::*;

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

#[pymodule]
fn chemcore(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(version, module)?)?;
    module.add_function(wrap_pyfunction!(formula_version, module)?)?;
    module.add_function(wrap_pyfunction!(core_hash, module)?)?;
    Ok(())
}
