//! The quality bitset of a stored reading (plan decision 5). The one definition is `sensors/quality.py`; these are the
//! same numbers, and a database test compares them with the `sensors_quality_flag` table.

pub const HEARTBEAT: i16 = 1;
pub const RECEIVE_TIME: i16 = 2;
pub const CLOCK_SUSPECT: i16 = 4;
pub const LATE: i16 = 8;
pub const OUT_OF_RANGE: i16 = 16;
pub const DEVICE_BAD: i16 = 32;
pub const MAINTENANCE: i16 = 64;
pub const SIMULATED: i16 = 128;

/// (bit, name, is bad), in bit order: the rows of `sensors_quality_flag`.
pub const FLAGS: [(i16, &str, bool); 8] = [
    (HEARTBEAT, "heartbeat", false),
    (RECEIVE_TIME, "receive_time", false),
    (CLOCK_SUSPECT, "clock_suspect", false),
    (LATE, "late", false),
    (OUT_OF_RANGE, "out_of_range", true),
    (DEVICE_BAD, "device_bad", true),
    (MAINTENANCE, "maintenance", true),
    (SIMULATED, "simulated", true),
];

/// Bits that make a reading bad: stored as evidence, left out of rollups and latest values.
pub const BAD_MASK: i16 = OUT_OF_RANGE | DEVICE_BAD | MAINTENANCE | SIMULATED;

/// Bits that say why or how a row was written rather than what the value is: two samples whose quality differs only
/// in these bits belong to the same run.
pub const ROW_BITS: i16 = HEARTBEAT | LATE;

pub fn is_bad(q: i16) -> bool {
    q & BAD_MASK != 0
}

/// The part of a quality that a run of reduced samples must share.
pub fn class(q: i16) -> i16 {
    q & !ROW_BITS
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bad_mask_is_240_and_bits_are_the_eight_powers_of_two() {
        assert_eq!(BAD_MASK, 240);
        let bits: Vec<i16> = FLAGS.iter().map(|f| f.0).collect();
        assert_eq!(bits, (0..8).map(|n| 1i16 << n).collect::<Vec<_>>());
        let bad: i16 = FLAGS.iter().filter(|f| f.2).map(|f| f.0).sum();
        assert_eq!(bad, BAD_MASK);
    }

    #[test]
    fn class_ignores_heartbeat_and_late_only() {
        assert_eq!(class(HEARTBEAT | LATE | RECEIVE_TIME), RECEIVE_TIME);
        assert!(is_bad(OUT_OF_RANGE | HEARTBEAT));
        assert!(!is_bad(LATE | HEARTBEAT | RECEIVE_TIME | CLOCK_SUSPECT));
    }
}
