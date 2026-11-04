//! The configuration the ingest runs on, read from the contract view `sensors_ingest_config` and the row
//! `sensors_contract` (sensors/CONTRACT.md). `build` is pure (tested without a database); `load` reads the view.

use crate::calib::Epoch;
use crate::model::{ChannelMap, Format, Shape, TimeUnit};
use crate::reduce::{Policy, Reduction};
use chrono::{DateTime, Utc};
use std::collections::BTreeMap;
use thiserror::Error;
use uuid::Uuid;

/// The contract version this build understands (`sensors_contract.schema_version`).
pub const SCHEMA_VERSION: i32 = 1;

/// The view's columns, in order: the ingest's copy of the contract, compared with the database by a test.
pub const VIEW_COLUMNS: [&str; 35] = [
    "connection_id",
    "host",
    "port",
    "use_tls",
    "username",
    "secret_file",
    "client_id",
    "keepalive_s",
    "device_id",
    "device_code",
    "topic",
    "expected_interval_s",
    "encoding",
    "shape",
    "time_path",
    "time_unit",
    "seq_path",
    "items_path",
    "name_key",
    "value_key",
    "channel_no",
    "channel_code",
    "quantity",
    "value_path",
    "item_name",
    "reduction",
    "deadband",
    "heartbeat_s",
    "range_min",
    "range_max",
    "channel_state",
    "valid_from",
    "valid_to",
    "a",
    "b",
];

#[derive(Debug, Clone, PartialEq)]
pub struct Contract {
    pub schema_version: i32,
    pub config_epoch: i64,
    pub future_skew_s: i64,
    pub retention_days: i64,
}

