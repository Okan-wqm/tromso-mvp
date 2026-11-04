//! The ingest service of the Sensors subsystem (plan decision 1): subscribe, decode, validate, reduce and batch-write.
//! The pure parts (decode, time rule, calibration, reducer) have no I/O and are tested on their own; the database
//! writer and the MQTT loop use them.
#![cfg_attr(test, allow(clippy::unwrap_used, clippy::expect_used, clippy::panic, clippy::indexing_slicing))]

pub mod calib;
pub mod config;
pub mod db;
pub mod decode;
pub mod env;
pub mod http;
pub mod model;
pub mod mqtt;
pub mod pipeline;
pub mod quality;
pub mod reduce;
pub mod service;
pub mod supervisor;
pub mod timerule;
