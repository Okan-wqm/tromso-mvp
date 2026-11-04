//! S0e spike: rumqttc 0.25 manual acks against Mosquitto 2.0.20 with a 5000-message in-flight window.
//! Run by spikes/s0e_live.sh (it starts the broker). Prints PASS/FAIL lines; exits non-zero on the first FAIL.
#![allow(clippy::unwrap_used, clippy::expect_used, clippy::panic, clippy::indexing_slicing)]

use rumqttc::{AsyncClient, Event, EventLoop, MqttOptions, Packet, Publish, QoS};
use std::time::Duration;
use tokio::sync::mpsc;
use tokio::time::timeout;

const TOPIC: &str = "spike/s0e";
const TOTAL: usize = 6000;

fn opts(id: &str, host: &str) -> MqttOptions {
    let mut o = MqttOptions::new(id, host, 1883);
    o.set_clean_session(false)
        .set_manual_acks(true)
        .set_keep_alive(Duration::from_secs(10))
        .set_request_channel_capacity(20_000)
        .set_max_packet_size(300 * 1024, 300 * 1024);
    o
}

/// Polls the event loop on its own task (as the ingest must: PINGREQ and PUBACK leave only through poll) and
/// forwards publishes through an unbounded channel (spike only).
fn spawn_loop(mut el: EventLoop) -> (mpsc::UnboundedReceiver<Publish>, tokio::task::JoinHandle<()>) {
    let (tx, rx) = mpsc::unbounded_channel();
    let h = tokio::spawn(async move {
        loop {
            match el.poll().await {
                Ok(Event::Incoming(Packet::Publish(p))) => {
                    if tx.send(p).is_err() {
                        return;
                    }
                }
                Ok(Event::Incoming(Packet::ConnAck(c))) => println!("  connack session_present={}", c.session_present),
                Ok(_) => {}
                Err(e) => {
                    println!("  eventloop error: {e}");
                    tokio::time::sleep(Duration::from_millis(200)).await;
                }
            }
        }
    });
    (rx, h)
}

async fn drain(rx: &mut mpsc::UnboundedReceiver<Publish>, quiet: Duration) -> Vec<Publish> {
    let mut v = Vec::new();
    while let Ok(Some(p)) = timeout(quiet, rx.recv()).await {
        v.push(p);
    }
    v
}

fn idx(p: &Publish) -> usize {
    std::str::from_utf8(&p.payload).unwrap().parse().unwrap()
}

fn check(ok: bool, what: &str) {
    if ok {
        println!("PASS: {what}");
    } else {
        println!("FAIL: {what}");
        std::process::exit(1);
    }
}

#[tokio::main]
async fn main() {
    let host = std::env::var("BROKER").unwrap_or_else(|_| "s0e-broker".into());
    // session + subscription
    let (sub, el) = AsyncClient::new(opts("s0e-sub", &host), 20_000);
    let (mut rx, h) = spawn_loop(el);
    sub.subscribe(TOPIC, QoS::AtLeastOnce).await.unwrap();
    tokio::time::sleep(Duration::from_millis(500)).await;

    // publisher, QoS 1
    let mut po = MqttOptions::new("s0e-pub", &host, 1883);
    po.set_inflight(200);
    let (publ, mut pel) = AsyncClient::new(po, 10_000);
    let ph = tokio::spawn(async move {
        loop {
            if pel.poll().await.is_err() {
                tokio::time::sleep(Duration::from_millis(100)).await;
            }
        }
    });
    for i in 0..TOTAL {
        publ.publish(TOPIC, QoS::AtLeastOnce, false, i.to_string()).await.unwrap();
    }

    // 1. without acks the broker stops at max_inflight_messages
    let first = drain(&mut rx, Duration::from_secs(3)).await;
    println!("  received without acking: {}", first.len());
    check(first.len() == 5000, "broker delivers exactly max_inflight_messages (5000) unacked QoS 1 messages, then stops");
    check(
        first.iter().enumerate().all(|(i, p)| idx(p) == i && p.qos == QoS::AtLeastOnce && !p.dup),
        "first delivery in publish order, QoS 1, DUP clear",
    );

    // 2. ack the first 2500 in order: the window moves by exactly that much
    for p in &first[..2500] {
        sub.ack(p).await.unwrap();
    }
    let second = drain(&mut rx, Duration::from_secs(3)).await;
    println!("  received after 2500 acks: {}", second.len());
    check(
        second.len() == 1000 && second.iter().enumerate().all(|(i, p)| idx(p) == 5000 + i),
        "acks free the window in order; the remaining 1000 arrive in order",
    );

    // 3. crash (TCP closed without DISCONNECT, nothing more acked) and reconnect with the same client id
    h.abort();
    drop(sub);
    drop(rx);
    tokio::time::sleep(Duration::from_secs(1)).await;
    let (sub2, el2) = AsyncClient::new(opts("s0e-sub", &host), 20_000);
    let (mut rx2, _h2) = spawn_loop(el2);
    let redo = drain(&mut rx2, Duration::from_secs(3)).await;
    let unacked: Vec<&Publish> = first[2500..].iter().chain(second.iter()).collect();
    println!("  redelivered after reconnect: {} of {} unacked", redo.len(), unacked.len());
    check(redo.len() == unacked.len(), "every unacked message is redelivered, none of the acked ones");
    check(redo.iter().zip(&unacked).all(|(r, u)| idx(r) == idx(u)), "redelivery keeps the original order");
    let dup = redo.iter().filter(|p| p.dup).count();
    println!("  DUP flag on redelivery: {dup} of {}", redo.len());
    let same_pkid = redo.iter().zip(&unacked).filter(|(r, u)| r.pkid == u.pkid).count();
    println!("  same packet id as the first delivery: {same_pkid} of {}", redo.len());

    // 4. ack all; then a stale PUBACK (already acked id) and an unknown one: the connection must survive
    for p in &redo {
        sub2.ack(p).await.unwrap();
    }
    sub2.ack(&first[0]).await.unwrap();
    let mut ghost = first[0].clone();
    ghost.pkid = 65_000;
    sub2.ack(&ghost).await.unwrap();
    tokio::time::sleep(Duration::from_millis(500)).await;
    publ.publish(TOPIC, QoS::AtLeastOnce, false, "7777").await.unwrap();
    let after = drain(&mut rx2, Duration::from_secs(3)).await;
    check(
        after.len() == 1 && idx(&after[0]) == 7777 && !after[0].dup,
        "a duplicate or unknown PUBACK is ignored by the broker: the connection stays up and delivery continues",
    );
    sub2.ack(&after[0]).await.unwrap();

    // 5. a QoS 0 publish reaches a QoS 1 subscriber as QoS 0 (outside the in-flight window: no broker brake)
    publ.publish(TOPIC, QoS::AtMostOnce, false, "8888").await.unwrap();
    let q0 = drain(&mut rx2, Duration::from_secs(2)).await;
    check(
        q0.len() == 1 && q0[0].qos == QoS::AtMostOnce,
        "QoS 0 publish is delivered at QoS 0 (not windowed, cannot be redelivered)",
    );
    ph.abort();
    println!("DONE");
}
