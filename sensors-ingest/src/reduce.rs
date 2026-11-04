//! The reducer (plan decisions 3 and 4): absolute deadband plus heartbeat against the last STORED value, with run
//! statistics on the row that closes a run. A pure state machine over `sensors_channel_state`; the writer commits the
//! state in the same transaction as the rows.
//!
//! Forward path (`ts > high_ts`):
//! - the first sample of a channel is stored;
//! - `reduction = all`: every sample is stored, `n = 1`;
//! - deadband: a sample is stored when `|value - anchor_value| >= deadband`, when its quality class differs from the
//!   anchor's (`quality::class`), or when `ts - anchor_ts >= heartbeat_s` (then flagged HEARTBEAT unless it also moved
//!   past the deadband); otherwise it is suppressed;
//! - a suppressed GOOD sample joins the open run (`run_n`, `run_sum`, `run_min`, `run_max`); the next stored good row
//!   of the same class closes the run and carries `n = run_n + 1` and the run statistics including its own value;
//! - the run is closed early, by a row at the run's last sample (`last_value_ts`, `last_value`), when the next sample
//!   has another quality class, comes more than a heartbeat after that last sample (a data gap), or would make the
//!   run sum overflow; so a suppressed
//!   sample is counted at a row less than two heartbeats after it and never across a gap or a quality change;
//! - a suppressed BAD sample is not counted (bad rows are excluded from every statistic) and leaves no row; its
//!   evidence is the stored bad row it was within the deadband of.
//!
//! Late path (`ts <= high_ts`, `high_ts` = newest forward time processed): the sample is stored as it is, flagged LATE,
//! `n = 1`, and the forward state is not touched. A redelivered sample that was stored conflicts on
//! `(channel_no, ts)` and is dropped by the database; one that was suppressed costs one extra LATE row (bounded by the
//! broker's unacked window, plan risk 2).

