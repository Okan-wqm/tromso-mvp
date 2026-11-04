//! The writer loop against the real schema: acknowledgement only after COMMIT, database failure, poison isolation,
//! shutdown drain, restart continuity, configuration reload, the single-writer lock.
#![allow(clippy::unwrap_used, clippy::expect_used, clippy::panic, clippy::indexing_slicing, clippy::await_holding_lock)]

mod common;

use chrono::{DateTime, Duration, Utc};
use common::*;
use sensors_ingest::config;
use sensors_ingest::pipeline::{self, DeadLimiter, Msg};
use sensors_ingest::service::{self, Acker, Envelope, Event, Settings, Shared};
use std::collections::HashMap;
use std::sync::atomic::Ordering;
use std::sync::{Arc, Mutex};
use tokio::sync::{mpsc, watch};
use uuid::Uuid;

static SERIAL: Mutex<()> = Mutex::new(());
fn serial() -> std::sync::MutexGuard<'static, ()> {
    SERIAL.lock().unwrap_or_else(|p| p.into_inner())
}

fn t0() -> DateTime<Utc> {
    let t = Utc::now() - Duration::days(20);
    DateTime::from_timestamp(t.timestamp(), 0).unwrap()
}

/// Records (message id, commits seen by the writer at the moment of the ack).
#[derive(Clone, Default)]
struct Log(Arc<Mutex<Vec<(u64, u64)>>>);
struct TestAck {
    id: u64,
    log: Log,
    shared: Arc<Shared>,
}
impl Acker for TestAck {
    fn ack(self: Box<Self>) {
        let commits = self.shared.commits.load(Ordering::SeqCst);
        self.log.0.lock().unwrap().push((self.id, commits));
    }
}
impl Log {
    fn ids(&self) -> Vec<u64> {
        self.0.lock().unwrap().iter().map(|x| x.0).collect()
    }
}

struct Harness {
    shared: Arc<Shared>,
    tx: mpsc::Sender<Envelope>,
    events: mpsc::UnboundedReceiver<Event>,
    stop: watch::Sender<bool>,
    task: tokio::task::JoinHandle<()>,
    log: Log,
    conn: Uuid,
}

fn settings(url: &str) -> Settings {
    let mut s = Settings::new(url);
    s.role = Some("sensors_ingest".into());
    s.batch_ms = 50;
    s.batch_max = 100;
    s.heartbeat = std::time::Duration::from_millis(300);
    s.config_poll = std::time::Duration::from_secs(2);
    s
}

fn start(s: Settings, conn: Uuid) -> Harness {
    let shared = Arc::new(Shared::default());
    let (tx, rx) = mpsc::channel(1000);
    let (etx, events) = mpsc::unbounded_channel();
    let (stop, srx) = watch::channel(false);
    let task = tokio::spawn(service::run(s, shared.clone(), rx, etx, srx));
    Harness { shared, tx, events, stop, task, log: Log::default(), conn }
}

impl Harness {
    async fn ready(&mut self) -> (u64, Arc<config::Config>) {
        loop {
            match tokio::time::timeout(std::time::Duration::from_secs(20), self.events.recv()).await {
                Ok(Some(Event::Ready { generation, config })) => return (generation, config),
                Ok(Some(_)) => {}
                other => panic!("no Ready: {other:?}"),
            }
        }
    }

    async fn send(&self, generation: u64, id: u64, topic: &str, body: serde_json::Value, t: DateTime<Utc>) {
        let msg = Msg {
            connection_id: self.conn,
            topic: topic.into(),
            payload: serde_json::to_vec(&body).unwrap(),
            received_at: t,
        };
        let ack = TestAck { id, log: self.log.clone(), shared: self.shared.clone() };
        self.tx.send(Envelope { generation, qos0: false, msg, ack: Some(Box::new(ack)) }).await.unwrap();
    }

    async fn wait_acked(&self, n: usize) {
        for _ in 0..200 {
            if self.log.ids().len() >= n {
                return;
            }
            tokio::time::sleep(std::time::Duration::from_millis(50)).await;
        }
        panic!("only {} of {n} acked", self.log.ids().len());
    }

