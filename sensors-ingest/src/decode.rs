//! Decode one MQTT message into raw samples (plan 2.1 PayloadFormat): a pure function, no I/O. The time rule and the
//! calibration are applied after it (`timerule`, `calib`). Golden vectors: `sensors/tests/vectors.json`.
//!
//! Rules:
//! - a payload larger than `MAX_PAYLOAD` is `oversize`; a payload that is not JSON is `not_json`;
//! - object shape: each channel's value is at its `value_path`; array shape: the items are at `items_path` (blank =
//!   the message is the array), an item belongs to the channel whose `item_name` equals the item's `name_key` field
//!   (numbers compared as text), its value is the `value_key` field;
//! - a value is a JSON number, a boolean (1/0) or a text holding a finite number; `null` is `missing_value`; anything
//!   else `bad_value`. A channel whose path is absent from the message is simply not in it (no fault); when no channel
//!   is found at all the message is `no_channel_match`;
//! - time: blank `time_path` gives no device time (the receive time is used, flagged); otherwise the time is read at
//!   `time_path` (array shape: inside the item first, then at the root); absent is `missing_time`, unreadable is
//!   `bad_time`, and the samples it would have dated are not kept. ISO 8601 needs an offset. Times are cut to
//!   microseconds (the stored precision);
//! - the sequence number at `seq_path` is kept when it is an integer and ignored otherwise (monitoring only).
//!
//! Good samples of a partly bad message are kept; each distinct fault becomes one dead letter of the message.

use crate::model::{ChannelMap, DeadReason, Format, Shape, TimeUnit};
use crate::ts::Ts;
use serde::Serialize;
use serde_json::Value;
use std::collections::BTreeSet;

/// The largest payload decoded; the broker's own limit is larger, so a bigger message reaches us and is dead-lettered
/// (evidence) rather than refused by the broker unseen.
pub const MAX_PAYLOAD: usize = 64 * 1024;

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct RawSample {
    pub channel_no: i32,
    pub value: f64,
    /// None when the format has no time path: the receive time is used.
    pub device_ts: Option<Ts>,
}

#[derive(Debug, Clone, PartialEq, Default, Serialize)]
pub struct Decoded {
    pub seq: Option<i64>,
    pub samples: Vec<RawSample>,
    /// Distinct, sorted.
    pub faults: Vec<DeadReason>,
}

pub fn decode(format: &Format, channels: &[ChannelMap], payload: &[u8]) -> Decoded {
    if payload.len() > MAX_PAYLOAD {
        return fault_only(DeadReason::Oversize);
    }
    // serde_json refuses nesting deeper than 128 levels, so hostile input cannot exhaust the stack.
    let Ok(root) = serde_json::from_slice::<Value>(payload) else {
        return fault_only(DeadReason::NotJson);
    };
    let mut out = Decoded { seq: pointer(&root, &format.seq_path).and_then(Value::as_i64), ..Decoded::default() };
    let mut faults = BTreeSet::new();
    let mut found = false;
    match format.shape {
        Shape::Object => {
            let time = read_time(format, &[&root]);
            for ch in channels {
                let Some(v) = pointer(&root, &ch.value_path) else { continue };
                found = true;
                take(&mut out.samples, &mut faults, ch.channel_no, v, &time);
            }
        }
        Shape::Array => {
            let items = if format.items_path.is_empty() { Some(&root) } else { pointer(&root, &format.items_path) };
            for item in items.and_then(Value::as_array).map(Vec::as_slice).unwrap_or_default() {
                let Some(name) = item.get(&format.name_key).and_then(as_name) else { continue };
                let mut time = None;
                for ch in channels.iter().filter(|c| !c.item_name.is_empty() && c.item_name == name) {
                    found = true;
                    let v = item.get(&format.value_key).unwrap_or(&Value::Null);
                    let t = time.get_or_insert_with(|| read_time(format, &[item, &root]));
                    take(&mut out.samples, &mut faults, ch.channel_no, v, t);
                }
            }
        }
    }
    if !found {
        faults.insert(DeadReason::NoChannelMatch);
    }
    out.faults = faults.into_iter().collect();
    out
}

fn fault_only(r: DeadReason) -> Decoded {
    Decoded { faults: vec![r], ..Decoded::default() }
}

/// RFC 6901 pointer; a blank path is "not configured" (None), never the whole document.
fn pointer<'a>(root: &'a Value, path: &str) -> Option<&'a Value> {
    if path.is_empty() { None } else { root.pointer(path) }
}

