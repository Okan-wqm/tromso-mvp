//! The writer against the real schema (Django migrations 0001/0002), acting as role `sensors_ingest`.
#![allow(clippy::unwrap_used, clippy::expect_used, clippy::panic, clippy::indexing_slicing, clippy::await_holding_lock)]

mod common;

use chrono::{DateTime, Duration, Utc};
use common::*;
use sensors_ingest::config::{self, VIEW_COLUMNS};
use sensors_ingest::db::{self, Status};
use sensors_ingest::model::DeadReason;
use sensors_ingest::pipeline::{self, DeadLimiter, Msg, Output, Reading};
use sensors_ingest::quality;
use sensors_ingest::reduce::{Row, State};
use std::collections::HashMap;
use std::sync::Mutex;
use uuid::Uuid;

/// The tests share one database: one at a time.
static SERIAL: Mutex<()> = Mutex::new(());

fn serial() -> std::sync::MutexGuard<'static, ()> {
    SERIAL.lock().unwrap_or_else(|p| p.into_inner())
}

fn t0() -> DateTime<Utc> {
    // twenty days ago at a whole second: inside the retention, before compression, reproducible keys
    let t = Utc::now() - Duration::days(20);
    DateTime::from_timestamp(t.timestamp(), 0).unwrap()
}

struct Setup {
    fx: Fx,
    dev: Uuid,
    ch_a: i32,
    ch_b: i32,
}

/// A device on `zz/plc` with two channels: A at /a (deadband 0.5, heartbeat 60 s, range 0..100) and B at /b (all).
async fn setup(a: &tokio_postgres::Client) -> Setup {
    reset(a).await;
    let fx = base(a, 1).await;
    let dev = Uuid::from_u128(0xD001);
    device(a, &fx, dev, "ZZ-PLC", "zz/plc", fx.format).await;
    let (_, ch_a) = channel(a, dev, "A", "/a", "", "deadband", 0.5, 60, Some((0.0, 100.0))).await;
    let (_, ch_b) = channel(a, dev, "B", "/b", "", "all", 0.0, 60, None).await;
    Setup { fx, dev, ch_a, ch_b }
}

fn msg(fx: &Fx, t: DateTime<Utc>, body: serde_json::Value) -> Msg {
    Msg {
        connection_id: fx.connection,
        topic: "zz/plc".into(),
        payload: serde_json::to_vec(&body).unwrap(),
        received_at: t,
    }
}

fn status(fx: &Fx) -> Vec<Status> {
    vec![Status { connection_id: fx.connection, connected: true, queue_depth: 3, version: "test".into() }]
}

#[tokio::test]
async fn the_contract_view_columns_and_quality_flags_equal_the_ingest_copy() {
    let Some(url) = url() else { return };
    let _g = serial();
    let c = ingest(&url).await;
    assert_eq!(db::view_columns(&c).await.unwrap(), VIEW_COLUMNS.to_vec());
    let flags = db::quality_flags(&c).await.unwrap();
    let mine: Vec<(i16, String, bool)> = quality::FLAGS.iter().map(|f| (f.0, f.1.to_string(), f.2)).collect();
    assert_eq!(flags, mine);
}

