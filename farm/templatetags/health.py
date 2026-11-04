"""How the health figures read on the page, in the person's language: a lice average to two decimals, a
medicine's withdrawal rules per species, the withdrawal line of a unit or a batch, and whether a record may still be voided."""
from django import template
from django.utils import formats
from django.utils.translation import gettext as _

from ..health import withdrawal
from ..stock.dates import earliest, site_earliest
from .stock import DASH, number

register = template.Library()


@register.filter
def lice(value):
    """An average of lice per fish: 0.18"""
    return DASH if value in (None, '') else number(value, 2)


@register.filter
def per_fish(count, stage):
    """A count's average of a stage per fish examined: 0.18"""
    return lice(count.per_fish(stage))


@register.filter
def told_of(told, event):
    """The Notified of a health event (farm.health.notices), or None when Mattilsynet has not been told of it."""
    return (told or {}).get(event.pk)


@register.filter
def withdrawal_rule(medicine):
    """A medicine's withdrawal on one line: 150 degree-days, 7 days, or both; per species when they differ."""
    return withdrawal.rules_text(medicine)


@register.filter
def withdrawal_lines(medicine):
    """[(who, Rule)] of a medicine's withdrawal rows, for the Medicines list."""
    return withdrawal.rule_lines(medicine)


def _date(day):
    return formats.date_format(day, 'DATE_FORMAT')


@register.filter
def withdrawal_until(item):
    """A Withdrawal's end as the treatments list writes it: until 13 Dec 2026 (harvest from 14 Dec 2026),
    "about" when projected, or that it is unknown."""
    if item is None:
        return DASH
    if item.until is None:
        return _('end unknown')
    params = {'last': _date(item.last_day), 'first': _date(item.until)}
    if item.estimated:
        return _('until about %(last)s (harvest from about %(first)s)') % params
    return _('until %(last)s (harvest from %(first)s)') % params


@register.filter
def withdrawal_reason(item):
    """Why a Withdrawal holds the fish."""
    return withdrawal.describe(item)


@register.filter
def unit_voidable(record):
    """Whether a treatment or a lice count is still inside the backdating window of every one of its units."""
    units = list(record.units.all()) if hasattr(record, 'units') else [record.unit]
    return not record.is_deleted and all(record.date >= earliest(unit) for unit in units)


@register.filter
def event_voidable(event):
    """Whether a health event is still inside its site's backdating window."""
    return not event.is_deleted and event.date >= site_earliest(event.site)
