//! The MQTT side (plan S7c): one reader per broker connection. It polls the rumqttc event loop on its own task at all
//! times (PINGREQ and PUBACK only leave through `poll`), turns each PUBLISH into an `Envelope` and puts it on the
//! bounded queue. Spike S0e: with manual acks the broker stops at `max_inflight_messages` unacknowledged QoS 1
//! messages, so for QoS 1 the queue is the brake and the reader may wait on it; QoS 0 is not windowed by the broker, so
//! a QoS 0 message that finds the queue full is counted (`qos0_dropped`) and logged, never waited on.
//!
//! Subscriptions and the clean stop go through the client (`Control`), never by cancelling a `poll` in flight.

use crate::config::ConnCfg;
use crate::pipeline::Msg;
use crate::service::{Acker, Envelope, Shared};
use chrono::Utc;
use rumqttc::{
    AsyncClient, Event, EventLoop, MqttOptions, Outgoing, Packet, Publish, QoS, TlsConfiguration, Transport,
};
use std::collections::BTreeSet;
use std::sync::atomic::Ordering;
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tokio::sync::mpsc;
use tokio::sync::mpsc::error::TrySendError;
use uuid::Uuid;

/// The largest MQTT packet accepted (above the broker's `max_packet_size`, so the client never refuses what the broker
/// sends and never loops on a redelivered large message).
pub const MAX_PACKET: usize = 300 * 1024;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Forwarded {
    Queued,
    /// QoS 0 and the queue was full: counted and dropped.
    DroppedQos0,
    /// The service is stopping: not queued and not acknowledged (QoS 1 is redelivered by the broker).
    Stopping,
    /// The writer is gone.
    Closed,
}

/// Puts one envelope on the queue following the rules above.
pub async fn forward(tx: &mpsc::Sender<Envelope>, env: Envelope, shared: &Shared) -> Forwarded {
    if shared.stopping.load(Ordering::SeqCst) {
        return Forwarded::Stopping;
    }
    if env.qos0 {
        return match tx.try_send(env) {
            Ok(()) => Forwarded::Queued,
            Err(TrySendError::Full(_)) => {
                let n = shared.qos0_dropped.fetch_add(1, Ordering::SeqCst) + 1;
                if n.is_power_of_two() {
                    tracing::warn!(dropped_total = n, "queue full: QoS 0 message dropped (QoS 0 has no redelivery)");
                }
                Forwarded::DroppedQos0
            }
            Err(TrySendError::Closed(_)) => Forwarded::Closed,
        };
    }
    match tx.send(env).await {
        Ok(()) => Forwarded::Queued,
        Err(_) => Forwarded::Closed,
    }
}

/// The session options of a connection: persistent session, manual acks, the packet limit, a request queue large
/// enough for every acknowledgement the queue can hold.
pub fn options(conn: &ConnCfg, password: Option<String>, queue_capacity: usize) -> MqttOptions {
    let mut o = MqttOptions::new(conn.client_id.clone(), conn.host.clone(), conn.port);
    o.set_clean_session(false)
        .set_manual_acks(true)
        .set_keep_alive(Duration::from_secs(u64::from(conn.keepalive_s)))
        .set_max_packet_size(MAX_PACKET, MAX_PACKET)
        .set_request_channel_capacity(queue_capacity.saturating_mul(2).max(20_000));
    if let Some(p) = password {
        o.set_credentials(conn.username.clone(), p);
    }
    o
}

/// Acknowledges through the session the message came on. If that session is gone the broker redelivers the message
/// to the next one (written again: idempotent rows, a late row for a suppressed sample).
struct MqttAck {
    client: AsyncClient,
    publish: Publish,
}

impl Acker for MqttAck {
    fn ack(self: Box<Self>) {
        if let Err(e) = self.client.try_ack(&self.publish) {
            tracing::warn!(error = %e, pkid = self.publish.pkid, "acknowledgement not sent: the broker will redeliver");
        }
    }
}

/// Handle of a running reader.
pub struct Reader {
    pub connection_id: Uuid,
    pub session_key: (String, u16, bool, String, String, String, u16),
    client: AsyncClient,
    topics: Arc<Mutex<BTreeSet<String>>>,
    task: tokio::task::JoinHandle<()>,
}

impl Reader {
    /// Subscribes to new topics and unsubscribes removed ones on the live session.
    pub fn update_topics(&self, wanted: &[String]) {
        let wanted: BTreeSet<String> = wanted.iter().cloned().collect();
        let mut cur = match self.topics.lock() {
            Ok(g) => g,
            Err(p) => p.into_inner(),
        };
        for t in wanted.difference(&cur) {
            if let Err(e) = self.client.try_subscribe(t.clone(), QoS::AtLeastOnce) {
                tracing::error!(error = %e, topic = %t, "subscribe not sent");
            }
        }
        for t in cur.difference(&wanted) {
            if let Err(e) = self.client.try_unsubscribe(t.clone()) {
                tracing::error!(error = %e, topic = %t, "unsubscribe not sent");
            }
        }
        *cur = wanted;
    }

