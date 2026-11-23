"""A device whose clock differs from the platform's (owner, 2026-11-09): its skew, measured by sensors/clock.py (the
device's time of its newest good value against the time the platform received it, ahead or behind), judged by the
user's limits (alarms.SeverityPolicy `clock_skew_seconds` and `clock_skew_deadband_seconds`, per severity, through
alarms.rules), the one judgement the alarm (sources.device_clocks), the device list and the unit's card all read.

- a level holds while the skew, either way, is past its limit (a device time the ingest replaced is ahead by more than
  the contract's future skew: it holds where that is at or past the limit);
- it clears once the skew is back inside the limit by the deadband, for the severity's off-delay;
- no recent value measures nothing: the level neither holds nor clears (an alarm does not end by going blind);
- "behind" is late delivery as much as a slow clock (an ingest restart, a gateway draining its store after a link drop),
  so it holds only when the device is behind on every pass of the severity's window (`clock_behind_window_seconds`, the
  user's: the minimum over the window, round-2 review N1), and never while the ingest says messages wait for the
  device's connection (a backlog being drained: it neither holds nor clears then). "Ahead" is judged at once: a stamp in
  the future is no delivery delay.
A value from a skewed device still decides its unit's status (the read layer, up to the ingest contract's hour) and its
water alarm is never delayed (sources.seen_at): this alarm says the clock is wrong, it never holds the water's back."""
from datetime import timedelta

from django.utils.translation import gettext as _

from sensors import clock as sensor_clock

from .models import Severity


def holds(skew, severity, rules):
    """Whether the skew is past the severity's limit (never "behind" while a backlog is drained)."""
    if skew.seconds < 0 and skew.draining:
        return False
    limit = rules.clock_skew(severity).total_seconds()
    return abs(skew.seconds) >= limit if skew.at_least else abs(skew.seconds) > limit


def clear(skew, severity, rules):
    """Whether the skew is back inside the severity's limit by its deadband."""
    inside = (rules.clock_skew(severity) - rules.clock_deadband(severity)).total_seconds()
    return not skew.draining and not skew.at_least and abs(skew.seconds) <= inside


def on_delay(skew, severity, rules):
    """How long a level must hold before it is raised: for a clock behind, its window (at least the severity's
    on-delay), so a backlog read mid-drain is not a slow clock; else the severity's own (None)."""
    if skew is None or skew.seconds >= 0:
        return None
    return max(rules.on_delay(severity), rules.clock_behind_window(severity))


def amount(skew):
    """'4 min' or '40 s', the skew's size."""
    size = timedelta(seconds=abs(skew.seconds))
    minutes = size // timedelta(minutes=1)
    if minutes:
        return _('%(minutes)d min') % {'minutes': minutes}
    return _('%(seconds)d s') % {'seconds': int(size.total_seconds())}


def describe(skew):
    """'Device clock is 4 min ahead', 'behind', or 'more than … ahead' when the ingest replaced its time."""
    if skew.at_least:
        return _('Device clock is more than %(amount)s ahead') % {'amount': amount(skew)}
    if skew.seconds > 0:
        return _('Device clock is %(amount)s ahead') % {'amount': amount(skew)}
    return _('Device clock is %(amount)s behind') % {'amount': amount(skew)}


def notes(device_ids, now, rules=None):
    """{device id: its note} of the devices whose clock is past the warning limit now (a note on a page: the alarm says
    the rest)."""
    from . import rules as alarm_rules
    rules = rules or alarm_rules.current()
    return {device_id: describe(skew) for device_id, skew in sensor_clock.skews(now, device_ids).items()
            if holds(skew, Severity.WARNING, rules)}
