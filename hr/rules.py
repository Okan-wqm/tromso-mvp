"""The rules a person's plan must keep, as pure functions: no query, no clock, no request. The caller reads the plan,
the leave and the holidays, and hands them over; what comes back is a list of findings, each with a code and a
severity. One place for each rule, and the same function whether the plan is being saved or only shown.

Blocking: a shift on a day of approved leave, and two shifts that overlap. By the setting `rest_rule` (warn or block): a
rest shorter than the minimum, measured between the real instants (so across a week's border and a night shift). Warn
only: more hours than the standard week, more days in a row than the maximum, work on a holiday. The statutory figures
are not constants here: they are settings the owner confirms (hr.models.SchedulingSettings)."""
from dataclasses import dataclass
from datetime import date, timedelta

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
    """The Monday of the ISO week of `day`."""
    return day - timedelta(days=day.weekday())


def findings(planned, leave_days, holidays, settings, weeks):
    """The findings for one person.

    `planned`: every Planned shift in the window (the weeks and a day or more either side, so the rest across a border
    and a run of days that crosses it are seen); `leave_days`: the days of approved leave; `holidays`: the days that
    are holidays for the person's site; `settings`: min_rest_minutes, standard_week_minutes, max_consecutive_days,
    rest_rule; `weeks`: the Mondays of the weeks a finding is wanted for (the rest of the window only gives context)."""
    wanted = {monday(week) for week in weeks}
    found = []
    ordered = sorted(planned, key=lambda item: (item.start, item.end))
    by_day = {}
    for item in ordered:
        by_day.setdefault(item.day, []).append(item)
        if item.day in leave_days and monday(item.day) in wanted:
            found.append(Finding(LEAVE_OVERLAP, BLOCK, item.day))
        if item.day in holidays and monday(item.day) in wanted:
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
        total = sum(item.net_minutes for item in ordered if monday(item.day) == week)
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
