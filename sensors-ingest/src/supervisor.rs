//! Ties the writer, the MQTT readers and the HTTP listener together (plan S7c). Readers run only while the writer is
//! Ready, on its generation; a configuration change resubscribes live (or restarts a reader whose session settings
//! changed); a database failure stops every reader at once (no acknowledgement can follow) and restarts them when the
//! writer is Ready again, so the broker redelivers. Shutdown: readers stop queueing, the writer commits and
//! acknowledges what is queued, then each session sends DISCONNECT (the broker keeps it).

use crate::config::{Config, ConnCfg};
use crate::http::{self, AppState};
use crate::mqtt::{self, Reader};
use crate::service::{self, Event, Settings, Shared};
use std::collections::HashMap;
use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::atomic::Ordering;
use std::sync::{Arc, RwLock};
use std::time::Duration;
use tokio::sync::{mpsc, watch};
use uuid::Uuid;

#[derive(Debug, Clone)]
pub struct Options {
    pub settings: Settings,
    /// Where each connection's `secret_file` is read (docker secrets: /run/secrets).
    pub secrets_dir: PathBuf,
    /// CA bundle for connections with `use_tls`.
    pub ca_file: String,
    /// The queue between readers and writer; at least the broker's `max_inflight_messages` per connection.
    pub queue_capacity: usize,
    pub http_addr: Option<SocketAddr>,
}

struct Sup {
    opts: Options,
    shared: Arc<Shared>,
    tx: mpsc::Sender<Envelope>,
    readers: HashMap<Uuid, Reader>,
    generation: u64,
    config: Arc<RwLock<Option<Arc<Config>>>>,
}

use crate::service::Envelope;

/// The broker password of a connection: the first line of its secret file (blank `secret_file`: no credentials).
fn password(dir: &std::path::Path, conn: &ConnCfg) -> Result<Option<String>, String> {
    if conn.secret_file.is_empty() {
        return Ok(None);
    }
    let path = dir.join(&conn.secret_file);
    let text = std::fs::read_to_string(&path).map_err(|e| format!("secret {}: {e}", path.display()))?;
    Ok(Some(text.lines().next().unwrap_or("").to_string()))
}

impl Sup {
    fn set_config(&self, cfg: &Arc<Config>) {
        match self.config.write() {
            Ok(mut g) => *g = Some(cfg.clone()),
            Err(p) => *p.into_inner() = Some(cfg.clone()),
        }
    }

    fn start_reader(&mut self, conn: &ConnCfg) {
        let pw = match password(&self.opts.secrets_dir, conn) {
            Ok(p) => p,
            Err(e) => {
                tracing::error!(connection = %conn.connection_id, error = %e, "reader not started");
                return;
            }
        };
        match mqtt::spawn(
            conn,
            pw,
            &self.opts.ca_file,
            self.generation,
            self.tx.clone(),
            self.shared.clone(),
            self.opts.queue_capacity,
        ) {
            Ok(r) => {
                self.readers.insert(conn.connection_id, r);
            }
            Err(e) => tracing::error!(connection = %conn.connection_id, error = %e, "reader not started"),
        }
    }

    fn abort_all(&mut self) {
        for (_, r) in self.readers.drain() {
            r.abort();
        }
        if let Ok(mut m) = self.shared.connected.lock() {
            m.clear();
        }
    }

    /// Brings the readers in line with a configuration.
    fn apply(&mut self, cfg: &Arc<Config>) {
        self.set_config(cfg);
        let gone: Vec<Uuid> = self.readers.keys().filter(|id| !cfg.connections.contains_key(id)).copied().collect();
        for id in gone {
            if let Some(r) = self.readers.remove(&id) {
                tracing::info!(connection = %id, "connection left the configuration: reader stopped");
                r.abort();
            }
        }
        for conn in cfg.connections.values() {
            let restart = self.readers.get(&conn.connection_id).map(|r| r.session_key != conn.session_key());
            match restart {
                None => self.start_reader(conn),
                Some(true) => {
                    if let Some(r) = self.readers.remove(&conn.connection_id) {
                        tracing::info!(connection = %conn.connection_id, "session settings changed: reconnecting");
                        r.abort();
                    }
                    self.start_reader(conn);
                }
                Some(false) => {
                    if let Some(r) = self.readers.get(&conn.connection_id) {
                        r.update_topics(&conn.topics());
                    }
                }
            }
        }
    }
}

/// Runs until `shutdown` turns true, then stops cleanly.
pub async fn run(opts: Options, mut shutdown: watch::Receiver<bool>) -> Result<(), String> {
    let shared = Arc::new(Shared::default());
    let (tx, rx) = mpsc::channel(opts.queue_capacity.max(1));
    let (etx, mut events) = mpsc::unbounded_channel();
    let (wstop, wstop_rx) = watch::channel(false);
    let writer = tokio::spawn(service::run(opts.settings.clone(), shared.clone(), rx, etx, wstop_rx));
    let config = Arc::new(RwLock::new(None));
    let http_task = match opts.http_addr {
        Some(addr) => {
            let listener =
                tokio::net::TcpListener::bind(addr).await.map_err(|e| format!("HTTP listener {addr}: {e}"))?;
            let app = http::router(AppState { shared: shared.clone(), config: config.clone() });
            let mut stop = shutdown.clone();
            Some(tokio::spawn(async move {
                let serve = axum::serve(listener, app).with_graceful_shutdown(async move {
                    while stop.changed().await.is_ok() {
                        if *stop.borrow() {
                            return;
                        }
                    }
                });
                if let Err(e) = serve.await {
                    tracing::error!(error = %e, "HTTP listener stopped");
                }
            }))
        }
        None => None,
    };
    let mut sup = Sup { opts, shared: shared.clone(), tx, readers: HashMap::new(), generation: 0, config };
    loop {
        tokio::select! {
            r = shutdown.changed() => {
                if r.is_err() || *shutdown.borrow() { break; }
            }
            ev = events.recv() => match ev {
                Some(Event::Ready { generation, config }) => {
                    sup.abort_all();
                    sup.generation = generation;
                    sup.apply(&config);
                }
                Some(Event::ConfigChanged(config)) => sup.apply(&config),
                Some(Event::RedeliverRequired) => {
                    tracing::warn!("database failure: every broker session closes unacknowledged until the database is back");
                    sup.abort_all();
                }
                Some(Event::Standby) => tracing::info!("standing by: another ingest is active"),
                None => break,
            }
        }
    }
    // clean stop: readers stop queueing, the writer commits and acknowledges what is queued, then DISCONNECT
    shared.stopping.store(true, Ordering::SeqCst);
    let _ = wstop.send(true);
    if tokio::time::timeout(Duration::from_secs(60), writer).await.is_err() {
        tracing::error!("writer did not stop within 60 s");
    }
    let readers: Vec<Reader> = sup.readers.drain().map(|(_, r)| r).collect();
    for r in readers {
        r.disconnect(Duration::from_secs(5)).await;
    }
    if let Some(h) = http_task {
        let _ = tokio::time::timeout(Duration::from_secs(5), h).await;
    }
    tracing::info!(
        acked = shared.acked.load(Ordering::SeqCst),
        qos0_dropped = shared.qos0_dropped.load(Ordering::SeqCst),
        "stopped"
    );
    Ok(())
}
