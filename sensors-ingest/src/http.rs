//! The internal HTTP listener (plan S7c): `GET /healthz` for the container health check and the Sensors overview,
//! `POST /decode` for the payload-format page's "test with a payload" box (decode plus the time rule; no database,
//! no secrets). Bound inside the compose network only, never published.

use crate::config::Config;
use crate::service::Shared;
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

pub fn router(_state: AppState) -> axum::Router {
    todo!("router")
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
