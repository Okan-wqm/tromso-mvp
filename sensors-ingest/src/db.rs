//! The database side of the ingest (plan S7b): sign in, the single-writer advisory lock, the channel states, and the
//! batch transaction that commits readings, states, device counters, dead letters and the ingest status together.
//! The caller acknowledges the batch's messages only after `write_batch` returned Ok (COMMIT done).

use crate::pipeline::{Output, Reading};
use crate::reduce::State;
use chrono::{DateTime, Utc};
use std::collections::HashMap;
use std::str::FromStr;
use tokio_postgres::{Client, Error, NoTls};
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
    /// QoS 0 messages dropped on a full queue since the ingest started (sensors_ingest_status.qos0_dropped).
    pub qos0_dropped: i64,
    /// Messages the database refused, dead-lettered bad_value, since the ingest started.
    pub poison_total: i64,
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
/// database owner and act as `sensors_ingest`). A statement that runs longer than 60 s is cancelled by the server, so
/// a stuck database cannot hold a batch (and its unacked messages) for ever.
pub async fn connect(
    conninfo: &str,
    password: Option<&str>,
    role: Option<&str>,
    timeout: std::time::Duration,
) -> Result<Client, Error> {
    let mut cfg = tokio_postgres::Config::from_str(conninfo)?;
    if let Some(p) = password {
        cfg.password(p);
    }
    cfg.connect_timeout(timeout)
        .keepalives(true)
        .keepalives_idle(std::time::Duration::from_secs(30))
        .application_name("sensors-ingest");
    let (client, connection) = cfg.connect(NoTls).await?;
    tokio::spawn(async move {
        if let Err(e) = connection.await {
            tracing::error!(error = %e, "database connection closed");
        }
    });
    client.batch_execute("SET statement_timeout = '60s'; SET lock_timeout = '30s'; SET TIME ZONE 'UTC'").await?;
    if let Some(r) = role {
        // a role name from our own configuration, quoted as an identifier
        client.batch_execute(&format!("SET ROLE \"{}\"", r.replace('"', "\"\""))).await?;
    }
    Ok(client)
}

/// Takes the single-writer lock without waiting; false when another session holds it.
pub async fn try_lock(client: &Client) -> Result<bool, Error> {
    client.query_one("SELECT pg_try_advisory_lock($1)", &[&LOCK_KEY]).await?.try_get(0)
}

/// The states of the given channels; channels without a row get the default (empty) state.
pub async fn load_states(client: &Client, channel_nos: &[i32]) -> Result<HashMap<i32, State>, Error> {
    let rows = client
        .query(
            "SELECT channel_no, last_seen_at, last_good_at, last_value, last_value_ts, last_quality, anchor_ts, \
             anchor_value, anchor_quality, run_n, run_sum, run_min, run_max, high_ts \
             FROM sensors_channel_state WHERE channel_no = ANY($1)",
            &[&channel_nos],
        )
        .await?;
    let mut out: HashMap<i32, State> = channel_nos.iter().map(|c| (*c, State::default())).collect();
    for r in rows {
        out.insert(
            r.try_get(0)?,
            State {
                last_seen_at: r.try_get(1)?,
                last_good_at: r.try_get(2)?,
                last_value: r.try_get(3)?,
                last_value_ts: r.try_get(4)?,
                last_quality: r.try_get(5)?,
                anchor_ts: r.try_get(6)?,
                anchor_value: r.try_get(7)?,
                anchor_quality: r.try_get(8)?,
                run_n: r.try_get(9)?,
                run_sum: r.try_get(10)?,
                run_min: r.try_get(11)?,
                run_max: r.try_get(12)?,
                high_ts: r.try_get(13)?,
            },
        );
    }
    Ok(out)
}

