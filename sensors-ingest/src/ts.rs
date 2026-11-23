//! The ingest's one timestamp type: a UTC instant with nanosecond precision, held in a `time::OffsetDateTime`.
//!
//! It replaced chrono (RUSTSEC-2026-0543: chrono is unmaintained) and keeps what chrono did, so nothing the ingest
//! accepts, refuses, stores or writes back changed (`time_pins.rs` and `tests/db.rs` pin it, and ran on chrono):
//!
//! - the range is chrono's, -262143-01-01T00:00:00Z to +262142-12-31T23:59:59.999999999Z: a time outside it is not a
//!   time (an epoch value beyond it is `bad_time`, the database driver refuses to decode one), and a limit that reaches
//!   beyond it is no limit (`checked_add`, `checked_sub`);
//! - a device's ISO 8601 time is read by `parse_rfc3339` (chrono's `DateTime::parse_from_rfc3339`); `/decode`'s
//!   `received_at` by `FromStr`, the relaxed form of chrono's serde (spaces, `+hhmm`, `UTC`, signed years), with
//!   chrono's error messages;
//! - second 60 is the next second (chrono kept a leap second and `to_micros` moved it there; the ingest never kept one
//!   longer). One leap-second text cannot be held: `+262142-12-31T23:59:60Z` (and later fractions of it), the leap
//!   second after the last representable one, which chrono read and this type refuses as out of range;
//! - written back as RFC 3339 in UTC with a `Z`, the fraction in the shortest of 3, 6 or 9 digits, a year outside
//!   0000..9999 with its sign (chrono's serde form; `Debug` and `Display` write the same);
//! - through the database as `timestamptz` (`with-time-0_3`), cut to microseconds toward 2000-01-01.
//!
//! No local time zone exists here: an offset is the one written in the text, and every stored time is UTC.

use bytes::BytesMut;
use serde::{Deserialize, Deserializer, Serialize, Serializer};
use std::fmt;
use std::ops::{Add, Sub};
use std::str::FromStr;
use time::{Date, Month, OffsetDateTime};
use tokio_postgres::types::{FromSql, IsNull, ToSql, Type, to_sql_checked};

/// A signed span of time (seconds and nanoseconds).
pub use time::SignedDuration as Duration;

/// Unix seconds of the first and the last second of the range (-262143-01-01T00:00:00Z, +262142-12-31T23:59:59Z).
pub const MIN_UNIX_S: i64 = -8_334_601_228_800;
pub const MAX_UNIX_S: i64 = 8_210_266_876_799;
/// The years of the range.
const MIN_YEAR: i64 = -262_143;
const MAX_YEAR: i64 = 262_142;
/// The Julian day of 1970-01-01.
const UNIX_EPOCH_JULIAN_DAY: i64 = 2_440_588;
const NANOS_PER_S: i128 = 1_000_000_000;
/// The longest span the time rule's limits are read as (chrono's `TimeDelta`: `i64::MAX` milliseconds, both ways).
const MAX_SPAN_S: i64 = i64::MAX / 1000;

/// A UTC instant inside the range. Ordered, hashed and compared as the instant.
#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Ts(OffsetDateTime);

impl Ts {
    pub fn now() -> Ts {
        Ts(OffsetDateTime::now_utc())
    }

    /// Every `Ts` is made here: UTC (all callers give UTC) and inside the range.
    fn new(t: OffsetDateTime) -> Option<Ts> {
        (MIN_UNIX_S..=MAX_UNIX_S).contains(&t.unix_timestamp()).then_some(Ts(t))
    }

    fn from_unix_nanos(nanos: i128) -> Option<Ts> {
        OffsetDateTime::from_unix_timestamp_nanos(nanos).ok().and_then(Ts::new)
    }

    pub fn from_unix_secs(secs: i64) -> Option<Ts> {
        Ts::from_unix_nanos(i128::from(secs) * NANOS_PER_S)
    }

    pub fn from_unix_millis(millis: i64) -> Option<Ts> {
        Ts::from_unix_nanos(i128::from(millis) * 1_000_000)
    }

    pub fn from_unix_micros(micros: i64) -> Option<Ts> {
        Ts::from_unix_nanos(i128::from(micros) * 1_000)
    }