fn as_name(v: &Value) -> Option<String> {
    match v {
        Value::String(s) => Some(s.clone()),
        Value::Number(n) => Some(n.to_string()),
        _ => None,
    }
}

/// None: no time path (receive time). Some(Ok): the device time. Some(Err): missing or unreadable.
type Time = Option<Result<Ts, DeadReason>>;

fn read_time(format: &Format, scopes: &[&Value]) -> Time {
    if format.time_path.is_empty() {
        return None;
    }
    let Some(v) = scopes.iter().find_map(|s| s.pointer(&format.time_path)) else {
        return Some(Err(DeadReason::MissingTime));
    };
    Some(parse_time(format.time_unit, v).map(Ts::trunc_micros).ok_or(DeadReason::BadTime))
}

fn parse_time(unit: TimeUnit, v: &Value) -> Option<Ts> {
    match unit {
        TimeUnit::Iso8601 => Ts::parse_rfc3339(v.as_str()?.trim()),
        TimeUnit::EpochS | TimeUnit::EpochMs => {
            let scale = if unit == TimeUnit::EpochS { 1_000_000 } else { 1_000 };
            match v {
                Value::Number(n) => match n.as_i64() {
                    Some(i) => Ts::from_unix_micros(i.checked_mul(scale)?),
                    None => from_float_micros(n.as_f64()?, scale),
                },
                Value::String(s) => {
                    let s = s.trim();
                    match s.parse::<i64>() {
                        Ok(i) => Ts::from_unix_micros(i.checked_mul(scale)?),
                        Err(_) => from_float_micros(s.parse::<f64>().ok()?, scale),
                    }
                }
                _ => None,
            }
        }
    }
}

fn from_float_micros(x: f64, scale: i64) -> Option<Ts> {
    #[allow(clippy::cast_precision_loss)]
    let micros = (x * scale as f64).round();
    // i64 microseconds cover +-292k years; anything beyond is not a time.
    if !micros.is_finite() || micros.abs() >= 9.0e18 {
        return None;
    }
    #[allow(clippy::cast_possible_truncation)]
    Ts::from_unix_micros(micros as i64)
}

fn as_value(v: &Value) -> Result<f64, DeadReason> {
    let x = match v {
        Value::Null => return Err(DeadReason::MissingValue),
        Value::Bool(b) => f64::from(u8::from(*b)),
        Value::Number(n) => n.as_f64().ok_or(DeadReason::BadValue)?,
        Value::String(s) => s.trim().parse::<f64>().map_err(|_| DeadReason::BadValue)?,
        Value::Array(_) | Value::Object(_) => return Err(DeadReason::BadValue),
    };
    if x.is_finite() { Ok(x) } else { Err(DeadReason::BadValue) }
}