/// No conflict target: inferring the arbiter index needs SELECT on the key columns, which the role does not have;
/// the primary key `(channel_no, ts)` is the only unique index of the table, so the effect is the same.
const INSERT_READINGS: &str = "INSERT INTO sensors_reading (channel_no, ts, value, n, quality, run_sum, run_min, run_max) \
     SELECT * FROM UNNEST($1::int4[], $2::timestamptz[], $3::float8[], $4::int4[], $5::int2[], $6::float8[], \
     $7::float8[], $8::float8[]) ON CONFLICT DO NOTHING";

/// One reading per statement (see `write_batch`).
const INSERT_ONE_READING: &str = "INSERT INTO sensors_reading (channel_no, ts, value, n, quality, run_sum, run_min, run_max) \n     VALUES ($1, $2, $3, $4, $5, $6, $7, $8) ON CONFLICT DO NOTHING";

/// Chunks are compressed after 14 days (sensors/CONTRACT.md); a row younger than this many days lands in an
/// uncompressed chunk.
pub const COMPRESSION_HORIZON_DAYS: i64 = 13;

const UPSERT_STATES: &str = "INSERT INTO sensors_channel_state (channel_no, last_seen_at, last_good_at, last_value, \
     last_value_ts, last_quality, anchor_ts, anchor_value, anchor_quality, run_n, run_sum, run_min, run_max, high_ts) \
     SELECT * FROM UNNEST($1::int4[], $2::timestamptz[], $3::timestamptz[], $4::float8[], $5::timestamptz[], \
     $6::int2[], $7::timestamptz[], $8::float8[], $9::int2[], $10::int4[], $11::float8[], $12::float8[], \
     $13::float8[], $14::timestamptz[]) \
     ON CONFLICT (channel_no) DO UPDATE SET last_seen_at = EXCLUDED.last_seen_at, \
     last_good_at = EXCLUDED.last_good_at, last_value = EXCLUDED.last_value, last_value_ts = EXCLUDED.last_value_ts, \
     last_quality = EXCLUDED.last_quality, anchor_ts = EXCLUDED.anchor_ts, anchor_value = EXCLUDED.anchor_value, \
     anchor_quality = EXCLUDED.anchor_quality, run_n = EXCLUDED.run_n, run_sum = EXCLUDED.run_sum, \
     run_min = EXCLUDED.run_min, run_max = EXCLUDED.run_max, high_ts = EXCLUDED.high_ts";

const UPSERT_DEVICES: &str = "INSERT INTO sensors_device_state (device_id, last_message_at, last_seq, accepted_total, \
     late_total, dead_total, ignored_total) \
     SELECT * FROM UNNEST($1::uuid[], $2::timestamptz[], $3::int8[], $4::int8[], $5::int8[], $6::int8[], $7::int8[]) \
     ON CONFLICT (device_id) DO UPDATE SET \
     last_message_at = GREATEST(sensors_device_state.last_message_at, EXCLUDED.last_message_at), \
     last_seq = COALESCE(EXCLUDED.last_seq, sensors_device_state.last_seq), \
     accepted_total = sensors_device_state.accepted_total + EXCLUDED.accepted_total, \
     late_total = sensors_device_state.late_total + EXCLUDED.late_total, \
     dead_total = sensors_device_state.dead_total + EXCLUDED.dead_total, \
     ignored_total = sensors_device_state.ignored_total + EXCLUDED.ignored_total";

const UPSERT_DEAD: &str = "INSERT INTO sensors_dead_letter (connection_id, device_id, topic, reason, payload_sha256, \
     payload, payload_len, count, first_at, last_at) \
     SELECT * FROM UNNEST($1::uuid[], $2::uuid[], $3::text[], $4::text[], $5::text[], $6::bytea[], $7::int4[], \
     $8::int4[], $9::timestamptz[], $10::timestamptz[]) \
     ON CONFLICT (connection_id, topic, reason, payload_sha256) DO UPDATE SET \
     count = sensors_dead_letter.count + EXCLUDED.count, \
     last_at = GREATEST(sensors_dead_letter.last_at, EXCLUDED.last_at)";

