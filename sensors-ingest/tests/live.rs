//! The whole service in process against a real Mosquitto and the real schema: MQTT to rows end to end, acknowledged
//! (nothing redelivered after a restart), a persistent session that keeps what was published while the ingest was
//! down, a new device subscribed without a restart, garbage dead-lettered. Needs TEST_MQTT_HOST (tests/run.sh starts
//! a broker with users `ingest`/`ingest-pw` and `dev`/`dev-pw`).
#![allow(clippy::unwrap_used, clippy::expect_used, clippy::panic, clippy::indexing_slicing, clippy::await_holding_lock)]

mod common;

use chrono::{DateTime, Duration, Utc};
use common::*;
use rumqttc::{AsyncClient, Event, MqttOptions, Packet, QoS};
use sensors_ingest::service::Settings;
use sensors_ingest::supervisor::{self, Options};
use std::sync::Mutex;
use tokio::sync::watch;
use uuid::Uuid;

static SERIAL: Mutex<()> = Mutex::new(());
fn serial() -> std::sync::MutexGuard<'static, ()> {
    SERIAL.lock().unwrap_or_else(|p| p.into_inner())
}

fn broker() -> Option<String> {
    match std::env::var("TEST_MQTT_HOST") {
        Ok(h) if !h.is_empty() => Some(h),
        _ => {
            assert!(std::env::var("REQUIRE_DB").is_err(), "REQUIRE_DB is set but TEST_MQTT_HOST is not");
            eprintln!("SKIPPED: TEST_MQTT_HOST not set");
            None
        }
    }
}

struct Running {
    stop: watch::Sender<bool>,
    task: tokio::task::JoinHandle<Result<(), String>>,
}

fn start(url: &str, secrets: &std::path::Path) -> Running {
    let mut s = Settings::new(url);
    s.role = Some("sensors_ingest".into());
    s.batch_ms = 100;
    s.config_poll = std::time::Duration::from_secs(2);
    let opts = Options {
        settings: s,
        secrets_dir: secrets.to_path_buf(),
        ca_file: "/etc/ssl/certs/ca-certificates.crt".into(),
        queue_capacity: 10_000,
        http_addr: None,
    };
    let (stop, rx) = watch::channel(false);
    Running { stop, task: tokio::spawn(supervisor::run(opts, rx)) }
}

impl Running {
    async fn stop(self) {
        self.stop.send(true).unwrap();
        tokio::time::timeout(std::time::Duration::from_secs(30), self.task).await.unwrap().unwrap().unwrap();
    }
}

/// Publishes QoS 1 messages and waits until the broker acknowledged every one.
async fn publish(host: &str, msgs: &[(String, Vec<u8>)]) {
    let mut o = MqttOptions::new(format!("pub-{}", Uuid::new_v4()), host, 1883);
    o.set_credentials("dev", "dev-pw").set_inflight(500).set_max_packet_size(300 * 1024, 300 * 1024);
    let (c, mut el) = AsyncClient::new(o, 20_000);
    let n = msgs.len();
    let poller = tokio::spawn(async move {
        let mut acked = 0;
        while acked < n {
            match el.poll().await {
                Ok(Event::Incoming(Packet::PubAck(_))) => acked += 1,
                Ok(_) => {}
                Err(e) => panic!("publisher: {e}"),
            }
        }
    });
    for (t, p) in msgs {
        c.publish(t.clone(), QoS::AtLeastOnce, false, p.clone()).await.unwrap();
    }
    tokio::time::timeout(std::time::Duration::from_secs(60), poller).await.unwrap().unwrap();
}

struct World {
    url: String,
    host: String,
    secrets: tempdir::Dir,
    fx: Fx,
    ch: i32,
}

mod tempdir {
    pub struct Dir(pub std::path::PathBuf);
    impl Drop for Dir {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }
}

async fn world(client_id: &str) -> Option<World> {
    let url = url()?;
    let host = broker()?;
    let a = admin(&url).await;
    reset(&a).await;
    let fx = base(&a, 3).await;
    a.execute(
        "UPDATE sensors_connection SET host = $1, client_id = $2 WHERE id = $3",
        &[&host, &client_id, &fx.connection],
    )
    .await
    .unwrap();
    let dev = Uuid::from_u128(0xD201);
    device(&a, &fx, dev, "ZZ-LIVE", "live/plc", fx.format).await;
    let (_, ch) = channel(&a, dev, "A", "/a", "", "all", 0.0, 60, None).await;
    let dir = std::env::temp_dir().join(format!("ingest-secrets-{}", Uuid::new_v4()));
    std::fs::create_dir_all(&dir).unwrap();
    std::fs::write(dir.join("mqtt_ingest"), "ingest-pw\n").unwrap();
    Some(World { url, host, secrets: tempdir::Dir(dir), fx, ch })
}

