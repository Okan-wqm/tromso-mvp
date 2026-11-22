//! Behaviour pins of every timestamp the ingest reads or writes, at the JSON boundary: the device time in a payload
//! (ISO 8601, epoch seconds, epoch milliseconds), how a bad one is refused, the `received_at` of `POST /decode`, the
//! time rule's borders and the text a time is written back as. They name no time type (text in, text out), so the
//! same tests ran on the chrono implementation and run on its replacement: written against chrono 0.4.45 and kept
//! unchanged when the crate moved to `time` (RUSTSEC-2026-0543, chrono unmaintained).
//!
//! No local time zone is used anywhere: every offset is the one written in the text. The Europe/Oslo daylight-saving
//! changes are pinned to show exactly that.

use crate::config::{Config, build, tests as cfgt};
use crate::decode::decode;
use crate::http::{AppState, router};
use crate::model::{ChannelMap, Format, Shape, TimeUnit};
use crate::service::Shared;
use axum::body::Body;
use axum::http::{Request, StatusCode};
use serde_json::{Value, json};
use std::sync::{Arc, RwLock};
use tower::ServiceExt;

const CH: i32 = 1;

fn format(unit: TimeUnit) -> Format {
    Format {
        shape: Shape::Object,
        time_path: "/t".into(),
        time_unit: unit,
        seq_path: String::new(),
        items_path: String::new(),
        name_key: String::new(),
        value_key: String::new(),
    }
}

fn channels() -> Vec<ChannelMap> {
    vec![ChannelMap { channel_no: CH, value_path: "/v".into(), item_name: String::new() }]
}

/// The device time `decode` reads from `{"t": <t>, "v": 1}`, as the text it is written back as, or the fault.
fn device_time(unit: TimeUnit, payload: &str) -> Result<String, String> {
    let d = serde_json::to_value(decode(&format(unit), &channels(), payload.as_bytes())).unwrap();
    match d["samples"].as_array().map(Vec::as_slice) {
        Some([s]) => Ok(s["device_ts"].as_str().unwrap().to_owned()),
        _ => Err(d["faults"].as_array().unwrap().iter().map(|f| f.as_str().unwrap()).collect::<Vec<_>>().join(",")),
    }
}

fn iso(text: &str) -> Result<String, String> {
    device_time(TimeUnit::Iso8601, &json!({"t": text, "v": 1}).to_string())
}