const UPSERT_STATUS: &str = "INSERT INTO sensors_ingest_status (connection_id, heartbeat_at, version, connected, \
     queue_depth, last_commit_at) \
     SELECT c, now(), v, k, q, CASE WHEN $5 THEN now() END \
     FROM UNNEST($1::uuid[], $2::text[], $3::bool[], $4::int4[]) AS u(c, v, k, q) \
     ON CONFLICT (connection_id) DO UPDATE SET heartbeat_at = now(), version = EXCLUDED.version, \
     connected = EXCLUDED.connected, queue_depth = EXCLUDED.queue_depth, \
     last_commit_at = COALESCE(EXCLUDED.last_commit_at, sensors_ingest_status.last_commit_at)";

async fn status_rows(
    client: &impl tokio_postgres::GenericClient,
    status: &[Status],
    committed: bool,
) -> Result<(), Error> {
    if status.is_empty() {
        return Ok(());
    }
    let ids: Vec<Uuid> = status.iter().map(|s| s.connection_id).collect();
    let versions: Vec<&str> = status.iter().map(|s| s.version.as_str()).collect();
    let connected: Vec<bool> = status.iter().map(|s| s.connected).collect();
    let depth: Vec<i32> = status.iter().map(|s| s.queue_depth.max(0)).collect();
    client.execute(UPSERT_STATUS, &[&ids, &versions, &connected, &depth, &committed]).await?;
    Ok(())
}

