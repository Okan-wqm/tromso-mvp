//! Chemistry that is not cleared for use yet: a module here may hold a PROVISIONAL constant, one not read in its
//! source, which the core's rule (every constant names the primary source it was read in) does not allow in
//! `chemcore-core`. So it lives beside the core, built on the core's public functions, and nothing the application
//! runs can reach it:
//!
//! - `chemcore-py` (the only way Django reaches chemistry) never depends on this crate, and `chemcore/scripts/test.sh`
//!   fails when it does; nothing here is bound to Python or shown on a page;
//! - it is not part of the core's digest (`chemcore_core::core_hash`, `chemcore/EXPECTED`) nor of any formula version:
//!   it changes no number the core returns;
//! - it is held to the core's gates all the same (rustfmt, clippy with the workspace's lints, its tests in `cargo
//!   test`, libm through the core only) and its public names and coefficients are on the browser guard's deny-list
//!   (`chemcore/scripts/gen_guard_list.py`).
//!
//! A module leaves this crate for `chemcore-core` only when an independent science review has cleared it and every
//! PROVISIONAL constant has been replaced by one read in its source, with the owner's approval: then the core's digest
//! moves (`chemcore/scripts/gen_expected.sh`) and whether `FORMULA_VERSION` moves is decided with it (README, chemcore).
#![no_std]
#![forbid(unsafe_code)]

pub mod gas_exchange;
