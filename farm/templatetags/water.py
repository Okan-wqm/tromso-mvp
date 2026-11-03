"""How water values read on the pages, in the person's language: each at its parameter's precision with
the language's decimal sign, a limit row as a short sentence, and how old a value is."""
from django import template
from django.utils import timezone
from django.utils.timesince import timesince
from django.utils.translation import gettext as _

from ..models.site import zone_of
from ..models.water import site_of
from ..water import parameters
from ..water.evaluate import ANY_WATER, Status
from .stock import DASH, number

register = template.Library()


@register.filter
def water_value(value, code):
    """A value of a parameter, at its precision: 7.45, 12.0, 0.0123."""
    if value in (None, ''):
        return DASH
    return number(value, parameters.get(code).decimals)


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
        who = f'{who} ({row.get_water_type_display().lower()})'
    return f'{who}: {", ".join(parts)}'


register.filter('limit_text', limit_text)


@register.filter
def age(moment):
    """How long ago, the largest unit only: "3 hours", "2 days"."""
    if not moment:
        return DASH
    return timesince(moment, timezone.now(), depth=1)


@register.filter
def site_clock(sample):
    """When a sample was taken, on the clock of its site, as a naive time the date filter shows as it is."""
    return timezone.make_naive(sample.measured_at, zone_of(site_of(sample.point)))


@register.filter
def status_label(status):
    return Status(status).label


@register.filter
def amount(value, decimals):
    """A worked-out value (the calculator's) at `decimals` decimals as the language writes it; a dash when
    there is none."""
    return DASH if value is None else number(value, int(decimals))


@register.filter
def ph_margin(value):
    """How far a pH is from a limit's border on the safe side, with its sign: +0.42, −0.10."""
    if value is None:
        return DASH
    rounded = round(value, 2)
    return ('+' if rounded > 0 else '−' if rounded < 0 else '') + number(abs(rounded), 2)