    async fn stop(self) -> Log {
        self.stop.send(true).unwrap();
        tokio::time::timeout(std::time::Duration::from_secs(20), self.task).await.unwrap().unwrap();
        self.log
    }
}

async fn plc(a: &tokio_postgres::Client) -> (Fx, i32) {
    reset(a).await;
    let fx = base(a, 2).await;
    let dev = Uuid::from_u128(0xD101);
    device(a, &fx, dev, "ZZ-PLC2", "zz/plc", fx.format).await;
    let (_, ch) = channel(a, dev, "A", "/a", "", "deadband", 0.5, 60, None).await;
    (fx, ch)
}

fn body(t: DateTime<Utc>, v: f64) -> serde_json::Value {
    serde_json::json!({"ts": t.to_rfc3339(), "a": v})
}

#[tokio::test]
async fn messages_are_acknowledged_only_after_their_batch_is_committed_and_in_order() {
    let Some(url) = url() else { return };
    let _g = serial();
    let a = admin(&url).await;
    let (fx, ch) = plc(&a).await;
    let mut h = start(settings(&url), fx.connection);
    let (generation, cfg) = h.ready().await;
    assert_eq!(cfg.channel_nos(), vec![ch]);
    for i in 0..250u64 {
        h.send(generation, i, "zz/plc", body(t0() + Duration::seconds(i as i64), i as f64), t0()).await;
    }
    h.wait_acked(250).await;
    let log = h.stop().await;
    let entries = log.0.lock().unwrap().clone();
    assert_eq!(log.ids(), (0..250).collect::<Vec<_>>());
    assert!(entries.iter().all(|(_, commits)| *commits >= 1));
    assert_eq!(count(&a, "SELECT count(*) FROM sensors_reading").await, 250);
    let st = a.query_one("SELECT connected FROM sensors_ingest_status", &[]).await.unwrap();
    assert!(!st.get::<_, bool>(0), "a stopped ingest says it is disconnected");
}

#[tokio::test]
async fn a_database_failure_acknowledges_nothing_and_asks_for_redelivery() {
    let Some(url) = url() else { return };
    let _g = serial();
    let a = admin(&url).await;
    let (fx, _) = plc(&a).await;
    let mut h = start(settings(&url), fx.connection);
    let (g1, _) = h.ready().await;
    for i in 0..10u64 {
        h.send(g1, i, "zz/plc", body(t0() + Duration::seconds(i as i64), i as f64), t0()).await;
    }
    h.wait_acked(10).await;
    // the writer's session is killed (a database restart, a network cut)
    a.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE application_name = 'sensors-ingest' AND datname = current_database()", &[])
        .await
        .unwrap();
    for i in 10..20u64 {
        h.send(g1, i, "zz/plc", body(t0() + Duration::seconds(i as i64), i as f64), t0()).await;
    }
    let mut asked = false;
    let g2 = loop {
        match tokio::time::timeout(std::time::Duration::from_secs(30), h.events.recv()).await.unwrap().unwrap() {
            Event::RedeliverRequired => asked = true,
            Event::Ready { generation, .. } => break generation,
            _ => {}
        }
    };
    assert!(asked);
    assert!(g2 > g1);
    tokio::time::sleep(std::time::Duration::from_millis(500)).await;
    assert_eq!(h.log.ids(), (0..10).collect::<Vec<_>>(), "nothing after the failure was acknowledged");
    // the broker redelivers 10..20 on the new sessions
    for i in 10..20u64 {
        h.send(g2, 100 + i, "zz/plc", body(t0() + Duration::seconds(i as i64), i as f64), t0()).await;
    }
    h.wait_acked(20).await;
    h.stop().await;
    assert_eq!(count(&a, "SELECT count(*) FROM sensors_reading").await, 20);
}

