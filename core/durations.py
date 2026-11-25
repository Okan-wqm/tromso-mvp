"""Durations in words, the one way the new look says them (the design: "37 h 30 min", "11 h", "30 min"; a difference as
"+10 h", "−7.5 h"), in the request's language (its units' msgids, its decimal separator). The classic look keeps its
minutes; a page that says a duration this way declares it to its parity test (core.pagesays.unsaid `said_as`, through
`said_as` below), so the fact is held, said another way."""
from decimal import Decimal

from django.utils.formats import number_format
from django.utils.translation import gettext as _


def minutes_said(minutes):
    """A duration of whole minutes: "37 h 30 min", "11 h", "30 min", "0 min"."""
    minutes = int(minutes)
    sign, minutes = ('−' if minutes < 0 else ''), abs(minutes)
    hours, rest = divmod(minutes, 60)
    if hours and rest:
        said = _('%(hours)s h %(minutes)s min') % {'hours': number_format(hours), 'minutes': number_format(rest)}
    elif hours:
        said = _('%(hours)s h') % {'hours': number_format(hours)}
    else:
        said = _('%(minutes)s min') % {'minutes': number_format(rest)}
    return sign + said


def hours_said(minutes, signed=False):
    """A duration as hours with at most one decimal ("37.5 h"); `signed`: a difference, "+10 h", "−7.5 h", "0 h"."""
    hours = (Decimal(int(minutes)) / 60).quantize(Decimal('0.1'))
    whole = hours == hours.to_integral()
    figure = number_format(int(abs(hours))) if whole else number_format(abs(hours), decimal_pos=1)
    sign = ('+' if hours > 0 else '−' if hours < 0 else '') if signed else ('−' if hours < 0 else '')
    return sign + _('%(hours)s h') % {'hours': figure}


def said_as(pairs):
    """{what the classic page says: what the new page says instead}, for core.pagesays.unsaid: each a duration said in
    minutes there and in words here (`pairs`: (classic text, new text))."""
    return {str(old): str(new) for old, new in pairs}
