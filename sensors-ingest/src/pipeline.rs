//! One batch of messages through route, decode, time rule, calibration, judgement and reducer: pure, no I/O. The
//! result is exactly what the writer commits in one transaction (readings, the final state of every touched channel,
//! device counters, dead letters aggregated by their unique key). The committed states are only read; the caller
//! replaces them with `Output::states` after COMMIT, so a failed transaction leaves the in-memory state as committed.

use crate::calib;
use crate::config::Config;
use crate::decode::decode;
use crate::model::DeadReason;
use crate::reduce::{self, Row, Sample, State};
use crate::timerule::{self, Limits};
use chrono::{DateTime, Utc};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, HashMap, HashSet};
use uuid::Uuid;

/// Bytes of a dead message kept (the table's CHECK).
pub const DEAD_PAYLOAD_MAX: usize = 4096;
/// New distinct dead letters per connection and hour before they fold into the `overflow` row.
pub const DEAD_PER_HOUR: usize = 1000;
pub const OVERFLOW: &str = "overflow";

#[derive(Debug, Clone, PartialEq)]
pub struct Msg {
    pub connection_id: Uuid,
    pub topic: String,
    pub payload: Vec<u8>,
    pub received_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Reading {
    pub channel_no: i32,
    pub row: Row,
}

#[derive(Debug, Clone, Default, PartialEq)]
pub struct DeviceDelta {
    pub last_message_at: Option<DateTime<Utc>>,
    pub last_seq: Option<i64>,
    pub accepted: i64,
    pub late: i64,
    pub dead: i64,
    pub ignored: i64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct DeadLetter {
    pub connection_id: Uuid,
    pub device_id: Option<Uuid>,
    pub topic: String,
    pub reason: DeadReason,
    pub payload_sha256: String,
    pub payload: Vec<u8>,
    pub payload_len: i32,
    pub count: i32,
    pub first_at: DateTime<Utc>,
    pub last_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Default, PartialEq)]
pub struct Output {
    pub readings: Vec<Reading>,
    pub states: BTreeMap<i32, State>,
    pub devices: BTreeMap<Uuid, DeviceDelta>,
    pub dead: Vec<DeadLetter>,
}

/// Bounds the dead letters a flood can create: per connection and clock hour, at most `cap` distinct keys keep their
/// own row; the rest are counted on the `overflow` row of their (topic, reason). Memory is at most `cap` keys per
/// connection.
#[derive(Debug, Clone)]
pub struct DeadLimiter {
    cap: usize,
    per_conn: HashMap<Uuid, (i64, HashSet<(String, DeadReason, String)>)>,
}

impl DeadLimiter {
    pub fn new(cap: usize) -> Self {
        DeadLimiter { cap, per_conn: HashMap::new() }
    }
}

pub fn process(_cfg: &Config, _committed: &HashMap<i32, State>, _limiter: &mut DeadLimiter, _msgs: &[Msg]) -> Output {
    todo!("process")
}

pub fn sha256_hex(bytes: &[u8]) -> String {
    let mut h = Sha256::new();
    h.update(bytes);
    h.finalize().iter().map(|b| format!("{b:02x}")).collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::{build, tests as cfgt};
    use crate::quality::{CLOCK_SUSPECT, HEARTBEAT, LATE, MAINTENANCE, OUT_OF_RANGE, RECEIVE_TIME};
    use chrono::{Duration, TimeZone};

    fn now() -> DateTime<Utc> {
        Utc.with_ymd_and_hms(2026, 11, 4, 12, 0, 0).unwrap()
    }
    fn conn() -> Uuid {
        Uuid::from_u128(1)
    }
    fn dev() -> Uuid {
        Uuid::from_u128(10)
    }
    fn cfg() -> Config {
        let mut r1 = cfgt::row(1, 10, "farm/plc", 1);
        r1.a = 2.0;
        r1.b = 1.0;
        let mut r2 = cfgt::row(1, 10, "farm/plc", 2);
        r2.channel_state = "maintenance".into();
        r2.reduction = "all".into();
        r2.deadband = 0.0;
        build(cfgt::contract(), vec![r1, r2]).unwrap()
    }
    fn msg(body: serde_json::Value, at: DateTime<Utc>) -> Msg {
        Msg {
            connection_id: conn(),
            topic: "farm/plc".into(),
            payload: serde_json::to_vec(&body).unwrap(),
            received_at: at,
        }
    }
    fn iso(t: DateTime<Utc>) -> String {
        t.to_rfc3339()
    }

    #[test]
    fn a_message_becomes_calibrated_judged_rows_state_and_device_counters() {
        let m = msg(serde_json::json!({"ts": iso(now()), "seq": 5, "v1": 10.0, "v2": 3.0}), now());
        let out = process(&cfg(), &HashMap::new(), &mut DeadLimiter::new(10), &[m]);
        assert_eq!(out.readings.len(), 2);
        let r1 = out.readings.iter().find(|r| r.channel_no == 1).unwrap();
        assert_eq!((r1.row.ts, r1.row.value, r1.row.quality, r1.row.n), (now(), 21.0, 0, 1));
        let r2 = out.readings.iter().find(|r| r.channel_no == 2).unwrap();
        assert_eq!(r2.row.quality, MAINTENANCE);
        assert_eq!(out.states[&1].anchor_value, Some(21.0));
        assert_eq!(out.states[&1].last_seen_at, Some(now()));
        // a maintenance value is bad: seen, but not the latest good value
        assert_eq!(out.states[&2].last_value, None);
        let d = &out.devices[&dev()];
        assert_eq!(
            d,
            &DeviceDelta { last_message_at: Some(now()), last_seq: Some(5), accepted: 1, late: 0, dead: 0, ignored: 0 }
        );
        assert!(out.dead.is_empty());
    }

    #[test]
    fn out_of_range_after_calibration_is_stored_flagged() {
        // range -5..40; raw 20 -> 41
        let m = msg(serde_json::json!({"ts": iso(now()), "v1": 20.0}), now());
        let out = process(&cfg(), &HashMap::new(), &mut DeadLimiter::new(10), &[m]);
        assert_eq!(out.readings[0].row.quality, OUT_OF_RANGE);
        assert_eq!(out.readings[0].row.value, 41.0);
    }

    #[test]
    fn the_time_rule_flags_and_refuses() {
        let ahead = msg(serde_json::json!({"ts": iso(now() + Duration::minutes(10)), "v1": 1.0}), now());
        let old = msg(serde_json::json!({"ts": iso(now() - Duration::days(800)), "v1": 1.0}), now());
        let out = process(&cfg(), &HashMap::new(), &mut DeadLimiter::new(10), &[ahead, old]);
        assert_eq!(out.readings.len(), 1);
        assert_eq!((out.readings[0].row.ts, out.readings[0].row.quality), (now(), CLOCK_SUSPECT));
        assert_eq!(out.dead.len(), 1);
        assert_eq!(out.dead[0].reason, DeadReason::TooOld);
        assert_eq!(out.dead[0].device_id, Some(dev()));
        assert_eq!(out.devices[&dev()].dead, 1);
        assert_eq!(out.devices[&dev()].accepted, 1);
    }

    #[test]
    fn no_time_path_gives_receive_time() {
        let mut r = cfgt::row(1, 10, "farm/plc", 1);
        r.time_path = String::new();
        let c = build(cfgt::contract(), vec![r]).unwrap();
        let m = msg(serde_json::json!({"v1": 1.0}), now() + Duration::nanoseconds(1_234_567));
        let out = process(&c, &HashMap::new(), &mut DeadLimiter::new(10), &[m]);
        assert_eq!(out.readings[0].row.quality, RECEIVE_TIME);
        assert_eq!(out.readings[0].row.ts, now() + Duration::microseconds(1234));
    }

    #[test]
    fn unrouted_and_undecodable_messages_are_dead_letters_with_hash_and_capped_payload() {
        let big = vec![b'x'; 5000];
        let m1 = Msg { connection_id: conn(), topic: "nobody/here".into(), payload: big.clone(), received_at: now() };
        let m2 =
            Msg { connection_id: conn(), topic: "farm/plc".into(), payload: b"{oops".to_vec(), received_at: now() };
        let out = process(&cfg(), &HashMap::new(), &mut DeadLimiter::new(10), &[m1, m2]);
        assert!(out.readings.is_empty());
        let nr = out.dead.iter().find(|d| d.reason == DeadReason::NoRoute).unwrap();
        assert_eq!((nr.device_id, nr.payload.len(), nr.payload_len), (None, DEAD_PAYLOAD_MAX, 5000));
        assert_eq!(nr.payload_sha256, sha256_hex(&big));
        assert_eq!(nr.payload_sha256.len(), 64);
        let nj = out.dead.iter().find(|d| d.reason == DeadReason::NotJson).unwrap();
        assert_eq!(nj.device_id, Some(dev()));
        assert_eq!(out.devices[&dev()].dead, 1);
        assert_eq!(out.devices[&dev()].accepted, 0);
    }

    #[test]
    fn the_same_dead_message_twice_in_a_batch_is_one_row_counted_twice() {
        let m =
            Msg { connection_id: conn(), topic: "farm/plc".into(), payload: b"garbage".to_vec(), received_at: now() };
        let mut m2 = m.clone();
        m2.received_at = now() + Duration::seconds(1);
        let out = process(&cfg(), &HashMap::new(), &mut DeadLimiter::new(10), &[m, m2]);
        assert_eq!(out.dead.len(), 1);
        assert_eq!(
            (out.dead[0].count, out.dead[0].first_at, out.dead[0].last_at),
            (2, now(), now() + Duration::seconds(1))
        );
    }

    #[test]
    fn a_flood_of_distinct_garbage_folds_into_the_overflow_row_per_hour() {
        let msgs: Vec<Msg> = (0..25)
            .map(|i| Msg {
                connection_id: conn(),
                topic: "farm/plc".into(),
                payload: format!("junk {i}").into_bytes(),
                received_at: now(),
            })
            .collect();
        let mut lim = DeadLimiter::new(10);
        let out = process(&cfg(), &HashMap::new(), &mut lim, &msgs);
        assert_eq!(out.dead.len(), 11);
        let over = out.dead.iter().find(|d| d.payload_sha256 == OVERFLOW).unwrap();
        assert_eq!((over.count, over.payload.len(), over.reason), (15, 0, DeadReason::NotJson));
        // a key already seen this hour keeps its row
        let again = process(&cfg(), &HashMap::new(), &mut lim, &msgs[..1]);
        assert_eq!(again.dead[0].payload_sha256, sha256_hex(b"junk 0"));
        // the next hour starts a new allowance
        let mut next = msgs[20].clone();
        next.received_at = now() + Duration::hours(1);
        let later = process(&cfg(), &HashMap::new(), &mut lim, &[next]);
        assert_eq!(later.dead[0].payload_sha256, sha256_hex(b"junk 20"));
    }

    #[test]
    fn the_batch_works_on_a_copy_of_the_committed_state() {
        let mut committed = HashMap::new();
        let m = msg(serde_json::json!({"ts": iso(now()), "v1": 10.0}), now());
        let out = process(&cfg(), &committed, &mut DeadLimiter::new(10), &[m.clone()]);
        assert!(committed.is_empty());
        committed.extend(out.states);
        // redelivered: late path, the stored row conflicts in the database
        let out2 = process(&cfg(), &committed, &mut DeadLimiter::new(10), &[m]);
        assert_eq!(out2.readings[0].row.quality, LATE);
        assert_eq!(out2.devices[&dev()].late, 1);
        assert_eq!(out2.devices[&dev()].accepted, 1);
    }

    #[test]
    fn suppressed_samples_carry_into_the_closing_row_across_messages_of_one_batch() {
        let msgs: Vec<Msg> = (0..=6)
            .map(|i| {
                let t = now() + Duration::seconds(i * 10);
                msg(serde_json::json!({"ts": iso(t), "v1": 10.0}), t)
            })
            .collect();
        let out = process(&cfg(), &HashMap::new(), &mut DeadLimiter::new(10), &msgs);
        let rows: Vec<&Row> = out.readings.iter().filter(|r| r.channel_no == 1).map(|r| &r.row).collect();
        assert_eq!(rows.len(), 2);
        assert_eq!((rows[1].n, rows[1].quality), (6, HEARTBEAT));
        assert_eq!(out.states[&1].run_n, 0);
        assert_eq!(out.devices[&dev()].accepted, 7);
    }

    #[test]
    fn a_calibration_that_overflows_is_a_bad_value() {
        let mut r = cfgt::row(1, 10, "farm/plc", 1);
        r.a = 1e300;
        let c = build(cfgt::contract(), vec![r]).unwrap();
        let m = msg(serde_json::json!({"ts": iso(now()), "v1": 1e300}), now());
        let out = process(&c, &HashMap::new(), &mut DeadLimiter::new(10), &[m]);
        assert!(out.readings.is_empty());
        assert_eq!(out.dead[0].reason, DeadReason::BadValue);
    }
}