    /// Clean stop: a DISCONNECT queued after every acknowledgement already queued (the broker keeps the session),
    /// then waits for the event loop to send it.
    pub async fn disconnect(self, timeout: Duration) {
        let _ = self.client.try_disconnect();
        let mut task = self.task;
        if tokio::time::timeout(timeout, &mut task).await.is_err() {
            tracing::warn!(connection = %self.connection_id, "disconnect not confirmed in time; closing");
            task.abort();
        }
    }

    /// Hard stop (database failure): the TCP connection closes without DISCONNECT; every unacknowledged message is
    /// redelivered to the next session.
    pub fn abort(self) {
        self.task.abort();
    }
}

fn tls(ca_file: &str) -> Result<Transport, String> {
    let ca = std::fs::read(ca_file).map_err(|e| format!("CA file {ca_file}: {e}"))?;
    Ok(Transport::Tls(TlsConfiguration::Simple { ca, alpn: None, client_auth: None }))
}

/// Starts the reader of one connection for `generation`.
pub fn spawn(
    conn: &ConnCfg,
    password: Option<String>,
    ca_file: &str,
    generation: u64,
    tx: mpsc::Sender<Envelope>,
    shared: Arc<Shared>,
    queue_capacity: usize,
) -> Result<Reader, String> {
    let mut opts = options(conn, password, queue_capacity);
    if conn.use_tls {
        opts.set_transport(tls(ca_file)?);
    }
    let (client, el) = AsyncClient::new(opts, queue_capacity.saturating_mul(2).max(20_000));
    let topics = Arc::new(Mutex::new(conn.topics().into_iter().collect::<BTreeSet<_>>()));
    let task = tokio::spawn(read_loop(conn.connection_id, el, client.clone(), topics.clone(), generation, tx, shared));
    Ok(Reader { connection_id: conn.connection_id, session_key: conn.session_key(), client, topics, task })
}

fn set_connected(shared: &Shared, id: Uuid, up: bool) {
    let mut m = match shared.connected.lock() {
        Ok(g) => g,
        Err(p) => p.into_inner(),
    };
    m.insert(id, up);
}

