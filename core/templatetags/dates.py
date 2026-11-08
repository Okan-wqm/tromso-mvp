"""`{% day_input "from" value %}`: a list's date filter as the forms' date (core.widgets.DayInput), typed and shown in the
person's language, read back by core.dates.read_day; never a browser date box. The clocks a page shows a time on
(`|date` and `|time` would show an aware moment on the server's UTC; core/clock_guard.py refuses that in the tests):
`|site_clock:site`, the site's (a Site, a zone or a zone's name; none: the company's), and `|company_clock`."""
from datetime import datetime
from zoneinfo import ZoneInfo

from django import template
from django.utils import timezone

from ..dates import company_zone
from ..widgets import DayInput

register = template.Library()


@register.simple_tag
def day_input(name, value='', **attrs):
    """The input; `attrs` become its attributes (id, data-autosubmit=True)."""
    attrs = {key.replace('_', '-'): ('' if item is True else item) for key, item in attrs.items()}
    return DayInput(attrs=attrs).render(name, value or None)


def zone_for(where):
    """The zone of `where`: a ZoneInfo, a zone's name, a Site (its `timezone`); None or '' is the company's."""
    if isinstance(where, ZoneInfo):
        return where
    name = getattr(where, 'timezone', where)
    return ZoneInfo(name) if isinstance(name, str) and name else company_zone()


def on(value, zone):
    """The moment on `zone`'s clock, naive on purpose: the template engine would bring an aware time back to the server's
    zone before `date` formats it. A naive value or a date is already a wall time and passes as it is."""
    if not isinstance(value, datetime) or timezone.is_naive(value):
        return value
    return timezone.make_naive(value, zone)


@register.filter
def site_clock(value, where=None):
    """The moment on the clock of a site (`where`: a Site, a zone or its name; none: the company's)."""
    return on(value, zone_for(where))


@register.filter
def company_clock(value):
    """The moment on the company's clock, for a page with no site's clock (the activity log, a record's history)."""
    return on(value, company_zone())
