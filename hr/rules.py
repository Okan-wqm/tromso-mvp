"""The rules a person's plan must keep, as pure functions: no query, no clock, no request. The caller reads the plan,
the leave and the holidays, and hands them over; what comes back is a list of findings, each with a code and a
severity. One place for each rule, and the same function whether the plan is being saved or only shown.

Blocking: a shift on a day of approved leave, and two shifts that overlap. By the setting `rest_rule` (warn or block): a
rest shorter than the minimum, measured between the real instants (so across a week's border and a night shift). Warn
only: more hours than the standard week, more days in a row than the maximum, work on a holiday. The statutory figures
are not constants here: they are settings the owner confirms (hr.models.SchedulingSettings)."""
from dataclasses import dataclass
from datetime import date, timedelta, timezone

from django.utils.translation import gettext, gettext_noop

BLOCK, WARN = 'block', 'warn'

LEAVE_OVERLAP = 'leave_overlap'
SPAN_OVERLAP = 'span_overlap'
REST_SHORT = 'rest_short'
WEEK_HOURS = 'week_hours'
CONSECUTIVE_DAYS = 'consecutive_days'
HOLIDAY_WORK = 'holiday_work'


# What a finding says, one sentence per code (msgids: the log stores them in English, a page shows them translated).
TEXT = {
    LEAVE_OVERLAP: gettext_noop('The person is on approved leave on this day.'),
    SPAN_OVERLAP: gettext_noop('This shift overlaps another shift of the person.'),
    REST_SHORT: gettext_noop('The rest since the last shift is shorter than the minimum.'),
    WEEK_HOURS: gettext_noop('The week is longer than the standard week.'),
    CONSECUTIVE_DAYS: gettext_noop('The person works more days in a row than the most allowed.'),
    HOLIDAY_WORK: gettext_noop('The person works on a holiday.'),
}


def text(finding):
    """The sentence for a finding, in the language of the person reading."""
    return gettext(TEXT[finding.code])


@dataclass(frozen=True)
class Planned:
    """One shift of one person: the day it starts, its real span (aware instants) and its planned minutes."""
    day: date
    start: object
    end: object
    net_minutes: int


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    day: date
    detail: int = 0          # minutes of rest, or of the week, or the days in a row, whichever the code is about

    @property
    def blocks(self):
        return self.severity == BLOCK


def monday(day):
    """The Monday of the ISO week of `day`: the one start of HR's week (a total, a rule, a page)."""
    return day - timedelta(days=day.weekday())


def week_minutes(planned, week):
    """The planned minutes of the week starting on the Monday `week`: the one weekly total, of the rule and of the
    roster's row."""
    return sum(item.net_minutes for item in planned if monday(item.day) == week)


