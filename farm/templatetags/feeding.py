"""How the feeding figures read on the page, in the person's language (farm/templatetags/stock.py does the
same for the stock): a recorded amount as it was typed, to the gram, a ratio to two decimals, a day as
today, yesterday or its date, and a dash for a value there is none of."""
from datetime import timedelta
from decimal import Decimal

from django import template
from django.utils import formats
from django.utils.translation import gettext as _

from ..feeding.ration import band_range
from .stock import DASH, number

register = template.Library()


def amount(kilos):
    """A recorded amount as it was typed, to the gram, without trailing zeros: 12.5, 0.035, 1,250 (the
    source rounded to 0.1 kg, so a 40 g ration read 0.0, FDR-40)."""
    exponent = Decimal(kilos).normalize().as_tuple().exponent
    return number(kilos, min(max(-exponent, 0), 3))


@register.filter
def feed_kg(value):
    """12.5 kg"""
    if value in (None, ''):
        return DASH
    # Translators: an amount of feed in kilograms, e.g. 12.5 kg.
    return _('%(value)s kg') % {'value': amount(value)}


@register.filter
def fcr(value):
    """A feed conversion ratio: 0.86"""
    return DASH if value in (None, '') else number(value, 2)


@register.filter
def fed_on(day, today):
    """Today, Yesterday, or the date."""
    if day in (None, ''):
        return DASH
    if day == today:
        return _('Today')
    if day == today - timedelta(days=1):
        return _('Yesterday')
    return formats.date_format(day, 'DATE_FORMAT')


@register.filter
def celsius(value):
    """13.2 °C"""
    if value in (None, ''):
        return DASH
    # Translators: a water temperature, e.g. 13.2 °C.
    return _('%(value)s °C') % {'value': number(value, 1)}


@register.filter
def age(delta):
    """How old a reading is: 45 min, 3 h, 2 d."""
    if delta in (None, ''):
        return DASH
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return _('%(count)d min') % {'count': minutes}
    if minutes < 48 * 60:
        return _('%(count)d h') % {'count': minutes // 60}
    return _('%(count)d d') % {'count': minutes // (24 * 60)}


@register.filter
def weights(band):
    """A weight band: 50–100 g, or from 500 g (a band of a protocol, stored or as the ration reads it)."""
    return band_range(band.min_weight_g, band.max_weight_g)


@register.filter
def lookup(mapping, key):
    """A value of a dict a page was given, by key: the fish an assignment row feeds now."""
    return mapping.get(key) if mapping else None


@register.filter
def difference(value, decimals=1):
    """A signed difference, to `decimals`: +3.5, −42."""
    if value in (None, ''):
        return DASH
    shown = number(abs(value), int(decimals))
    return shown if not value else ('+' if value > 0 else '−') + shown