#[tokio::test]
async fn a_message_that_breaks_its_batch_is_isolated_and_dead_lettered_and_the_rest_committed() {
    let Some(url) = url() else { return };
    let _g = serial();
    let a = admin(&url).await;
    let (fx, ch) = plc(&a).await;
    // stands for any unforeseen row the table refuses
    a.batch_execute(
        "CREATE OR REPLACE FUNCTION zz_poison() RETURNS trigger AS $$ BEGIN \
         RAISE EXCEPTION 'poison' USING ERRCODE = '23514'; END $$ LANGUAGE plpgsql; \
         DROP TRIGGER IF EXISTS zz_poison ON sensors_reading; \
         CREATE TRIGGER zz_poison BEFORE INSERT ON sensors_reading FOR EACH ROW WHEN (NEW.value = 666) \
         EXECUTE FUNCTION zz_poison();",
    )
    .await
    .unwrap();
    let mut h = start(settings(&url), fx.connection);
    let (g, _) = h.ready().await;
    for (i, v) in [1.0, 2.0, 666.0, 3.0, 4.0].iter().enumerate() {
        h.send(g, i as u64, "zz/plc", body(t0() + Duration::seconds(i as i64), *v), t0()).await;
    }
    h.wait_acked(5).await;
    let shared = h.shared.clone();
    h.stop().await;
    a.batch_execute("DROP TRIGGER zz_poison ON sensors_reading; DROP FUNCTION zz_poison()").await.unwrap();
    let vals: Vec<f64> = a
        .query("SELECT value FROM sensors_reading WHERE channel_no = $1 ORDER BY ts", &[&ch])
        .await
        .unwrap()
        .iter()
        .map(|r| r.get(0))
        .collect();
    assert_eq!(vals, vec![1.0, 2.0, 3.0, 4.0]);
    let dl = a.query_one("SELECT reason, count FROM sensors_dead_letter", &[]).await.unwrap();
    assert_eq!((dl.get::<_, String>(0), dl.get::<_, i32>(1)), ("bad_value".into(), 1));
    assert_eq!(shared.poison.load(Ordering::SeqCst), 1);
    // the state stayed consistent: the poison value never became the anchor
    let anchor: f64 = a
        .query_one("SELECT anchor_value FROM sensors_channel_state WHERE channel_no = $1", &[&ch])
        .await
        .unwrap()
        .get(0);
    assert_eq!(anchor, 4.0);
}

#[tokio::test]
async fn shutdown_commits_and_acknowledges_everything_queued() {
    let Some(url) = url() else { return };
    let _g = serial();
    let a = admin(&url).await;
    let (fx, _) = plc(&a).await;
    let mut s = settings(&url);
    s.batch_ms = 60_000; // only size or shutdown cuts a batch
    s.batch_max = 10_000;
    let mut h = start(s, fx.connection);
    let (g, _) = h.ready().await;
    for i in 0..300u64 {
        h.send(g, i, "zz/plc", body(t0() + Duration::seconds(i as i64), (i * 7 % 13) as f64), t0()).await;
    }
    let log = h.stop().await;
    assert_eq!(log.ids(), (0..300).collect::<Vec<_>>());
    let n: i64 = a.query_one("SELECT sum(n)::int8 FROM sensors_reading", &[]).await.unwrap().get(0);
    let run_n: i32 = a.query_one("SELECT run_n FROM sensors_channel_state", &[]).await.unwrap().get(0);
    assert_eq!(n + i64::from(run_n), 300);
}