#[tokio::test]
async fn config_loads_through_the_view_with_epochs_and_routes() {
    let Some(url) = url() else { return };
    let _g = serial();
    let a = admin(&url).await;
    let s = setup(&a).await;
    let arr = Uuid::from_u128(0xF0A1);
    format_row(&a, arr, "array fmt", "array", "/t", "epoch_ms", "", "/items", "n", "v").await;
    let probe = Uuid::from_u128(0xD002);
    device(&a, &s.fx, probe, "ZZ-PROBE", "zz/+/probe", arr).await;
    let (do_id, ch_do) = channel(&a, probe, "DO", "", "do", "deadband", 0.1, 300, None).await;
    let t1 = t0();
    a.execute(
        "INSERT INTO sensors_calibration (valid_from, gain, \"offset\", performed_by, note, created_at, channel_id) \
         VALUES ($1, 2, 1, '', '', now(), $2), ($3, 3, 0, '', '', now(), $2)",
        &[&t1, &do_id, &(t1 + Duration::days(1))],
    )
    .await
    .unwrap();
    let mut c = ingest(&url).await;
    let cfg = config::load(&mut c).await.unwrap();
    assert!(cfg.rejected.is_empty(), "{:?}", cfg.rejected);
    assert_eq!(cfg.contract.schema_version, 1);
    assert_eq!((cfg.contract.future_skew_s, cfg.contract.retention_days, cfg.contract.late_limit_days), (60, 730, 728));
    let mut nos = cfg.channel_nos();
    nos.sort();
    assert_eq!(nos, vec![s.ch_a, s.ch_b, ch_do]);
    let d = cfg.route(s.fx.connection, "zz/hall/probe").unwrap();
    assert_eq!(d.device_id, probe);
    let ch = &d.channels[0];
    assert_eq!(ch.epochs.len(), 2);
    assert_eq!((ch.epochs[0].valid_from, ch.epochs[0].a, ch.epochs[0].b), (None, 2.0, 1.0));
    assert_eq!((ch.epochs[1].valid_from, ch.epochs[1].a), (Some(t1 + Duration::days(1)), 3.0));
    assert_eq!(cfg.route(s.fx.connection, "zz/plc").unwrap().device_id, s.dev);
    // the epoch moved with every change, and the contract row says so
    assert!(cfg.contract.config_epoch > 0);
}

#[tokio::test]
async fn one_writer_holds_the_lock() {
    let Some(url) = url() else { return };
    let _g = serial();
    let c1 = ingest(&url).await;
    let c2 = ingest(&url).await;
    assert!(db::try_lock(&c1).await.unwrap());
    assert!(!db::try_lock(&c2).await.unwrap());
    drop(c1);
    // the server releases a session lock when the session ends
    let mut got = false;
    for _ in 0..50 {
        if db::try_lock(&c2).await.unwrap() {
            got = true;
            break;
        }
        tokio::time::sleep(std::time::Duration::from_millis(100)).await;
    }
    assert!(got);
}

