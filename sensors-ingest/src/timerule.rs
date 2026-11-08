//! The time rule (plan decision 5, contract `future_skew_s`, `late_limit_days`): which time a sample is stored at.
//!
//! - no device time (the format has no time path): the receive time, flagged RECEIVE_TIME;
//! - device time more than `future_skew_s` after the receive time: the receive time, flagged CLOCK_SUSPECT (a device
//!   clock running ahead must not push the channel's newest time into the future, which would send every later
//!   sample down the late path);
//! - device time older than `late_limit_days` before the receive time: refused, dead letter `too_old` (the contract keeps it two
//!   days inside the raw retention: retention would
//!   drop it at once, and a dropped chunk is never refilled);
//! - otherwise the device time, unflagged, however far in the past (a gateway replaying a backlog is normal).
//!
//! Both times are cut to microseconds (the stored precision) so the in-memory key equals the stored key.

use crate::model::{DeadReason, to_micros};
use crate::quality::{CLOCK_SUSPECT, RECEIVE_TIME};
use chrono::{DateTime, Duration, Utc};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Limits {
    pub future_skew_s: i64,
    pub late_limit_days: i64,
}

/// The stored time and its quality bits, or the reason the sample is refused.
pub fn resolve(
    device_ts: Option<DateTime<Utc>>,
    received_at: DateTime<Utc>,
    limits: Limits,
) -> Result<(DateTime<Utc>, i16), DeadReason> {
    let received_at = to_micros(received_at);
    let Some(device_ts) = device_ts.map(to_micros) else {
        return Ok((received_at, RECEIVE_TIME));
    };
    let latest = Duration::try_seconds(limits.future_skew_s).and_then(|d| received_at.checked_add_signed(d));
    if latest.is_some_and(|l| device_ts > l) {
        return Ok((received_at, CLOCK_SUSPECT));
    }
    // A late limit beyond the representable range means nothing is too old.
    let oldest = Duration::try_days(limits.late_limit_days).and_then(|d| received_at.checked_sub_signed(d));
    if oldest.is_some_and(|o| device_ts < o) {
        return Err(DeadReason::TooOld);
    }
    Ok((device_ts, 0))
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;
    use proptest::prelude::*;

    const L: Limits = Limits { future_skew_s: 60, late_limit_days: 730 };

    fn now() -> DateTime<Utc> {
        Utc.with_ymd_and_hms(2026, 11, 4, 12, 0, 0).unwrap() + Duration::nanoseconds(123_456_789)
    }

    fn micros(t: DateTime<Utc>) -> DateTime<Utc> {
        DateTime::<Utc>::from_timestamp_micros(t.timestamp_micros()).unwrap()
    }

    #[test]
    fn no_device_time_takes_the_receive_time_flagged() {
        assert_eq!(resolve(None, now(), L), Ok((micros(now()), RECEIVE_TIME)));
    }

    #[test]
    fn device_time_inside_the_skew_is_kept() {
        let t = now() + Duration::seconds(60);
        assert_eq!(resolve(Some(t), now(), L), Ok((micros(t), 0)));
        let past = now() - Duration::days(3);
        assert_eq!(resolve(Some(past), now(), L), Ok((micros(past), 0)));
    }

    #[test]
    fn device_time_beyond_the_skew_is_replaced_and_flagged() {
        let t = now() + Duration::seconds(61);
        assert_eq!(resolve(Some(t), now(), L), Ok((micros(now()), CLOCK_SUSPECT)));
        let year_ahead = now() + Duration::days(365);
        assert_eq!(resolve(Some(year_ahead), now(), L), Ok((micros(now()), CLOCK_SUSPECT)));
    }

    #[test]
    fn older_than_retention_is_too_old_and_the_border_is_kept() {
        let border = now() - Duration::days(730);
        assert_eq!(resolve(Some(border), now(), L), Ok((micros(border), 0)));
        let older = border - Duration::microseconds(1);
        assert_eq!(resolve(Some(older), now(), L), Err(DeadReason::TooOld));
    }

    #[test]
    fn a_zero_skew_accepts_only_times_up_to_receipt() {
        let l = Limits { future_skew_s: 0, late_limit_days: 730 };
        assert_eq!(resolve(Some(now()), now(), l), Ok((micros(now()), 0)));
        let ahead = now() + Duration::microseconds(1);
        assert_eq!(resolve(Some(ahead), now(), l), Ok((micros(now()), CLOCK_SUSPECT)));
    }

    proptest! {
        // The stored time is never more than the skew after receipt, never older than the late limit, and is the device
        // time whenever it is accepted unflagged.
        #[test]
        fn stored_time_is_bounded(offset_s in -80_000_000i64..80_000_000) {
            let t = now() + Duration::seconds(offset_s);
            match resolve(Some(t), now(), L) {
                Ok((ts, q)) => {
                    prop_assert!(ts <= now() + Duration::seconds(L.future_skew_s));
                    prop_assert!(ts >= now() - Duration::days(L.late_limit_days) - Duration::microseconds(1));
                    if q == 0 { prop_assert_eq!(ts, micros(t)); } else { prop_assert_eq!(q, CLOCK_SUSPECT); }
                }
                Err(r) => {
                    prop_assert_eq!(r, DeadReason::TooOld);
                    prop_assert!(t < now() - Duration::days(L.late_limit_days));
                }
            }
        }
    }
}
