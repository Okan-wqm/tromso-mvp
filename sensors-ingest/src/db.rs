//! The database side of the ingest (plan S7b): sign in, the single-writer advisory lock, the channel states, and the
//! batch transaction that commits readings, states, device counters, dead letters and the ingest status together.
//! The caller acknowledges the batch's messages only after `write_batch` returned Ok (COMMIT done).

use crate::pipeline::Output;
use crate::reduce::State;
use std::collections::HashMap;
use tokio_postgres::{Client, Error};
use uuid::Uuid;

/// `pg_advisory_lock` key held by the one active ingest (the bytes of "SENS"), from sensors/CONTRACT.md.
pub const LOCK_KEY: i64 = 1_397_050_963;

/// What the ingest says about one broker connection in `sensors_ingest_status`.
#[derive(Debug, Clone, PartialEq)]
pub struct Status {
    pub connection_id: Uuid,
    pub connected: bool,
    pub queue_depth: i32,
    pub version: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Default)]
pub struct Written {
    pub readings_inserted: u64,
    /// Rows the key already held (a redelivered message): not stored twice.
    pub readings_existing: u64,
    pub dead_letters: u64,
}

/// Connects with a libpq-style connection string plus an optional password (read from a secret file by the caller,
/// never from the environment), spawns the connection driver, and optionally `SET ROLE`s (tests sign in as the
/// database owner and act as `sensors_ingest`). Fails if the server does not answer within `timeout`.
pub async fn connect(
    _conninfo: &str,
    _password: Option<&str>,
    _role: Option<&str>,
    _timeout: std::time::Duration,
) -> Result<Client, Error> {
    todo!("connect")
}

/// Takes the single-writer lock without waiting; false when another session holds it.
pub async fn try_lock(_client: &Client) -> Result<bool, Error> {
    todo!("try_lock")
}

/// The states of the given channels; channels without a row get the default (empty) state.
pub async fn load_states(_client: &Client, _channel_nos: &[i32]) -> Result<HashMap<i32, State>, Error> {
    todo!("load_states")
}

/// One transaction: readings (`ON CONFLICT DO NOTHING`), channel states (upsert), device counters (added), dead
/// letters (counted on conflict), the status of the given connections with `last_commit_at = now()`. Nothing is
/// written if any statement fails.
pub async fn write_batch(_client: &mut Client, _out: &Output, _status: &[Status]) -> Result<Written, Error> {
    todo!("write_batch")
}

/// The heartbeat: `sensors_ingest_status` rows with `heartbeat_at = now()`.
pub async fn write_status(_client: &Client, _status: &[Status]) -> Result<(), Error> {
    todo!("write_status")
}

/// A data or integrity error caused by the batch's content (SQLSTATE classes 22 and 23): retrying the same batch
/// fails again, so the caller isolates the message that causes it. Anything else (connection, server) is transient.
pub fn is_data_error(_e: &Error) -> bool {
    todo!("is_data_error")
}

/// The rows of `sensors_quality_flag`, in bit order.
pub async fn quality_flags(client: &Client) -> Result<Vec<(i16, String, bool)>, Error> {
    let rows = client.query("SELECT bit, name, is_bad FROM sensors_quality_flag ORDER BY bit", &[]).await?;
    rows.iter().map(|r| Ok((r.try_get(0)?, r.try_get(1)?, r.try_get(2)?))).collect()
}

/// The column names of the contract view, in order.
pub async fn view_columns(client: &Client) -> Result<Vec<String>, Error> {
    let stmt = client.prepare("SELECT * FROM sensors_ingest_config LIMIT 0").await?;
    Ok(stmt.columns().iter().map(|c| c.name().to_string()).collect())
}
