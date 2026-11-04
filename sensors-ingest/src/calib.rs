//! Calibration and unit conversion (plan decision 10): the contract view gives one row per calibration epoch with the
//! composed affine map `value = a * raw + b` (`a = unit_factor * gain`, `b = unit_factor * offset + unit_offset`) and
//! the epoch's `[valid_from, valid_to)`; the first epoch starts at -infinity. The epoch is chosen by the sample's
//! stored time (device time), so late data is calibrated as it was then. Then the value is judged against the range
//! and the channel's state.

use crate::quality::{MAINTENANCE, OUT_OF_RANGE};
use chrono::{DateTime, Utc};

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Epoch {
    /// None = -infinity.
    pub valid_from: Option<DateTime<Utc>>,
    pub a: f64,
    pub b: f64,
}

/// Epochs sorted by `valid_from` (None first). Returns None when no epoch covers `ts` or the result is not finite.
pub fn apply(_epochs: &[Epoch], _ts: DateTime<Utc>, _raw: f64) -> Option<f64> {
    todo!("calibration")
}

/// Quality bits from the calibrated value and the channel: OUT_OF_RANGE outside `[range_min, range_max]` (both ends
/// inside), MAINTENANCE when the channel is in maintenance.
pub fn judge(_value: f64, _range: Option<(f64, f64)>, _maintenance: bool) -> i16 {
    todo!("judge")
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;
    use proptest::prelude::*;

    fn t(day: u32) -> DateTime<Utc> {
        Utc.with_ymd_and_hms(2026, 10, day, 0, 0, 0).unwrap()
    }

    fn epochs() -> Vec<Epoch> {
        vec![
            Epoch { valid_from: None, a: 0.1, b: -2.0 },
            Epoch { valid_from: Some(t(10)), a: 2.0 * 1.1, b: 2.0 * -0.2 + 1.0 },
            Epoch { valid_from: Some(t(20)), a: 2.0 * 0.5, b: 2.0 * 3.0 + 1.0 },
        ]
    }

    #[test]
    fn the_epoch_is_chosen_by_the_sample_time_with_closed_start() {
        let e = epochs();
        assert_eq!(apply(&e, t(1), 10.0), Some(0.1 * 10.0 - 2.0));
        assert_eq!(apply(&e, t(10), 10.0), Some(e[1].a * 10.0 + e[1].b));
        assert_eq!(apply(&e, t(19), 10.0), Some(e[1].a * 10.0 + e[1].b));
        assert_eq!(apply(&e, t(20), 10.0), Some(10.0 + 7.0));
        assert_eq!(apply(&e, t(30), 10.0), Some(17.0));
    }

    #[test]
    fn no_epoch_before_the_first_start_gives_none() {
        let e = vec![Epoch { valid_from: Some(t(10)), a: 1.0, b: 0.0 }];
        assert_eq!(apply(&e, t(9), 1.0), None);
        assert_eq!(apply(&[], t(9), 1.0), None);
    }

    #[test]
    fn an_overflowing_result_gives_none() {
        let e = vec![Epoch { valid_from: None, a: 1e300, b: 0.0 }];
        assert_eq!(apply(&e, t(1), 1e10), None);
    }

    #[test]
    fn judge_range_and_maintenance() {
        assert_eq!(judge(5.0, Some((0.0, 10.0)), false), 0);
        assert_eq!(judge(0.0, Some((0.0, 10.0)), false), 0);
        assert_eq!(judge(10.0, Some((0.0, 10.0)), false), 0);
        assert_eq!(judge(10.000001, Some((0.0, 10.0)), false), OUT_OF_RANGE);
        assert_eq!(judge(-0.1, Some((0.0, 10.0)), true), OUT_OF_RANGE | MAINTENANCE);
        assert_eq!(judge(1e9, None, false), 0);
        assert_eq!(judge(1.0, None, true), MAINTENANCE);
    }

    proptest! {
        #[test]
        fn single_epoch_is_affine(raw in -1e6f64..1e6, a in -1e3f64..1e3, b in -1e3f64..1e3) {
            prop_assume!(a != 0.0);
            let e = [Epoch { valid_from: None, a, b }];
            prop_assert_eq!(apply(&e, t(1), raw), Some(a * raw + b));
        }
    }
}
