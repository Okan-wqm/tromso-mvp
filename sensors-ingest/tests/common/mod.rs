//! Database fixtures for the integration tests. They run against a database migrated by Django (the schema owner):
//! `TEST_DATABASE_URL` is a libpq string signing in as the owner (never the dev database `balik`); the ingest's side
//! acts as role `sensors_ingest` through `SET ROLE`, so its grants are what is tested. `tests/run.sh` sets it up.
#![allow(clippy::unwrap_used, clippy::expect_used, clippy::panic, clippy::indexing_slicing, dead_code)]

use std::time::Duration;
use tokio_postgres::Client;
use uuid::Uuid;

pub fn url() -> Option<String> {
    match std::env::var("TEST_DATABASE_URL") {
        Ok(u) if !u.is_empty() => {
            assert!(!u.contains("dbname=balik ") && !u.ends_with("dbname=balik"), "never the dev database");
            Some(u)
        }
        _ => {
            assert!(std::env::var("REQUIRE_DB").is_err(), "REQUIRE_DB is set but TEST_DATABASE_URL is not");
            eprintln!("SKIPPED: TEST_DATABASE_URL not set (tests/run.sh sets it)");
            None
        }
    }
}

pub async fn admin(url: &str) -> Client {
    sensors_ingest::db::connect(url, None, None, Duration::from_secs(10)).await.unwrap()
}

pub async fn ingest(url: &str) -> Client {
    sensors_ingest::db::connect(url, None, Some("sensors_ingest"), Duration::from_secs(10)).await.unwrap()
}

/// Empties every sensors table the tests touch (as the owner).
pub async fn reset(a: &Client) {
    a.batch_execute(
        "TRUNCATE sensors_reading, sensors_channel_state, sensors_device_state, sensors_ingest_status, \
         sensors_dead_letter, sensors_calibration; \
         DELETE FROM sensors_channel; DELETE FROM sensors_device; DELETE FROM sensors_payload_format; \
         DELETE FROM sensors_connection; DELETE FROM sites WHERE code LIKE 'ZZ%';",
    )
    .await
    .unwrap();
}

pub struct Fx {
    pub site: Uuid,
    pub connection: Uuid,
    pub format: Uuid,
}

const AUDIT: &str = "now(), now(), 1, false";

pub async fn base(a: &Client, n: u128) -> Fx {
    let site = Uuid::from_u128(0x5000 + n);
    let connection = Uuid::from_u128(0xC000 + n);
    let format = Uuid::from_u128(0xF000 + n);
    a.execute(
        &format!(
            "INSERT INTO sites (id, created_at, updated_at, version, is_deleted, name, code, organisation_number, \
             type, status, is_active, description, street, city, state, postal_code, country, region, timezone, \
             site_manager, contact_email, contact_phone, notes, lice_area, production_form) \
             VALUES ($1, {AUDIT}, 'Ingest test site', 'ZZ' || $2, '', 'land_based', 'active', true, '', '', '', '', \
             '', 'NO', '', 'Europe/Oslo', '', '', '', '', '', '')"
        ),
        &[&site, &n.to_string()],
    )
    .await
    .unwrap();
    a.execute(
        &format!(
            "INSERT INTO sensors_connection (id, created_at, updated_at, version, is_deleted, name, host, port, \
             use_tls, username, secret_file, client_id, keepalive_s, is_active) \
             VALUES ($1, {AUDIT}, 'conn ' || $2, 'mosquitto', 1883, false, 'ingest', 'mqtt_ingest', 'ingest-' || $2, 30, true)"
        ),
        &[&connection, &n.to_string()],
    )
    .await
    .unwrap();
    format_row(a, format, &format!("fmt {n}"), "object", "/ts", "iso8601", "/seq", "", "", "").await;
    Fx { site, connection, format }
}

#[allow(clippy::too_many_arguments)]
pub async fn format_row(
    a: &Client,
    id: Uuid,
    name: &str,
    shape: &str,
    time_path: &str,
    time_unit: &str,
    seq_path: &str,
    items_path: &str,
    name_key: &str,
    value_key: &str,
) {
    a.execute(
        &format!(
            "INSERT INTO sensors_payload_format (id, created_at, updated_at, version, is_deleted, name, encoding, \
             shape, time_path, time_unit, seq_path, items_path, name_key, value_key) \
             VALUES ($1, {AUDIT}, $2, 'json', $3, $4, $5, $6, $7, $8, $9)"
        ),
        &[&id, &name, &shape, &time_path, &time_unit, &seq_path, &items_path, &name_key, &value_key],
    )
    .await
    .unwrap();
}

pub async fn device(a: &Client, fx: &Fx, id: Uuid, code: &str, topic: &str, format: Uuid) {
    a.execute(
        &format!(
            "INSERT INTO sensors_device (id, created_at, updated_at, version, is_deleted, code, name, topic, \
             expected_interval_s, manufacturer, model, note, is_active, connection_id, site_id, payload_format_id) \
             VALUES ($1, {AUDIT}, $2, $2, $3, 1, '', '', '', true, $4, $5, $6)"
        ),
        &[&id, &code, &topic, &fx.connection, &fx.site, &format],
    )
    .await
    .unwrap();
}

/// A channel; returns its channel number (drawn by the database).
#[allow(clippy::too_many_arguments)]
pub async fn channel(
    a: &Client,
    device: Uuid,
    code: &str,
    value_path: &str,
    item_name: &str,
    reduction: &str,
    deadband: f64,
    heartbeat_s: i32,
    range: Option<(f64, f64)>,
) -> (Uuid, i32) {
    let id = Uuid::new_v4();
    let row = a
        .query_one(
            &format!(
                "INSERT INTO sensors_channel (id, created_at, updated_at, version, is_deleted, code, name, quantity, \
                 unit, unit_factor, unit_offset, value_path, item_name, address_protocol, address, reduction, deadband, \
                 heartbeat_s, range_min, range_max, state, note, device_id) \
                 VALUES ($1, {AUDIT}, $2, $2, 'temperature_c', 'C', 1, 0, $3, $4, 'mqtt', '{{}}', $5, $6, $7, $8, $9, \
                 'active', '', $10) RETURNING channel_no"
            ),
            &[
                &id,
                &code,
                &value_path,
                &item_name,
                &reduction,
                &deadband,
                &heartbeat_s,
                &range.map(|r| r.0),
                &range.map(|r| r.1),
                &device,
            ],
        )
        .await
        .unwrap();
    (id, row.get(0))
}

pub async fn count(a: &Client, sql: &str) -> i64 {
    a.query_one(sql, &[]).await.unwrap().get(0)
}
