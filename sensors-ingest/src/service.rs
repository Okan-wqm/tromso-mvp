//! The writer loop (plan S7b/S7c): takes envelopes from the bounded queue the MQTT readers fill, cuts batches (time or
//! size), runs the pipeline, commits one transaction per batch and only then acknowledges the batch's messages, in
//! order. It owns the single-writer lock, reloads the configuration on NOTIFY or a 30 s epoch poll, writes the status
//! heartbeat, isolates a message that makes a batch fail with a data error, and on any database failure acknowledges
//! nothing, bumps the generation (queued envelopes of the old generation are dropped unacknowledged) and asks the
//! supervisor to restart the MQTT sessions once the database is back, so the broker redelivers in order.

use crate::config::Config;
use crate::pipeline::Msg;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicI64, AtomicU64, Ordering};
use std::time::Duration;
use tokio::sync::{mpsc, watch};

/// Acknowledges one message to its broker. Called only after the message's batch is committed.
pub trait Acker: Send {
    fn ack(self: Box<Self>);
}

/// A message as the reader received it.
pub struct Envelope {
    /// The reader generation it came from; an envelope of an older generation is dropped unacknowledged.
    pub generation: u64,
    /// QoS 0 messages have no acknowledgement and are never redelivered.
    pub qos0: bool,
    pub msg: Msg,
    pub ack: Option<Box<dyn Acker>>,
}

/// What the writer tells the supervisor.
#[derive(Debug, Clone)]
pub enum Event {
    /// Waiting for another ingest to release the lock.
    Standby,
    /// Lock held, configuration and states loaded: readers of `generation` may run on this configuration.
    Ready { generation: u64, config: Arc<Config> },
    /// The configuration changed while running (same generation).
    ConfigChanged(Arc<Config>),
    /// The database failed: nothing of the current batch was acknowledged; restart the MQTT sessions when Ready.
    RedeliverRequired,
}

#[derive(Debug, Clone)]
pub struct Settings {
    pub conninfo: String,
    pub password: Option<String>,
    /// `SET ROLE` after sign-in (tests); production signs in as the role itself.
    pub role: Option<String>,
    pub batch_ms: u64,
    pub batch_max: usize,
    pub heartbeat: Duration,
    pub config_poll: Duration,
    pub version: String,
    pub dead_per_hour: usize,
}

impl Settings {
    pub fn new(conninfo: &str) -> Self {
        Settings {
            conninfo: conninfo.to_string(),
            password: None,
            role: None,
            batch_ms: 250,
            batch_max: 5000,
            heartbeat: Duration::from_secs(10),
            config_poll: Duration::from_secs(30),
            version: env!("CARGO_PKG_VERSION").to_string(),
            dead_per_hour: crate::pipeline::DEAD_PER_HOUR,
        }
    }
}

/// Shared with the readers and the health endpoint.
#[derive(Default)]
pub struct Shared {
    pub generation: AtomicU64,
    pub ready: AtomicBool,
    pub stopping: AtomicBool,
    /// Unix seconds of the last successful database write (commit or heartbeat), 0 never.
    pub last_db_ok: AtomicI64,
    pub commits: AtomicU64,
    pub acked: AtomicU64,
    pub qos0_dropped: AtomicU64,
    pub discarded: AtomicU64,
    pub poison: AtomicU64,
    pub queue_depth: AtomicI64,
    /// Connections the readers report connected, by connection id.
    pub connected: std::sync::Mutex<std::collections::HashMap<uuid::Uuid, bool>>,
}

impl Shared {
    pub fn current_generation(&self) -> u64 {
        self.generation.load(Ordering::SeqCst)
    }
}

/// Runs until `shutdown` turns true; then drains the queue (commit, then acknowledge), writes the status as
/// disconnected and returns.
pub async fn run(
    _settings: Settings,
    _shared: Arc<Shared>,
    _rx: mpsc::Receiver<Envelope>,
    _events: mpsc::UnboundedSender<Event>,
    _shutdown: watch::Receiver<bool>,
) {
    todo!("writer loop")
}
