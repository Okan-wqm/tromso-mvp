"""A date typed into a page, the European way in every language (owner rule): dd.mm.yyyy, or ISO (2026-11-06) as an
address carries it, inside one window of dates (01.01.1900 to 31.12.2100). The one reading of a list's date filter
(?from=, ?to=, ?week=: `read_day`) and the rules every form's date and moment field follows (`install`, from core apps):
another shape (11/06/2026, 06-11-2026, a two-digit year) is never reinterpreted, a date outside the window is refused
(never a server error further on), and a moment needs its time (never a silent 00:00)."""
import re
from datetime import date, datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django import forms
from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.utils import formats, timezone
from django.utils.translation import gettext, gettext_lazy as _

FIRST, LAST = date(1900, 1, 1), date(2100, 12, 31)
DAY_SHAPE = re.compile(r'^([0-9]{1,2}\.[0-9]{1,2}\.[0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2})$')   # ASCII digits only
TIME = re.compile(r'[0-9]{1,2}:[0-9]{2}')

SHAPE = _('Give the date as dd.mm.yyyy, e.g. 06.11.2026.')
MOMENT_SHAPE = _('Give the date and the time as dd.mm.yyyy HH:MM, e.g. 06.11.2026 09:19.')
OUTSIDE = _('Give a date from 01.01.1900 to 31.12.2100.')


def inside(day):
    return day is not None and FIRST <= day <= LAST


def company_zone():
    """The company's time zone (settings.COMPANY_TIME_ZONE, checked when the server starts: farm.checks): the clock of a
    place without a site, never the server's UTC (settings.TIME_ZONE). A site reads its own (farm's zone_of)."""
    return ZoneInfo(settings.COMPANY_TIME_ZONE)


def company_today():
    """Today on the company's clock."""
    return timezone.localdate(timezone=company_zone())


def read_day(text, request=None):
    """The one day parser: the date in `text` (dd.mm.yyyy or ISO in ASCII digits, inside the window), or None. With `request`, a text that is not such a date
    is said back to the person (a list still answers, unfiltered by it)."""
    if not isinstance(text, str):                     # a number, a date object, a list: not a date typed
        return None
    text = text.strip()
    if not text:
        return None
    found = None
    if DAY_SHAPE.match(text):
        for shape in formats.get_format('DATE_INPUT_FORMATS'):
            try:
                found = datetime.strptime(text, shape).date()
                break
            except ValueError:
                continue
    if inside(found):
        return found
    if request is not None:
        messages.error(request, gettext('“%(text)s” is not a date this page reads: give it as dd.mm.yyyy, e.g. 06.11.2026, '
                                        'from 01.01.1900 to 31.12.2100.') % {'text': text})
    return None


MOMENT_SHAPE_ADDRESS = re.compile(r'^(?:([0-9]{4}-[0-9]{2}-[0-9]{2})T|([0-9]{1,2}\.[0-9]{1,2}\.[0-9]{4}) )'
                                  r'([0-9]{1,2}):([0-9]{2})$')                         # ASCII digits only


def read_moment(text):
    """The one moment parser of an address (a chart's ?at=, a replay's start and end): the wall time in `text`, as the
    links write it (2026-11-06T09:19) or the European way (06.11.2026 09:19), its day read by read_day (so inside the
    window of dates), naive; None for anything else. The caller reads it on its site's clock and refuses a None."""
    if not isinstance(text, str):
        return None
    found = MOMENT_SHAPE_ADDRESS.match(text.strip())
    if found is None:
        return None
    day = read_day(found[1] or found[2])
    hour, minute = int(found[3]), int(found[4])
    if day is None or hour > 23 or minute > 59:
        return None
    return datetime(day.year, day.month, day.day, hour, minute)


STORED_MOMENT = re.compile(r'^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}(:[0-9]{2}(\.[0-9]{1,6})?)?[+-][0-9]{2}:[0-9]{2}$')


def stored_moment(text):
    """An instant the code wrote itself as ISO with its offset (a report's content, `found_at`), aware; None for anything
    else. Never for what a person typed: that is read_moment's, on a site's clock."""
    if not isinstance(text, str) or not STORED_MOMENT.match(text):
        return None
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    return moment if inside(moment.date()) else None


PERIOD_KEY = re.compile(r'^([0-9]{4})(?:-W([0-9]{2})|-([0-9]{2}))?$')          # ASCII digits only


