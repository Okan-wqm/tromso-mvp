//! The many-sources bench (bench/run.sh multisource): one MQTT connection per device, each with its own credential
//! and topic, 1 message per second with a jittered start, three payload formats of the golden vectors (a PLC object
//! with ISO time, a probe array with epoch ms, a flow meter with ISO UTC time), some devices with a clock 10 minutes
//! ahead, two brokers. At OUTAGE_AT seconds the OUTAGE devices disconnect for OUTAGE_S seconds, keep measuring, then
//! reconnect and send their backlog at once (a gateway coming back). Every PUBACK is counted per device.
//! A poller reads `sensors_channel_state.high_ts` of the `all` channels every 100 ms (as the database owner) and
//! records commit latency = first time a new device time is seen committed - that device time.
//!
//! Env: DEVICES (file: "index password broker format skew outage" per line), SECONDS, OUTAGE_AT, OUTAGE_S,
//! STATS_FILE (writes "index sent acked" per device), DB (libpq string of the owner), PREFIX (topic prefix).
#![allow(clippy::unwrap_used, clippy::expect_used, clippy::panic, clippy::indexing_slicing)]

use rumqttc::{AsyncClient, Event, MqttOptions, Packet, QoS};
use sensors_ingest::ts::Ts;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, Instant};

fn env<T: std::str::FromStr>(k: &str, d: T) -> T {
    std::env::var(k).ok().and_then(|v| v.parse().ok()).unwrap_or(d)
}

struct Dev {
    index: usize,
    password: String,
    broker: String,
    format: u8,
    skew: bool,
    outage: bool,
}

/// RFC 3339 with milliseconds at a whole-hour offset: `2026-11-04T13:00:00.000+01:00`, or `...Z` at offset 0.
fn rfc3339_millis(t_ms: i64, offset_h: i8) -> String {
    let t = time::OffsetDateTime::from_unix_timestamp_nanos(i128::from(t_ms) * 1_000_000)
        .unwrap()
        .to_offset(time::UtcOffset::from_hms(offset_h, 0, 0).unwrap());
    let zone = if offset_h == 0 { "Z".to_string() } else { format!("{offset_h:+03}:00") };
    let (h, m, s, ms) = (t.hour(), t.minute(), t.second(), t.millisecond());
    format!("{:04}-{:02}-{:02}T{h:02}:{m:02}:{s:02}.{ms:03}{zone}", t.year(), u8::from(t.month()), t.day())
}

fn payload(d: &Dev, seq: u64, t_ms: i64, x: f64) -> Vec<u8> {
    let t_ms = if d.skew { t_ms + 600_000 } else { t_ms };
    let v = match d.format {
        0 => serde_json::json!({
            "ts": rfc3339_millis(t_ms, 1),
            "seq": seq,
            "tags": {"temp_inlet": {"value": 9.5 + x}, "o2_sump": {"value": 10.0 + x}, "ph_sump": {"value": 7.3 + x / 10.0}}
        }),
        1 => serde_json::json!({
            "seq": seq,
            "items": [{"n": "do", "v": 9.0 + x, "t": t_ms}, {"n": "temp", "v": 9.8 + x, "t": t_ms}, {"n": "sat", "v": 95.0 + 5.0 * x, "t": t_ms}]
        }),
        _ => {
            serde_json::json!({"time": rfc3339_millis(t_ms, 0), "sequence": seq, "flow_m3h": 40.0 + 3.0 * x})
        }
    };
    serde_json::to_vec(&v).unwrap()
}

