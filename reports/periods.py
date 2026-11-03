"""The periods reports are owed for and their deadlines, on the authorities' calendar.

The deadlines are calendar days in Norway ("senest i løpet av tirsdag", "den 7. i påfølgende måned"), so they are
dates read in Europe/Oslo, whatever clock a site keeps (a site without a time zone runs on the company's, UTC):
today is today in Oslo, and a report is overdue once today in Oslo is after its deadline. Weeks are ISO weeks
(Monday to Sunday) numbered in the ISO week-numbering year: 28 December 2026 to 3 January 2027 is 2026-W53
(which year Mattilsynet expects at that edge is not stated by it; docs/regulatory-reports.md, 5.2)."""
from dataclasses import dataclass
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from django.utils import formats, timezone
from django.utils.translation import gettext as _

OSLO = ZoneInfo('Europe/Oslo')

WEEK, MONTH, YEAR = 'week', 'month', 'year'


def oslo_today(now=None):
    """Today on the authorities' calendar."""
    return timezone.localdate(now, timezone=OSLO)


def month_start(day):
    return day.replace(day=1)


def next_month(day):
    """The first day of the month after `day`'s."""
    return (day.replace(day=1) + timedelta(days=32)).replace(day=1)


def week_start(day):
    """The Monday of `day`'s ISO week."""
    return day - timedelta(days=day.isoweekday() - 1)


@dataclass(frozen=True, order=True)
class Period:
    """An ISO week (`start` a Monday), a calendar month (`start` the 1st) or a calendar year (`start` 1 January)."""
    grain: str
    start: date

    def __post_init__(self):
        if self.grain == WEEK and self.start.isoweekday() != 1:
            raise ValueError(f'A week starts on a Monday, not {self.start}.')
        if self.grain == MONTH and self.start.day != 1:
            raise ValueError(f'A month starts on the 1st, not {self.start}.')
        if self.grain == YEAR and (self.start.month, self.start.day) != (1, 1):
            raise ValueError(f'A year starts on 1 January, not {self.start}.')

    @classmethod
    def of(cls, grain, day):
        """The period of `grain` that `day` falls in."""
        if grain == WEEK:
            return cls(WEEK, week_start(day))
        if grain == MONTH:
            return cls(MONTH, month_start(day))
        return cls(YEAR, day.replace(month=1, day=1))

    @property
    def end(self):
        """The period's last day."""
        if self.grain == WEEK:
            return self.start + timedelta(days=6)
        if self.grain == MONTH:
            return next_month(self.start) - timedelta(days=1)
        return self.start.replace(month=12, day=31)

    @property
    def next(self):
        if self.grain == WEEK:
            return Period(WEEK, self.start + timedelta(days=7))
        if self.grain == MONTH:
            return Period(MONTH, next_month(self.start))
        return Period(YEAR, self.start.replace(year=self.start.year + 1))

    @property
    def iso(self):
        """(ISO year, ISO week) of a week; (year, month) of a month; (year,) of a year."""
        if self.grain == WEEK:
            year, week, _day = self.start.isocalendar()
            return year, week
        if self.grain == MONTH:
            return self.start.year, self.start.month
        return (self.start.year,)

    @property
    def key(self):
        """How the period is written in an address and a file name: 2026-W45, 2026-11, 2026."""
        if self.grain == WEEK:
            return '%d-W%02d' % self.iso
        if self.grain == MONTH:
            return '%d-%02d' % self.iso
        return str(self.start.year)

    @classmethod
    def from_key(cls, key):
        """The period written as `key` (2026-W45, 2026-11, 2026); ValueError when it is not one."""
        if '-W' in key:
            year, week = key.split('-W')
            return cls(WEEK, date.fromisocalendar(int(year), int(week), 1))
        if '-' in key:
            year, month = key.split('-')
            return cls(MONTH, date(int(year), int(month), 1))
        return cls(YEAR, date(int(key), 1, 1))

    def label(self):
        """The period as a person reads it, in their language: week 45 of 2026, November 2026, 2026."""
        if self.grain == WEEK:
            year, week = self.iso
            return _('Week %(week)d of %(year)d') % {'week': week, 'year': year}
        if self.grain == MONTH:
            return formats.date_format(self.start, 'YEAR_MONTH_FORMAT')
        return str(self.start.year)

    def __str__(self):
        return self.key


def periods_between(grain, first, last):
    """Every period of `grain` that overlaps the days from `first` to `last`, oldest first."""
    found, period = [], Period.of(grain, first)
    while period.start <= last:
        found.append(period)
        period = period.next
    return found


def tuesday_after(period):
    """The Tuesday of the week after a week: the sea-lice deadline (lakselusforskriften § 10)."""
    return period.end + timedelta(days=2)


def seventh_after(period):
    """The 7th of the month after a month, or of January after a year (akvakulturdriftsforskriften § 44, § 44a,
    § 58; the cleaner-fish report)."""
    return period.end + timedelta(days=7)


def thursday_before(period):
    """The Thursday of the week before a week: the planned-slaughter deadline (restkontrollforskriften § 9a)."""
    return period.start - timedelta(days=4)