#[tokio::test]
async fn a_restarted_ingest_continues_exactly_where_the_committed_state_left() {
    let Some(url) = url() else { return };
    let _g = serial();
    let a = admin(&url).await;
    let (fx, ch) = plc(&a).await;
    let stream: Vec<(DateTime<Utc>, f64)> =
        (0..400i64).map(|i| (t0() + Duration::seconds(i * 7), ((i * 37) % 23) as f64 * 0.11)).collect();
    for (part, range) in [(0, 0..170usize), (1, 170..400)] {
        let mut h = start(settings(&url), fx.connection);
        let (g, _) = h.ready().await;
        for i in range.clone() {
            let (t, v) = stream[i];
            h.send(g, i as u64, "zz/plc", body(t, v), t).await;
        }
        h.wait_acked(range.len()).await;
        h.stop().await;
        let _ = part;
    }
    // the same stream through the pipeline in one go
    let mut c = ingest(&url).await;
    let cfg = config::load(&mut c).await.unwrap();
    let msgs: Vec<Msg> = stream
        .iter()
        .map(|(t, v)| Msg {
            connection_id: fx.connection,
            topic: "zz/plc".into(),
            payload: serde_json::to_vec(&body(*t, *v)).unwrap(),
            received_at: *t,
        })
        .collect();
    let out = pipeline::process(&cfg, &HashMap::new(), &mut DeadLimiter::new(10), &msgs);
    let want: Vec<(DateTime<Utc>, f64, i32, i16)> =
        out.readings.iter().map(|r| (r.row.ts, r.row.value, r.row.n, r.row.quality)).collect();
    let got: Vec<(DateTime<Utc>, f64, i32, i16)> = a
        .query("SELECT ts, value, n, quality FROM sensors_reading WHERE channel_no = $1 ORDER BY ts", &[&ch])
        .await
        .unwrap()
        .iter()
        .map(|r| (r.get(0), r.get(1), r.get(2), r.get(3)))
        .collect();
    assert_eq!(got, want);
}

#[tokio::test]
async fn a_configuration_change_is_picked_up_without_a_restart() {
    let Some(url) = url() else { return };
    let _g = serial();
    let a = admin(&url).await;
    let (fx, _) = plc(&a).await;
    let mut h = start(settings(&url), fx.connection);
    let (g, _) = h.ready().await;
    let dev2 = Uuid::from_u128(0xD102);
    device(&a, &fx, dev2, "ZZ-NEW", "zz/new", fx.format).await;
    let (_, ch2) = channel(&a, dev2, "N", "/a", "", "all", 0.0, 60, None).await;
    let cfg = loop {
        match tokio::time::timeout(std::time::Duration::from_secs(10), h.events.recv()).await.unwrap().unwrap() {
            Event::ConfigChanged(c) if c.channel_nos().contains(&ch2) => break c,
            _ => {}
        }
    };
    assert!(cfg.route(fx.connection, "zz/new").is_some());
    h.send(g, 1, "zz/new", body(t0(), 5.0), t0()).await;
    h.wait_acked(1).await;
    h.stop().await;
    assert_eq!(count(&a, &format!("SELECT count(*) FROM sensors_reading WHERE channel_no = {ch2}")).await, 1);
}

#[tokio::test]
async fn a_second_ingest_stands_by_until_the_first_stops() {
    let Some(url) = url() else { return };
    let _g = serial();
    let a = admin(&url).await;
    let (fx, _) = plc(&a).await;
    let mut first = start(settings(&url), fx.connection);
    first.ready().await;
    let mut second = start(settings(&url), fx.connection);
    let ev = tokio::time::timeout(std::time::Duration::from_secs(10), second.events.recv()).await.unwrap().unwrap();
    assert!(matches!(ev, Event::Standby));
    assert!(!second.shared.ready.load(Ordering::SeqCst));
    first.stop().await;
    second.ready().await;
    assert!(second.shared.ready.load(Ordering::SeqCst));
    second.stop().await;
}

#[tokio::test]
async fn the_heartbeat_keeps_the_status_fresh_while_idle() {
    let Some(url) = url() else { return };
    let _g = serial();
    let a = admin(&url).await;
    let (fx, _) = plc(&a).await;
    let mut h = start(settings(&url), fx.connection);
    h.ready().await;
    tokio::time::sleep(std::time::Duration::from_millis(400)).await;
    let first: DateTime<Utc> = a.query_one("SELECT heartbeat_at FROM sensors_ingest_status", &[]).await.unwrap().get(0);
    tokio::time::sleep(std::time::Duration::from_millis(800)).await;
    let later: DateTime<Utc> = a.query_one("SELECT heartbeat_at FROM sensors_ingest_status", &[]).await.unwrap().get(0);
    assert!(later > first);
    assert!(h.shared.last_db_ok.load(Ordering::SeqCst) > 0);
    h.stop().await;
}