#[tokio::test]
async fn a_batch_commits_readings_states_devices_dead_letters_and_status_and_a_redelivery_adds_no_row() {
    let Some(url) = url() else { return };
    let _g = serial();
    let a = admin(&url).await;
    let s = setup(&a).await;
    let mut c = ingest(&url).await;
    let cfg = config::load(&mut c).await.unwrap();
    let t = t0();
    let msgs: Vec<Msg> = (0..10)
        .map(|i| {
            let ti = t + Duration::seconds(i);
            msg(&s.fx, ti, serde_json::json!({"ts": ti.to_rfc3339(), "seq": i, "a": 10.0 + 0.1 * i as f64, "b": i}))
        })
        .chain([Msg {
            connection_id: s.fx.connection,
            topic: "zz/plc".into(),
            payload: b"{bad".to_vec(),
            received_at: t,
        }])
        .chain([Msg {
            connection_id: s.fx.connection,
            topic: "zz/none".into(),
            payload: b"{}".to_vec(),
            received_at: t,
        }])
        .collect();
    let committed = db::load_states(&c, &cfg.channel_nos()).await.unwrap();
    assert!(committed.values().all(|st| *st == State::default()));
    let out = pipeline::process(&cfg, &committed, &mut DeadLimiter::new(100), &msgs);
    let w = db::write_batch(&mut c, &out, &status(&s.fx)).await.unwrap();
    assert_eq!(w.readings_inserted as usize, out.readings.len());
    assert_eq!(w.readings_existing, 0);
    assert_eq!(count(&a, "SELECT count(*) FROM sensors_reading").await, out.readings.len() as i64);
    // A: 10.0 stored, 10.1..10.4 suppressed, 10.5 stored with n = 6
    let n_a: i64 =
        a.query_one("SELECT sum(n)::int8 FROM sensors_reading WHERE channel_no = $1", &[&s.ch_a]).await.unwrap().get(0);
    assert_eq!(n_a, 6);
    let loaded = db::load_states(&c, &[s.ch_a, s.ch_b]).await.unwrap();
    assert_eq!(loaded[&s.ch_a], out.states[&s.ch_a]);
    assert_eq!(loaded[&s.ch_b], out.states[&s.ch_b]);
    let dev = a
        .query_one(
            "SELECT accepted_total, late_total, dead_total, last_seq, last_message_at FROM sensors_device_state WHERE device_id = $1",
            &[&s.dev],
        )
        .await
        .unwrap();
    assert_eq!((dev.get::<_, i64>(0), dev.get::<_, i64>(1), dev.get::<_, i64>(2)), (10, 0, 1));
    assert_eq!(dev.get::<_, Option<i64>>(3), Some(9));
    let dl = a.query("SELECT reason, device_id, count FROM sensors_dead_letter ORDER BY reason", &[]).await.unwrap();
    let dl: Vec<(String, Option<Uuid>, i32)> = dl.iter().map(|r| (r.get(0), r.get(1), r.get(2))).collect();
    assert_eq!(dl, vec![("no_route".into(), None, 1), ("not_json".into(), Some(s.dev), 1)]);
    let st = a
        .query_one("SELECT connected, queue_depth, version, last_commit_at IS NOT NULL FROM sensors_ingest_status", &[])
        .await
        .unwrap();
    assert_eq!(
        (st.get::<_, bool>(0), st.get::<_, i32>(1), st.get::<_, String>(2), st.get::<_, bool>(3)),
        (true, 3, "test".into(), true)
    );

    // the same messages again (a redelivery after a crash between COMMIT and PUBACK)
    let committed: HashMap<i32, State> = out.states.clone().into_iter().collect();
    let out2 = pipeline::process(&cfg, &committed, &mut DeadLimiter::new(100), &msgs);
    assert!(out2.readings.iter().all(|r| r.row.quality & quality::LATE != 0));
    let w2 = db::write_batch(&mut c, &out2, &status(&s.fx)).await.unwrap();
    // stored rows conflict; the last message (at the newest time) is a duplicate; the other seven suppressed A
    // samples (10.1-10.4, 10.6-10.8) come back as LATE rows: the bounded residual of plan risk 2
    assert_eq!(w2.readings_inserted, 7);
    assert_eq!(w2.readings_existing as usize, out2.readings.len() - 7);
    let counts = a.query("SELECT count FROM sensors_dead_letter ORDER BY reason", &[]).await.unwrap();
    assert_eq!(counts.iter().map(|r| r.get::<_, i32>(0)).collect::<Vec<_>>(), vec![2, 2]);
    let dev =
        a.query_one("SELECT accepted_total, late_total, ignored_total FROM sensors_device_state", &[]).await.unwrap();
    assert_eq!((dev.get::<_, i64>(0), dev.get::<_, i64>(1), dev.get::<_, i64>(2)), (20, 9, 1));
}

#[tokio::test]
async fn a_failing_statement_writes_nothing_and_is_a_data_error() {
    let Some(url) = url() else { return };
    let _g = serial();
    let a = admin(&url).await;
    let s = setup(&a).await;
    let mut c = ingest(&url).await;
    let good = Row { ts: t0(), value: 1.0, n: 1, quality: 0, run_sum: None, run_min: None, run_max: None };
    // n = 2 without run statistics breaks the table's CHECK
    let bad = Row { ts: t0() + Duration::seconds(1), n: 2, ..good };
    let mut out = Output {
        readings: vec![Reading { channel_no: s.ch_a, row: good }, Reading { channel_no: s.ch_a, row: bad }],
        ..Output::default()
    };
    out.states.insert(s.ch_a, State { run_n: 3, ..State::default() });
    let e = db::write_batch(&mut c, &out, &status(&s.fx)).await.unwrap_err();
    assert!(db::is_data_error(&e), "{e:?}");
    assert_eq!(count(&a, "SELECT count(*) FROM sensors_reading").await, 0);
    assert_eq!(count(&a, "SELECT count(*) FROM sensors_channel_state").await, 0);
    assert_eq!(count(&a, "SELECT count(*) FROM sensors_ingest_status").await, 0);
    // the session is usable afterwards
    out.readings.pop();
    db::write_batch(&mut c, &out, &status(&s.fx)).await.unwrap();
    assert_eq!(count(&a, "SELECT count(*) FROM sensors_reading").await, 1);
}

