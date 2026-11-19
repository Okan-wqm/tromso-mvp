//! chemcore: the water chemistry of the fish farm (the Deffeyes chart, the calculator, the replay), as pure
//! functions of floats. No I/O, no global state, no cache, no language: results are numbers and stable codes.
//! Every transcendental function is `libm`'s (see Cargo.toml); `no_std` makes a stray `f64::exp` a compile error.
#![no_std]
#![forbid(unsafe_code)]

extern crate alloc;

pub mod analysis;
pub mod chemistry;
pub mod dosing;
pub mod fresh;
pub mod geometry;
pub mod num;
pub mod plots;
pub mod scale;

mod digest {
    include!(concat!(env!("OUT_DIR"), "/core_hash.rs"));
}
use digest::CORE_HASH;

/// The crate's version (Cargo.toml).
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

/// Bumped whenever any number the core returns may change (a formula, a constant, the solver, `libm`). The golden
/// reference names the version it was recorded with. The application works out every value by this version; every
/// result says the version it was worked out by (`chemistry::Equilibria::formula`).
pub const FORMULA_VERSION: u32 = 3;

/// The formula versions the core can still work out, so a value shown before a change can be reproduced exactly:
/// 1 (golden v1: the ionic strength from the salinity alone, the Debye-Hückel A of a fixed ε 79) and 3 (I1 and I2:
/// fresh water's own ionic strength, A of the temperature, the band from 1 to 5 permil; crate::fresh).
pub const FORMULAS: [u32; 2] = [1, 3];

/// A digest of the core's source (every file of `src/`, line endings normalised), 16 hexadecimal digits: the
/// server compares it with `chemcore/EXPECTED` at start (Django check core.E001), so a stale build never serves.
pub fn core_hash() -> &'static str {
    CORE_HASH
}
