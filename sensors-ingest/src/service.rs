//! The writer loop (plan S7b/S7c): takes envelopes from the bounded queue the MQTT readers fill, cuts batches (time or
//! size), runs the pipeline, commits one transaction per batch and only then acknowledges the batch's messages, in
//! order. It owns the single-writer lock, reloads the configuration on NOTIFY or a 30 s epoch poll, writes the status
//! heartbeat, isolates a message that makes a batch fail with a data error, and on any database failure acknowledges
//! nothing, bumps the generation (queued envelopes of the old generation are dropped unacknowledged) and asks the
//! supervisor to restart the MQTT sessions once the database is back, so the broker redelivers in order.

use crate::config::{self, Config};
use crate::db::{self, Status};
use crate::pipeline::{self, DeadLimiter, Msg, Output};
use crate::reduce::State;
use futures_util::StreamExt;
use std::collections::HashMap;
use std::str::FromStr;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicI64, AtomicU64, Ordering};
use std::time::Duration;
use tokio::sync::{mpsc, watch};
use tokio_postgres::{AsyncMessage, Client};

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
            batch_max: 20_000,
            heartbeat: Duration::from_secs(10),
            config_poll: Duration::from_secs(30),
            version: env!("CARGO_PKG_VERSION").to_string(),
            dead_per_hour: crate::pipeline::DEAD_PER_HOUR,
        }
    }
}

/// Commit durations kept for the percentiles.
pub const COMMIT_SAMPLES: usize = 10_000;

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
    /// Durations of the most recent commits (milliseconds, at most COMMIT_SAMPLES), for /healthz percentiles.
    pub commit_ms: std::sync::Mutex<std::collections::VecDeque<u32>>,
    /// Connections the readers report connected, by connection id.
    pub connected: std::sync::Mutex<std::collections::HashMap<uuid::Uuid, bool>>,
}

impl Shared {
    pub fn record_commit(&self, d: Duration) {
        let ms = u32::try_from(d.as_millis()).unwrap_or(u32::MAX);
        let mut q = match self.commit_ms.lock() {
            Ok(g) => g,
            Err(p) => p.into_inner(),
        };
        if q.len() >= COMMIT_SAMPLES {
            q.pop_front();
        }
        q.push_back(ms);
    }

    /// (p50, p99, max, count) of the recorded commit durations in milliseconds.
    pub fn commit_percentiles(&self) -> (u32, u32, u32, usize) {
        let mut v: Vec<u32> = match self.commit_ms.lock() {
            Ok(g) => g.iter().copied().collect(),
            Err(p) => p.into_inner().iter().copied().collect(),
        };
        if v.is_empty() {
            return (0, 0, 0, 0);
        }
        v.sort_unstable();
        let at = |q: usize| v.get((v.len() * q).div_ceil(100).saturating_sub(1)).copied().unwrap_or(0);
        (at(50), at(99), v.last().copied().unwrap_or(0), v.len())
    }

    pub fn current_generation(&self) -> u64 {
        self.generation.load(Ordering::SeqCst)
    }
}

/// Runs until `shutdown` turns true; then drains the queue (commit, then acknowledge), writes the status as
/// disconnected and returns.
pub async fn run(
    settings: Settings,
    shared: Arc<Shared>,
    mut rx: mpsc::Receiver<Envelope>,
    events: mpsc::UnboundedSender<Event>,
    mut shutdown: watch::Receiver<bool>,
) {
    let mut w = Writer {
        limiter: DeadLimiter::new(settings.dead_per_hour),
        settings,
        shared,
        events,
        committed: HashMap::new(),
        cfg: None,
        client: None,
        listener: None,
        listen_client: None,
        counter_base: None,
        notices: None,
    };
    loop {
        if *shutdown.borrow() {
            return;
        }
        if !w.open(&mut shutdown).await {
            return;
        }
        match w.serve(&mut rx, &mut shutdown).await {
            Served::Stopped => return,
            Served::DbFailed => w.fail(),
        }
    }
}

enum Served {
    Stopped,
    DbFailed,
}

/// A batch: the messages and, in the same order, their acknowledgements.
#[derive(Default)]
struct Batch {
    msgs: Vec<Msg>,
    acks: Vec<Option<Box<dyn Acker>>>,
}

