"""How the harvest's differences read on the page: the book against the scale, signed (+12 kg, −4.8 %)."""
from django import template

from .stock import DASH, kilos, percent

register = template.Library()


def _sign(value):
    return '+' if value > 0 else ('−' if value < 0 else '±')


@register.filter
def signed_kilos(value):
    """+12 kg, −250 kg"""
    if value in (None, ''):
        return DASH
    return _sign(value) + kilos(abs(value))


@register.filter
def signed_percent(value):
    """+4.8 %, −1.2 %"""
    if value in (None, ''):
        return DASH
    return _sign(value) + percent(abs(value), 1)
