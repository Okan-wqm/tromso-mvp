//! The internal HTTP listener (plan S7c): `GET /healthz` for the container health check and the Sensors overview,
//! `POST /decode` for the payload-format page's "test with a payload" box (decode plus the time rule; no database,
//! no secrets). Bound inside the compose network only, never published.

use crate::config::Config;
use crate::model::{ChannelMap, Format};
use crate::service::Shared;
use crate::timerule::{self, Limits};
use axum::Json;
use axum::extract::State;
use axum::http::StatusCode;
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::sync::atomic::Ordering;
use std::sync::{Arc, RwLock};

/// A database write older than this makes the service unhealthy (the heartbeat writes every 10 s).
pub const DB_STALE_S: i64 = 60;
/// The largest request body accepted by /decode (a payload above `decode::MAX_PAYLOAD` is reported `oversize`).
pub const BODY_LIMIT: usize = 256 * 1024;

#[derive(Clone)]
pub struct AppState {
    pub shared: Arc<Shared>,
    pub config: Arc<RwLock<Option<Arc<Config>>>>,
}

pub fn router(state: AppState) -> axum::Router {
    axum::Router::new()
        .route("/healthz", axum::routing::get(healthz))
        .route("/decode", axum::routing::post(decode))
        .layer(axum::extract::DefaultBodyLimit::max(BODY_LIMIT))
        .with_state(state)
}

fn current(state: &AppState) -> Option<Arc<Config>> {
    match state.config.read() {
        Ok(g) => g.clone(),
        Err(p) => p.into_inner().clone(),
    }
}

async fn healthz(State(state): State<AppState>) -> (StatusCode, Json<serde_json::Value>) {
    let sh = &state.shared;
    let mut problems: Vec<String> = Vec::new();
    if !sh.ready.load(Ordering::SeqCst) {
        problems.push("writer not ready (database, lock or configuration)".into());
    }
    let age = chrono::Utc::now().timestamp() - sh.last_db_ok.load(Ordering::SeqCst);
    if age > DB_STALE_S {
        problems.push(format!("no database write for {age} s"));
    }
    let connected = match sh.connected.lock() {
        Ok(g) => g.clone(),
        Err(p) => p.into_inner().clone(),
    };
    let mut brokers = serde_json::Map::new();
    if let Some(cfg) = current(&state) {
        for id in cfg.connections.keys() {
            let up = connected.get(id).copied().unwrap_or(false);
            if !up {
                problems.push(format!("broker connection {id} down"));
            }
            brokers.insert(id.to_string(), serde_json::Value::Bool(up));
        }
    }
    let body = serde_json::json!({
        "status": if problems.is_empty() { "ok" } else { "unhealthy" },
        "problems": problems,
        "brokers": brokers,
        "generation": sh.current_generation(),
        "commits": sh.commits.load(Ordering::SeqCst),
        "acked": sh.acked.load(Ordering::SeqCst),
        "queue_depth": sh.queue_depth.load(Ordering::SeqCst),
        "qos0_dropped": sh.qos0_dropped.load(Ordering::SeqCst),
        "discarded_stale": sh.discarded.load(Ordering::SeqCst),
        "poison": sh.poison.load(Ordering::SeqCst),
        "version": env!("CARGO_PKG_VERSION"),
    });
    let code = if problems.is_empty() { StatusCode::OK } else { StatusCode::SERVICE_UNAVAILABLE };
    (code, Json(body))
}

#[derive(Deserialize)]
struct DecodeRequest {
    format: Format,
    channels: Vec<ChannelMap>,
    payload: String,
    received_at: Option<DateTime<Utc>>,
}

#[derive(Serialize)]
struct DecodedSample {
    channel_no: i32,
    /// The value as decoded, before calibration (the box has no channel calibration).
    value: f64,
    ts: DateTime<Utc>,
    quality: i16,
}