struct Writer {
    settings: Settings,
    shared: Arc<Shared>,
    events: mpsc::UnboundedSender<Event>,
    limiter: DeadLimiter,
    committed: HashMap<i32, State>,
    cfg: Option<Arc<Config>>,
    client: Option<Client>,
    listener: Option<tokio::task::JoinHandle<()>>,
    listen_client: Option<Client>,
    /// The status counters as the previous run left them (read once, at the first open).
    counter_base: Option<(i64, i64)>,
    notices: Option<mpsc::UnboundedReceiver<i64>>,
}

fn now_s() -> i64 {
    chrono::Utc::now().timestamp()
}

/// Sleeps, or returns false early when shutdown is asked.
async fn pause(d: Duration, shutdown: &mut watch::Receiver<bool>) -> bool {
    tokio::select! {
        _ = tokio::time::sleep(d) => true,
        r = shutdown.changed() => r.is_ok() && !*shutdown.borrow(),
    }
}

impl Writer {
    fn emit(&self, e: Event) {
        // the supervisor may be gone during shutdown; nothing else listens
        let _ = self.events.send(e);
    }

    /// Connects, takes the lock (standing by while another ingest holds it), loads the configuration and the states.
    /// Returns false when shutdown is asked meanwhile.
    async fn open(&mut self, shutdown: &mut watch::Receiver<bool>) -> bool {
        let mut backoff = Duration::from_millis(500);
        let mut standby_said = false;
        loop {
            if *shutdown.borrow() {
                return false;
            }
            match self.try_open(&mut standby_said).await {
                Ok(true) => return true,
                Ok(false) => {
                    if !pause(Duration::from_secs(2), shutdown).await {
                        return false;
                    }
                }
                Err(e) => {
                    tracing::error!(error = %e, retry_in_ms = backoff.as_millis() as u64, "database not usable");
                    self.client = None;
                    if !pause(backoff, shutdown).await {
                        return false;
                    }
                    backoff = (backoff * 2).min(Duration::from_secs(30));
                }
            }
        }
    }

    /// Ok(false): another ingest holds the lock.
    async fn try_open(&mut self, standby_said: &mut bool) -> Result<bool, String> {
        let s = &self.settings;
        if self.client.as_ref().is_none_or(|c| c.is_closed()) {
            let c = db::connect(&s.conninfo, s.password.as_deref(), s.role.as_deref(), Duration::from_secs(10))
                .await
                .map_err(|e| format!("connect: {e}"))?;
            self.client = Some(c);
        }
        let client = self.client.as_mut().ok_or("no client")?;
        if !db::try_lock(client).await.map_err(|e| format!("lock: {e}"))? {
            if !*standby_said {
                tracing::info!("another ingest holds the writer lock: standing by");
                *standby_said = true;
                let _ = self.events.send(Event::Standby);
            }
            return Ok(false);
        }
        let cfg = config::load(client).await.map_err(|e| format!("configuration: {e}"))?;
        for r in &cfg.rejected {
            tracing::error!(row = %r, "configuration row left out");
        }
        self.committed = db::load_states(client, &cfg.channel_nos()).await.map_err(|e| format!("states: {e}"))?;
        if self.counter_base.is_none() {
            self.counter_base = Some(db::status_counters(client).await.map_err(|e| format!("status counters: {e}"))?);
        }
        let cfg = Arc::new(cfg);
        self.cfg = Some(cfg.clone());
        self.start_listener().await;
        self.shared.ready.store(true, Ordering::SeqCst);
        self.shared.last_db_ok.store(now_s(), Ordering::SeqCst);
        let generation = self.shared.current_generation();
        tracing::info!(
            generation,
            epoch = cfg.contract.config_epoch,
            channels = cfg.channel_nos().len(),
            "writer ready"
        );
        self.emit(Event::Ready { generation, config: cfg });
        Ok(true)
    }

