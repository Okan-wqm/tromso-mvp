"""How the store's figures read on the page, in the person's language (the stock's and the feeding's
filters, farm/templatetags, do the same): a quantity to the gram with its unit, a sum of money with its
currency, days of cover, a dash for a value there is none of."""
from django import template
from django.utils.translation import gettext as _

from farm.templatetags.feeding import amount
from farm.templatetags.stock import DASH, number

register = template.Library()


@register.filter
def quantity(value, unit='kg'):
    """1,250.5 kg, 0.035 kg, 12 units: as recorded, to the gram, with the item's unit."""
    if value in (None, ''):
        return DASH
    # Translators: a quantity and its unit, e.g. 1,250.5 kg.
    return _('%(value)s %(unit)s') % {'value': amount(value), 'unit': unit}


@register.filter
def delta(value, unit='kg'):
    """A line's change: +1,250 kg into a location, −12.5 kg out of it."""
    if value in (None, ''):
        return DASH
    sign = '+' if value > 0 else '−'
    return sign + quantity(abs(value), unit)


@register.filter
def money(value, currency):
    """12,500.00 NOK"""
    if value in (None, ''):
        return DASH
    return f'{number(value, 2)} {currency}'


@register.filter
def days(value):
    """Days of cover: 12.5 days."""
    if value in (None, ''):
        return DASH
    # Translators: days of cover, e.g. 12.5 days.
    return _('%(value)s days') % {'value': number(value, 1)}


@register.filter
def of(mapping, key):
    """`held|of:location.pk`: a value of a dictionary the view built, or None."""
    return mapping.get(key) if mapping else None
