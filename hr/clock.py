"""A shift on a day as real instants. A shift is a wall-clock start and end; the day it belongs to is the day it starts;
the zone is the site's (`farm.models.site.zone_of`). The length of a shift is the distance between its two instants, so
22:00-06:00 is 7 hours on the night the clocks go forward and 9 hours on the night they go back (the source took the
wall-clock difference: docs/aquaculture-platform-bugs.md HR-08)."""
from datetime import datetime, time, timedelta, timezone as utc


def span(day, shift, zone):
    """(start, end) of `shift` on `day` as aware UTC instants. A time that does not exist (the hour skipped when the
    clocks go forward) or exists twice takes its first reading."""
    start = datetime.combine(day, shift.starts_at, tzinfo=zone)
    end_day = day if shift.ends_at > shift.starts_at else day + timedelta(days=1)
    end = datetime.combine(end_day, shift.ends_at, tzinfo=zone)
    return start.astimezone(utc.utc), end.astimezone(utc.utc)


def minutes(start, end):
    """Whole minutes between two instants."""
    return int((end - start).total_seconds() // 60)


def net_minutes(start, end, break_minutes):
    """The planned minutes of a span without its unpaid break."""
    return minutes(start, end) - break_minutes


def start_of_day(day, zone):
    """The first instant of `day` on the zone's clock, in UTC."""
    return datetime.combine(day, time.min, tzinfo=zone).astimezone(utc.utc)