    /// LISTEN on its own connection; a lost listener only means the 30 s poll finds the change.
    async fn start_listener(&mut self) {
        if let Some(h) = self.listener.take() {
            h.abort();
        }
        self.listen_client = None;
        let s = &self.settings;
        let mut cfg = match tokio_postgres::Config::from_str(&s.conninfo) {
            Ok(c) => c,
            Err(e) => {
                tracing::warn!(error = %e, "listener not started");
                return;
            }
        };
        if let Some(p) = &s.password {
            cfg.password(p);
        }
        cfg.connect_timeout(Duration::from_secs(10)).application_name("sensors-ingest-listen");
        let (client, mut conn) = match cfg.connect(tokio_postgres::NoTls).await {
            Ok(v) => v,
            Err(e) => {
                tracing::warn!(error = %e, "listener not connected; the epoch poll covers it");
                return;
            }
        };
        let (tx, rx) = mpsc::unbounded_channel();
        self.listener = Some(tokio::spawn(async move {
            let mut stream = futures_util::stream::poll_fn(move |cx| conn.poll_message(cx));
            while let Some(m) = stream.next().await {
                match m {
                    Ok(AsyncMessage::Notification(n)) => {
                        if tx.send(n.payload().parse::<i64>().unwrap_or(-1)).is_err() {
                            return;
                        }
                    }
                    Ok(_) => {}
                    Err(e) => {
                        tracing::warn!(error = %e, "listener connection lost; the epoch poll covers it");
                        return;
                    }
                }
            }
        }));
        let mut setup = String::new();
        if let Some(r) = &s.role {
            setup.push_str(&format!("SET ROLE \"{}\"; ", r.replace('"', "\"\"")));
        }
        setup.push_str("LISTEN sensors_config");
        if let Err(e) = client.batch_execute(&setup).await {
            tracing::warn!(error = %e, "LISTEN failed; the epoch poll covers it");
            return;
        }
        self.listen_client = Some(client);
        self.notices = Some(rx);
    }

    fn status(&self, connected_override: Option<bool>) -> Vec<Status> {
        let Some(cfg) = &self.cfg else { return Vec::new() };
        let map = match self.shared.connected.lock() {
            Ok(g) => g.clone(),
            Err(p) => p.into_inner().clone(),
        };
        let depth = i32::try_from(self.shared.queue_depth.load(Ordering::SeqCst)).unwrap_or(i32::MAX);
        let base = self.counter_base.unwrap_or((0, 0));
        cfg.connections
            .keys()
            .map(|id| Status {
                connection_id: *id,
                connected: connected_override.unwrap_or_else(|| map.get(id).copied().unwrap_or(false)),
                queue_depth: depth.max(0),
                version: self.settings.version.clone(),
                qos0_dropped: base
                    .0
                    .saturating_add(i64::try_from(self.shared.qos0_dropped.load(Ordering::SeqCst)).unwrap_or(i64::MAX)),
                poison_total: base
                    .1
                    .saturating_add(i64::try_from(self.shared.poison.load(Ordering::SeqCst)).unwrap_or(i64::MAX)),
            })
            .collect()
    }

    async fn serve(&mut self, rx: &mut mpsc::Receiver<Envelope>, shutdown: &mut watch::Receiver<bool>) -> Served {
        let mut batch = Batch::default();
        let mut deadline: Option<tokio::time::Instant> = None;
        let mut heartbeat = tokio::time::interval(self.settings.heartbeat);
        let mut poll = tokio::time::interval(self.settings.config_poll);
        poll.tick().await;
        let mut notices = self.notices.take();
        loop {
            let generation = self.shared.current_generation();
            self.shared.queue_depth.store(i64::try_from(rx.len()).unwrap_or(i64::MAX), Ordering::SeqCst);
            let sleep_until = deadline.unwrap_or_else(|| tokio::time::Instant::now() + Duration::from_secs(3600));
            tokio::select! {
                biased;
                r = shutdown.changed() => {
                    if r.is_err() || *shutdown.borrow() {
                        return self.stop(rx, batch).await;
                    }
                }
                env = rx.recv() => match env {
                    Some(e) if e.generation == generation => {
                        batch.msgs.push(e.msg);
                        batch.acks.push(e.ack);
                        if deadline.is_none() {
                            deadline = Some(tokio::time::Instant::now() + Duration::from_millis(self.settings.batch_ms));
                        }
                        if batch.msgs.len() >= self.settings.batch_max {
                            deadline = None;
                            if !self.flush(std::mem::take(&mut batch)).await { return Served::DbFailed; }
                        }
                    }
                    Some(_) => { self.shared.discarded.fetch_add(1, Ordering::SeqCst); }
                    None => {
                        // every reader is gone: commit what is here and wait for the shutdown
                        deadline = None;
                        if !self.flush(std::mem::take(&mut batch)).await { return Served::DbFailed; }
                        if shutdown.changed().await.is_err() || *shutdown.borrow() {
                            return self.stop(rx, Batch::default()).await;
                        }
                    }
                },
                _ = tokio::time::sleep_until(sleep_until), if deadline.is_some() => {
                    deadline = None;
                    if !self.flush(std::mem::take(&mut batch)).await { return Served::DbFailed; }
                }
                n = async { match notices.as_mut() { Some(r) => r.recv().await, None => std::future::pending().await } } => {
                    match n {
                        Some(epoch) => {
                            let known = self.cfg.as_ref().map(|c| c.contract.config_epoch);
                            if Some(epoch) != known {
                                deadline = None;
                                if !self.flush(std::mem::take(&mut batch)).await { return Served::DbFailed; }
                                if !self.reload().await { return Served::DbFailed; }
                            }
                        }
                        None => notices = None,
                    }
                }
                _ = poll.tick() => {
                    let Some(client) = self.client.as_ref() else { return Served::DbFailed };
                    match client.query_one("SELECT config_epoch FROM sensors_contract WHERE id = 1", &[]).await {
                        Ok(row) => {
                            let epoch: Option<i64> = row.try_get(0).ok();
                            if epoch != self.cfg.as_ref().map(|c| c.contract.config_epoch) {
                                deadline = None;
                                if !self.flush(std::mem::take(&mut batch)).await { return Served::DbFailed; }
                                if !self.reload().await { return Served::DbFailed; }
                            }
                        }
                        Err(e) => { tracing::error!(error = %e, "epoch poll failed"); return Served::DbFailed; }
                    }
                }
                _ = heartbeat.tick() => {
                    let st = self.status(None);
                    let Some(client) = self.client.as_ref() else { return Served::DbFailed };
                    match db::write_status(client, &st).await {
                        Ok(()) => self.shared.last_db_ok.store(now_s(), Ordering::SeqCst),
                        Err(e) => { tracing::error!(error = %e, "status heartbeat failed"); return Served::DbFailed; }
                    }
                    let dropped = self.shared.qos0_dropped.load(Ordering::SeqCst);
                    if dropped > 0 {
                        tracing::warn!(qos0_dropped_total = dropped, "QoS 0 messages were dropped on a full queue");
                    }
                }
            }
        }
    }