fn plc(t: DateTime<Utc>, i: i64) -> (String, Vec<u8>) {
    ("live/plc".into(), serde_json::to_vec(&serde_json::json!({"ts": t.to_rfc3339(), "seq": i, "a": i})).unwrap())
}

async fn rows_until(a: &tokio_postgres::Client, sql: &str, want: i64) -> i64 {
    let mut got = 0;
    for _ in 0..300 {
        got = count(a, sql).await;
        if got >= want {
            return got;
        }
        tokio::time::sleep(std::time::Duration::from_millis(100)).await;
    }
    got
}

#[tokio::test]
async fn a_qos1_stream_is_stored_once_and_acknowledged_so_a_restart_redelivers_nothing() {
    let _g = serial();
    let Some(w) = world("ingest-live-1").await else { return };
    let a = admin(&w.url).await;
    let run = start(&w.url, &w.secrets.0);
    tokio::time::sleep(std::time::Duration::from_secs(2)).await;
    let t = Utc::now() - Duration::hours(1);
    let msgs: Vec<_> = (0..3000).map(|i| plc(t + Duration::milliseconds(i * 100), i)).collect();
    publish(&w.host, &msgs).await;
    let sql = format!("SELECT count(*) FROM sensors_reading WHERE channel_no = {}", w.ch);
    assert_eq!(rows_until(&a, &sql, 3000).await, 3000);
    run.stop().await;
    let st = a.query_one("SELECT connected, last_commit_at IS NOT NULL FROM sensors_ingest_status", &[]).await.unwrap();
    assert_eq!((st.get::<_, bool>(0), st.get::<_, bool>(1)), (false, true));
    // a restart: had any message not been acknowledged the broker would redeliver it as a LATE row
    let run = start(&w.url, &w.secrets.0);
    tokio::time::sleep(std::time::Duration::from_secs(4)).await;
    run.stop().await;
    assert_eq!(count(&a, &sql).await, 3000);
    let late: i64 = count(&a, "SELECT count(*) FROM sensors_reading WHERE quality & 8 <> 0").await;
    assert_eq!(late, 0);
    let dev = a.query_one("SELECT accepted_total, last_seq FROM sensors_device_state", &[]).await.unwrap();
    assert_eq!((dev.get::<_, i64>(0), dev.get::<_, Option<i64>>(1)), (3000, Some(2999)));
}

#[tokio::test]
async fn messages_published_while_the_ingest_is_down_arrive_after_it_comes_back() {
    let _g = serial();
    let Some(w) = world("ingest-live-2").await else { return };
    let a = admin(&w.url).await;
    // a first run makes the persistent session and its subscription
    let run = start(&w.url, &w.secrets.0);
    tokio::time::sleep(std::time::Duration::from_secs(2)).await;
    run.stop().await;
    let t = Utc::now() - Duration::hours(1);
    let msgs: Vec<_> = (0..500).map(|i| plc(t + Duration::seconds(i), i)).collect();
    publish(&w.host, &msgs).await;
    let run = start(&w.url, &w.secrets.0);
    let sql = format!("SELECT count(*) FROM sensors_reading WHERE channel_no = {}", w.ch);
    assert_eq!(rows_until(&a, &sql, 500).await, 500);
    run.stop().await;
}

#[tokio::test]
async fn a_new_device_is_subscribed_and_garbage_is_dead_lettered_without_a_restart() {
    let _g = serial();
    let Some(w) = world("ingest-live-3").await else { return };
    let a = admin(&w.url).await;
    let run = start(&w.url, &w.secrets.0);
    tokio::time::sleep(std::time::Duration::from_secs(2)).await;
    let dev = Uuid::from_u128(0xD202);
    device(&a, &w.fx, dev, "ZZ-LIVE-NEW", "live/+/probe", w.fx.format).await;
    let (_, ch2) = channel(&a, dev, "B", "/a", "", "all", 0.0, 60, None).await;
    tokio::time::sleep(std::time::Duration::from_secs(2)).await;
    let t = Utc::now() - Duration::minutes(5);
    let body = serde_json::to_vec(&serde_json::json!({"ts": t.to_rfc3339(), "a": 7})).unwrap();
    publish(&w.host, &[("live/hall/probe".into(), body), ("live/plc".into(), b"not json".to_vec())]).await;
    let sql = format!("SELECT count(*) FROM sensors_reading WHERE channel_no = {ch2}");
    assert_eq!(rows_until(&a, &sql, 1).await, 1);
    assert_eq!(rows_until(&a, "SELECT count(*) FROM sensors_dead_letter WHERE reason = 'not_json'", 1).await, 1);
    run.stop().await;
}