#[tokio::test]
async fn the_heartbeat_writes_status_without_a_commit_time() {
    let Some(url) = url() else { return };
    let _g = serial();
    let a = admin(&url).await;
    let s = setup(&a).await;
    let c = ingest(&url).await;
    db::write_status(&c, &status(&s.fx)).await.unwrap();
    let r = a.query_one("SELECT heartbeat_at, last_commit_at FROM sensors_ingest_status", &[]).await.unwrap();
    let first: DateTime<Utc> = r.get(0);
    assert!(r.get::<_, Option<DateTime<Utc>>>(1).is_none());
    tokio::time::sleep(std::time::Duration::from_millis(20)).await;
    let mut st = status(&s.fx);
    st[0].connected = false;
    db::write_status(&c, &st).await.unwrap();
    let r = a.query_one("SELECT heartbeat_at, connected FROM sensors_ingest_status", &[]).await.unwrap();
    assert!(r.get::<_, DateTime<Utc>>(0) > first);
    assert!(!r.get::<_, bool>(1));
}

#[tokio::test]
async fn the_dead_letter_flood_is_capped_and_readings_never_are() {
    let Some(url) = url() else { return };
    let _g = serial();
    let a = admin(&url).await;
    let s = setup(&a).await;
    let mut c = ingest(&url).await;
    let cfg = config::load(&mut c).await.unwrap();
    let t = t0();
    let mut msgs: Vec<Msg> = (0..30)
        .map(|i| Msg {
            connection_id: s.fx.connection,
            topic: "zz/plc".into(),
            payload: format!("junk {i}").into_bytes(),
            received_at: t,
        })
        .collect();
    msgs.extend((0..30).map(|i| {
        let ti = t + Duration::seconds(i);
        msg(&s.fx, ti, serde_json::json!({"ts": ti.to_rfc3339(), "b": i}))
    }));
    let out = pipeline::process(&cfg, &HashMap::new(), &mut DeadLimiter::new(10), &msgs);
    db::write_batch(&mut c, &out, &status(&s.fx)).await.unwrap();
    assert_eq!(count(&a, "SELECT count(*) FROM sensors_dead_letter").await, 11);
    assert_eq!(count(&a, "SELECT count::int8 FROM sensors_dead_letter WHERE payload_sha256 = 'overflow'").await, 20);
    assert_eq!(count(&a, "SELECT count(*) FROM sensors_reading").await, 30);
    let r = a
        .query_one(
            "SELECT payload_sha256, payload, payload_len FROM sensors_dead_letter WHERE payload = 'junk 0'::bytea",
            &[],
        )
        .await
        .unwrap();
    assert_eq!(r.get::<_, String>(0), pipeline::sha256_hex(b"junk 0"));
    assert_eq!(r.get::<_, i32>(2), 6);
}

#[tokio::test]
async fn the_ingest_role_cannot_read_readings_or_configuration() {
    let Some(url) = url() else { return };
    let _g = serial();
    let c = ingest(&url).await;
    for sql in [
        "SELECT 1 FROM sensors_reading LIMIT 1",
        "SELECT 1 FROM sensors_channel LIMIT 1",
        "SELECT 1 FROM sensors_credential LIMIT 1",
    ] {
        let e = c.query(sql, &[]).await.unwrap_err();
        assert_eq!(e.code().map(|c| c.code()), Some("42501"), "{sql}");
    }
}