def findings(planned, leave_days, holidays, settings, weeks, only=None):
    """The findings for one person.

    `planned`: every Planned shift in the window (the weeks and a day or more either side, so the rest across a border
    and a run of days that crosses it are seen); `leave_days`: the days of approved leave; `holidays`: the days that
    are holidays for the person's site; `settings`: min_rest_minutes, standard_week_minutes, max_consecutive_days,
    rest_rule; `weeks`: the Mondays of the weeks a finding is wanted for (the rest of the window only gives context);
    `only`: when given, the leave and holiday findings are for those days alone (the days a save changes: an old
    conflict elsewhere in the week is not the new plan's)."""
    wanted = {monday(week) for week in weeks}
    found = []
    ordered = sorted(planned, key=lambda item: (item.start, item.end))
    by_day = {}
    for item in ordered:
        by_day.setdefault(item.day, []).append(item)
        if item.day in leave_days and monday(item.day) in wanted and (only is None or item.day in only):
            found.append(Finding(LEAVE_OVERLAP, BLOCK, item.day))
        if item.day in holidays and monday(item.day) in wanted and (only is None or item.day in only):
            found.append(Finding(HOLIDAY_WORK, WARN, item.day))
    for before, after in zip(ordered, ordered[1:]):
        if monday(after.day) not in wanted and monday(before.day) not in wanted:
            continue
        if after.start < before.end:
            found.append(Finding(SPAN_OVERLAP, BLOCK, after.day))
            continue
        rest = int((after.start - before.end).total_seconds() // 60)
        if rest < settings.min_rest_minutes:
            found.append(Finding(REST_SHORT, settings.rest_rule, after.day, rest))
    for week in sorted(wanted):
        total = week_minutes(ordered, week)
        if total > settings.standard_week_minutes:
            found.append(Finding(WEEK_HOURS, WARN, week, total))
    found.extend(_runs(sorted(by_day), settings.max_consecutive_days, wanted))
    return found


def _runs(days, longest, wanted):
    """A finding on the day a run of working days goes past `longest`, for the weeks wanted."""
    found, run = [], 0
    previous = None
    for day in days:
        run = run + 1 if previous is not None and day - previous == timedelta(days=1) else 1
        if run > longest and monday(day) in wanted:
            found.append(Finding(CONSECUTIVE_DAYS, WARN, day, run))
        previous = day
    return found


# ---- who is where: a person's state on a day, from the plan, the punches and the leave ------------------------------
UPCOMING, PRESENT, LATE, NOT_IN, ABSENT, ON_LEAVE, DONE = ('upcoming', 'present', 'late', 'not_in', 'absent', 'on_leave',
                                                           'done')
FORGOTTEN = 'forgotten'          # a clock-in left open past the limit: nobody knows whether the person is there
STATES = (UPCOMING, PRESENT, LATE, NOT_IN, ABSENT, ON_LEAVE, DONE, FORGOTTEN)


def forgotten_before(now, forgotten_after_hours):
    """The instant before which an open clock-in counts as a forgotten clock-out at `now`: the limit is HR's setting
    (SchedulingSettings.forgotten_after_hours), never a figure here. Counted in UTC: hours taken off a moment on a
    site's own clock would be an hour out on the night the clocks change."""
    return now.astimezone(timezone.utc) - timedelta(hours=forgotten_after_hours)    # elapsed hours, in any zone


def forgotten(clock_in, clock_out, now, forgotten_after_hours):
    """Whether a stretch is a forgotten clock-out (the owner, F-095): still open, and open longer than the limit. The one
    rule for the board, the emergency count, the person's own clock-in and clock-out and the Attendance page. Nobody
    knows when the person left, so nothing may read it as presence or as worked time, and nothing closes it but a
    person who knows the real time (a lead's correction on the Attendance page)."""
    return clock_out is None and clock_in < forgotten_before(now, forgotten_after_hours)


@dataclass(frozen=True)
class Standing:
    """A person's state now: `state`, the first clock-in and the last clock-out that count for the shift, and the
    minutes late (past the grace)."""
    state: str
    first_in: object = None
    last_out: object = None
    late_minutes: int = 0


def status(span, punches, on_leave, now, grace_minutes, absent_after_minutes, window_minutes, forgotten_after_hours):
    """The state of one person: nothing stored, all read. `span` is the planned (start, end) as instants, or None;
    `punches` are (clock_in, clock_out or None) of the person, which count for the shift when the clock-in falls from the
    punch window before the start up to the end (all of them when nothing is planned: an unplanned presence is still a
    presence). A record is a fact and the plan an intent: a person who clocked in is present or late (or done once they clocked
    out) whatever the plan says; one who did not is upcoming until the start plus the grace, not in until the start plus the
    later of the grace and the absent-after minutes, and absent after that. On approved leave a person who did not clock in is
    on leave; one who did is present (or done) all the same: the board is the headcount on site, in an emergency too.
    An open clock-in (no clock-out yet) counts whatever the window: the person is on site now, called in hours before the
    shift or still there after it; only the shift's own clock-ins (inside the window) say whether they were late.
    Until it is open longer than `forgotten_after_hours`: then it is a forgotten clock-out (`forgotten`), a state of its
    own whatever the plan or the leave, with the clock-in it has been open since. Not present (nobody knows), not done
    (no time to say), and not absent either: the person may be back at work, unable to clock in beside it."""
    left_open = next((punch for punch in punches if forgotten(punch[0], punch[1], now, forgotten_after_hours)), None)
    if left_open is not None:
        return Standing(FORGOTTEN, left_open[0])
    counted = inside = list(punches)
    if span is not None:
        start, end = span
        earliest = start - timedelta(minutes=window_minutes)
        inside = [punch for punch in punches if earliest <= punch[0] < end]
        counted = inside + [punch for punch in punches if punch[1] is None and punch not in inside]
    if counted:                         # a clock-in is a fact: it beats the plan and the leave
        first_in = min(punch[0] for punch in (inside or counted))
        late = 0
        if span is not None and inside and not on_leave:  # called in on a day of leave is never late
            late = max(0, int((first_in - span[0]).total_seconds() // 60) - grace_minutes)
        if any(punch[1] is None for punch in counted):
            return Standing(LATE if late else PRESENT, first_in, None, late)
        return Standing(DONE, first_in, max(punch[1] for punch in counted), late)
    if on_leave:
        return Standing(ON_LEAVE)
    if span is None:
        return None
    start = span[0]
    if now < start + timedelta(minutes=grace_minutes):
        return Standing(UPCOMING)
    if now < start + timedelta(minutes=max(grace_minutes, absent_after_minutes)):
        return Standing(NOT_IN)
    return Standing(ABSENT)