    /// A whole second of a calendar day (no second 60), or None when there is no such time in the range.
    pub fn ymd_hms(year: i32, month: u8, day: u8, hour: u8, minute: u8, second: u8) -> Option<Ts> {
        if second > 59 {
            return None;
        }
        let f = Fields {
            year: i64::from(year),
            month: i64::from(month),
            day: i64::from(day),
            hour: i64::from(hour),
            minute: i64::from(minute),
            second: i64::from(second),
            nano: 0,
            offset_s: 0,
        };
        f.resolve().ok()
    }

    /// Whole seconds since 1970-01-01T00:00:00Z, rounded down.
    pub fn unix_secs(self) -> i64 {
        self.0.unix_timestamp()
    }

    /// Whole milliseconds since 1970-01-01T00:00:00Z, rounded down.
    pub fn unix_millis(self) -> i64 {
        // |seconds| <= 8.4e12 in the range: no overflow
        self.unix_secs() * 1_000 + i64::from(self.0.millisecond())
    }

    /// Whole microseconds since 1970-01-01T00:00:00Z, rounded down.
    pub fn unix_micros(self) -> i64 {
        // |seconds| * 1e6 <= 8.4e18 < i64::MAX in the range: no overflow
        self.unix_secs() * 1_000_000 + i64::from(self.0.microsecond())
    }

    /// The instant at the precision PostgreSQL stores (microseconds, cut down), so the in-memory key equals the stored
    /// key.
    #[must_use]
    pub fn trunc_micros(self) -> Ts {
        Ts::from_unix_micros(self.unix_micros()).unwrap_or(self)
    }

    /// None when the result is outside the range.
    pub fn checked_add(self, d: Duration) -> Option<Ts> {
        self.0.checked_add(d).and_then(Ts::new)
    }

    /// None when the result is outside the range.
    pub fn checked_sub(self, d: Duration) -> Option<Ts> {
        self.0.checked_sub(d).and_then(Ts::new)
    }

    /// A device's ISO 8601 time: RFC 3339 exactly as chrono's `parse_from_rfc3339` read it. Four-digit year,
    /// `-`, month, `-`, day, `T`/`t`/space, `hh:mm:ss` (second 60 allowed at any minute), an optional `.` and one or
    /// more digits (beyond nine ignored), then `Z`/`z` or `+hh:mm`/`-hh:mm`/`−hh:mm` (U+2212) under 24 hours, and
    /// nothing after it. No white space anywhere (the caller trims the ends).
    pub fn parse_rfc3339(s: &str) -> Option<Ts> {
        let b = s.as_bytes();
        if b.len() < 19 {
            return None;
        }
        let d = |i: usize| b.get(i).filter(|c| c.is_ascii_digit()).map(|c| i64::from(c - b'0'));
        let year = d(0)? * 1000 + d(1)? * 100 + d(2)? * 10 + d(3)?;
        let month = d(5)? * 10 + d(6)?;
        let day = d(8)? * 10 + d(9)?;
        let hour = d(11)? * 10 + d(12)?;
        let minute = d(14)? * 10 + d(15)?;
        let second = d(17)? * 10 + d(18)?;
        let seps = b.get(4) == Some(&b'-')
            && b.get(7) == Some(&b'-')
            && matches!(b.get(10), Some(b't' | b'T' | b' '))
            && b.get(13) == Some(&b':')
            && b.get(16) == Some(&b':');
        if !seps {
            return None;
        }
        let (rest, nano) = if b.get(19) == Some(&b'.') { nanosecond(s.get(20..)?).ok()? } else { (s.get(19..)?, 0) };
        let (rest, offset_s) = offset(rest, Colon::Required).ok()?;
        if !rest.is_empty() {
            return None;
        }
        Fields { year, month, day, hour, minute, second, nano, offset_s }.resolve().ok()
    }
}

impl Add<Duration> for Ts {
    type Output = Ts;

    /// Panics outside the range, as chrono's operator did; the service's code uses `checked_add`.
    #[allow(clippy::panic)]
    fn add(self, d: Duration) -> Ts {
        self.checked_add(d).unwrap_or_else(|| panic!("`Ts + Duration` overflowed"))
    }
}