/// The statistics oracle through PostgreSQL: a long noisy stream with plateaus, written batch by batch through the
/// real writer; the rollup formulas (count-weighted sum, min, max over clean rows) plus the open run equal the
/// unreduced stream, overall and per hour bucket within the run-attribution bound.
#[tokio::test]
async fn statistics_oracle_through_the_database() {
    let Some(url) = url() else { return };
    let _g = serial();
    let a = admin(&url).await;
    let s = setup(&a).await;
    let mut c = ingest(&url).await;
    let cfg = config::load(&mut c).await.unwrap();
    let mut committed = db::load_states(&c, &cfg.channel_nos()).await.unwrap();
    let mut lim = DeadLimiter::new(100);
    let t = t0();
    let mut x: u64 = 0x9E37_79B9_7F4A_7C15;
    let mut rnd = || {
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        (x % 10_000) as f64 / 10_000.0
    };
    let mut v = 20.0;
    let mut values = Vec::new();
    let mut msgs = Vec::new();
    for i in 0..6000i64 {
        // plateaus: 2 of every 10 minutes flat
        if (i / 60) % 10 >= 2 {
            v += (rnd() - 0.5) * 0.4;
        }
        let v = v.clamp(1.0, 99.0);
        values.push(v);
        let ti = t + Duration::seconds(i);
        msgs.push(msg(&s.fx, ti, serde_json::json!({"ts": ti.to_rfc3339(), "a": v})));
    }
    for chunk in msgs.chunks(250) {
        let out = pipeline::process(&cfg, &committed, &mut lim, chunk);
        db::write_batch(&mut c, &out, &status(&s.fx)).await.unwrap();
        committed.extend(out.states);
    }
    let st = &committed[&s.ch_a];
    let r = a
        .query_one(
            "SELECT sum(n)::int8, sum(coalesce(run_sum, value)), min(coalesce(run_min, value)), \
             max(coalesce(run_max, value)), count(*) FROM sensors_reading WHERE channel_no = $1 AND quality & 240 = 0",
            &[&s.ch_a],
        )
        .await
        .unwrap();
    let n: i64 = r.get(0);
    let sum: f64 = r.get(1);
    let rows: i64 = r.get(4);
    assert_eq!(n + i64::from(st.run_n), values.len() as i64);
    let want: f64 = values.iter().sum();
    assert!((sum + st.run_sum.unwrap_or(0.0) - want).abs() < 1e-6 * want, "{sum} {want}");
    let mn = values.iter().cloned().fold(f64::INFINITY, f64::min);
    let mx = values.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
    assert_eq!(r.get::<_, f64>(2).min(st.run_min.unwrap_or(f64::INFINITY)), mn);
    assert_eq!(r.get::<_, f64>(3).max(st.run_max.unwrap_or(f64::NEG_INFINITY)), mx);
    eprintln!(
        "oracle: {} samples stored as {rows} rows ({:.1} %)",
        values.len(),
        100.0 * rows as f64 / values.len() as f64
    );
    // per hour: each sample is counted at most two heartbeats (120 s) after it, so an hour's count differs from the
    // stream's by at most the samples of the last 120 s of the hour
    let hours = a
        .query(
            "SELECT time_bucket('1 hour', ts) AS h, sum(n)::int8 FROM sensors_reading WHERE channel_no = $1 \
             AND quality & 240 = 0 GROUP BY h ORDER BY h",
            &[&s.ch_a],
        )
        .await
        .unwrap();
    for h in hours {
        let start: DateTime<Utc> = h.get(0);
        let got: i64 = h.get(1);
        let direct = (0..values.len() as i64).filter(|i| {
            let ti = t + Duration::seconds(*i);
            ti >= start && ti < start + Duration::hours(1)
        });
        let direct = direct.count() as i64;
        assert!((got - direct).abs() <= 120, "hour {start}: {got} vs {direct}");
    }
    let _ = DeadReason::ALL;
}
