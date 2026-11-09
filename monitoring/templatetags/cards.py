"""What the card widgets' partials ask of monitoring/cards/render.py: a water value as a card says it (`face`), the
reading a value widget is bound to (`bound`), and the bar of a value against its limits (`bar`). No figure is worked out
here."""
from django import template

from farm.water import parameters, read as water_read

from ..cards import render

register = template.Library()


@register.filter
def face(reading, now):
    return render.face(reading, now)


@register.simple_tag
def bound(card, view):
    """The face of the reading a value or bar widget shows: its parameter at its point (the middle by default)."""
    code = view.bind.get('parameter')
    return render.face(render.reading_at(card, code, view.bind.get('point', water_read.MIDDLE)), card.now,
                       parameters.get(code))


@register.filter
def bar(face):
    return render.bar(face)


@register.simple_tag
def key_water():
    """[(code, short label)] of the key water values (the catalogue's), for the key-values table."""
    from ..cards.catalogue import KEY_WATER
    return [(code, parameters.get(code).short) for code in KEY_WATER]


@register.simple_tag
def card_states():
    """[(key, word)] of the states a card can be in, worst first (monitoring/read.py STATES): the one place the words are
    spelled, for the announcer's words and the designer's "show as"."""
    from .. import read
    return read.STATES
