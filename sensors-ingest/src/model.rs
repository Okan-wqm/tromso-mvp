//! Configuration types read from the contract view `sensors_ingest_config`, and the dead-letter reasons.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Shape {
    Object,
    Array,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TimeUnit {
    Iso8601,
    EpochS,
    EpochMs,
}

/// How a device's message is laid out (`sensors_payload_format`). Paths are JSON pointers (RFC 6901); blank means
/// "not configured".
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Format {
    pub shape: Shape,
    #[serde(default)]
    pub time_path: String,
    pub time_unit: TimeUnit,
    #[serde(default)]
    pub seq_path: String,
    #[serde(default)]
    pub items_path: String,
    #[serde(default)]
    pub name_key: String,
    #[serde(default)]
    pub value_key: String,
}

/// Where one channel's value sits in a message: `value_path` (object shape) or `item_name` (array shape).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ChannelMap {
    pub channel_no: i32,
    #[serde(default)]
    pub value_path: String,
    #[serde(default)]
    pub item_name: String,
}

/// Why a message (or part of it) became a dead letter: the `chk_sensors_dead_letter_reason` list.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DeadReason {
    NotJson,
    NoRoute,
    NoChannelMatch,
    MissingTime,
    BadTime,
    TooOld,
    MissingValue,
    BadValue,
    Oversize,
}

impl DeadReason {
    pub const ALL: [DeadReason; 9] = [
        DeadReason::NotJson,
        DeadReason::NoRoute,
        DeadReason::NoChannelMatch,
        DeadReason::MissingTime,
        DeadReason::BadTime,
        DeadReason::TooOld,
        DeadReason::MissingValue,
        DeadReason::BadValue,
        DeadReason::Oversize,
    ];

    pub fn as_str(self) -> &'static str {
        match self {
            DeadReason::NotJson => "not_json",
            DeadReason::NoRoute => "no_route",
            DeadReason::NoChannelMatch => "no_channel_match",
            DeadReason::MissingTime => "missing_time",
            DeadReason::BadTime => "bad_time",
            DeadReason::TooOld => "too_old",
            DeadReason::MissingValue => "missing_value",
            DeadReason::BadValue => "bad_value",
            DeadReason::Oversize => "oversize",
        }
    }
}