async fn device(
    d: Dev,
    prefix: String,
    seconds: u64,
    outage_at: u64,
    outage_s: u64,
    sent: Arc<AtomicU64>,
    acked: Arc<AtomicU64>,
) {
    let jitter = Duration::from_millis((d.index as u64 * 7919) % 1000);
    tokio::time::sleep(jitter).await;
    let start = Instant::now();
    let topic = format!("{prefix}{}", d.index);
    let connect = || {
        let mut o = MqttOptions::new(format!("ms-dev-{}", d.index), d.broker.clone(), 1883);
        o.set_credentials(format!("dev-{}", d.index), d.password.clone())
            .set_clean_session(false)
            .set_keep_alive(Duration::from_secs(30))
            .set_inflight(100);
        let (c, mut el) = AsyncClient::new(o, 2000);
        let a = acked.clone();
        let h = tokio::spawn(async move {
            loop {
                match el.poll().await {
                    Ok(Event::Incoming(Packet::PubAck(_))) => {
                        a.fetch_add(1, Ordering::Relaxed);
                    }
                    Ok(_) => {}
                    Err(_) => tokio::time::sleep(Duration::from_millis(500)).await,
                }
            }
        });
        (c, h)
    };
    let (mut c, mut h) = connect();
    let mut tick = tokio::time::interval(Duration::from_secs(1));
    let mut backlog: Vec<Vec<u8>> = Vec::new();
    let mut down = false;
    let mut seq = 0u64;
    loop {
        tick.tick().await;
        let el = start.elapsed().as_secs();
        if el >= seconds {
            break;
        }
        let in_outage = d.outage && el >= outage_at && el < outage_at + outage_s;
        if in_outage && !down {
            let _ = c.disconnect().await;
            tokio::time::sleep(Duration::from_millis(300)).await;
            h.abort();
            down = true;
        }
        if !in_outage && down {
            let (c2, h2) = connect();
            c = c2;
            h = h2;
            down = false;
            for p in backlog.drain(..) {
                c.publish(topic.clone(), QoS::AtLeastOnce, false, p).await.unwrap();
            }
        }
        seq += 1;
        let t_ms = Ts::now().unix_millis();
        let x = ((seq as f64) / 120.0 + d.index as f64).sin() * 0.3 + ((seq * 31 + d.index as u64) % 17) as f64 / 170.0;
        let p = payload(&d, seq, t_ms, x);
        sent.fetch_add(1, Ordering::Relaxed);
        if down {
            backlog.push(p);
        } else {
            c.publish(topic.clone(), QoS::AtLeastOnce, false, p).await.unwrap();
        }
    }
    // let the last acknowledgements arrive
    for _ in 0..300 {
        if acked.load(Ordering::Relaxed) >= sent.load(Ordering::Relaxed) {
            break;
        }
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
    let _ = c.disconnect().await;
    tokio::time::sleep(Duration::from_millis(500)).await;
    h.abort();
}

async fn poll_latency(db: String, seconds: u64, out: Arc<std::sync::Mutex<Vec<i64>>>) {
    let (client, conn) = tokio_postgres::connect(&db, tokio_postgres::NoTls).await.unwrap();
    tokio::spawn(conn);
    let probes: Vec<i32> = client
        .query(
            "SELECT c.channel_no FROM sensors_channel c JOIN sensors_device d ON d.id = c.device_id \
             WHERE c.reduction = 'all' AND d.note NOT LIKE '%skew%' AND d.note NOT LIKE '%outage%'",
            &[],
        )
        .await
        .unwrap()
        .iter()
        .map(|r| r.get(0))
        .collect();
    let mut last: std::collections::HashMap<i32, Ts> = Default::default();
    let start = Instant::now();
    while start.elapsed().as_secs() < seconds {
        let rows = client
            .query("SELECT channel_no, high_ts FROM sensors_channel_state WHERE channel_no = ANY($1)", &[&probes])
            .await
            .unwrap();
        let now = Ts::now();
        for r in rows {
            let ch: i32 = r.get(0);
            let Some(high): Option<Ts> = r.get(1) else { continue };
            if last.get(&ch) != Some(&high) {
                if last.contains_key(&ch) {
                    out.lock().unwrap().push((now - high).whole_milliseconds() as i64);
                }
                last.insert(ch, high);
            }
        }
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
}

fn pct(v: &mut [i64], p: usize) -> i64 {
    if v.is_empty() {
        return -1;
    }
    v.sort_unstable();
    v[(v.len() * p).div_ceil(100).saturating_sub(1)]
}

#[tokio::main(flavor = "multi_thread")]
async fn main() {
    let seconds: u64 = env("SECONDS", 120);
    let outage_at: u64 = env("OUTAGE_AT", 60);
    let outage_s: u64 = env("OUTAGE_S", 30);
    let prefix: String = env("PREFIX", "ms/dev-".to_string());
    let list = std::fs::read_to_string(env("DEVICES", "devices.txt".to_string())).unwrap();
    let devs: Vec<Dev> = list
        .lines()
        .filter(|l| !l.trim().is_empty())
        .map(|l| {
            let f: Vec<&str> = l.split_whitespace().collect();
            Dev {
                index: f[0].parse().unwrap(),
                password: f[1].to_string(),
                broker: f[2].to_string(),
                format: f[3].parse().unwrap(),
                skew: f[4] == "1",
                outage: f[5] == "1",
            }
        })
        .collect();
    let n = devs.len();
    let lat = Arc::new(std::sync::Mutex::new(Vec::new()));
    let poller = std::env::var("DB").ok().map(|db| tokio::spawn(poll_latency(db, seconds + 20, lat.clone())));
    let mut counters = Vec::new();
    let mut tasks = Vec::new();
    for d in devs {
        let (s, a) = (Arc::new(AtomicU64::new(0)), Arc::new(AtomicU64::new(0)));
        counters.push((d.index, s.clone(), a.clone()));
        tasks.push(tokio::spawn(device(d, prefix.clone(), seconds, outage_at, outage_s, s, a)));
    }
    for t in tasks {
        let _ = t.await;
    }
    if let Some(p) = poller {
        let _ = p.await;
    }
    let (mut sent, mut acked) = (0u64, 0u64);
    let mut text = String::new();
    for (i, s, a) in &counters {
        let (s, a) = (s.load(Ordering::Relaxed), a.load(Ordering::Relaxed));
        sent += s;
        acked += a;
        text.push_str(&format!("{i} {s} {a}\n"));
    }
    if let Ok(path) = std::env::var("STATS_FILE") {
        std::fs::write(path, text).unwrap();
    }
    let mut l = lat.lock().unwrap().clone();
    let count = l.len();
    println!(
        "devices={n} sent={sent} acked={acked} latency_ms p50={} p95={} p99={} max={} samples={count}",
        pct(&mut l, 50),
        pct(&mut l, 95),
        pct(&mut l, 99),
        pct(&mut l, 100)
    );
}
