//! Ties the writer, the MQTT readers and the HTTP listener together (plan S7c). Readers run only while the writer is
//! Ready, on its generation; a configuration change resubscribes live (or restarts a reader whose session settings
//! changed); a database failure stops every reader at once (no acknowledgement can follow) and restarts them when the
//! writer is Ready again, so the broker redelivers. Shutdown: readers stop queueing, the writer commits and
//! acknowledges what is queued, then each session sends DISCONNECT (the broker keeps it).

use crate::service::Settings;
use std::net::SocketAddr;
use std::path::PathBuf;
use tokio::sync::watch;

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

/// Runs until `shutdown` turns true, then stops cleanly.
pub async fn run(_opts: Options, _shutdown: watch::Receiver<bool>) -> Result<(), String> {
    todo!("supervisor")
}
