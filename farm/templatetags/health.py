"""How the health figures read on the page, in the person's language: a lice average to two decimals, a
medicine's withdrawal rules per species, the withdrawal line of a unit or a batch, and whether a record may still be voided."""
from django import template

from ..handling import withdrawal as registry
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


@register.filter
def harvest_from(item):
    """The end of a withdrawal (a Withdrawal of the health records or a WithdrawalBlock of the registry) in the one
    wording of every page (farm.handling.withdrawal.harvest_from): harvest from 14.12.2026, "about" when projected, or
    end unknown."""
    if item is None:
        return DASH
    return registry.harvest_from(item.until, getattr(item, 'approximate', getattr(item, 'estimated', False)))


@register.filter
def held_until(item):
    """The end of a Withdrawal as the Treatments list says it, both days (farm.handling.withdrawal.held_until): until
    13.12.2026 (harvest from 14.12.2026)."""
    if item is None:
        return DASH
    return registry.held_until(item.until, getattr(item, 'approximate', getattr(item, 'estimated', False)))


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