/// `t` is raw JSON (a number as written, or a quoted text).
fn epoch(unit: TimeUnit, t: &str) -> Result<String, String> {
    device_time(unit, &format!(r#"{{"t": {t}, "v": 1}}"#))
}

/// Every case is checked; all mismatches are reported together.
fn check<F: Fn(&str) -> Result<String, String>>(what: &str, f: F, cases: &[(&str, Result<&str, &str>)]) {
    let bad: Vec<String> = cases
        .iter()
        .filter_map(|(input, want)| {
            let got = f(input);
            let want = want.map(str::to_owned).map_err(str::to_owned);
            (got != want).then(|| format!("{what} {input:?}: got {got:?}, want {want:?}"))
        })
        .collect();
    assert!(bad.is_empty(), "\n{}", bad.join("\n"));
}

const BAD: Result<&str, &str> = Err("bad_time");

#[test]
fn iso_offsets_separators_and_utc_conversion() {
    check(
        "iso",
        iso,
        &[
            ("2026-11-04T12:00:00Z", Ok("2026-11-04T12:00:00Z")),
            ("2026-11-04t12:00:00z", Ok("2026-11-04T12:00:00Z")),
            ("2026-11-04 12:00:00Z", Ok("2026-11-04T12:00:00Z")),
            ("2026-11-04T12:00:00+00:00", Ok("2026-11-04T12:00:00Z")),
            ("2026-11-04T12:00:00-00:00", Ok("2026-11-04T12:00:00Z")),
            ("2026-11-04T13:30:00+01:30", Ok("2026-11-04T12:00:00Z")),
            ("2026-11-04T00:30:00+01:00", Ok("2026-11-03T23:30:00Z")),
            ("2026-11-04T23:30:00-01:00", Ok("2026-11-05T00:30:00Z")),
            ("2026-11-04T12:00:00+23:59", Ok("2026-11-03T12:01:00Z")),
            ("2026-11-04T12:00:00-23:59", Ok("2026-11-05T11:59:00Z")),
            // U+2212 MINUS SIGN is accepted as the offset's sign
            ("2026-11-04T11:00:00\u{2212}01:00", Ok("2026-11-04T12:00:00Z")),
            // surrounding white space is trimmed before parsing
            ("  2026-11-04T12:00:00Z \n", Ok("2026-11-04T12:00:00Z")),
        ],
    );
}

#[test]
fn iso_oslo_daylight_saving_changes_use_the_written_offset_only() {
    check(
        "iso",
        iso,
        &[
            // 2026-03-29: Oslo clocks jump 02:00 -> 03:00 (CET -> CEST); 02:30 local does not exist there, but a written
            // offset is taken as written.
            ("2026-03-29T01:59:59+01:00", Ok("2026-03-29T00:59:59Z")),
            ("2026-03-29T02:30:00+01:00", Ok("2026-03-29T01:30:00Z")),
            ("2026-03-29T03:00:00+02:00", Ok("2026-03-29T01:00:00Z")),
            // 2026-10-25: 03:00 CEST -> 02:00 CET; 02:30 local happens twice, the offset tells which.
            ("2026-10-25T02:30:00+02:00", Ok("2026-10-25T00:30:00Z")),
            ("2026-10-25T02:30:00+01:00", Ok("2026-10-25T01:30:00Z")),
            // no offset: refused, never read as local time
            ("2026-10-25T02:30:00", BAD),
        ],
    );
}

#[test]
fn iso_leap_days_and_leap_seconds() {
    check(
        "iso",
        iso,
        &[
            ("2024-02-29T23:59:59.999999Z", Ok("2024-02-29T23:59:59.999999Z")),
            ("2000-02-29T00:00:00Z", Ok("2000-02-29T00:00:00Z")),
            ("0000-02-29T00:00:00Z", Ok("0000-02-29T00:00:00Z")),
            ("2023-02-29T00:00:00Z", BAD),
            ("1900-02-29T00:00:00Z", BAD),
            ("2024-02-30T00:00:00Z", BAD),
            ("2026-04-31T00:00:00Z", BAD),
            ("2024-02-29T23:30:00-01:00", Ok("2024-03-01T00:30:00Z")),
            ("2024-03-01T00:30:00+01:00", Ok("2024-02-29T23:30:00Z")),
            // second 60 (a leap second, at any minute) is the next minute's second 0
            ("2016-12-31T23:59:60Z", Ok("2017-01-01T00:00:00Z")),
            ("2016-12-31T23:59:60.5Z", Ok("2017-01-01T00:00:00.500Z")),
            ("2026-11-04T12:00:60Z", Ok("2026-11-04T12:01:00Z")),
            ("2016-12-31T23:59:60+01:00", Ok("2016-12-31T23:00:00Z")),
            ("2026-11-04T12:00:61Z", BAD),
        ],
    );
}

#[test]
fn iso_sub_second_precision_is_cut_to_microseconds() {
    check(
        "iso",
        iso,
        &[
            ("2026-11-04T12:00:00.5Z", Ok("2026-11-04T12:00:00.500Z")),
            ("2026-11-04T12:00:00.25Z", Ok("2026-11-04T12:00:00.250Z")),
            ("2026-11-04T12:00:00.100000Z", Ok("2026-11-04T12:00:00.100Z")),
            ("2026-11-04T12:00:00.000000Z", Ok("2026-11-04T12:00:00Z")),
            ("2026-11-04T12:00:00.1234Z", Ok("2026-11-04T12:00:00.123400Z")),
            ("2026-11-04T12:00:00.000001Z", Ok("2026-11-04T12:00:00.000001Z")),
            ("2026-11-04T12:00:00.123456Z", Ok("2026-11-04T12:00:00.123456Z")),
            // beyond microseconds: cut, never rounded
            ("2026-11-04T12:00:00.1234569Z", Ok("2026-11-04T12:00:00.123456Z")),
            ("2026-11-04T12:00:00.9999999Z", Ok("2026-11-04T12:00:00.999999Z")),
            ("2026-11-04T12:00:00.0000009Z", Ok("2026-11-04T12:00:00Z")),
            ("2026-11-04T12:00:00.999999999999999999999Z", Ok("2026-11-04T12:00:00.999999Z")),
            ("1969-12-31T23:59:59.9999999Z", Ok("1969-12-31T23:59:59.999999Z")),
            ("2026-11-04T12:00:00.Z", BAD),
            ("2026-11-04T12:00:00,5Z", BAD),
            ("2026-11-04T12:00:00.\u{e9}Z", BAD),
        ],
    );
}

#[test]
fn iso_far_past_and_far_future() {
    check(
        "iso",
        iso,
        &[
            ("0000-01-01T00:00:00Z", Ok("0000-01-01T00:00:00Z")),
            ("0001-01-01T00:00:00Z", Ok("0001-01-01T00:00:00Z")),
            ("1970-01-01T00:00:00Z", Ok("1970-01-01T00:00:00Z")),
            ("9999-12-31T23:59:59.999999Z", Ok("9999-12-31T23:59:59.999999Z")),
            // the offset may carry a time beyond 0000..9999: written with a sign
            ("0000-01-01T00:00:00+00:01", Ok("-0001-12-31T23:59:00Z")),
            ("9999-12-31T23:59:59-00:01", Ok("+10000-01-01T00:00:59Z")),
            // only four-digit years
            ("+10000-01-01T00:00:00Z", BAD),
            ("-0001-01-01T00:00:00Z", BAD),
            ("10000-01-01T00:00:00Z", BAD),
            ("999-01-01T00:00:00Z", BAD),
        ],
    );
}

#[test]
fn iso_malformed_is_bad_time() {
    check(
        "iso",
        iso,
        &[
            ("", BAD),
            ("   ", BAD),
            ("garbage", BAD),
            ("2026-11-04", BAD),
            ("2026-11-04T12:00Z", BAD),
            ("2026-11-04T12:00:00", BAD),
            ("2026-11-04T12:00:00ZZ", BAD),
            ("2026-11-04T12:00:00Z+01:00", BAD),
            ("2026-11-04T12:00:00 Z", BAD),
            ("2026-11-04X12:00:00Z", BAD),
            ("2026/11/04T12:00:00Z", BAD),
            ("2026-1-04T12:00:00Z", BAD),
            ("2026-11-4T12:00:00Z", BAD),
            ("2026-11-04T1:00:00Z", BAD),
            ("2026-00-04T12:00:00Z", BAD),
            ("2026-13-04T12:00:00Z", BAD),
            ("2026-11-00T12:00:00Z", BAD),
            ("2026-11-04T24:00:00Z", BAD),
            ("2026-11-04T23:60:00Z", BAD),
            ("2026-11-04T12:00:00+24:00", BAD),
            ("2026-11-04T12:00:00+01:60", BAD),
            ("2026-11-04T12:00:00+0100", BAD),
            ("2026-11-04T12:00:00+01", BAD),
            ("2026-11-04T12:00:00+1:00", BAD),
            ("2026-11-04T12:00:00UTC", BAD),
            ("2026-11-04T12:00:00GMT", BAD),
            ("\u{663}026-11-04T12:00:00Z", BAD),
            ("2026-11-04T12:00:00\u{2013}01:00", BAD),
            ("2026-11-04T12:00:00.5\u{e9}", BAD),
        ],
    );
    // not a text: bad_time; absent: missing_time
    check(
        "iso raw",
        |t| device_time(TimeUnit::Iso8601, &format!(r#"{{"t": {t}, "v": 1}}"#)),
        &[("1762257600", BAD), ("null", BAD), ("true", BAD), ("[\"2026-11-04T12:00:00Z\"]", BAD), ("{}", BAD)],
    );
    assert_eq!(device_time(TimeUnit::Iso8601, r#"{"v": 1}"#), Err("missing_time".into()));
}

#[test]
fn epoch_seconds() {
    check(
        "epoch_s",
        |t| epoch(TimeUnit::EpochS, t),
        &[
            ("0", Ok("1970-01-01T00:00:00Z")),
            ("-1", Ok("1969-12-31T23:59:59Z")),
            ("1709251199", Ok("2024-02-29T23:59:59Z")),
            ("1762257600", Ok("2025-11-04T12:00:00Z")),
            ("\"1762257600\"", Ok("2025-11-04T12:00:00Z")),
            ("\" 1762257600 \"", Ok("2025-11-04T12:00:00Z")),
            ("1762257600.5", Ok("2025-11-04T12:00:00.500Z")),
            ("\"1762257600.5\"", Ok("2025-11-04T12:00:00.500Z")),
            ("1.5e9", Ok("2017-07-14T02:40:00Z")),
            ("\"1.5e9\"", Ok("2017-07-14T02:40:00Z")),
            ("-0.5", Ok("1969-12-31T23:59:59.500Z")),
            // a float is rounded to the microsecond (half away from zero)
            ("0.0000005", Ok("1970-01-01T00:00:00.000001Z")),
            ("0.0000004", Ok("1970-01-01T00:00:00Z")),
            ("-0.0000005", Ok("1969-12-31T23:59:59.999999Z")),
            ("1.0000015", Ok("1970-01-01T00:00:01.000002Z")),
            // the representable range: years -262143 to 262142
            ("8210266876799", Ok("+262142-12-31T23:59:59Z")),
            ("8210266876800", BAD),
            ("-8334601228800", Ok("-262143-01-01T00:00:00Z")),
            ("-8334601228801", BAD),
            ("253402300800", Ok("+10000-01-01T00:00:00Z")),
            ("-62167219201", Ok("-0001-12-31T23:59:59Z")),
            // overflow of seconds to microseconds, and numbers beyond i64
            ("9223372036854775807", BAD),
            ("-9223372036854775808", BAD),
            ("18446744073709551615", BAD),
            ("9.0e12", BAD),
            ("1e300", BAD),
            ("\"NaN\"", BAD),
            ("\"inf\"", BAD),
            ("\"-inf\"", BAD),
            ("\"\"", BAD),
            ("\"0x10\"", BAD),
            ("\"12abc\"", BAD),
            ("\"2026-11-04T12:00:00Z\"", BAD),
            ("true", BAD),
            ("null", BAD),
            ("[1]", BAD),
        ],
    );
}

#[test]
fn epoch_milliseconds() {
    check(
        "epoch_ms",
        |t| epoch(TimeUnit::EpochMs, t),
        &[
            ("0", Ok("1970-01-01T00:00:00Z")),
            ("1", Ok("1970-01-01T00:00:00.001Z")),
            ("-1", Ok("1969-12-31T23:59:59.999Z")),
            ("1762257600123", Ok("2025-11-04T12:00:00.123Z")),
            ("\"1762257600123\"", Ok("2025-11-04T12:00:00.123Z")),
            ("1762257600123.4", Ok("2025-11-04T12:00:00.123400Z")),
            ("1762257600123.4567", Ok("2025-11-04T12:00:00.123457Z")),
            ("0.0005", Ok("1970-01-01T00:00:00.000001Z")),
            ("1709251199999", Ok("2024-02-29T23:59:59.999Z")),
            ("8210266876799999", Ok("+262142-12-31T23:59:59.999Z")),
            ("8210266876800000", BAD),
            ("-8334601228800000", Ok("-262143-01-01T00:00:00Z")),
            ("-8334601228800001", BAD),
            ("9223372036854775807", BAD),
            ("\"x\"", BAD),
        ],
    );
}

// ---- POST /decode: received_at as the request gives it, the time rule's borders, the text written back ----

fn state(config: Option<Config>) -> AppState {
    AppState { shared: Arc::new(Shared::default()), config: Arc::new(RwLock::new(config.map(Arc::new))) }
}

fn config(future_skew_s: i64, late_limit_days: i64) -> Config {
    let mut c = cfgt::contract();
    c.future_skew_s = future_skew_s;
    c.late_limit_days = late_limit_days;
    build(c, vec![cfgt::row(1, 10, "farm/plc", 1)]).unwrap()
}

async fn post(s: &AppState, body: Value) -> (StatusCode, Value) {
    let req = Request::post("/decode").header("content-type", "application/json").body(Body::from(body.to_string()));
    let resp = router(s.clone()).oneshot(req.unwrap()).await.unwrap();
    let status = resp.status();
    let bytes = axum::body::to_bytes(resp.into_body(), 1 << 20).await.unwrap();
    (status, serde_json::from_slice(&bytes).unwrap_or(Value::Null))
}

/// What /decode stores a message at: `(ts, quality)`, or the faults; the request's status when it is refused.
async fn stored(s: &AppState, time_path: &str, payload: Value, received_at: &str) -> Result<(String, i64), String> {
    let (code, body) = post(
        s,
        json!({
            "format": {"shape": "object", "time_path": time_path, "time_unit": "iso8601"},
            "channels": [{"channel_no": 1, "value_path": "/v"}],
            "payload": payload.to_string(),
            "received_at": received_at,
        }),
    )
    .await;
    if code != StatusCode::OK {
        return Err(format!("http {}", code.as_u16()));
    }
    match body["samples"].as_array().map(Vec::as_slice) {
        Some([x]) => Ok((x["ts"].as_str().unwrap().to_owned(), x["quality"].as_i64().unwrap())),
        _ => Err(body["faults"].to_string()),
    }
}

/// The receive time as /decode reads it: a message without a time path is stored at it (flagged RECEIVE_TIME).
async fn received(text: &str) -> Result<String, String> {
    let rt = i64::from(crate::quality::RECEIVE_TIME);
    match stored(&state(None), "", json!({"v": 1}), text).await {
        Ok((ts, q)) if q == rt => Ok(ts),
        Ok(other) => panic!("{text:?}: {other:?}"),
        Err(e) => Err(e),
    }
}

#[tokio::test]
async fn decode_reads_received_at_in_the_relaxed_rfc3339_form() {
    const REFUSED: Result<&str, &str> = Err("http 422");
    let cases: &[(&str, Result<&str, &str>)] = &[
        ("2026-11-04T12:00:01Z", Ok("2026-11-04T12:00:01Z")),
        ("2026-11-04t12:00:01z", Ok("2026-11-04T12:00:01Z")),
        ("2026-11-04 12:00:01Z", Ok("2026-11-04T12:00:01Z")),
        ("2026-11-04T13:00:01+01:00", Ok("2026-11-04T12:00:01Z")),
        ("2026-11-04T13:00:01 +01:00", Ok("2026-11-04T12:00:01Z")),
        ("2026-11-04T13:00:01+0100", Ok("2026-11-04T12:00:01Z")),
        ("2026-11-04T13:00:01+01 00", Ok("2026-11-04T12:00:01Z")),
        ("2026-11-04T11:00:01\u{2212}01:00", Ok("2026-11-04T12:00:01Z")),
        ("2026-11-04T12:00:01UTC", Ok("2026-11-04T12:00:01Z")),
        ("2026-11-04T12:00:01 utc", Ok("2026-11-04T12:00:01Z")),
        ("2026-1-4T1:2:3Z", Ok("2026-01-04T01:02:03Z")),
        (" 2026-11-04T12:00:01Z ", Ok("2026-11-04T12:00:01Z")),
        ("2026 - 11 - 04T12 : 00 : 01Z", Ok("2026-11-04T12:00:01Z")),
        ("+12026-11-04T12:00:01Z", Ok("+12026-11-04T12:00:01Z")),
        ("-0001-12-31T23:59:59Z", Ok("-0001-12-31T23:59:59Z")),
        ("+262142-12-31T23:59:59.999999Z", Ok("+262142-12-31T23:59:59.999999Z")),
        ("-262143-01-01T00:00:00Z", Ok("-262143-01-01T00:00:00Z")),
        ("+262143-01-01T00:00:00Z", REFUSED),
        ("-262144-12-31T23:59:59Z", REFUSED),
        ("+262142-12-31T23:59:59-00:01", REFUSED),
        ("-262143-01-01T00:00:00+00:01", REFUSED),
        ("2026-11-04T12:00:01.1234567Z", Ok("2026-11-04T12:00:01.123456Z")),
        ("2026-11-04T12:00:01.5Z", Ok("2026-11-04T12:00:01.500Z")),
        ("2026-11-04T12:00:60Z", Ok("2026-11-04T12:01:00Z")),
        ("2026-11-04T12:00:60.25Z", Ok("2026-11-04T12:01:00.250Z")),
        ("2024-02-29T00:00:00Z", Ok("2024-02-29T00:00:00Z")),
        ("2026-10-25T02:30:00+02:00", Ok("2026-10-25T00:30:00Z")),
        ("2026-10-25T02:30:00+01:00", Ok("2026-10-25T01:30:00Z")),
        ("2023-02-29T00:00:00Z", REFUSED),
        ("2026-11-04T12:00:01", REFUSED),
        ("2026-11-04T12:00:01+01", REFUSED),
        ("2026-11-04T12:00:01+24:00", REFUSED),
        ("2026-11-04T12:00:01+01:60", REFUSED),
        ("2026-11-04T24:00:00Z", REFUSED),
        ("2026-11-04T12:00:61Z", REFUSED),
        ("12026-11-04T12:00:01Z", REFUSED),
        ("2026-11-04T12:00:01.Z", REFUSED),
        ("2026-11-04T12:00:01ZZ", REFUSED),
        ("2026-11-04", REFUSED),
        ("", REFUSED),
        ("garbage", REFUSED),
    ];
    let mut bad = Vec::new();
    for (input, want) in cases {
        let got = received(input).await;
        let want = want.map(str::to_owned).map_err(str::to_owned);
        if got != want {
            bad.push(format!("received_at {input:?}: got {got:?}, want {want:?}"));
        }
    }
    assert!(bad.is_empty(), "\n{}", bad.join("\n"));
    // not a text, or null (= now): a number is refused
    let s = state(None);
    let (code, _) = post(
        &s,
        json!({"format": {"shape": "object", "time_unit": "iso8601"}, "channels": [], "payload": "{}", "received_at": 5}),
    )
    .await;
    assert_eq!(code, StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn decode_time_rule_borders_at_microsecond_precision() {
    let s = state(None); // no configuration: future skew 60 s, late limit 728 days
    let at = |t: &str| json!({"t": t, "v": 1});
    let r = "2026-11-04T12:00:00Z";
    let suspect = i64::from(crate::quality::CLOCK_SUSPECT);
    assert_eq!(stored(&s, "/t", at("2026-11-04T12:01:00Z"), r).await, Ok(("2026-11-04T12:01:00Z".into(), 0)));
    assert_eq!(
        stored(&s, "/t", at("2026-11-04T12:01:00.000001Z"), r).await,
        Ok(("2026-11-04T12:00:00Z".into(), suspect))
    );
    // 728 days before 2026-11-04 is 2024-11-06 (2024-02-29 lies outside the window)
    assert_eq!(stored(&s, "/t", at("2024-11-06T12:00:00Z"), r).await, Ok(("2024-11-06T12:00:00Z".into(), 0)));
    assert_eq!(stored(&s, "/t", at("2024-11-06T11:59:59.999999Z"), r).await, Err("[\"too_old\"]".into()));
    // a window across a leap day: 728 days before 2025-02-28 is 2023-03-03
    let r = "2025-02-28T00:00:00Z";
    assert_eq!(stored(&s, "/t", at("2023-03-03T00:00:00Z"), r).await, Ok(("2023-03-03T00:00:00Z".into(), 0)));
    assert_eq!(stored(&s, "/t", at("2023-03-02T23:59:59.999999Z"), r).await, Err("[\"too_old\"]".into()));
    // both times are cut to microseconds before they are compared
    let r = "2026-11-04T12:00:00.0000009Z";
    assert_eq!(stored(&s, "/t", at("2026-11-04T12:01:00.0000009Z"), r).await, Ok(("2026-11-04T12:01:00Z".into(), 0)));
    assert_eq!(
        stored(&s, "/t", at("2026-11-04T12:01:00.000001Z"), r).await,
        Ok(("2026-11-04T12:00:00Z".into(), suspect))
    );
    // the receive time is stored cut, and written back in the shortest of .3 / .6 digits
    assert_eq!(received("2026-11-04T12:00:00.120000Z").await, Ok("2026-11-04T12:00:00.120Z".into()));
    assert_eq!(received("2026-11-04T12:00:00.000999999Z").await, Ok("2026-11-04T12:00:00.000999Z".into()));
}

#[tokio::test]
async fn decode_time_rule_limits_beyond_the_representable_range() {
    let at = |t: &str| json!({"t": t, "v": 1});
    let r = "2026-11-04T12:00:00Z";
    let suspect = i64::from(crate::quality::CLOCK_SUSPECT);
    let old = at("1970-01-01T00:00:00Z");
    let now = at(r);
    let far = at("9999-12-31T23:59:59Z");
    // a zero skew accepts up to receipt; a negative one flags even the receive time itself
    let s = state(Some(config(0, 728)));
    assert_eq!(stored(&s, "/t", now.clone(), r).await, Ok((r.into(), 0)));
    let s = state(Some(config(-1, 728)));
    assert_eq!(stored(&s, "/t", now.clone(), r).await, Ok((r.into(), suspect)));
    // a skew so far back that the earliest accepted time is not representable: no skew check at all
    let s = state(Some(config(-9_000_000_000_000, 728)));
    assert_eq!(stored(&s, "/t", far.clone(), r).await, Ok(("9999-12-31T23:59:59Z".into(), 0)));
    // ... or not even a duration (chrono's limit, i64::MAX milliseconds)
    let s = state(Some(config(i64::MIN, 728)));
    assert_eq!(stored(&s, "/t", far.clone(), r).await, Ok(("9999-12-31T23:59:59Z".into(), 0)));
    let s = state(Some(config(i64::MAX, 728)));
    assert_eq!(stored(&s, "/t", far.clone(), r).await, Ok(("9999-12-31T23:59:59Z".into(), 0)));
    let s = state(Some(config(9_223_372_036_854_775, 728)));
    assert_eq!(stored(&s, "/t", far.clone(), r).await, Ok(("9999-12-31T23:59:59Z".into(), 0)));
    // a late limit of 0 refuses anything before receipt; a negative one refuses even the receive time
    let s = state(Some(config(60, 0)));
    assert_eq!(stored(&s, "/t", now.clone(), r).await, Ok((r.into(), 0)));
    assert_eq!(stored(&s, "/t", at("2026-11-04T11:59:59.999999Z"), r).await, Err("[\"too_old\"]".into()));
    let s = state(Some(config(60, -1)));
    assert_eq!(stored(&s, "/t", now.clone(), r).await, Err("[\"too_old\"]".into()));
    // a late limit beyond the representable range (or beyond a duration): nothing is too old
    for days in [100_000_000, -100_000_000, 106_751_991_167, 106_751_991_168, i64::MAX, i64::MIN] {
        let s = state(Some(config(60, days)));
        assert_eq!(stored(&s, "/t", old.clone(), r).await, Ok(("1970-01-01T00:00:00Z".into(), 0)), "days {days}");
    }
}