impl Sub<Duration> for Ts {
    type Output = Ts;

    /// Panics outside the range, as chrono's operator did; the service's code uses `checked_sub`.
    #[allow(clippy::panic)]
    fn sub(self, d: Duration) -> Ts {
        self.checked_sub(d).unwrap_or_else(|| panic!("`Ts - Duration` overflowed"))
    }
}

impl Sub for Ts {
    type Output = Duration;

    /// The span between two instants of the range (at most about 524,000 years: never overflows).
    fn sub(self, other: Ts) -> Duration {
        self.0 - other.0
    }
}

/// RFC 3339 in UTC: `2026-11-04T12:00:00.123Z`, the fraction in the shortest of 3, 6 or 9 digits (none when zero), a
/// year outside 0000..9999 with its sign (`+10000`, `-0001`).
impl fmt::Display for Ts {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let (year, month, day) = self.0.to_calendar_date();
        if (0..=9999).contains(&year) {
            write!(f, "{year:04}")?;
        } else {
            write!(f, "{year:+05}")?;
        }
        let (h, m, s) = (self.0.hour(), self.0.minute(), self.0.second());
        write!(f, "-{:02}-{day:02}T{h:02}:{m:02}:{s:02}", u8::from(month))?;
        let nano = self.0.nanosecond();
        if nano == 0 {
        } else if nano % 1_000_000 == 0 {
            write!(f, ".{:03}", nano / 1_000_000)?;
        } else if nano % 1_000 == 0 {
            write!(f, ".{:06}", nano / 1_000)?;
        } else {
            write!(f, ".{nano:09}")?;
        }
        f.write_str("Z")
    }
}

impl fmt::Debug for Ts {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        fmt::Display::fmt(self, f)
    }
}

/// Why a text is not a time; the messages are chrono's.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ParseError {
    OutOfRange,
    Impossible,
    Invalid,
    TooShort,
    TooLong,
}

impl fmt::Display for ParseError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            ParseError::OutOfRange => "input is out of range",
            ParseError::Impossible => "no possible date and time matching input",
            ParseError::Invalid => "input contains invalid characters",
            ParseError::TooShort => "premature end of input",
            ParseError::TooLong => "trailing input",
        })
    }
}

impl std::error::Error for ParseError {}

/// The relaxed RFC 3339 of chrono's `FromStr` (and so of its serde): white space before any number and around the
/// separators, numbers without zero padding, a year of any length with a sign (four digits at most without one),
/// `T`/`t`/one space between date and time, an optional fraction, then `Z`/`z`, `UTC` in any case, or an offset whose
/// colon may be missing or replaced by spaces; white space at the end.
impl FromStr for Ts {
    type Err = ParseError;

    fn from_str(s: &str) -> Result<Ts, ParseError> {
        let (s, year) = numeric(s, 4, true)?;
        let year = i64::from(i32::try_from(year).map_err(|_| ParseError::OutOfRange)?);
        let s = literal(s.trim_start(), "-")?;
        let (s, month) = numeric(s, 2, false)?;
        in_range(month, 1, 12)?;
        let s = literal(s.trim_start(), "-")?;
        let (s, day) = numeric(s, 2, false)?;
        in_range(day, 1, 31)?;
        let s = match s.as_bytes().first() {
            Some(b't' | b'T' | b' ') => tail(s, 1),
            Some(_) => return Err(ParseError::Invalid),
            None => return Err(ParseError::TooShort),
        };
        let (s, hour) = numeric(s, 2, false)?;
        in_range(hour, 0, 23)?;
        let s = literal(s.trim_start(), ":")?;
        let (s, minute) = numeric(s, 2, false)?;
        in_range(minute, 0, 59)?;
        let s = literal(s.trim_start(), ":")?;
        let (s, second) = numeric(s, 2, false)?;
        in_range(second, 0, 60)?;
        let (s, nano) = match s.strip_prefix('.') {
            Some(r) => nanosecond(r)?,
            None => (s, 0),
        };
        let s = s.trim_start();
        let (s, offset_s) = if s.as_bytes().get(..3).is_some_and(|p| p.eq_ignore_ascii_case(b"UTC")) {
            (tail(s, 3), 0)
        } else {
            offset(s, Colon::Optional)?
        };
        if !s.trim_start().is_empty() {
            return Err(ParseError::TooLong);
        }
        Fields { year, month, day, hour, minute, second, nano, offset_s }.resolve()
    }
}

