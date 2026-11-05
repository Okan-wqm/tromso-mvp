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
pub const VIEW_COLUMNS: [&str; 36] = [
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
    "is_simulated",
];

#[derive(Debug, Clone, PartialEq)]
pub struct Contract {
    pub schema_version: i32,
    pub config_epoch: i64,
    pub future_skew_s: i64,
    pub retention_days: i64,
    /// Days back a device time may be before the message is `too_old` (two days inside the retention).
    pub late_limit_days: i64,
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
    pub is_simulated: bool,
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
    /// A simulator or test device: its values are stored flagged SIMULATED (128).
    pub simulated: bool,
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
pub fn topic_matches(filter: &str, topic: &str) -> bool {
    let mut f = filter.split('/');
    let mut t = topic.split('/');
    loop {
        match (f.next(), t.next()) {
            (None, None) => return true,
            (Some("+"), Some(_)) => {}
            (Some(a), Some(b)) if a == b => {}
            _ => return false,
        }
    }
}

impl Config {
    /// The device a message on `topic` of connection `conn` belongs to: an exact topic first, else the matching
    /// filter with the fewest `+` levels, ties broken by device code (a deterministic choice).
    pub fn route(&self, conn: Uuid, topic: &str) -> Option<&DeviceCfg> {
        let c = self.connections.get(&conn)?;
        c.devices
            .iter()
            .filter(|d| topic_matches(&d.topic, topic))
            .min_by(|x, y| wildcards(&x.topic).cmp(&wildcards(&y.topic)).then_with(|| x.code.cmp(&y.code)))
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

fn wildcards(filter: &str) -> usize {
    filter.split('/').filter(|l| *l == "+").count()
}

fn valid_topic(t: &str) -> bool {
    !t.is_empty() && !t.contains('#') && !t.starts_with('$') && t.split('/').all(|l| l == "+" || !l.contains('+'))
}

type Checked = (Format, Policy, Option<(f64, f64)>, bool, u16, u16);

/// Checks one view row; Err names what is wrong.
fn check(r: &ViewRow) -> Result<Checked, String> {
    let port = u16::try_from(r.port).ok().filter(|p| *p >= 1).ok_or_else(|| format!("port {}", r.port))?;
    let keepalive = u16::try_from(r.keepalive_s)
        .ok()
        .filter(|k| (5..=600).contains(k))
        .ok_or_else(|| format!("keepalive_s {}", r.keepalive_s))?;
    if r.host.is_empty() || r.client_id.is_empty() {
        return Err("host or client_id blank".into());
    }
    if r.secret_file.contains('/') || r.secret_file.contains('\\') || r.secret_file == "." || r.secret_file == ".." {
        return Err(format!("secret_file {:?} is not a plain file name", r.secret_file));
    }
    if !valid_topic(&r.topic) {
        return Err(format!("topic {:?}", r.topic));
    }
    if r.encoding != "json" {
        return Err(format!("encoding {:?}", r.encoding));
    }
    let shape = match r.shape.as_str() {
        "object" => Shape::Object,
        "array" => Shape::Array,
        s => return Err(format!("shape {s:?}")),
    };
    let time_unit = match r.time_unit.as_str() {
        "iso8601" => TimeUnit::Iso8601,
        "epoch_s" => TimeUnit::EpochS,
        "epoch_ms" => TimeUnit::EpochMs,
        s => return Err(format!("time_unit {s:?}")),
    };
    match shape {
        Shape::Object if r.value_path.is_empty() => return Err("object shape without value_path".into()),
        Shape::Array if r.item_name.is_empty() || r.name_key.is_empty() || r.value_key.is_empty() => {
            return Err("array shape without item_name, name_key or value_key".into());
        }
        _ => {}
    }
    if !(10..=86_400).contains(&r.heartbeat_s) {
        return Err(format!("heartbeat_s {}", r.heartbeat_s));
    }
    let reduction = match r.reduction.as_str() {
        "all" => Reduction::All,
        "deadband" if r.deadband.is_finite() && r.deadband > 0.0 => Reduction::Deadband(r.deadband),
        s => return Err(format!("reduction {s:?} with deadband {}", r.deadband)),
    };
    let maintenance = match r.channel_state.as_str() {
        "active" => false,
        "maintenance" => true,
        s => return Err(format!("channel_state {s:?}")),
    };
    let range = match (r.range_min, r.range_max) {
        (None, None) => None,
        (Some(lo), Some(hi)) if lo.is_finite() && hi.is_finite() && lo < hi => Some((lo, hi)),
        (lo, hi) => return Err(format!("range {lo:?}..{hi:?}")),
    };
    if !(r.a.is_finite() && r.b.is_finite() && r.a != 0.0) {
        return Err(format!("calibration a={} b={}", r.a, r.b));
    }
    let format = Format {
        shape,
        time_path: r.time_path.clone(),
        time_unit,
        seq_path: r.seq_path.clone(),
        items_path: r.items_path.clone(),
        name_key: r.name_key.clone(),
        value_key: r.value_key.clone(),
    };
    Ok((format, Policy { reduction, heartbeat_s: i64::from(r.heartbeat_s) }, range, maintenance, port, keepalive))
}

/// Builds the configuration from the contract row and the view rows. A row with a value this build does not know
/// (shape, time unit, reduction, state, encoding) or out of the contract's ranges is left out and named in
/// `rejected`, never guessed.
pub fn build(contract: Contract, rows: Vec<ViewRow>) -> Result<Config, ConfigError> {
    if contract.schema_version != SCHEMA_VERSION {
        return Err(ConfigError::Version { found: contract.schema_version, expected: SCHEMA_VERSION });
    }
    let mut connections: BTreeMap<Uuid, ConnCfg> = BTreeMap::new();
    let mut rejected = Vec::new();
    for r in rows {
        let (format, policy, range, maintenance, port, keepalive_s) = match check(&r) {
            Ok(v) => v,
            Err(why) => {
                rejected.push(format!("channel {} of device {}: {why}", r.channel_no, r.device_code));
                continue;
            }
        };
        let conn = connections.entry(r.connection_id).or_insert_with(|| ConnCfg {
            connection_id: r.connection_id,
            host: r.host.clone(),
            port,
            use_tls: r.use_tls,
            username: r.username.clone(),
            secret_file: r.secret_file.clone(),
            client_id: r.client_id.clone(),
            keepalive_s,
            devices: Vec::new(),
        });
        if !conn.devices.iter().any(|d| d.device_id == r.device_id) {
            conn.devices.push(DeviceCfg {
                device_id: r.device_id,
                code: r.device_code.clone(),
                topic: r.topic.clone(),
                expected_interval_s: r.expected_interval_s,
                format,
                channels: Vec::new(),
                maps: Vec::new(),
                simulated: r.is_simulated,
            });
        }
        let Some(dev) = conn.devices.iter_mut().find(|d| d.device_id == r.device_id) else { continue };
        let epoch = Epoch { valid_from: r.valid_from, a: r.a, b: r.b };
        match dev.channels.iter_mut().find(|c| c.channel_no == r.channel_no) {
            Some(ch) => ch.epochs.push(epoch),
            None => dev.channels.push(ChannelCfg {
                channel_no: r.channel_no,
                code: r.channel_code.clone(),
                quantity: r.quantity.clone(),
                map: ChannelMap {
                    channel_no: r.channel_no,
                    value_path: r.value_path.clone(),
                    item_name: r.item_name.clone(),
                },
                policy,
                range,
                maintenance,
                epochs: vec![epoch],
            }),
        }
    }
    for conn in connections.values_mut() {
        conn.devices.sort_by(|a, b| a.code.cmp(&b.code));
        for dev in &mut conn.devices {
            dev.channels.sort_by_key(|c| c.channel_no);
            for ch in &mut dev.channels {
                ch.epochs.sort_by(|a, b| a.valid_from.cmp(&b.valid_from));
            }
            dev.maps = dev.channels.iter().map(|c| c.map.clone()).collect();
        }
    }
    Ok(Config { contract, connections, rejected })
}

/// Reads `sensors_contract` and the view in one REPEATABLE READ snapshot.
pub async fn load(client: &mut tokio_postgres::Client) -> Result<Config, ConfigError> {
    let tx = client
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::RepeatableRead)
        .read_only(true)
        .start()
        .await?;
    let c = tx
        .query_opt(
            "SELECT schema_version, config_epoch, future_skew_s, retention_days, late_limit_days FROM sensors_contract \n             WHERE id = 1",
            &[],
        )
        .await?
        .ok_or(ConfigError::NoContract)?;
    let contract = Contract {
        schema_version: c.try_get(0)?,
        config_epoch: c.try_get(1)?,
        future_skew_s: i64::from(c.try_get::<_, i32>(2)?),
        retention_days: i64::from(c.try_get::<_, i32>(3)?),
        late_limit_days: i64::from(c.try_get::<_, i32>(4)?),
    };
    let sql = format!(
        "SELECT {} FROM sensors_ingest_config ORDER BY channel_no, valid_from NULLS FIRST",
        VIEW_COLUMNS.join(", ")
    );
    let mut rows = Vec::new();
    for r in tx.query(&sql, &[]).await? {
        rows.push(ViewRow {
            connection_id: r.try_get("connection_id")?,
            host: r.try_get("host")?,
            port: r.try_get("port")?,
            use_tls: r.try_get("use_tls")?,
            username: r.try_get("username")?,
            secret_file: r.try_get("secret_file")?,
            client_id: r.try_get("client_id")?,
            keepalive_s: r.try_get("keepalive_s")?,
            device_id: r.try_get("device_id")?,
            device_code: r.try_get("device_code")?,
            topic: r.try_get("topic")?,
            expected_interval_s: r.try_get("expected_interval_s")?,
            encoding: r.try_get("encoding")?,
            shape: r.try_get("shape")?,
            time_path: r.try_get("time_path")?,
            time_unit: r.try_get("time_unit")?,
            seq_path: r.try_get("seq_path")?,
            items_path: r.try_get("items_path")?,
            name_key: r.try_get("name_key")?,
            value_key: r.try_get("value_key")?,
            channel_no: r.try_get("channel_no")?,
            channel_code: r.try_get("channel_code")?,
            quantity: r.try_get("quantity")?,
            value_path: r.try_get("value_path")?,
            item_name: r.try_get("item_name")?,
            reduction: r.try_get("reduction")?,
            deadband: r.try_get("deadband")?,
            heartbeat_s: r.try_get("heartbeat_s")?,
            range_min: r.try_get("range_min")?,
            range_max: r.try_get("range_max")?,
            channel_state: r.try_get("channel_state")?,
            valid_from: r.try_get("valid_from")?,
            valid_to: r.try_get("valid_to")?,
            a: r.try_get("a")?,
            b: r.try_get("b")?,
            is_simulated: r.try_get("is_simulated")?,
        });
    }
    tx.commit().await?;
    build(contract, rows)
}

#[cfg(test)]
pub(crate) mod tests {
    use super::*;
    use chrono::TimeZone;

    pub fn contract() -> Contract {
        Contract { schema_version: 1, config_epoch: 7, future_skew_s: 60, retention_days: 730, late_limit_days: 728 }
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
            is_simulated: false,
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
    fn a_simulated_device_is_marked() {
        let mut sim = row(1, 10, "demo/sim-t-01", 1);
        sim.is_simulated = true;
        let real = row(1, 11, "farm/probe", 2);
        let cfg = build(contract(), vec![sim, real]).unwrap();
        let c = &cfg.connections[&Uuid::from_u128(1)];
        let by = |id| c.devices.iter().find(|d| d.device_id == Uuid::from_u128(id)).unwrap().simulated;
        assert!(by(10));
        assert!(!by(11));
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
