//! The MQTT side (plan S7c): one reader per broker connection. It polls the rumqttc event loop on its own task at all
//! times (PINGREQ and PUBACK only leave through `poll`), turns each PUBLISH into an `Envelope` and puts it on the
//! bounded queue. Spike S0e: with manual acks the broker stops at `max_inflight_messages` unacknowledged QoS 1
//! messages, so for QoS 1 the queue is the brake and the reader may wait on it; QoS 0 is not windowed by the broker, so
//! a QoS 0 message that finds the queue full is counted (`qos0_dropped`) and logged, never waited on.

use crate::config::ConnCfg;
use crate::service::{Envelope, Shared};
use rumqttc::MqttOptions;
use tokio::sync::mpsc;

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
pub async fn forward(_tx: &mpsc::Sender<Envelope>, _env: Envelope, _shared: &Shared) -> Forwarded {
    todo!("forward")
}

/// The session options of a connection: persistent session, manual acks, the packet limit, a request queue large
/// enough for every acknowledgement the queue can hold.
pub fn options(_conn: &ConnCfg, _password: Option<String>, _queue_capacity: usize) -> MqttOptions {
    todo!("options")
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
