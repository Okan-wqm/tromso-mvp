"""How the feeding figures read on the page, in the person's language (farm/templatetags/stock.py does the
same for the stock): a recorded amount as it was typed, to the gram, a ratio to two decimals, a day as
today, yesterday or its date, and a dash for a value there is none of."""
from datetime import timedelta
from decimal import Decimal

from django import template
from django.utils import formats
from django.utils.translation import gettext as _

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