async fn decode(State(state): State<AppState>, Json(req): Json<DecodeRequest>) -> Json<serde_json::Value> {
    let limits = current(&state)
        .map(|c| Limits { future_skew_s: c.contract.future_skew_s, late_limit_days: c.contract.late_limit_days })
        .unwrap_or(Limits { future_skew_s: 60, late_limit_days: 728 });
    let received_at = req.received_at.unwrap_or_else(Utc::now);
    let d = crate::decode::decode(&req.format, &req.channels, req.payload.as_bytes());
    let mut faults = d.faults.clone();
    let mut samples = Vec::new();
    for s in &d.samples {
        match timerule::resolve(s.device_ts, received_at, limits) {
            Ok((ts, quality)) => samples.push(DecodedSample { channel_no: s.channel_no, value: s.value, ts, quality }),
            Err(r) => faults.push(r),
        }
    }
    faults.sort();
    faults.dedup();
    Json(serde_json::json!({"seq": d.seq, "samples": samples, "faults": faults}))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::{build, tests as cfgt};
    use axum::body::Body;
    use axum::http::{Request, StatusCode};
    use std::sync::atomic::Ordering;
    use tower::ServiceExt;
    use uuid::Uuid;

    fn state() -> AppState {
        let cfg = build(cfgt::contract(), vec![cfgt::row(1, 10, "farm/plc", 1)]).unwrap();
        AppState { shared: Arc::new(Shared::default()), config: Arc::new(RwLock::new(Some(Arc::new(cfg)))) }
    }

    async fn call(s: &AppState, req: Request<Body>) -> (StatusCode, serde_json::Value) {
        let resp = router(s.clone()).oneshot(req).await.unwrap();
        let status = resp.status();
        let bytes = axum::body::to_bytes(resp.into_body(), 1 << 20).await.unwrap();
        (status, serde_json::from_slice(&bytes).unwrap_or(serde_json::Value::Null))
    }

    fn get(path: &str) -> Request<Body> {
        Request::get(path).body(Body::empty()).unwrap()
    }

    fn post(path: &str, v: serde_json::Value) -> Request<Body> {
        Request::post(path).header("content-type", "application/json").body(Body::from(v.to_string())).unwrap()
    }

    #[tokio::test]
    async fn healthz_needs_ready_a_recent_database_write_and_every_broker_connected() {
        let s = state();
        let (code, body) = call(&s, get("/healthz")).await;
        assert_eq!(code, StatusCode::SERVICE_UNAVAILABLE);
        assert_eq!(body["status"], "unhealthy");
        s.shared.ready.store(true, Ordering::SeqCst);
        s.shared.last_db_ok.store(chrono::Utc::now().timestamp(), Ordering::SeqCst);
        s.shared.connected.lock().unwrap().insert(Uuid::from_u128(1), true);
        let (code, body) = call(&s, get("/healthz")).await;
        assert_eq!(code, StatusCode::OK, "{body}");
        assert_eq!(body["status"], "ok");
        s.shared.connected.lock().unwrap().insert(Uuid::from_u128(1), false);
        assert_eq!(call(&s, get("/healthz")).await.0, StatusCode::SERVICE_UNAVAILABLE);
        s.shared.connected.lock().unwrap().insert(Uuid::from_u128(1), true);
        s.shared.last_db_ok.store(chrono::Utc::now().timestamp() - DB_STALE_S - 1, Ordering::SeqCst);
        let (code, body) = call(&s, get("/healthz")).await;
        assert_eq!(code, StatusCode::SERVICE_UNAVAILABLE);
        assert!(body["problems"].to_string().contains("database"), "{body}");
        s.shared.qos0_dropped.store(3, Ordering::SeqCst);
        assert_eq!(call(&s, get("/healthz")).await.1["qos0_dropped"], 3);
        for ms in 1..=100u32 {
            s.shared.record_commit(std::time::Duration::from_millis(u64::from(ms)));
        }
        let body = call(&s, get("/healthz")).await.1;
        assert_eq!(
            (body["commit_ms"]["p50"].as_u64(), body["commit_ms"]["p99"].as_u64(), body["commit_ms"]["max"].as_u64()),
            (Some(50), Some(99), Some(100))
        );
        assert_eq!(body["commit_ms"]["count"], 100);
    }

    #[tokio::test]
    async fn decode_returns_samples_with_the_time_rule_and_faults() {
        let s = state();
        let req = post(
            "/decode",
            serde_json::json!({
                "format": {"shape": "object", "time_path": "/ts", "time_unit": "iso8601", "seq_path": "/seq"},
                "channels": [{"channel_no": 1, "value_path": "/a"}, {"channel_no": 2, "value_path": "/b"}],
                "payload": "{\"ts\": \"2026-11-04T12:00:00Z\", \"seq\": 9, \"a\": 1.5, \"b\": \"x\"}",
                "received_at": "2026-11-04T12:00:01Z"
            }),
        );
        let (code, body) = call(&s, req).await;
        assert_eq!(code, StatusCode::OK, "{body}");
        assert_eq!(body["seq"], 9);
        assert_eq!(body["samples"][0]["channel_no"], 1);
        assert_eq!(body["samples"][0]["value"], 1.5);
        assert_eq!(body["samples"][0]["ts"], "2026-11-04T12:00:00Z");
        assert_eq!(body["samples"][0]["quality"], 0);
        assert_eq!(body["faults"], serde_json::json!(["bad_value"]));
    }

    #[tokio::test]
    async fn decode_applies_the_future_skew_and_reports_garbage() {
        let s = state();
        let ahead = post(
            "/decode",
            serde_json::json!({
                "format": {"shape": "object", "time_path": "/ts", "time_unit": "epoch_s"},
                "channels": [{"channel_no": 1, "value_path": "/a"}],
                "payload": "{\"ts\": 1800000000, \"a\": 1}",
                "received_at": "2026-11-04T12:00:00Z"
            }),
        );
        let (_, body) = call(&s, ahead).await;
        assert_eq!(body["samples"][0]["quality"], crate::quality::CLOCK_SUSPECT);
        assert_eq!(body["samples"][0]["ts"], "2026-11-04T12:00:00Z");
        let garbage = post(
            "/decode",
            serde_json::json!({"format": {"shape": "object", "time_unit": "iso8601"},
                               "channels": [{"channel_no": 1, "value_path": "/a"}], "payload": "{nope"}),
        );
        let (code, body) = call(&s, garbage).await;
        assert_eq!(code, StatusCode::OK);
        assert_eq!(body["faults"], serde_json::json!(["not_json"]));
    }

    #[tokio::test]
    async fn a_malformed_request_is_a_client_error() {
        let s = state();
        let (code, _) = call(&s, post("/decode", serde_json::json!({"format": "nope"}))).await;
        assert!(code.is_client_error());
        let big = "x".repeat(BODY_LIMIT + 1);
        let req = Request::post("/decode").header("content-type", "application/json").body(Body::from(big)).unwrap();
        assert!(call(&s, req).await.0.is_client_error());
    }
}
