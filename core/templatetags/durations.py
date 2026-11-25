"""The shared duration words (core.durations) in templates: `{{ settings.standard_week_minutes|minutes_said }}` ("37 h
30 min"), `{{ row.over_minutes|hours_said:"signed" }}` ("+10 h"), `{{ settings.forgotten_after_hours|whole_hours_said }}`
("16 h")."""
from django import template

from core import durations

register = template.Library()


@register.filter
def minutes_said(minutes):
    return durations.minutes_said(minutes)


@register.filter
def hours_said(minutes, signed=''):
    return durations.hours_said(minutes, signed=signed == 'signed')


@register.filter
def whole_hours_said(hours):
    return durations.minutes_said(int(hours) * 60)
