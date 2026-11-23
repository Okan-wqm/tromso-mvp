//! Load generator for the S10 bench (bench/run.sh): publishes QoS 1 messages at a steady rate over many device topics
//! and accounts for every PUBACK, so a broker crash can be measured as "acknowledged by the broker but never stored".
//!
//! Env: BROKER (host), MQTT_USER, MQTT_PASSWORD, DEVICES (topics bench/dev-<i>), CHANNELS (values per message),
//! RATE (messages per second, all devices), SECONDS, GARBAGE (1: distinct non-JSON payloads instead), ACKED_FILE
//! (optional: writes "device seq" per acknowledged message), CLIENT_ID, TOPIC_PREFIX (default bench/dev-),
//! DEVICE_OFFSET (first device number, so several publishers can share the load).
//! Payload: {"t": <epoch ms>, "seq": n, "v": {"c0": x, ...}}; device times are unique per device (1 ms apart at least).
#![allow(clippy::unwrap_used, clippy::expect_used, clippy::panic, clippy::indexing_slicing)]

use rumqttc::{AsyncClient, Event, MqttOptions, Outgoing, Packet, QoS};
use std::collections::{HashMap, VecDeque};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

fn env<T: std::str::FromStr>(k: &str, d: T) -> T {
    std::env::var(k).ok().and_then(|v| v.parse().ok()).unwrap_or(d)
}

#[tokio::main]
async fn main() {
    let host: String = env("BROKER", "mosquitto".to_string());
    let devices: usize = env("DEVICES", 100);
    let channels: usize = env("CHANNELS", 5);
    let rate: u64 = env("RATE", 10_000);
    let seconds: u64 = env("SECONDS", 60);
    let garbage: u8 = env("GARBAGE", 0);
    let prefix: String = env("TOPIC_PREFIX", "bench/dev-".to_string());
    let offset: usize = env("DEVICE_OFFSET", 0);
    let mut o = MqttOptions::new(env("CLIENT_ID", "bench-publisher".to_string()), host, 1883);
    o.set_credentials(env("MQTT_USER", "bench".to_string()), env("MQTT_PASSWORD", String::new()))
        .set_inflight(1000)
        .set_clean_session(false)
        .set_keep_alive(Duration::from_secs(10))
        .set_max_packet_size(300 * 1024, 300 * 1024);
    let (c, mut el) = AsyncClient::new(o, 50_000);
    // pkid -> (device, seq), filled in publish order as rumqttc assigns packet ids (Outgoing::Publish events)
    let order: Arc<Mutex<VecDeque<(usize, u64)>>> = Arc::new(Mutex::new(VecDeque::new()));
    let acked = Arc::new(Mutex::new(Vec::<(usize, u64)>::new()));
    let (o2, a2) = (order.clone(), acked.clone());
    let errors = Arc::new(Mutex::new(0u64));
    let e2 = errors.clone();
    let poller = tokio::spawn(async move {
        let mut pending: HashMap<u16, (usize, u64)> = HashMap::new();
        loop {
            match el.poll().await {
                Ok(Event::Outgoing(Outgoing::Publish(pkid))) => {
                    if let Some(m) = o2.lock().unwrap().pop_front() {
                        // a resend after reconnect reuses the id: keep the first mapping
                        pending.entry(pkid).or_insert(m);
                    }
                }
                Ok(Event::Incoming(Packet::PubAck(a))) => {
                    if let Some(m) = pending.remove(&a.pkid) {
                        a2.lock().unwrap().push(m);
                    }
                }
                Ok(_) => {}
                Err(_) => {
                    *e2.lock().unwrap() += 1;
                    tokio::time::sleep(Duration::from_millis(200)).await;
                }
            }
        }
    });
    let start = Instant::now();
    let base_ms = sensors_ingest::ts::Ts::now().unix_millis() - 1000 * (seconds as i64 + 5);
    let step_ms = (devices as u64 * 1000 / rate).max(1) as i64;
    println!("base_ms={base_ms} step_ms={step_ms}");
    let mut seq = vec![0u64; devices];
    let mut tick = tokio::time::interval(Duration::from_millis(10));
    let per_tick = (rate / 100).max(1) as usize;
    let total = rate * seconds;
    let mut sent = 0u64;
    let mut x: u64 = 0x2545_F491_4F6C_DD1D;
    while sent < total {
        tick.tick().await;
        for _ in 0..per_tick {
            if sent >= total {
                break;
            }
            let d = (sent as usize) % devices;
            seq[d] += 1;
            let s = seq[d];
            let payload = if garbage == 1 {
                format!("garbage {sent} {{").into_bytes()
            } else {
                let mut v = serde_json::Map::new();
                for k in 0..channels {
                    x ^= x << 13;
                    x ^= x >> 7;
                    x ^= x << 17;
                    let noise = (x % 1000) as f64 / 1000.0 - 0.5;
                    let val = 10.0 + k as f64 + (s as f64 / 600.0).sin() + noise * 0.05;
                    v.insert(format!("c{k}"), serde_json::json!(val));
                }
                // device time: base + seq * (1000 / per-device rate) ms, unique per device
                serde_json::to_vec(&serde_json::json!({"t": base_ms + s as i64 * step_ms, "seq": s, "v": v})).unwrap()
            };
            order.lock().unwrap().push_back((d, s));
            c.publish(format!("{prefix}{}", d + offset), QoS::AtLeastOnce, false, payload).await.unwrap();
            sent += 1;
        }
    }
    let publish_s = start.elapsed().as_secs_f64();
    // wait for the remaining acknowledgements (up to 60 s)
    for _ in 0..600 {
        if acked.lock().unwrap().len() as u64 >= sent {
            break;
        }
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
    let n_acked = acked.lock().unwrap().len();
    if let Ok(path) = std::env::var("ACKED_FILE") {
        let text: String = acked.lock().unwrap().iter().map(|(d, s)| format!("{d} {s}\n")).collect();
        std::fs::write(path, text).unwrap();
    }
    println!(
        "sent={sent} acked={n_acked} publish_s={publish_s:.1} rate={:.0} errors={} done_s={:.1}",
        sent as f64 / publish_s,
        errors.lock().unwrap(),
        start.elapsed().as_secs_f64()
    );
    poller.abort();
}
