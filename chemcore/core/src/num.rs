//! The arithmetic of the core: every transcendental function comes from `libm` (never from the platform), and each
//! one fails exactly where CPython's `math` module raises, so that the core refuses the inputs the Python formulas
//! refused, with the same kind of error (the golden reference records which; chemcore/golden/v1/edges):
//!
//! - `div`: a division by zero (0.0 or -0.0) is `ZeroDivision` (Python's `ZeroDivisionError`);
//! - `ln`, `log10`: an argument at or below 0 is `Domain` (`ValueError: math domain error`); NaN gives NaN;
//! - `sqrt`: an argument below 0 is `Domain`; -0.0 gives -0.0;
//! - `exp`: a finite argument whose result overflows is `Overflow` (`OverflowError: math range error`);
//! - `pow` (`math.pow` and `x ** n`): 0 to a negative power and a negative base to a non-integer power are `Domain`,
//!   a finite overflow is `Overflow`.
//!
//! Non-finite values are refused at the core's public functions (`NonFinite`): a NaN is never returned as a number.

/// Why the core refused to compute.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ChemError {
    /// Outside a function's mathematical domain (Python: ValueError).
    Domain,
    /// A division by zero (Python: ZeroDivisionError).
    ZeroDivision,
    /// A finite input whose result does not fit a float (Python: OverflowError).
    Overflow,
    /// A non-finite input, or a result that is not a finite number.
    NonFinite,
}

/// A number or the reason there is none.
pub type R = Result<f64, ChemError>;

#[inline]
pub fn div(a: f64, b: f64) -> R {
    if b == 0.0 {
        Err(ChemError::ZeroDivision)
    } else {
        Ok(a / b)
    }
}

#[inline]
pub fn ln(x: f64) -> R {
    if x.is_nan() {
        Ok(x)
    } else if x <= 0.0 {
        Err(ChemError::Domain)
    } else {
        Ok(libm::log(x))
    }
}

#[inline]
pub fn log10(x: f64) -> R {
    if x.is_nan() {
        Ok(x)
    } else if x <= 0.0 {
        Err(ChemError::Domain)
    } else {
        Ok(libm::log10(x))
    }
}

#[inline]
pub fn sqrt(x: f64) -> R {
    if x < 0.0 {
        Err(ChemError::Domain)
    } else {
        Ok(libm::sqrt(x))
    }
}

#[inline]
pub fn exp(x: f64) -> R {
    let result = libm::exp(x);
    if result.is_infinite() && x.is_finite() {
        Err(ChemError::Overflow)
    } else {
        Ok(result)
    }
}

#[inline]
pub fn pow(x: f64, y: f64) -> R {
    if x.is_finite() && y.is_finite() {
        if x == 0.0 && y < 0.0 {
            return Err(ChemError::Domain);
        }
        if x < 0.0 && libm::floor(y) != y {
            return Err(ChemError::Domain);
        }
    }
    let result = libm::pow(x, y);
    if result.is_infinite() && x.is_finite() && y.is_finite() {
        Err(ChemError::Overflow)
    } else {
        Ok(result)
    }
}

/// A finite input, or `NonFinite`.
#[inline]
pub fn finite(x: f64) -> R {
    if x.is_finite() {
        Ok(x)
    } else {
        Err(ChemError::NonFinite)
    }
}