/// One row of the view.
#[derive(Debug, Clone, PartialEq)]
pub struct ViewRow {
    pub connection_id: Uuid,
    pub host: String,
    pub port: i32,
    pub use_tls: bool,
    pub username: String,
    pub secret_file: String,
    pub client_id: String,
    pub keepalive_s: i32,
    pub device_id: Uuid,
    pub device_code: String,
    pub topic: String,
    pub expected_interval_s: i32,
    pub encoding: String,
    pub shape: String,
    pub time_path: String,
    pub time_unit: String,
    pub seq_path: String,
    pub items_path: String,
    pub name_key: String,
    pub value_key: String,
    pub channel_no: i32,
    pub channel_code: String,
    pub quantity: String,
    pub value_path: String,
    pub item_name: String,
    pub reduction: String,
    pub deadband: f64,
    pub heartbeat_s: i32,
    pub range_min: Option<f64>,
    pub range_max: Option<f64>,
    pub channel_state: String,
    pub valid_from: Option<DateTime<Utc>>,
    pub valid_to: Option<DateTime<Utc>>,
    pub a: f64,
    pub b: f64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ChannelCfg {
    pub channel_no: i32,
    pub code: String,
    pub quantity: String,
    pub map: ChannelMap,
    pub policy: Policy,
    pub range: Option<(f64, f64)>,
    pub maintenance: bool,
    /// Sorted by `valid_from`, the first from the beginning.
    pub epochs: Vec<Epoch>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct DeviceCfg {
    pub device_id: Uuid,
    pub code: String,
    pub topic: String,
    pub expected_interval_s: i32,
    pub format: Format,
    pub channels: Vec<ChannelCfg>,
    /// The channels' maps, in `channels` order, as `decode` takes them.
    pub maps: Vec<ChannelMap>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ConnCfg {
    pub connection_id: Uuid,
    pub host: String,
    pub port: u16,
    pub use_tls: bool,
    pub username: String,
    pub secret_file: String,
    pub client_id: String,
    pub keepalive_s: u16,
    pub devices: Vec<DeviceCfg>,
}

impl ConnCfg {
    /// Everything that needs a new MQTT session when it changes (the device list only changes subscriptions).
    pub fn session_key(&self) -> (String, u16, bool, String, String, String, u16) {
        (
            self.host.clone(),
            self.port,
            self.use_tls,
            self.username.clone(),
            self.secret_file.clone(),
            self.client_id.clone(),
            self.keepalive_s,
        )
    }

    /// The topic filters to subscribe to, distinct, sorted.
    pub fn topics(&self) -> Vec<String> {
        let mut t: Vec<String> = self.devices.iter().map(|d| d.topic.clone()).collect();
        t.sort();
        t.dedup();
        t
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct Config {
    pub contract: Contract,
    pub connections: BTreeMap<Uuid, ConnCfg>,
    /// Rows that could not be used, with the reason (logged; the rest of the configuration runs).
    pub rejected: Vec<String>,
}

#[derive(Debug, Error)]
pub enum ConfigError {
    #[error("contract schema_version {found}, this ingest understands {expected}")]
    Version { found: i32, expected: i32 },
    #[error("database: {0}")]
    Db(#[from] tokio_postgres::Error),
    #[error("sensors_contract has no row")]
    NoContract,
}

/// Whether an MQTT topic filter (no `#`, `+` only as a whole level) matches a topic.
pub fn topic_matches(_filter: &str, _topic: &str) -> bool {
    todo!("topic_matches")
}

impl Config {
    /// The device a message on `topic` of connection `conn` belongs to: an exact topic first, else the matching
    /// filter with the fewest `+` levels, ties broken by device code (a deterministic choice; overlaps are logged
    /// at load).
    pub fn route(&self, _conn: Uuid, _topic: &str) -> Option<&DeviceCfg> {
        todo!("route")
    }

    pub fn channel_nos(&self) -> Vec<i32> {
        self.connections
            .values()
            .flat_map(|c| c.devices.iter())
            .flat_map(|d| d.channels.iter())
            .map(|c| c.channel_no)
            .collect()
    }
}

/// Builds the configuration from the contract row and the view rows. A row with a value this build does not know
/// (shape, time unit, reduction, state, encoding) or out of the contract's ranges is left out and named in
/// `rejected`, never guessed.
pub fn build(_contract: Contract, _rows: Vec<ViewRow>) -> Result<Config, ConfigError> {
    todo!("build")
}

/// Reads `sensors_contract` and the view in one REPEATABLE READ snapshot.
pub async fn load(_client: &mut tokio_postgres::Client) -> Result<Config, ConfigError> {
    todo!("load")
}

#[cfg(test)]
pub(crate) mod tests {
    use super::*;
    use chrono::TimeZone;

    pub fn contract() -> Contract {
        Contract { schema_version: 1, config_epoch: 7, future_skew_s: 60, retention_days: 730 }
    }

    pub fn row(conn: u128, device: u128, topic: &str, channel_no: i32) -> ViewRow {
        ViewRow {
            connection_id: Uuid::from_u128(conn),
            host: "mosquitto".into(),
            port: 1883,
            use_tls: false,
            username: "ingest".into(),
            secret_file: "mqtt_ingest".into(),
            client_id: "sensors-ingest".into(),
            keepalive_s: 30,
            device_id: Uuid::from_u128(device),
            device_code: format!("DEV-{device}"),
            topic: topic.into(),
            expected_interval_s: 1,
            encoding: "json".into(),
            shape: "object".into(),
            time_path: "/ts".into(),
            time_unit: "iso8601".into(),
            seq_path: "/seq".into(),
            items_path: String::new(),
            name_key: String::new(),
            value_key: String::new(),
            channel_no,
            channel_code: format!("ch{channel_no}"),
            quantity: "temperature_c".into(),
            value_path: format!("/v{channel_no}"),
            item_name: String::new(),
            reduction: "deadband".into(),
            deadband: 0.1,
            heartbeat_s: 60,
            range_min: Some(-5.0),
            range_max: Some(40.0),
            channel_state: "active".into(),
            valid_from: None,
            valid_to: None,
            a: 1.0,
            b: 0.0,
        }
    }

    #[test]
    fn topic_filters() {
        assert!(topic_matches("farm/a/b", "farm/a/b"));
        assert!(!topic_matches("farm/a/b", "farm/a/b/c"));
        assert!(!topic_matches("farm/a/b", "farm/a"));
        assert!(topic_matches("farm/+/b", "farm/x/b"));
        assert!(topic_matches("farm/+/b", "farm//b"));
        assert!(!topic_matches("farm/+/b", "farm/x/y/b"));
        assert!(topic_matches("+", "x"));
        assert!(!topic_matches("+", "x/y"));
        assert!(!topic_matches("farm/a+/b", "farm/ax/b"));
    }

    #[test]
    fn rows_group_into_connections_devices_channels_and_epochs() {
        let t1 = Utc.with_ymd_and_hms(2026, 10, 1, 0, 0, 0).unwrap();
        let mut r1 = row(1, 10, "farm/hall/plc", 5);
        r1.valid_to = Some(t1);
        let mut r2 = row(1, 10, "farm/hall/plc", 5);
        r2.valid_from = Some(t1);
        r2.a = 2.0;
        let mut r3 = row(1, 10, "farm/hall/plc", 6);
        r3.channel_state = "maintenance".into();
        r3.reduction = "all".into();
        r3.deadband = 0.0;
        r3.range_min = None;
        r3.range_max = None;
        let r4 = row(1, 11, "farm/+/probe", 7);
        let cfg = build(contract(), vec![r3, r2, r1, r4]).unwrap();
        assert!(cfg.rejected.is_empty(), "{:?}", cfg.rejected);
        let conn = &cfg.connections[&Uuid::from_u128(1)];
        assert_eq!((conn.port, conn.keepalive_s), (1883, 30));
        assert_eq!(conn.devices.len(), 2);
        let dev = conn.devices.iter().find(|d| d.device_id == Uuid::from_u128(10)).unwrap();
        assert_eq!(dev.format.shape, Shape::Object);
        assert_eq!(dev.format.time_unit, TimeUnit::Iso8601);
        let c5 = dev.channels.iter().find(|c| c.channel_no == 5).unwrap();
        assert_eq!(
            c5.epochs,
            vec![Epoch { valid_from: None, a: 1.0, b: 0.0 }, Epoch { valid_from: Some(t1), a: 2.0, b: 0.0 }]
        );
        assert_eq!(c5.policy, Policy { reduction: Reduction::Deadband(0.1), heartbeat_s: 60 });
        assert_eq!(c5.range, Some((-5.0, 40.0)));
        assert!(!c5.maintenance);
        let c6 = dev.channels.iter().find(|c| c.channel_no == 6).unwrap();
        assert!(c6.maintenance);
        assert_eq!(c6.policy.reduction, Reduction::All);
        assert_eq!(c6.range, None);
        assert_eq!(conn.topics(), vec!["farm/+/probe".to_string(), "farm/hall/plc".to_string()]);
        let mut nos = cfg.channel_nos();
        nos.sort();
        assert_eq!(nos, vec![5, 6, 7]);
    }

    #[test]
    fn unknown_values_are_rejected_not_guessed() {
        let mut bad_shape = row(1, 10, "a", 1);
        bad_shape.shape = "csv".into();
        let mut bad_unit = row(1, 11, "b", 2);
        bad_unit.time_unit = "epoch_us".into();
        let mut bad_red = row(1, 12, "c", 3);
        bad_red.reduction = "swinging_door".into();
        let mut bad_db = row(1, 13, "d", 4);
        bad_db.deadband = f64::NAN;
        let mut bad_port = row(2, 14, "e", 5);
        bad_port.port = 70000;
        let mut bad_topic = row(1, 15, "f/#", 6);
        bad_topic.channel_no = 6;
        let mut bad_state = row(1, 16, "g", 7);
        bad_state.channel_state = "retired".into();
        let mut bad_enc = row(1, 17, "h", 8);
        bad_enc.encoding = "csv".into();
        let good = row(1, 18, "ok", 9);
        let cfg = build(
            contract(),
            vec![bad_shape, bad_unit, bad_red, bad_db, bad_port, bad_topic, bad_state, bad_enc, good],
        )
        .unwrap();
        assert_eq!(cfg.channel_nos(), vec![9]);
        assert_eq!(cfg.rejected.len(), 8, "{:?}", cfg.rejected);
    }

    #[test]
    fn another_contract_version_refuses_to_run() {
        let mut c = contract();
        c.schema_version = 2;
        assert!(matches!(build(c, vec![]), Err(ConfigError::Version { found: 2, expected: 1 })));
    }

    #[test]
    fn route_prefers_exact_then_fewest_wildcards_then_code() {
        let rows = vec![
            row(1, 10, "farm/+/+", 1),
            row(1, 11, "farm/hall/+", 2),
            row(1, 12, "farm/hall/plc", 3),
            row(2, 13, "farm/hall/plc", 4),
        ];
        let cfg = build(contract(), rows).unwrap();
        let c1 = Uuid::from_u128(1);
        assert_eq!(cfg.route(c1, "farm/hall/plc").unwrap().device_id, Uuid::from_u128(12));
        assert_eq!(cfg.route(c1, "farm/hall/x").unwrap().device_id, Uuid::from_u128(11));
        assert_eq!(cfg.route(c1, "farm/sea/x").unwrap().device_id, Uuid::from_u128(10));
        assert!(cfg.route(c1, "other/x").is_none());
        assert_eq!(cfg.route(Uuid::from_u128(2), "farm/hall/plc").unwrap().device_id, Uuid::from_u128(13));
        assert!(cfg.route(Uuid::from_u128(3), "farm/hall/plc").is_none());
    }
}