impl Serialize for Ts {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.collect_str(self)
    }
}

impl<'de> Deserialize<'de> for Ts {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Ts, D::Error> {
        struct Visitor;
        impl serde::de::Visitor<'_> for Visitor {
            type Value = Ts;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("an RFC 3339 formatted date and time string")
            }
            fn visit_str<E: serde::de::Error>(self, v: &str) -> Result<Ts, E> {
                v.parse().map_err(E::custom)
            }
        }
        deserializer.deserialize_str(Visitor)
    }
}

impl ToSql for Ts {
    fn to_sql(&self, ty: &Type, out: &mut BytesMut) -> Result<IsNull, Box<dyn std::error::Error + Sync + Send>> {
        self.0.to_sql(ty, out)
    }

    fn accepts(ty: &Type) -> bool {
        <OffsetDateTime as ToSql>::accepts(ty)
    }

    to_sql_checked!();
}

impl<'a> FromSql<'a> for Ts {
    /// `infinity`, `-infinity` and the years after 262142 are refused, as chrono's driver support refused them.
    fn from_sql(ty: &Type, raw: &'a [u8]) -> Result<Ts, Box<dyn std::error::Error + Sync + Send>> {
        Ts::new(OffsetDateTime::from_sql(ty, raw)?).ok_or_else(|| "value too large to decode".into())
    }

    fn accepts(ty: &Type) -> bool {
        <OffsetDateTime as FromSql>::accepts(ty)
    }
}

/// `seconds` as a span, or None beyond chrono's `TimeDelta` (`i64::MAX` milliseconds either way): the time rule
/// reads a limit beyond it as no limit.
pub fn try_seconds(seconds: i64) -> Option<Duration> {
    (-MAX_SPAN_S..=MAX_SPAN_S).contains(&seconds).then(|| Duration::seconds(seconds))
}

/// `days` as a span, or None beyond chrono's `TimeDelta` (see `try_seconds`).
pub fn try_days(days: i64) -> Option<Duration> {
    days.checked_mul(86_400).and_then(try_seconds)
}

// ---- parsing: chrono 0.4.45's scanners (format/scan.rs, format/parse.rs), error for error ----

type Scan<'a, T> = Result<(&'a str, T), ParseError>;

/// The rest of `s` after `n` bytes that the caller knows are ASCII.
fn tail(s: &str, n: usize) -> &str {
    s.get(n..).unwrap_or_default()
}

fn in_range(v: i64, lo: i64, hi: i64) -> Result<(), ParseError> {
    if (lo..=hi).contains(&v) { Ok(()) } else { Err(ParseError::OutOfRange) }
}

/// A non-negative number of `min` to `max` digits; more digits are left for the caller.
fn number(s: &str, min: usize, max: usize) -> Scan<'_, i64> {
    let b = s.as_bytes();
    if b.len() < min {
        return Err(ParseError::TooShort);
    }
    let mut n: i64 = 0;
    for (i, c) in b.iter().take(max).enumerate() {
        if !c.is_ascii_digit() {
            return if i < min { Err(ParseError::Invalid) } else { Ok((tail(s, i), n)) };
        }
        n = n.checked_mul(10).and_then(|n| n.checked_add(i64::from(c - b'0'))).ok_or(ParseError::OutOfRange)?;
    }
    Ok((tail(s, max.min(b.len())), n))
}

/// A number after optional white space; with `signed`, a leading `+` or `-` allows any number of digits.
fn numeric(s: &str, width: usize, signed: bool) -> Scan<'_, i64> {
    let s = s.trim_start();
    if signed {
        if let Some(r) = s.strip_prefix('-') {
            let (r, v) = number(r, 1, usize::MAX)?;
            return Ok((r, -v));
        }
        if let Some(r) = s.strip_prefix('+') {
            return number(r, 1, usize::MAX);
        }
    }
    number(s, 1, width)
}