    /// Reloads the configuration; states of channels new to it are read from the table.
    async fn reload(&mut self) -> bool {
        let Some(client) = self.client.as_mut() else { return false };
        let cfg = match config::load(client).await {
            Ok(c) => c,
            Err(config::ConfigError::Db(e)) => {
                tracing::error!(error = %e, "configuration reload failed");
                return false;
            }
            Err(e) => {
                tracing::error!(error = %e, "configuration not usable: the previous one stays");
                return true;
            }
        };
        for r in &cfg.rejected {
            tracing::error!(row = %r, "configuration row left out");
        }
        let new: Vec<i32> = cfg.channel_nos().into_iter().filter(|c| !self.committed.contains_key(c)).collect();
        if !new.is_empty() {
            match db::load_states(client, &new).await {
                Ok(s) => self.committed.extend(s),
                Err(e) => {
                    tracing::error!(error = %e, "states of new channels not read");
                    return false;
                }
            }
        }
        let cfg = Arc::new(cfg);
        tracing::info!(epoch = cfg.contract.config_epoch, channels = cfg.channel_nos().len(), "configuration reloaded");
        self.cfg = Some(cfg.clone());
        self.emit(Event::ConfigChanged(cfg));
        true
    }

    fn applied(&mut self, out: Output, acks: Vec<Option<Box<dyn Acker>>>) {
        self.committed.extend(out.states);
        self.shared.commits.fetch_add(1, Ordering::SeqCst);
        self.shared.last_db_ok.store(now_s(), Ordering::SeqCst);
        #[cfg(feature = "failpoints")]
        failpoint_after_commit(self.shared.commits.load(Ordering::SeqCst));
        for a in acks.into_iter().flatten() {
            a.ack();
            self.shared.acked.fetch_add(1, Ordering::SeqCst);
        }
    }

    /// Commits a batch and then acknowledges it. False on a database failure (nothing acknowledged).
    async fn flush(&mut self, batch: Batch) -> bool {
        if batch.msgs.is_empty() {
            return true;
        }
        let started = std::time::Instant::now();
        let Some(cfg) = self.cfg.clone() else { return false };
        let out = pipeline::process(&cfg, &self.committed, &mut self.limiter, &batch.msgs);
        let status = self.status(None);
        let Some(client) = self.client.as_mut() else { return false };
        match db::write_batch(client, &out, &status).await {
            Ok(_) => {
                self.shared.record_commit(started.elapsed());
                self.applied(out, batch.acks);
                true
            }
            Err(e) if db::is_data_error(&e) => {
                tracing::warn!(error = %e, messages = batch.msgs.len(), "batch refused by a data rule: isolating the message");
                self.isolate(&cfg, batch).await
            }
            Err(e) => {
                tracing::error!(error = %e, messages = batch.msgs.len(), "batch not committed: nothing acknowledged");
                false
            }
        }
    }