def read_period(key):
    """A period's key as an address writes it (2026-W45, 2026-11, 2026): ('week', its Monday), ('month', its first day) or
    ('year', 1 January), inside the window of dates; None for anything else (a week the year has not, month 13, year 1)."""
    found = PERIOD_KEY.match(key) if isinstance(key, str) else None
    if found is None:
        return None
    year, week, month = int(found[1]), found[2], found[3]
    try:
        if week is not None:
            grain, start = 'week', date.fromisocalendar(year, int(week), 1)
        elif month is not None:
            grain, start = 'month', date(year, int(month), 1)
        else:
            grain, start = 'year', date(year, 1, 1)
    except ValueError:
        return None
    return (grain, start) if inside(start) else None


SKIPPED = _('This time does not exist on the site’s clock (the clocks go forward): choose another.')
REPEATED = _('This time happens twice on the site’s clock (the clocks go back): choose another.')


def on_clock(wall, zone):
    """The one check of a wall time on a clock: the aware moment that `wall` (naive) is on `zone`; ValidationError when the
    clocks skip it (code 'skipped', a spring night) or show it twice (code 'repeated', an autumn night)."""
    first, second = wall.replace(fold=0, tzinfo=zone), wall.replace(fold=1, tzinfo=zone)
    # through UTC: astimezone to its own zone changes nothing, so a skipped time would read back as itself
    if timezone.make_naive(first.astimezone(dt_timezone.utc), zone) != wall:     # first: in a gap the folds differ too
        raise ValidationError(SKIPPED, code='skipped')
    if first.utcoffset() != second.utcoffset():
        raise ValidationError(REPEATED, code='repeated')
    return first


def on_clock_or_earlier(wall, zone):
    """`on_clock`, but a wall time the clocks show twice (an autumn night) is the earlier of the two, not refused: for a
    moment that only names a neighbourhood (an alarm's opening in a link, the 12 hours each side of it). A skipped time
    is still refused (ValidationError, code 'skipped')."""
    try:
        return on_clock(wall, zone)
    except ValidationError as error:
        if error.code != 'repeated':
            raise
        return wall.replace(fold=0, tzinfo=zone)


def _shaped(text):
    """Whether `text` is a real calendar date in an accepted shape, inside the window or not."""
    for shape in formats.get_format('DATE_INPUT_FORMATS'):
        try:
            datetime.strptime(text, shape)
            return True
        except ValueError:
            continue
    return False


def show_day(day):
    """A date as an input shows it: dd.mm.yyyy."""
    return formats.localize_input(day) if day else ''


def _in_window(value):
    day = value.date() if isinstance(value, datetime) else value
    if day is not None and not inside(day):
        raise ValidationError(OUTSIDE, code='outside')


def install():
    """The rules of every form's date and moment field (called once, from core apps): the shared boxes, the shape said in
    the error, the window, and a moment's time required."""
    from .widgets import DayInput, MomentInput

    forms.DateField.widget = DayInput
    forms.DateTimeField.widget = MomentInput
    forms.DateField.default_error_messages = {**forms.DateField.default_error_messages, 'invalid': SHAPE}
    forms.DateTimeField.default_error_messages = {**forms.DateTimeField.default_error_messages, 'invalid': MOMENT_SHAPE}
    forms.DateField.default_validators = [_in_window]
    forms.DateTimeField.default_validators = [_in_window]
    day_to_python, moment_to_python = forms.DateField.to_python, forms.DateTimeField.to_python

    def day(self, value):
        if isinstance(value, str) and value.strip() and not DAY_SHAPE.match(value.strip()):
            raise ValidationError(self.error_messages['invalid'], code='invalid')
        return day_to_python(self, value)

    def moment(self, value):
        if isinstance(value, str) and value.strip():
            text = value.strip()
            day_part = re.split(r'[ T]', text)[0]
            if not TIME.search(text) or not DAY_SHAPE.match(day_part):
                raise ValidationError(self.error_messages['invalid'], code='invalid')
            if read_day(day_part) is None and _shaped(day_part):      # a real date outside the window: before any
                raise ValidationError(OUTSIDE, code='outside')          # time-zone sum overflows on it
        return moment_to_python(self, value)

    forms.DateField.to_python = day
    forms.DateTimeField.to_python = moment
