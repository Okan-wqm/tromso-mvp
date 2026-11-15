"""What the card's templates ask of monitoring/cards/render.py and monitoring/read.py: a water value as a card says it
(`face`), what a value or bar widget is bound to (`bound`), a fitted card's value tile (`tile`), the bar of a value
against its limits (`bar`), the pH window (`ph_window`), a reason in short (`brief`) and the band's clock (`clock`). No figure is worked
out here."""
from django import template
from django.utils.formats import date_format
from django.utils.html import format_html

from farm.water import parameters

from ..cards import render

register = template.Library()


@register.filter
def face(reading, now):
    return render.face(reading, now)


@register.filter
def clock(moment):
    """The time a screen's cards were computed, as the band's figure. The sentence around it is the translator's
    ("computed at %(time)s": the time comes first in Turkish), so the element is built here and its text escaped
    (`format_html`); a template never switches escaping off (core.tests_escaping). The band's template styles it."""
    return format_html('<b>{}</b>', date_format(moment, 'TIME_FORMAT'))


@register.simple_tag
def bound(card, view):
    """The face of what a value or bar widget shows: a water parameter at its point (the middle by default), or a value
    the unit's chart works out."""
    return render.bound(card, view)


@register.simple_tag
def tile(card, view):
    """A fitted card's value tile (render.Tile)."""
    return render.tile(card, view)


@register.simple_tag
def ph_window(card):
    """The pH window of a card (render.PhWindow)."""
    return render.ph_window(card)


@register.simple_tag
def other_points(card):
    """The unit's other sampling points with their oxygen, temperature and pH (render.other_points)."""
    return render.other_points(card)


@register.simple_tag
def chart(card):
    """The card's Deffeyes chart as a picture of its own size, with its words (render.DrawnChart)."""
    return render.chart(card)


@register.filter
def bar(face):
    return render.bar(face)


@register.filter
def brief(reason):
    """A reason of a card's state in short (monitoring/read.py Brief): a value against the bound it is past, or its own
    words."""
    from .. import read
    return read.brief_of(reason)


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
