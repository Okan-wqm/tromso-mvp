//! The ingest service of the Sensors subsystem (plan decision 1): subscribe, decode, validate, reduce and batch-write.
//! The pure parts (decode, time rule, calibration, reducer) have no I/O and are tested on their own; the database
//! writer and the MQTT loop use them.
#![cfg_attr(test, allow(clippy::unwrap_used, clippy::expect_used, clippy::panic, clippy::indexing_slicing))]

pub mod calib;
pub mod decode;
pub mod model;
pub mod quality;
pub mod reduce;
pub mod timerule;