/// One transaction: readings (`ON CONFLICT DO NOTHING`), channel states (upsert), device counters (added), dead
/// letters (counted on conflict), the status of the given connections with `last_commit_at = now()`. Nothing is
/// written if any statement fails.
pub async fn write_batch(client: &mut Client, out: &Output, status: &[Status]) -> Result<Written, Error> {
    let tx = client.transaction().await?;
    let mut w = Written::default();
    if !out.readings.is_empty() {
        // TimescaleDB 2.17.2 drops every later row of a multi-row INSERT ... ON CONFLICT DO NOTHING once one row
        // conflicts inside a COMPRESSED chunk (tests/db.rs late_rows_and_duplicates...). Rows that can meet a
        // compressed chunk with a conflict - late rows, and anything older than the compression horizon - go one per
        // statement; the rest (forward rows of recent, uncompressed chunks) in one batched statement.
        let horizon = Utc::now() - chrono::Duration::days(COMPRESSION_HORIZON_DAYS);
        let (single, batch): (Vec<&Reading>, Vec<&Reading>) =
            out.readings.iter().partition(|x| x.row.quality & crate::quality::LATE != 0 || x.row.ts < horizon);
        if !batch.is_empty() {
            let r = &batch;
            let ch: Vec<i32> = r.iter().map(|x| x.channel_no).collect();
            let ts: Vec<DateTime<Utc>> = r.iter().map(|x| x.row.ts).collect();
            let v: Vec<f64> = r.iter().map(|x| x.row.value).collect();
            let n: Vec<i32> = r.iter().map(|x| x.row.n).collect();
            let q: Vec<i16> = r.iter().map(|x| x.row.quality).collect();
            let s: Vec<Option<f64>> = r.iter().map(|x| x.row.run_sum).collect();
            let mn: Vec<Option<f64>> = r.iter().map(|x| x.row.run_min).collect();
            let mx: Vec<Option<f64>> = r.iter().map(|x| x.row.run_max).collect();
            w.readings_inserted = tx.execute(INSERT_READINGS, &[&ch, &ts, &v, &n, &q, &s, &mn, &mx]).await?;
        }
        if !single.is_empty() {
            let one = tx.prepare(INSERT_ONE_READING).await?;
            for x in single {
                let r = &x.row;
                w.readings_inserted += tx
                    .execute(
                        &one,
                        &[&x.channel_no, &r.ts, &r.value, &r.n, &r.quality, &r.run_sum, &r.run_min, &r.run_max],
                    )
                    .await?;
            }
        }
        w.readings_existing = (out.readings.len() as u64).saturating_sub(w.readings_inserted);
    }
    if !out.states.is_empty() {
        let st: Vec<(&i32, &State)> = out.states.iter().collect();
        let ch: Vec<i32> = st.iter().map(|x| *x.0).collect();
        let col_t = |f: fn(&State) -> Option<DateTime<Utc>>| st.iter().map(|x| f(x.1)).collect::<Vec<_>>();
        let col_f = |f: fn(&State) -> Option<f64>| st.iter().map(|x| f(x.1)).collect::<Vec<_>>();
        let col_q = |f: fn(&State) -> Option<i16>| st.iter().map(|x| f(x.1)).collect::<Vec<_>>();
        let run_n: Vec<i32> = st.iter().map(|x| x.1.run_n).collect();
        tx.execute(
            UPSERT_STATES,
            &[
                &ch,
                &col_t(|s| s.last_seen_at),
                &col_t(|s| s.last_good_at),
                &col_f(|s| s.last_value),
                &col_t(|s| s.last_value_ts),
                &col_q(|s| s.last_quality),
                &col_t(|s| s.anchor_ts),
                &col_f(|s| s.anchor_value),
                &col_q(|s| s.anchor_quality),
                &run_n,
                &col_f(|s| s.run_sum),
                &col_f(|s| s.run_min),
                &col_f(|s| s.run_max),
                &col_t(|s| s.high_ts),
            ],
        )
        .await?;
    }
    if !out.devices.is_empty() {
        let d: Vec<_> = out.devices.iter().collect();
        let ids: Vec<Uuid> = d.iter().map(|x| *x.0).collect();
        let at: Vec<Option<DateTime<Utc>>> = d.iter().map(|x| x.1.last_message_at).collect();
        let seq: Vec<Option<i64>> = d.iter().map(|x| x.1.last_seq).collect();
        let acc: Vec<i64> = d.iter().map(|x| x.1.accepted).collect();
        let late: Vec<i64> = d.iter().map(|x| x.1.late).collect();
        let dead: Vec<i64> = d.iter().map(|x| x.1.dead).collect();
        let ign: Vec<i64> = d.iter().map(|x| x.1.ignored).collect();
        tx.execute(UPSERT_DEVICES, &[&ids, &at, &seq, &acc, &late, &dead, &ign]).await?;
    }
    if !out.dead.is_empty() {
        let d = &out.dead;
        let conn: Vec<Uuid> = d.iter().map(|x| x.connection_id).collect();
        let dev: Vec<Option<Uuid>> = d.iter().map(|x| x.device_id).collect();
        let topic: Vec<&str> = d.iter().map(|x| x.topic.as_str()).collect();
        let reason: Vec<&str> = d.iter().map(|x| x.reason.as_str()).collect();
        let sha: Vec<&str> = d.iter().map(|x| x.payload_sha256.as_str()).collect();
        let payload: Vec<&[u8]> = d.iter().map(|x| x.payload.as_slice()).collect();
        let len: Vec<i32> = d.iter().map(|x| x.payload_len).collect();
        let count: Vec<i32> = d.iter().map(|x| x.count).collect();
        let first: Vec<DateTime<Utc>> = d.iter().map(|x| x.first_at).collect();
        let last: Vec<DateTime<Utc>> = d.iter().map(|x| x.last_at).collect();
        w.dead_letters = tx
            .execute(UPSERT_DEAD, &[&conn, &dev, &topic, &reason, &sha, &payload, &len, &count, &first, &last])
            .await?;
    }
    status_rows(&tx, status, true).await?;
    tx.commit().await?;
    Ok(w)
}

/// The heartbeat: `sensors_ingest_status` rows with `heartbeat_at = now()`.
pub async fn write_status(client: &Client, status: &[Status]) -> Result<(), Error> {
    status_rows(client, status, false).await
}

/// A data or integrity error caused by the batch's content (SQLSTATE classes 22 and 23): retrying the same batch
/// fails again, so the caller isolates the message that causes it. Anything else (connection, server) is transient.
pub fn is_data_error(e: &Error) -> bool {
    e.code().is_some_and(|c| c.code().starts_with("22") || c.code().starts_with("23"))
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