fn literal<'a>(s: &'a str, lit: &str) -> Result<&'a str, ParseError> {
    if s.len() < lit.len() {
        return Err(ParseError::TooShort);
    }
    s.strip_prefix(lit).ok_or(ParseError::Invalid)
}

/// The digits of a fraction (at least one) as nanoseconds; digits after the ninth are skipped.
fn nanosecond(s: &str) -> Scan<'_, i64> {
    const SCALE: [i64; 10] = [0, 100_000_000, 10_000_000, 1_000_000, 100_000, 10_000, 1_000, 100, 10, 1];
    let (r, v) = number(s, 1, 9)?;
    let scale = SCALE.get(s.len() - r.len()).copied().ok_or(ParseError::OutOfRange)?;
    Ok((r.trim_start_matches(|c: char| c.is_ascii_digit()), v * scale))
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Colon {
    /// exactly one `:` between hours and minutes
    Required,
    /// any number of `:` and white space, none included
    Optional,
}

/// `Z`/`z` or a sign (`+`, `-`, U+2212) with two-digit hours and two-digit minutes (00-59), as seconds east of UTC.
fn offset(s: &str, colon: Colon) -> Scan<'_, i64> {
    if let Some(r) = s.strip_prefix(['Z', 'z']) {
        return Ok((r, 0));
    }
    let (s, negative) = match s.chars().next() {
        Some(c @ '+') => (tail(s, c.len_utf8()), false),
        Some(c @ ('-' | '\u{2212}')) => (tail(s, c.len_utf8()), true),
        Some(_) => return Err(ParseError::Invalid),
        None => return Err(ParseError::TooShort),
    };
    let two = |s: &str| match s.as_bytes() {
        [a, b, ..] => Ok((*a, *b)),
        _ => Err(ParseError::TooShort),
    };
    let hours = match two(s)? {
        (h1 @ b'0'..=b'9', h2 @ b'0'..=b'9') => i64::from((h1 - b'0') * 10 + (h2 - b'0')),
        _ => return Err(ParseError::Invalid),
    };
    let s = tail(s, 2);
    let s = match colon {
        Colon::Required => match s.as_bytes().first() {
            Some(b':') => tail(s, 1),
            Some(_) => return Err(ParseError::Invalid),
            None => return Err(ParseError::TooShort),
        },
        Colon::Optional => s.trim_start_matches(|c: char| c == ':' || c.is_whitespace()),
    };
    let minutes = match two(s) {
        Ok((m1 @ b'0'..=b'5', m2 @ b'0'..=b'9')) => i64::from((m1 - b'0') * 10 + (m2 - b'0')),
        Ok((b'6'..=b'9', b'0'..=b'9')) => return Err(ParseError::OutOfRange),
        Ok(_) => return Err(ParseError::Invalid),
        Err(_) => return Err(ParseError::TooShort),
    };
    let seconds = hours * 3600 + minutes * 60;
    Ok((tail(s, 2), if negative { -seconds } else { seconds }))
}

/// A local date and time with its offset, checked in chrono's order: the date (in the range of years, a real day),
/// the time (second 60 is a leap second), the offset (under 24 hours), then the instant in UTC (in the range).
struct Fields {
    year: i64,
    month: i64,
    day: i64,
    hour: i64,
    minute: i64,
    /// 0..=60
    second: i64,
    /// 0..1e9
    nano: i64,
    offset_s: i64,
}

impl Fields {
    fn resolve(&self) -> Result<Ts, ParseError> {
        let days = self.days_since_epoch().ok_or(ParseError::OutOfRange)?;
        let time_ok = (0..24).contains(&self.hour)
            && (0..60).contains(&self.minute)
            && (0..=60).contains(&self.second)
            && (0..1_000_000_000).contains(&self.nano);
        if !time_ok {
            return Err(ParseError::OutOfRange);
        }
        if self.offset_s.abs() >= 86_400 {
            return Err(ParseError::OutOfRange);
        }
        // chrono held second 60 as second 59 plus a second of fraction: the instant's second is :59
        let leap = self.second == 60;
        let local_s = days * 86_400 + self.hour * 3600 + self.minute * 60 + self.second.min(59);
        let utc_s = local_s - self.offset_s;
        if !(MIN_UNIX_S..=MAX_UNIX_S).contains(&utc_s) {
            return Err(ParseError::Impossible);
        }
        let nanos = i128::from(utc_s) * NANOS_PER_S + i128::from(leap) * NANOS_PER_S + i128::from(self.nano);
        // only a leap second after the last second of the range is not representable
        Ts::from_unix_nanos(nanos).ok_or(ParseError::OutOfRange)
    }