fn take(samples: &mut Vec<RawSample>, faults: &mut BTreeSet<DeadReason>, channel_no: i32, v: &Value, time: &Time) {
    let value = match as_value(v) {
        Ok(x) => x,
        Err(r) => {
            faults.insert(r);
            return;
        }
    };
    let device_ts = match time {
        None => None,
        Some(Ok(t)) => Some(*t),
        Some(Err(r)) => {
            faults.insert(*r);
            return;
        }
    };
    samples.push(RawSample { channel_no, value, device_ts });
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{Shape, TimeUnit};
    use serde::Deserialize;

    #[derive(Deserialize)]
    struct File {
        vectors: Vec<Vector>,
    }
    #[derive(Deserialize)]
    struct Vector {
        name: String,
        format: Format,
        channels: Vec<ChannelMap>,
        payload: Option<serde_json::Value>,
        payload_text: Option<String>,
        expect: Expect,
    }
    #[derive(Deserialize)]
    struct Expect {
        seq: Option<i64>,
        faults: Vec<DeadReason>,
        samples: Vec<ExpectSample>,
    }
    #[derive(Deserialize)]
    struct ExpectSample {
        channel_no: i32,
        value: f64,
        device_ts: Option<Ts>,
    }

    fn vectors() -> Vec<Vector> {
        let path = concat!(env!("CARGO_MANIFEST_DIR"), "/../sensors/tests/vectors.json");
        let text = std::fs::read_to_string(path).expect("golden vectors");
        serde_json::from_str::<File>(&text).expect("vectors parse").vectors
    }

    #[test]
    fn golden_vectors() {
        let all = vectors();
        assert!(all.len() >= 20);
        for v in all {
            let bytes = match (&v.payload, &v.payload_text) {
                (Some(p), None) => serde_json::to_vec(p).unwrap(),
                (None, Some(t)) => t.as_bytes().to_vec(),
                _ => panic!("{}: payload or payload_text", v.name),
            };
            let got = decode(&v.format, &v.channels, &bytes);
            assert_eq!(got.seq, v.expect.seq, "{} seq", v.name);
            assert_eq!(got.faults, v.expect.faults, "{} faults", v.name);
            let want: Vec<RawSample> = v
                .expect
                .samples
                .iter()
                .map(|s| RawSample { channel_no: s.channel_no, value: s.value, device_ts: s.device_ts })
                .collect();
            assert_eq!(got.samples, want, "{} samples", v.name);
        }
    }

    fn object() -> Format {
        Format {
            shape: Shape::Object,
            time_path: String::new(),
            time_unit: TimeUnit::Iso8601,
            seq_path: String::new(),
            items_path: String::new(),
            name_key: String::new(),
            value_key: String::new(),
        }
    }

    #[test]
    fn oversize_is_refused_before_parsing() {
        let ch = [ChannelMap { channel_no: 1, value_path: "/v".into(), item_name: String::new() }];
        let mut big = br#"{"v": 1, "pad": ""#.to_vec();
        big.extend(std::iter::repeat_n(b'x', MAX_PAYLOAD));
        big.extend(br#""}"#);
        let got = decode(&object(), &ch, &big);
        assert_eq!(got.faults, vec![DeadReason::Oversize]);
        assert!(got.samples.is_empty());
        let mut fits = br#"{"v": 1, "pad": ""#.to_vec();
        fits.extend(std::iter::repeat_n(b'x', MAX_PAYLOAD - fits.len() - 2));
        fits.extend(br#""}"#);
        assert_eq!(fits.len(), MAX_PAYLOAD);
        assert_eq!(decode(&object(), &ch, &fits).samples.len(), 1);
    }

    #[test]
    fn deeply_nested_garbage_does_not_overflow_the_stack() {
        let ch = [ChannelMap { channel_no: 1, value_path: "/v".into(), item_name: String::new() }];
        let deep = "[".repeat(50_000);
        assert_eq!(decode(&object(), &ch, deep.as_bytes()).faults, vec![DeadReason::NotJson]);
    }

    #[test]
    fn invalid_utf8_and_empty_payloads_are_not_json() {
        let ch = [ChannelMap { channel_no: 1, value_path: "/v".into(), item_name: String::new() }];
        assert_eq!(decode(&object(), &ch, &[0xff, 0xfe, b'{']).faults, vec![DeadReason::NotJson]);
        assert_eq!(decode(&object(), &ch, b"").faults, vec![DeadReason::NotJson]);
    }

    mod props {
        use super::*;
        use proptest::prelude::*;

        proptest! {
            // Whatever bytes arrive, decode returns (never panics) and either keeps samples or names a fault.
            #[test]
            fn any_bytes_decode_without_panic(bytes in proptest::collection::vec(any::<u8>(), 0..512)) {
                let ch = [ChannelMap { channel_no: 1, value_path: "/v".into(), item_name: String::new() }];
                let got = decode(&object(), &ch, &bytes);
                prop_assert!(!got.samples.is_empty() || !got.faults.is_empty());
                prop_assert!(got.samples.iter().all(|s| s.value.is_finite()));
            }

            // Any finite number written in a message comes back bit for bit.
            #[test]
            fn finite_numbers_round_trip(x in any::<f64>().prop_filter("finite", |x| x.is_finite())) {
                let ch = [ChannelMap { channel_no: 7, value_path: "/v".into(), item_name: String::new() }];
                let payload = serde_json::to_vec(&serde_json::json!({"v": x})).unwrap();
                let got = decode(&object(), &ch, &payload);
                prop_assert_eq!(got.faults.len(), 0);
                prop_assert_eq!(got.samples.len(), 1);
                prop_assert_eq!(got.samples[0].value.to_bits(), x.to_bits());
            }

            // Epoch milliseconds keep their millisecond.
            #[test]
            fn epoch_ms_exact(ms in 0i64..4_102_444_800_000) {
                let mut f = object();
                f.time_path = "/t".into();
                f.time_unit = TimeUnit::EpochMs;
                let ch = [ChannelMap { channel_no: 7, value_path: "/v".into(), item_name: String::new() }];
                let payload = serde_json::to_vec(&serde_json::json!({"t": ms, "v": 1})).unwrap();
                let got = decode(&f, &ch, &payload);
                prop_assert_eq!(got.samples[0].device_ts.map(Ts::unix_millis), Some(ms));
            }
        }
    }
}