use crate::quality::{self, HEARTBEAT, LATE};
use chrono::{DateTime, Duration, Utc};

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Reduction {
    All,
    Deadband(f64),
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Policy {
    pub reduction: Reduction,
    pub heartbeat_s: i64,
}

/// One row of `sensors_channel_state` (without the key).
#[derive(Debug, Clone, Default, PartialEq)]
pub struct State {
    /// Receive time of the newest message carrying this channel (any quality, any path).
    pub last_seen_at: Option<DateTime<Utc>>,
    /// Receive time of the newest good forward sample.
    pub last_good_at: Option<DateTime<Utc>>,
    /// The newest good forward sample (stored or not), its time and quality.
    pub last_value: Option<f64>,
    pub last_value_ts: Option<DateTime<Utc>>,
    pub last_quality: Option<i16>,
    /// The last stored forward row: what the deadband and the heartbeat are measured from.
    pub anchor_ts: Option<DateTime<Utc>>,
    pub anchor_value: Option<f64>,
    pub anchor_quality: Option<i16>,
    /// Good samples suppressed since the anchor.
    pub run_n: i32,
    pub run_sum: Option<f64>,
    pub run_min: Option<f64>,
    pub run_max: Option<f64>,
    /// Newest forward time processed; an older or equal time takes the late path.
    pub high_ts: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Sample {
    pub ts: DateTime<Utc>,
    pub value: f64,
    pub quality: i16,
    pub received_at: DateTime<Utc>,
}

/// A row of `sensors_reading` without the channel number.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Row {
    pub ts: DateTime<Utc>,
    pub value: f64,
    pub n: i32,
    pub quality: i16,
    pub run_sum: Option<f64>,
    pub run_min: Option<f64>,
    pub run_max: Option<f64>,
}

#[derive(Debug, Clone, PartialEq, Default)]
pub struct Step {
    /// At most two rows: a run closed early, then the sample itself.
    pub rows: Vec<Row>,
    pub late: bool,
}

pub fn step(policy: &Policy, st: &mut State, s: Sample) -> Step {
    st.last_seen_at = Some(st.last_seen_at.map_or(s.received_at, |seen| seen.max(s.received_at)));
    if st.high_ts.is_some_and(|high| s.ts <= high) {
        return Step { rows: vec![plain(s.ts, s.value, s.quality | LATE)], late: true };
    }
    st.high_ts = Some(s.ts);
    let heartbeat = Duration::try_seconds(policy.heartbeat_s).unwrap_or(Duration::MAX);
    let good = !quality::is_bad(s.quality);
    let mut rows = Vec::with_capacity(2);

    // Close the open run early at its last sample: on a quality change or after a data gap.
    if st.run_n > 0 {
        let changed = st.anchor_quality.is_none_or(|aq| quality::class(aq) != quality::class(s.quality));
        let gap = st.last_value_ts.is_none_or(|last| s.ts - last > heartbeat);
        // the table refuses a non-finite run sum: close the run before adding a value would overflow it
        let overflow = !(st.run_sum.unwrap_or(0.0) + s.value).is_finite();
        if changed || gap || overflow {
            if let Some(row) = close_run_at_last(st) {
                rows.push(row);
            }
        }
    }

    let store = match (st.anchor_ts, st.anchor_value, st.anchor_quality) {
        (Some(ats), Some(av), Some(aq)) => match policy.reduction {
            Reduction::All => Some(s.quality),
            Reduction::Deadband(d) => {
                if quality::class(aq) != quality::class(s.quality) || (s.value - av).abs() >= d {
                    Some(s.quality)
                } else if s.ts - ats >= heartbeat {
                    Some(s.quality | HEARTBEAT)
                } else {
                    None
                }
            }
        },
        _ => Some(s.quality),
    };

    match store {
        Some(q) => {
            let row = if good { close_run_with(st, s.ts, s.value, q) } else { plain(s.ts, s.value, q) };
            set_anchor(st, &row);
            rows.push(row);
        }
        None if good => {
            st.run_n = st.run_n.saturating_add(1);
            st.run_sum = Some(st.run_sum.unwrap_or(0.0) + s.value);
            st.run_min = Some(st.run_min.map_or(s.value, |m| m.min(s.value)));
            st.run_max = Some(st.run_max.map_or(s.value, |m| m.max(s.value)));
        }
        None => {}
    }
    if good {
        st.last_good_at = Some(st.last_good_at.map_or(s.received_at, |g| g.max(s.received_at)));
        st.last_value = Some(s.value);
        st.last_value_ts = Some(s.ts);
        st.last_quality = Some(quality::class(s.quality));
    }
    Step { rows, late: false }
}

fn plain(ts: DateTime<Utc>, value: f64, quality: i16) -> Row {
    Row { ts, value, n: 1, quality, run_sum: None, run_min: None, run_max: None }
}

fn set_anchor(st: &mut State, row: &Row) {
    st.anchor_ts = Some(row.ts);
    st.anchor_value = Some(row.value);
    st.anchor_quality = Some(row.quality);
}

fn reset_run(st: &mut State) {
    st.run_n = 0;
    st.run_sum = None;
    st.run_min = None;
    st.run_max = None;
}

/// The row of a stored good sample: it closes the open run (which then counts in its `n` and statistics).
fn close_run_with(st: &mut State, ts: DateTime<Utc>, value: f64, quality: i16) -> Row {
    let row = if st.run_n == 0 {
        plain(ts, value, quality)
    } else {
        Row {
            ts,
            value,
            n: st.run_n.saturating_add(1),
            quality,
            run_sum: Some(st.run_sum.unwrap_or(0.0) + value),
            run_min: Some(st.run_min.map_or(value, |m| m.min(value))),
            run_max: Some(st.run_max.map_or(value, |m| m.max(value))),
        }
    };
    reset_run(st);
    row
}

/// The row that closes the open run at its own last sample (`last_value_ts`, `last_value`, which a run's samples always
/// are: they are the newest good forward samples). That row becomes the anchor.
fn close_run_at_last(st: &mut State) -> Option<Row> {
    let (ts, value, q) = (st.last_value_ts?, st.last_value?, st.last_quality.or(st.anchor_quality)?);
    let row = if st.run_n == 1 {
        plain(ts, value, quality::class(q))
    } else {
        Row {
            ts,
            value,
            n: st.run_n,
            quality: quality::class(q),
            run_sum: st.run_sum,
            run_min: st.run_min,
            run_max: st.run_max,
        }
    };
    reset_run(st);
    set_anchor(st, &row);
    Some(row)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::quality::{OUT_OF_RANGE, RECEIVE_TIME};
    use chrono::TimeZone;
    use proptest::prelude::*;

    fn t0() -> DateTime<Utc> {
        Utc.with_ymd_and_hms(2026, 11, 4, 0, 0, 0).unwrap()
    }
    fn at(s: i64) -> DateTime<Utc> {
        t0() + Duration::seconds(s)
    }
    fn smp(s: i64, v: f64, q: i16) -> Sample {
        Sample { ts: at(s), value: v, quality: q, received_at: at(s) + Duration::milliseconds(300) }
    }
    fn db(d: f64, h: i64) -> Policy {
        Policy { reduction: Reduction::Deadband(d), heartbeat_s: h }
    }
    fn run(p: &Policy, st: &mut State, samples: &[Sample]) -> Vec<Row> {
        samples.iter().flat_map(|s| step(p, st, *s).rows).collect()
    }
    fn plain(ts: i64, v: f64, q: i16) -> Row {
        Row { ts: at(ts), value: v, n: 1, quality: q, run_sum: None, run_min: None, run_max: None }
    }

    #[test]
    fn first_sample_is_stored_and_becomes_the_anchor() {
        let mut st = State::default();
        let out = step(&db(0.1, 60), &mut st, smp(0, 5.0, 0));
        assert_eq!(out, Step { rows: vec![plain(0, 5.0, 0)], late: false });
        assert_eq!((st.anchor_ts, st.anchor_value, st.anchor_quality), (Some(at(0)), Some(5.0), Some(0)));
        assert_eq!((st.high_ts, st.last_value, st.last_value_ts), (Some(at(0)), Some(5.0), Some(at(0))));
        assert_eq!(st.last_seen_at, Some(at(0) + Duration::milliseconds(300)));
        assert_eq!(st.last_good_at, st.last_seen_at);
        assert_eq!(st.run_n, 0);
    }

    #[test]
    fn deadband_compares_with_the_stored_anchor_not_the_previous_sample() {
        // creep: each step below the deadband, the sum of steps above it
        let mut st = State::default();
        let rows = run(&db(0.1, 600), &mut st, &[smp(0, 0.0, 0), smp(1, 0.06, 0), smp(2, 0.12, 0)]);
        assert_eq!(rows.len(), 2);
        let closing = rows[1];
        assert_eq!((closing.ts, closing.value, closing.n), (at(2), 0.12, 2));
        assert_eq!((closing.run_sum, closing.run_min, closing.run_max), (Some(0.06 + 0.12), Some(0.06), Some(0.12)));
        assert_eq!(closing.quality, 0);
        assert_eq!((st.run_n, st.run_sum), (0, None));
    }

    #[test]
    fn exactly_the_deadband_is_stored() {
        let mut st = State::default();
        let rows = run(&db(0.5, 600), &mut st, &[smp(0, 1.0, 0), smp(1, 1.5, 0), smp(2, 1.0, 0)]);
        assert_eq!(rows.iter().map(|r| r.value).collect::<Vec<_>>(), vec![1.0, 1.5, 1.0]);
    }

    #[test]
    fn a_flat_signal_is_stored_once_per_heartbeat_and_flagged() {
        let mut st = State::default();
        let samples: Vec<Sample> = (0..=12).map(|i| smp(i * 10, 7.0, 0)).collect();
        let rows = run(&db(0.1, 60), &mut st, &samples);
        assert_eq!(rows.iter().map(|r| r.ts).collect::<Vec<_>>(), vec![at(0), at(60), at(120)]);
        assert_eq!(rows[1].quality, HEARTBEAT);
        assert_eq!(
            (rows[1].n, rows[1].run_sum, rows[1].run_min, rows[1].run_max),
            (6, Some(42.0), Some(7.0), Some(7.0))
        );
        assert_eq!(rows[2].n, 6);
    }

    #[test]
    fn a_move_past_the_deadband_at_the_heartbeat_is_not_flagged_heartbeat() {
        let mut st = State::default();
        let rows = run(&db(0.1, 60), &mut st, &[smp(0, 7.0, 0), smp(60, 8.0, 0)]);
        assert_eq!(rows[1].quality, 0);
    }

    #[test]
    fn reduction_all_stores_every_sample_once() {
        let mut st = State::default();
        let p = Policy { reduction: Reduction::All, heartbeat_s: 60 };
        let samples: Vec<Sample> = (0..5).map(|i| smp(i, 7.0, 0)).collect();
        let rows = run(&p, &mut st, &samples);
        assert_eq!(rows, (0..5).map(|i| plain(i, 7.0, 0)).collect::<Vec<_>>());
    }

    #[test]
    fn a_quality_change_closes_the_run_at_its_last_sample_first() {
        let mut st = State::default();
        let rows =
            run(&db(1.0, 600), &mut st, &[smp(0, 5.0, 0), smp(1, 5.1, 0), smp(2, 5.2, 0), smp(3, 5.2, RECEIVE_TIME)]);
        assert_eq!(rows.len(), 3);
        assert_eq!(
            rows[1],
            Row {
                ts: at(2),
                value: 5.2,
                n: 2,
                quality: 0,
                run_sum: Some(5.1 + 5.2),
                run_min: Some(5.1),
                run_max: Some(5.2)
            }
        );
        assert_eq!(rows[2], plain(3, 5.2, RECEIVE_TIME));
    }

    #[test]
    fn a_run_of_one_closed_early_is_a_plain_row() {
        let mut st = State::default();
        let rows = run(&db(1.0, 600), &mut st, &[smp(0, 5.0, 0), smp(1, 5.1, 0), smp(2, 5.1, OUT_OF_RANGE)]);
        assert_eq!(rows, vec![plain(0, 5.0, 0), plain(1, 5.1, 0), plain(2, 5.1, OUT_OF_RANGE)]);
    }

    #[test]
    fn a_gap_longer_than_the_heartbeat_closes_the_run_before_it() {
        let mut st = State::default();
        let rows = run(&db(1.0, 60), &mut st, &[smp(0, 5.0, 0), smp(10, 5.1, 0), smp(20, 5.2, 0), smp(81, 5.2, 0)]);
        // the run (10 s, 20 s) is counted at 20 s, not at 81 s
        assert_eq!(rows[1].ts, at(20));
        assert_eq!(rows[1].n, 2);
        assert_eq!(rows[2], Row { quality: HEARTBEAT, ..plain(81, 5.2, 0) });
    }

    #[test]
    fn a_heartbeat_right_after_the_run_closes_into_the_new_row() {
        let mut st = State::default();
        let rows = run(&db(1.0, 60), &mut st, &[smp(0, 5.0, 0), smp(30, 5.1, 0), smp(60, 5.2, 0)]);
        assert_eq!(rows.len(), 2);
        assert_eq!((rows[1].ts, rows[1].n, rows[1].quality), (at(60), 2, HEARTBEAT));
    }

    #[test]
    fn bad_samples_are_reduced_but_never_counted() {
        let mut st = State::default();
        let rows = run(
            &db(1.0, 600),
            &mut st,
            &[smp(0, 50.0, OUT_OF_RANGE), smp(1, 50.2, OUT_OF_RANGE), smp(2, 50.4, OUT_OF_RANGE), smp(3, 5.0, 0)],
        );
        assert_eq!(rows, vec![plain(0, 50.0, OUT_OF_RANGE), plain(3, 5.0, 0)]);
        assert_eq!(st.run_n, 0);
        // the bad samples did not become the latest good value
        assert_eq!((st.last_value, st.last_value_ts), (Some(5.0), Some(at(3))));
    }

    #[test]
    fn bad_samples_do_not_move_the_latest_good_value() {
        let mut st = State::default();
        run(&db(1.0, 600), &mut st, &[smp(0, 5.0, 0), smp(1, 99.0, OUT_OF_RANGE)]);
        assert_eq!((st.last_value, st.last_value_ts, st.last_quality), (Some(5.0), Some(at(0)), Some(0)));
        assert_eq!(st.last_good_at, Some(at(0) + Duration::milliseconds(300)));
        assert_eq!(st.last_seen_at, Some(at(1) + Duration::milliseconds(300)));
    }

    #[test]
    fn an_older_or_equal_time_takes_the_late_path_and_leaves_the_forward_state() {
        let mut st = State::default();
        run(&db(1.0, 600), &mut st, &[smp(0, 5.0, 0), smp(10, 5.1, 0)]);
        let before = st.clone();
        let out = step(&db(1.0, 600), &mut st, smp(5, 9.0, 0));
        assert_eq!(out, Step { rows: vec![plain(5, 9.0, LATE)], late: true });
        let out = step(&db(1.0, 600), &mut st, smp(10, 5.1, 0));
        assert_eq!(out, Step { rows: vec![plain(10, 5.1, LATE)], late: true });
        assert_eq!(st.last_seen_at, Some(at(10) + Duration::milliseconds(300)));
        assert_eq!(State { last_seen_at: before.last_seen_at, ..st.clone() }, before);
    }

    #[test]
    fn a_run_whose_sum_would_overflow_is_closed_before_it_does() {
        // the table refuses a non-finite run_sum: a run of huge values must never produce one
        let mut st = State::default();
        let samples: Vec<Sample> = (0..6).map(|i| smp(i, 1e308, 0)).collect();
        let rows = run(&db(1.0, 600), &mut st, &samples);
        assert!(rows.iter().all(|r| r.run_sum.is_none_or(f64::is_finite)), "{rows:?}");
        assert!(st.run_sum.is_none_or(f64::is_finite));
        let n: i32 = rows.iter().map(|r| r.n).sum::<i32>() + st.run_n;
        assert_eq!(n, 6);
    }

    #[test]
    fn late_keeps_the_sample_quality_bits() {
        let mut st = State::default();
        run(&db(1.0, 600), &mut st, &[smp(10, 5.0, 0)]);
        let out = step(&db(1.0, 600), &mut st, smp(5, 99.0, OUT_OF_RANGE));
        assert_eq!(out.rows, vec![plain(5, 99.0, OUT_OF_RANGE | LATE)]);
    }

    // ---- the statistics oracle -------------------------------------------------------------------------------

    #[derive(Debug, Clone)]
    struct Gen {
        policy: Policy,
        samples: Vec<Sample>,
    }

    fn stream() -> impl Strategy<Value = Gen> {
        (
            prop_oneof![Just(None), (0.01f64..2.0).prop_map(Some)],
            10i64..300,
            proptest::collection::vec((1i64..200, -1.0f64..1.0, 0u8..20, any::<bool>()), 1..400),
        )
            .prop_map(|(d, h, steps)| {
                let mut ts = 0i64;
                let mut v = 10.0;
                let mut samples = Vec::new();
                for (dt, dv, qsel, gap) in steps {
                    ts += if gap && dt > 190 { dt * 10 } else { dt };
                    v += dv;
                    let q = match qsel {
                        0 => OUT_OF_RANGE,
                        1 => RECEIVE_TIME,
                        _ => 0,
                    };
                    samples.push(Sample { ts: at(ts), value: v, quality: q, received_at: at(ts) });
                }
                let reduction = d.map_or(Reduction::All, Reduction::Deadband);
                Gen { policy: Policy { reduction, heartbeat_s: h }, samples }
            })
    }

    fn close(a: f64, b: f64) -> bool {
        (a - b).abs() <= 1e-9 * (1.0 + a.abs().max(b.abs()))
    }

    proptest! {
        #![proptest_config(ProptestConfig::with_cases(512))]

        /// The rows plus the open run account for every good sample exactly once: count, sum, min and max equal the
        /// unreduced stream; each good row closes exactly the pending samples before it and sits less than two
        /// heartbeats after the oldest of them; step-after reconstruction is within the deadband of every good sample.
        #[test]
        fn oracle(g in stream()) {
            let mut st = State::default();
            let mut rows = Vec::new();
            let mut pending: std::collections::VecDeque<Sample> = Default::default();
            for s in &g.samples {
                let out = step(&g.policy, &mut st, *s);
                prop_assert!(!out.late);
                prop_assert!(out.rows.len() <= 2);
                if !quality::is_bad(s.quality) { pending.push_back(*s); }
                for r in &out.rows {
                    if quality::is_bad(r.quality) { prop_assert_eq!(r.n, 1); continue; }
                    let k = usize::try_from(r.n).unwrap();
                    prop_assert!(k >= 1 && k <= pending.len());
                    let closed: Vec<Sample> = pending.drain(..k).collect();
                    let last = closed[k - 1];
                    prop_assert_eq!((last.ts, last.value), (r.ts, r.value));
                    prop_assert!(closed.iter().all(|c| quality::class(c.quality) == quality::class(r.quality)));
                    let sum: f64 = closed.iter().map(|c| c.value).sum();
                    let mn = closed.iter().map(|c| c.value).fold(f64::INFINITY, f64::min);
                    let mx = closed.iter().map(|c| c.value).fold(f64::NEG_INFINITY, f64::max);
                    if k == 1 {
                        prop_assert_eq!((r.run_sum, r.run_min, r.run_max), (None, None, None));
                    } else {
                        prop_assert!(close(r.run_sum.unwrap(), sum));
                        prop_assert_eq!((r.run_min, r.run_max), (Some(mn), Some(mx)));
                    }
                    let lag = r.ts - closed[0].ts;
                    prop_assert!(lag < Duration::seconds(2 * g.policy.heartbeat_s), "lag {lag}");
                }
                rows.extend(out.rows);
            }
            // the open run is exactly the pending samples
            prop_assert_eq!(usize::try_from(st.run_n).unwrap(), pending.len());
            if !pending.is_empty() {
                prop_assert!(close(st.run_sum.unwrap(), pending.iter().map(|c| c.value).sum()));
            }
            // rows strictly increasing in time (no key collision on the forward path)
            prop_assert!(rows.windows(2).all(|w| w[0].ts < w[1].ts));
            // totals: rollup formulas over the good rows plus the open run equal the unreduced stream
            let good: Vec<&Sample> = g.samples.iter().filter(|s| !quality::is_bad(s.quality)).collect();
            let n_rows: i64 = rows.iter().filter(|r| !quality::is_bad(r.quality)).map(|r| i64::from(r.n)).sum();
            prop_assert_eq!(n_rows + i64::from(st.run_n), i64::try_from(good.len()).unwrap());
            let sum_rows: f64 = rows.iter().filter(|r| !quality::is_bad(r.quality)).map(|r| r.run_sum.unwrap_or(r.value)).sum();
            prop_assert!(close(sum_rows + st.run_sum.unwrap_or(0.0), good.iter().map(|s| s.value).sum()));
            // step-after reconstruction
            if let Reduction::Deadband(d) = g.policy.reduction {
                for s in &good {
                    let r = rows.iter().rev().find(|r| r.ts <= s.ts).unwrap();
                    prop_assert!((r.value - s.value).abs() < d || r.ts == s.ts);
                }
            } else {
                prop_assert_eq!(rows.len(), g.samples.len());
            }
        }

        /// Resuming from a saved state gives the same rows as an uninterrupted run (restart safety: the state row is
        /// all the reducer needs).
        #[test]
        fn resume_from_saved_state(g in stream(), cut in 0usize..400) {
            let cut = cut.min(g.samples.len());
            let mut a = State::default();
            let whole: Vec<Row> = run(&g.policy, &mut a, &g.samples);
            let mut b = State::default();
            let mut parts = run(&g.policy, &mut b, &g.samples[..cut]);
            let mut saved = b.clone();
            parts.extend(run(&g.policy, &mut saved, &g.samples[cut..]));
            prop_assert_eq!(whole, parts);
            prop_assert_eq!(a, saved);
        }

        /// A batch committed and then redelivered (crash between COMMIT and PUBACK): every redelivered sample takes
        /// the late path; after the key dedup the only extra rows are the samples the batch had suppressed, each
        /// counted once more (the measured residual of plan risk 2).
        #[test]
        fn redelivered_batch_costs_only_its_suppressed_samples(g in stream(), cut in 0usize..400) {
            let cut = cut.min(g.samples.len());
            let mut st = State::default();
            let first = run(&g.policy, &mut st, &g.samples);
            let batch = &g.samples[cut..];
            let mut again = Vec::new();
            for s in batch {
                let out = step(&g.policy, &mut st, *s);
                prop_assert!(out.late);
                again.extend(out.rows);
            }
            let stored: std::collections::HashSet<DateTime<Utc>> = first.iter().map(|r| r.ts).collect();
            let extra: Vec<&Row> = again.iter().filter(|r| !stored.contains(&r.ts)).collect();
            let suppressed = batch.iter().filter(|s| !stored.contains(&s.ts)).count();
            prop_assert_eq!(extra.len(), suppressed);
            prop_assert!(extra.iter().all(|r| r.quality & LATE != 0 && r.n == 1));
        }

        /// Late data (a shuffled tail) is counted once each: good rows plus the open run still equal the good samples.
        #[test]
        fn late_samples_are_counted_once(g in stream(), seed in any::<u64>()) {
            let mut samples = g.samples.clone();
            let n = samples.len();
            if n > 3 {
                // move a deterministic pseudo-random subset to the end (they arrive late)
                let mut late = Vec::new();
                let mut i = 0;
                let mut x = seed | 1;
                samples.retain(|_| { i += 1; x ^= x << 13; x ^= x >> 7; x ^= x << 17; i == n || x % 4 != 0 });
                for s in &g.samples { if !samples.contains(s) { late.push(*s); } }
                samples.extend(late);
            }
            let mut st = State::default();
            let rows = run(&g.policy, &mut st, &samples);
            let good = samples.iter().filter(|s| !quality::is_bad(s.quality)).count();
            let late_good: Vec<&Row> = rows.iter().filter(|r| r.quality & LATE != 0 && !quality::is_bad(r.quality)).collect();
            let n_rows: i64 = rows.iter().filter(|r| !quality::is_bad(r.quality)).map(|r| i64::from(r.n)).sum();
            // a late sample at a time already stored (impossible here: times are unique) would be dropped by the key
            prop_assert!(late_good.iter().all(|r| r.n == 1));
            prop_assert_eq!(n_rows + i64::from(st.run_n), i64::try_from(good).unwrap());
        }
    }
}