    fn days_since_epoch(&self) -> Option<i64> {
        if !(MIN_YEAR..=MAX_YEAR).contains(&self.year) {
            return None;
        }
        let month = Month::try_from(u8::try_from(self.month).ok()?).ok()?;
        let date =
            Date::from_calendar_date(i32::try_from(self.year).ok()?, month, u8::try_from(self.day).ok()?).ok()?;
        Some(i64::from(date.to_julian_day()) - UNIX_EPOCH_JULIAN_DAY)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The first and the last instant of the range, in nanoseconds since 1970-01-01T00:00:00Z.
    const MIN_UNIX_NANOS: i128 = MIN_UNIX_S as i128 * NANOS_PER_S;
    const MAX_UNIX_NANOS: i128 = MAX_UNIX_S as i128 * NANOS_PER_S + (NANOS_PER_S - 1);

    fn p(s: &str) -> Result<String, ParseError> {
        s.parse::<Ts>().map(|t| t.to_string())
    }

    #[test]
    fn the_range_constants_are_the_calendar_dates() {
        let min = Ts::ymd_hms(-262_143, 1, 1, 0, 0, 0).unwrap();
        let max = Ts::ymd_hms(262_142, 12, 31, 23, 59, 59).unwrap();
        assert_eq!((min.unix_secs(), max.unix_secs()), (MIN_UNIX_S, MAX_UNIX_S));
        assert_eq!(Ts::ymd_hms(-262_144, 12, 31, 23, 59, 59), None);
        assert_eq!(Ts::ymd_hms(262_143, 1, 1, 0, 0, 0), None);
        assert_eq!(Ts::from_unix_secs(MIN_UNIX_S - 1), None);
        assert_eq!(Ts::from_unix_secs(MAX_UNIX_S + 1), None);
        let last = Ts::from_unix_nanos(MAX_UNIX_NANOS).unwrap();
        assert_eq!(last.to_string(), "+262142-12-31T23:59:59.999999999Z");
        assert_eq!(Ts::from_unix_nanos(MIN_UNIX_NANOS).unwrap().to_string(), "-262143-01-01T00:00:00Z");
        assert_eq!(Ts::from_unix_nanos(MIN_UNIX_NANOS - 1), None);
        assert_eq!(Ts::from_unix_nanos(MAX_UNIX_NANOS + 1), None);
        assert_eq!(Ts::ymd_hms(2026, 11, 4, 12, 0, 60), None);
    }

    #[test]
    fn unix_counts_round_down_and_back() {
        let t = Ts::from_unix_nanos(-1).unwrap(); // 1969-12-31T23:59:59.999999999Z
        assert_eq!((t.unix_secs(), t.unix_millis(), t.unix_micros()), (-1, -1, -1));
        assert_eq!(t.trunc_micros().to_string(), "1969-12-31T23:59:59.999999Z");
        let t = Ts::from_unix_micros(1_762_257_600_123_456).unwrap();
        assert_eq!(
            (t.unix_secs(), t.unix_millis(), t.unix_micros()),
            (1_762_257_600, 1_762_257_600_123, 1_762_257_600_123_456)
        );
        for us in [i64::from(i32::MIN), -1, 0, 1, MIN_UNIX_S * 1_000_000, MAX_UNIX_S * 1_000_000 + 999_999] {
            assert_eq!(Ts::from_unix_micros(us).unwrap().unix_micros(), us);
        }
        let last = Ts::from_unix_nanos(MAX_UNIX_NANOS).unwrap();
        assert_eq!(last.trunc_micros().to_string(), "+262142-12-31T23:59:59.999999Z");
    }

    #[test]
    fn arithmetic_stays_inside_the_range() {
        let t = Ts::ymd_hms(2024, 2, 28, 23, 0, 0).unwrap();
        assert_eq!((t + Duration::hours(1)).to_string(), "2024-02-29T00:00:00Z");
        assert_eq!((t + Duration::days(1) + Duration::hours(1)).to_string(), "2024-03-01T00:00:00Z");
        assert_eq!(t + Duration::hours(1) - t, Duration::hours(1));
        let max = Ts::from_unix_secs(MAX_UNIX_S).unwrap();
        let min = Ts::from_unix_secs(MIN_UNIX_S).unwrap();
        assert_eq!(max.checked_add(Duration::nanoseconds(999_999_999)).map(Ts::unix_secs), Some(MAX_UNIX_S));
        assert_eq!(max.checked_add(Duration::seconds(1)), None);
        assert_eq!(min.checked_sub(Duration::nanoseconds(1)), None);
        assert_eq!(min.checked_add(Duration::MAX), None);
        assert_eq!(max.checked_sub(Duration::MIN), None);
        assert_eq!(max - min, Duration::seconds(MAX_UNIX_S - MIN_UNIX_S));
    }

    #[test]
    #[should_panic(expected = "`Ts + Duration` overflowed")]
    fn the_operator_panics_beyond_the_range() {
        let _ = Ts::from_unix_secs(MAX_UNIX_S).unwrap() + Duration::seconds(1);
    }

    #[test]
    #[should_panic(expected = "`Ts - Duration` overflowed")]
    fn the_subtraction_operator_panics_beyond_the_range() {
        let _ = Ts::from_unix_secs(MIN_UNIX_S).unwrap() - Duration::seconds(1);
    }

    #[test]
    fn spans_end_where_chrono_s_time_delta_ended() {
        assert_eq!(try_seconds(9_223_372_036_854_775), Some(Duration::seconds(9_223_372_036_854_775)));
        assert_eq!(try_seconds(-9_223_372_036_854_775), Some(Duration::seconds(-9_223_372_036_854_775)));
        assert_eq!(try_seconds(9_223_372_036_854_776), None);
        assert_eq!(try_seconds(-9_223_372_036_854_776), None);
        assert_eq!(try_seconds(i64::MIN), None);
        assert_eq!(try_days(106_751_991_167), Some(Duration::seconds(106_751_991_167 * 86_400)));
        assert_eq!(try_days(106_751_991_168), None);
        assert_eq!(try_days(-106_751_991_168), None);
        assert_eq!(try_days(i64::MAX), None);
    }

    #[test]
    fn written_as_chrono_s_serde_wrote_it() {
        let t = |s: &str| s.parse::<Ts>().unwrap();
        assert_eq!(serde_json::to_string(&t("2026-11-04T12:00:00.12Z")).unwrap(), "\"2026-11-04T12:00:00.120Z\"");
        assert_eq!(format!("{:?}", t("2026-11-04T12:00:00.000000001Z")), "2026-11-04T12:00:00.000000001Z");
        assert_eq!(t("0000-06-01T00:00:00Z").to_string(), "0000-06-01T00:00:00Z");
        assert_eq!(t("-0001-06-01T00:00:00Z").to_string(), "-0001-06-01T00:00:00Z");
        assert_eq!(t("9999-06-01T00:00:00Z").to_string(), "9999-06-01T00:00:00Z");
        assert_eq!(t("+10000-06-01T00:00:00Z").to_string(), "+10000-06-01T00:00:00Z");
        let back: Ts = serde_json::from_str("\"2026-11-04T12:00:00.120Z\"").unwrap();
        assert_eq!(back, t("2026-11-04T12:00:00.12Z"));
    }

    #[test]
    fn refusals_carry_chrono_s_messages() {
        assert_eq!(p(""), Err(ParseError::TooShort));
        assert_eq!(p("2026-11-04T12:00:01"), Err(ParseError::TooShort));
        assert_eq!(p("2026-11-04T12:00:01+01"), Err(ParseError::TooShort));
        assert_eq!(p("garbage"), Err(ParseError::Invalid));
        assert_eq!(p("2026/11/04T12:00:01Z"), Err(ParseError::Invalid));
        assert_eq!(p("2026-11-04T12:00:01ZZ"), Err(ParseError::TooLong));
        assert_eq!(p("2026-13-04T12:00:01Z"), Err(ParseError::OutOfRange));
        assert_eq!(p("2023-02-29T12:00:01Z"), Err(ParseError::OutOfRange));
        assert_eq!(p("2026-11-04T12:00:01+24:00"), Err(ParseError::OutOfRange));
        assert_eq!(p("2026-11-04T12:00:01+01:60"), Err(ParseError::OutOfRange));
        assert_eq!(p("+262143-01-01T00:00:00Z"), Err(ParseError::OutOfRange));
        assert_eq!(p("+99999999999-01-01T00:00:00Z"), Err(ParseError::OutOfRange));
        assert_eq!(p("+99999999999999999999-01-01T00:00:00Z"), Err(ParseError::OutOfRange));
        assert_eq!(p("+262142-12-31T23:59:59-00:01"), Err(ParseError::Impossible));
        let e = serde_json::from_str::<Ts>("\"2026-11-04\"").unwrap_err().to_string();
        assert!(e.starts_with("premature end of input"), "{e}");
        let e = serde_json::from_str::<Ts>("5").unwrap_err().to_string();
        assert!(e.starts_with("invalid type: integer `5`, expected an RFC 3339 formatted date and time string"), "{e}");
    }

    #[test]
    fn leap_seconds_at_the_ends_of_the_range() {
        // chrono read the second after the last one as a leap second; this type cannot hold it (module doc)
        assert_eq!(p("+262142-12-31T23:59:60Z"), Err(ParseError::OutOfRange));
        assert_eq!(p("+262142-12-31T23:59:59.999999999Z"), Ok("+262142-12-31T23:59:59.999999999Z".into()));
        // a leap second whose second :59 lies before the range is outside it, as in chrono
        assert_eq!(p("-262143-01-01T00:00:60+00:01"), Err(ParseError::Impossible));
        assert_eq!(p("-262143-01-01T00:01:60+00:01"), Ok("-262143-01-01T00:01:00Z".into()));
    }

    #[test]
    fn the_database_value_range_is_checked_without_a_server() {
        let ty = Type::TIMESTAMPTZ;
        let decode = |us: i64| Ts::from_sql(&ty, &us.to_be_bytes()).map(|t| t.to_string()).map_err(|e| e.to_string());
        assert_eq!(decode(0), Ok("2000-01-01T00:00:00Z".into()));
        assert_eq!(decode(-1), Ok("1999-12-31T23:59:59.999999Z".into()));
        let too_large = Err("value too large to decode".to_string());
        assert_eq!(decode(i64::MAX), too_large); // infinity
        assert_eq!(decode(i64::MIN), too_large); // -infinity
        assert!(<Ts as FromSql>::accepts(&Type::TIMESTAMPTZ) && !<Ts as FromSql>::accepts(&Type::TIMESTAMP));
        assert!(<Ts as ToSql>::accepts(&Type::TIMESTAMPTZ) && !<Ts as ToSql>::accepts(&Type::TEXT));
        let mut out = BytesMut::new();
        let t: Ts = "1999-12-31T23:59:59.9999995Z".parse().unwrap();
        t.to_sql(&ty, &mut out).unwrap();
        assert_eq!(out.as_ref(), 0i64.to_be_bytes()); // cut toward 2000-01-01
    }

    proptest::proptest! {
        // Any instant of the range is written and read back unchanged, both forms of RFC 3339 agree on it, and the
        // text keeps the instant's order.
        #[test]
        fn text_round_trips(n in MIN_UNIX_NANOS..=MAX_UNIX_NANOS, m in MIN_UNIX_NANOS..=MAX_UNIX_NANOS) {
            let (a, b) = (Ts::from_unix_nanos(n).unwrap(), Ts::from_unix_nanos(m).unwrap());
            let text = a.to_string();
            proptest::prop_assert_eq!(text.parse::<Ts>(), Ok(a));
            if !text.starts_with(['+', '-']) {
                proptest::prop_assert_eq!(Ts::parse_rfc3339(&text), Some(a));
            }
            proptest::prop_assert_eq!(a.cmp(&b), n.cmp(&m));
            proptest::prop_assert_eq!(a.unix_micros(), i64::try_from(n.div_euclid(1000)).unwrap());
        }
    }
}