    /// One message per transaction; a message the database refuses becomes a `bad_value` dead letter (its payload kept
    /// as evidence), is counted as poison and acknowledged, so it can never block the stream.
    async fn isolate(&mut self, cfg: &Arc<Config>, batch: Batch) -> bool {
        let status = self.status(None);
        for (msg, ack) in batch.msgs.into_iter().zip(batch.acks) {
            let one = std::slice::from_ref(&msg);
            let out = pipeline::process(cfg, &self.committed, &mut self.limiter, one);
            let Some(client) = self.client.as_mut() else { return false };
            match db::write_batch(client, &out, &status).await {
                Ok(_) => self.applied(out, vec![ack]),
                Err(e) if db::is_data_error(&e) => {
                    let poison = pipeline::poison(cfg, &msg);
                    match db::write_batch(client, &poison, &status).await {
                        Ok(_) => {
                            tracing::error!(error = %e, topic = %msg.topic, "message refused by the database: dead-lettered as bad_value")
                        }
                        Err(e2) if db::is_data_error(&e2) => tracing::error!(
                            error = %e, dead_letter_error = %e2, topic = %msg.topic,
                            sha256 = %pipeline::sha256_hex(&msg.payload),
                            "message refused by the database and its dead letter too: acknowledged so it cannot block the stream"
                        ),
                        Err(e2) => {
                            tracing::error!(error = %e2, "dead letter not committed: nothing acknowledged");
                            return false;
                        }
                    }
                    self.shared.poison.fetch_add(1, Ordering::SeqCst);
                    self.applied(Output::default(), vec![ack]);
                }
                Err(e) => {
                    tracing::error!(error = %e, "message not committed: nothing acknowledged");
                    return false;
                }
            }
        }
        true
    }

    /// Database failure: forget the session, the lock and the in-memory states (reloaded when the database is back),
    /// and make every queued envelope stale so none is acknowledged.
    fn fail(&mut self) {
        self.shared.ready.store(false, Ordering::SeqCst);
        let g = self.shared.generation.fetch_add(1, Ordering::SeqCst) + 1;
        tracing::error!(
            generation = g,
            "database failure: MQTT sessions restart after the database is back (broker redelivers)"
        );
        self.client = None;
        self.committed.clear();
        if let Some(h) = self.listener.take() {
            h.abort();
        }
        self.emit(Event::RedeliverRequired);
    }

    /// Shutdown: everything already queued is committed and then acknowledged; the status says disconnected.
    async fn stop(&mut self, rx: &mut mpsc::Receiver<Envelope>, mut batch: Batch) -> Served {
        let generation = self.shared.current_generation();
        while let Ok(e) = rx.try_recv() {
            if e.generation == generation {
                batch.msgs.push(e.msg);
                batch.acks.push(e.ack);
            }
        }
        let n = batch.msgs.len();
        if !self.flush(batch).await {
            tracing::error!(messages = n, "final batch not committed: not acknowledged (the broker redelivers)");
        }
        if let Some(client) = self.client.as_ref() {
            if let Err(e) = db::write_status(client, &self.status(Some(false))).await {
                tracing::warn!(error = %e, "final status not written");
            }
        }
        self.shared.ready.store(false, Ordering::SeqCst);
        if let Some(h) = self.listener.take() {
            h.abort();
        }
        tracing::info!(drained = n, "writer stopped");
        Served::Stopped
    }
}

/// Test builds only (`--features failpoints`, never the production image): `INGEST_FAILPOINT_ABORT_AFTER_COMMIT=N`
/// aborts the process right after the N-th COMMIT and before its acknowledgements, once per container (a marker file
/// stops the restarted process from aborting again). The end-to-end drill measures what the broker then redelivers.
#[cfg(feature = "failpoints")]
fn failpoint_after_commit(commits: u64) {
    let marker = std::path::Path::new("/tmp/ingest-failpoint-done");
    let at = std::env::var("INGEST_FAILPOINT_ABORT_AFTER_COMMIT").ok().and_then(|v| v.parse::<u64>().ok());
    if at == Some(commits) && !marker.exists() {
        let _ = std::fs::write(marker, b"done");
        tracing::error!(commits, "failpoint: aborting after COMMIT, before the acknowledgements");
        std::process::abort();
    }
}
