"""How the stock's numbers read on the page, in the person's language: grouped digits, the decimals a
farmer reads them with, the unit after the number, and a dash for a value there is none of. The values
are computed at full precision (farm/stock/read.py); only here are they rounded."""
from decimal import ROUND_HALF_UP, Decimal

from django import template
from django.utils import formats
from django.utils.translation import gettext as _

register = template.Library()
DASH = '—'


def number(value, decimals=0):
    """A quantity as the language writes it, digits grouped, rounded half up to `decimals` (Django's
    number_format cuts the decimals off instead of rounding them)."""
    value = Decimal(value).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
    return formats.number_format(value, decimals, use_l10n=True, force_grouping=True)


_number = number


# A value a template asks for on a unit without fish (stock.count of None) comes as '' or None: a dash.
@register.filter
def fish(value):
    """12,400"""
    return DASH if value in (None, '') else _number(value, 0)


@register.filter
def signed(value):
    """A change in fish: +5,000 or −12."""
    return DASH if value in (None, '') else ('+' if value > 0 else '−') + _number(abs(value), 0)


def weight_decimals(grams):
    """145 g, 62.5 g, 4.25 g, and under a gram as many decimals as it takes (0.075 g; eggs to 0.0001 g)."""
    if grams >= 100:
        return 0
    if grams >= 10:
        return 1
    if grams >= 1:
        return 2
    exponent = Decimal(grams).quantize(Decimal('0.0001')).normalize().as_tuple().exponent
    return max(2, -exponent)


@register.filter
def grams(value):
    """An average weight: 145 g."""
    if value in (None, ''):
        return DASH
    # Translators: an average weight in grams, e.g. 145 g.
    return _('%(value)s g') % {'value': _number(value, weight_decimals(value))}


@register.filter
def kilos(value):
    """A biomass: 1,798 kg, or 4.25 kg under 10 kg."""
    if value in (None, ''):
        return DASH
    # Translators: a weight in kilograms, e.g. 1,798 kg.
    return _('%(value)s kg') % {'value': _number(value, 2 if value < 10 else 0)}


@register.filter
def tonnes(value):
    """A total biomass: 3.2 t from a tonne up, else in kg."""
    if value in (None, ''):
        return DASH
    if value >= 1000:
        # Translators: a weight in tonnes, e.g. 3.2 t.
        return _('%(value)s t') % {'value': _number(value / 1000, 1)}
    return kilos(value)


@register.filter
def density(value):
    """35.9 kg/m³"""
    if value in (None, ''):
        return DASH
    return _('%(value)s kg/m³') % {'value': _number(value, 1)}


@register.filter
def times(value):
    """A ratio, as a species' size limit reads: 2×, 2.5× (no decimals a limit was not given with)."""
    if value in (None, ''):
        return DASH
    value = Decimal(value)
    decimals = 0 if value == value.to_integral_value() else 2 if value * 10 % 1 else 1
    # Translators: a ratio, how many times as much, e.g. 2× (a size limit).
    return _('%(value)s×') % {'value': _number(value, decimals)}


@register.filter
def percent(value, decimals=0):
    """97.4 % in English and Norwegian, %97,4 in Turkish."""
    if value in (None, ''):
        return DASH
    # Translators: a percentage; write the sign where your language puts it (Turkish: %%%(value)s).
    return _('%(value)s %%') % {'value': _number(value, int(decimals))}


@register.filter
def bar_width(value):
    """The filled part of a capacity bar, in % (at most 100)."""
    if value in (None, ''):
        return '0'
    return f'{min(Decimal(value), Decimal(100)):.1f}'


@register.filter
def join_codes(batches):
    """B-2026-001 + B-2026-002: the codes of the batches of a unit's fish."""
    return ' + '.join(batch.code for batch in batches)