async fn read_loop(
    id: Uuid,
    mut el: EventLoop,
    client: AsyncClient,
    topics: Arc<Mutex<BTreeSet<String>>>,
    generation: u64,
    tx: mpsc::Sender<Envelope>,
    shared: Arc<Shared>,
) {
    let mut backoff = Duration::from_millis(500);
    loop {
        match el.poll().await {
            Ok(Event::Incoming(Packet::ConnAck(ack))) => {
                backoff = Duration::from_millis(500);
                set_connected(&shared, id, true);
                let list: Vec<String> = match topics.lock() {
                    Ok(g) => g.iter().cloned().collect(),
                    Err(p) => p.into_inner().iter().cloned().collect(),
                };
                tracing::info!(connection = %id, session_present = ack.session_present, topics = list.len(), "connected to the broker");
                if !list.is_empty() {
                    let subs = list.into_iter().map(|t| rumqttc::SubscribeFilter::new(t, QoS::AtLeastOnce));
                    if let Err(e) = client.try_subscribe_many(subs) {
                        tracing::error!(connection = %id, error = %e, "subscribe not sent");
                    }
                }
            }
            Ok(Event::Incoming(Packet::Publish(p))) => {
                if shared.current_generation() != generation {
                    continue; // an old session: not queued, not acknowledged (redelivered to the new one)
                }
                let qos0 = p.qos == QoS::AtMostOnce;
                let msg = Msg {
                    connection_id: id,
                    topic: p.topic.clone(),
                    payload: p.payload.to_vec(),
                    received_at: Utc::now(),
                };
                let ack: Option<Box<dyn Acker>> =
                    if qos0 { None } else { Some(Box::new(MqttAck { client: client.clone(), publish: p })) };
                if forward(&tx, Envelope { generation, qos0, msg, ack }, &shared).await == Forwarded::Closed {
                    tracing::info!(connection = %id, "queue closed: reader ends");
                    return;
                }
            }
            Ok(Event::Outgoing(Outgoing::Disconnect)) => {
                set_connected(&shared, id, false);
                tracing::info!(connection = %id, "disconnected from the broker (session kept)");
                return;
            }
            Ok(_) => {}
            Err(e) => {
                set_connected(&shared, id, false);
                tracing::warn!(connection = %id, error = %e, retry_in_ms = backoff.as_millis() as u64, "broker connection failed");
                tokio::time::sleep(backoff).await;
                backoff = (backoff * 2).min(Duration::from_secs(30));
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::pipeline::Msg;
    use crate::service::Acker;
    use chrono::Utc;
    use std::sync::Arc;
    use std::sync::atomic::{AtomicU64, Ordering};
    use std::time::Duration;
    use uuid::Uuid;

    struct Count(Arc<AtomicU64>);
    impl Acker for Count {
        fn ack(self: Box<Self>) {
            self.0.fetch_add(1, Ordering::SeqCst);
        }
    }

    fn env(qos0: bool, acks: &Arc<AtomicU64>) -> Envelope {
        Envelope {
            generation: 0,
            qos0,
            msg: Msg {
                connection_id: Uuid::nil(),
                topic: "t".into(),
                payload: b"{}".to_vec(),
                received_at: Utc::now(),
            },
            ack: if qos0 { None } else { Some(Box::new(Count(acks.clone()))) },
        }
    }

    #[tokio::test]
    async fn qos0_finding_the_queue_full_is_counted_and_dropped_never_waited_on() {
        let shared = Shared::default();
        let acks = Arc::new(AtomicU64::new(0));
        let (tx, mut rx) = mpsc::channel(2);
        assert_eq!(forward(&tx, env(true, &acks), &shared).await, Forwarded::Queued);
        assert_eq!(forward(&tx, env(false, &acks), &shared).await, Forwarded::Queued);
        let r = tokio::time::timeout(Duration::from_millis(200), forward(&tx, env(true, &acks), &shared)).await;
        assert_eq!(r, Ok(Forwarded::DroppedQos0));
        assert_eq!(shared.qos0_dropped.load(Ordering::SeqCst), 1);
        assert!(rx.recv().await.is_some());
    }

    #[tokio::test]
    async fn qos1_waits_for_room_and_is_never_dropped() {
        let shared = Arc::new(Shared::default());
        let acks = Arc::new(AtomicU64::new(0));
        let (tx, mut rx) = mpsc::channel(1);
        assert_eq!(forward(&tx, env(false, &acks), &shared).await, Forwarded::Queued);
        let (tx2, sh2, acks2) = (tx.clone(), shared.clone(), acks.clone());
        let waiting = tokio::spawn(async move { forward(&tx2, env(false, &acks2), &sh2).await });
        tokio::time::sleep(Duration::from_millis(100)).await;
        assert!(!waiting.is_finished(), "a QoS 1 message waits for room");
        assert!(rx.recv().await.is_some());
        assert_eq!(waiting.await.unwrap(), Forwarded::Queued);
        assert_eq!(shared.qos0_dropped.load(Ordering::SeqCst), 0);
    }

    #[tokio::test]
    async fn while_stopping_nothing_is_queued_or_acknowledged() {
        let shared = Shared::default();
        shared.stopping.store(true, Ordering::SeqCst);
        let acks = Arc::new(AtomicU64::new(0));
        let (tx, mut rx) = mpsc::channel(4);
        assert_eq!(forward(&tx, env(false, &acks), &shared).await, Forwarded::Stopping);
        assert!(rx.try_recv().is_err());
        assert_eq!(acks.load(Ordering::SeqCst), 0);
    }

    #[tokio::test]
    async fn a_closed_queue_is_reported() {
        let shared = Shared::default();
        let acks = Arc::new(AtomicU64::new(0));
        let (tx, rx) = mpsc::channel(4);
        drop(rx);
        assert_eq!(forward(&tx, env(false, &acks), &shared).await, Forwarded::Closed);
    }

    #[test]
    fn session_options_are_persistent_with_manual_acks() {
        let conn = ConnCfg {
            connection_id: Uuid::nil(),
            host: "broker".into(),
            port: 1883,
            use_tls: false,
            username: "ingest".into(),
            secret_file: "x".into(),
            client_id: "sensors-ingest".into(),
            keepalive_s: 30,
            devices: vec![],
        };
        let o = options(&conn, Some("pw".into()), 10_000);
        assert!(!o.clean_session());
        assert!(o.manual_acks());
        assert_eq!(o.keep_alive(), Duration::from_secs(30));
        assert_eq!(o.client_id(), "sensors-ingest");
        assert_eq!(o.broker_address(), ("broker".to_string(), 1883));
        assert_eq!(o.max_packet_size(), MAX_PACKET);
        assert!(o.request_channel_capacity() >= 20_000);
        assert_eq!(o.credentials().map(|l| (l.username, l.password)), Some(("ingest".to_string(), "pw".to_string())));
    }
}
