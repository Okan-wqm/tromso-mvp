"""How water values read on the pages, in the person's language: each at its parameter's precision with
the language's decimal sign, a limit row as a short sentence, and how old a value is."""
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

from django import template
from django.utils import timezone
from django.utils.timesince import timesince
from django.utils.translation import gettext as _

from core import text

from ..models.site import zone_of
from ..models.water_point import site_of
from ..water import messages, parameters, read as water_read
from ..water.evaluate import ANY_WATER, Status
from .stock import DASH, number

register = template.Library()


@register.filter
def water_value(value, code):
    """A value of a parameter, at its precision: 7.45, 12.0, 0.0123."""
    if value in (None, ''):
        return DASH
    return number(value, parameters.get(code).decimals)


# How many decimals more than its parameter keeps a worked-out value may be said with, to read on the side of a bound it
# is on (`value_past`).
EXTRA_DECIMALS = 3


def value_past(reading, limit, below):
    """The reading's value as a sentence says it beside `limit`, the bound its judgement named (evaluate.crossed: `below`
    is whether it was past it from under). A worked-out value is judged unrounded (`Reading.exact`, the audit of
    2026-11-19, F3) and shown at its parameter's decimals, so a true 59.988221 % past a limit of 60.0 is shown 60.0 and a
    sentence that set it beside the bound read "60.0 < critical limit 60.0". Where the shown value reads past the bound,
    it is said as `water_value` says it; where it reads on it (rounded onto it), the exact value with the fewest extra
    decimals that read past ("59.99 < 60.0"), at most `EXTRA_DECIMALS` and, past them, cut toward the side it is on, so
    it is never rounded onto the bound. Display only: nothing here judges, and a value the bound does not name, or one
    judged as entered (`exact` None: it has no more decimals than are shown), is said as it always was."""
    shown = water_value(reading.value, reading.code)
    exact = reading.exact
    if exact is None or not _past(exact, limit, below) or _past(reading.value, limit, below):
        return shown
    decimals = parameters.get(reading.code).decimals
    for places in range(decimals + 1, decimals + EXTRA_DECIMALS + 1):
        rounded = exact.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
        if _past(rounded, limit, below):
            return number(rounded, places)
    return number(exact.quantize(Decimal(1).scaleb(-places), rounding=ROUND_FLOOR if below else ROUND_CEILING), places)


def _past(value, limit, below):
    return value < limit if below else value > limit


@register.filter
def bound(row, name):
    """One bound of a limit row, at its parameter's precision; a dash when open."""
    return water_value(getattr(row, name), row.parameter)


def limit_text(row):
    """A limit row as the forms and the drawer say it: "Atlantic salmon (sea water): critical below 60,
    warning below 80, warning above 110"."""
    def show(value):
        return number(value, row.measure.decimals)

    parts = []
    if row.critical_low is not None:
        parts.append(_('critical below %(value)s') % {'value': show(row.critical_low)})
    if row.warning_low is not None:
        parts.append(_('warning below %(value)s') % {'value': show(row.warning_low)})
    if row.warning_high is not None:
        parts.append(_('warning above %(value)s') % {'value': show(row.warning_high)})
    if row.critical_high is not None:
        parts.append(_('critical above %(value)s') % {'value': show(row.critical_high)})
    who = row.species.common_name
    if row.water_type != ANY_WATER:
        who = f'{who} ({text.lower(row.get_water_type_display())})'
    return f'{who}: {", ".join(parts)}'


register.filter('limit_text', limit_text)


@register.filter
def age(moment):
    """How long ago, the largest unit only: "3 hours", "2 days"."""
    if not moment:
        return DASH
    return timesince(moment, timezone.now(), depth=1)


@register.filter
def sample_clock(sample):
    """When a sample was taken, on the clock of its site, as a naive time the date filter shows as it is."""
    return timezone.make_naive(sample.measured_at, zone_of(site_of(sample.point)))


@register.filter
def status_label(status):
    return Status(status).label


@register.filter
def ionic_strength_unit(equilibria):
    """The unit of a water's ionic strength (messages.ionic_strength_unit): mol/kg H₂O or mol/L."""
    return messages.ionic_strength_unit(equilibria)


@register.filter
def amount(value, decimals):
    """A worked-out value (the calculator's) at `decimals` decimals as the language writes it; a dash when
    there is none."""
    return DASH if value is None else number(value, int(decimals))


@register.filter
def ph_margin(value):
    """How far a pH is from a limit's border on the safe side, with its sign: +0.42, −0.10."""
    return signed_amount(value, 2)


@register.filter
def signed_amount(value, decimals):
    """A change with its sign, at `decimals` decimals as the language writes it: +0.500, −1.25, 0."""
    if value is None:
        return DASH
    rounded = round(value, int(decimals))
    return ('+' if rounded > 0 else '−' if rounded < 0 else '') + number(abs(rounded), int(decimals))


def short_age(moment, now=None):
    """How long ago: the seconds of a live value under a minute ("12 s"), else as `age` says it ("3 hours")."""
    if not moment:
        return DASH
    now = now or timezone.now()
    seconds = int((now - moment).total_seconds())
    if seconds < 60:
        return _('%(count)d s') % {'count': max(seconds, 0)}
    return timesince(moment, now, depth=1)


@register.filter
def source(reading, now=None):
    """Where a value comes from and how old it is, as every page with a latest value shows it (owner rule A1), for
    farm/_water_source.html: {'origin': 'unit sensor #12', 'age': '12 s ago'}, 'system sensor #3' and '40 s ago',
    'manual' and '2 days ago'; `now`: the moment the age is counted to (a past moment's Deffeyes), else now."""
    if not reading:
        return None
    # Translators: how old a value is, e.g. "12 s ago", "2 days ago".
    return {'origin': water_read.origin_text(reading), 'age': _('%(age)s ago') % {'age': short_age(reading.at, now or None)}}
