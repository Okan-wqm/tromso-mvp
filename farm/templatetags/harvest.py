"""How the harvest's differences read on the page: the book against the scale, signed (+12 kg, −4.8 %), and what a
handling rule asks for (5 days (120 h), 60 degree-days)."""
from django import template

from ..handling import fasting
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


@register.filter
def rule_asks(rule):
    """What a handling rule asks: 36 h, 5 days (120 h), 60 degree-days, or 3 days (72 h) and 60 degree-days."""
    return fasting.asks_text(rule.min_fasting_hours, rule.min_fasting_degree_days, days=True)
