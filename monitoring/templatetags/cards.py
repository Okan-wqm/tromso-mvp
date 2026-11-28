"""What the card's templates ask of monitoring/cards/render.py and monitoring/read.py: a water value as a card says it
(`face`), what a value or bar widget is bound to (`bound`), a fitted card's value tile (`tile`), the bar of a value
against its limits (`bar`), the pH window (`ph_window`), a reason in short (`brief`) and the band's clock (`clock`). No figure is worked
out here."""
from django import template
from django.utils.formats import date_format
from django.utils.html import format_html

from farm.handling.withdrawal import harvest_from

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
def ph_window(card, view=None):
    """The pH window of a card (render.PhWindow), its words placed for the width its widget has."""
    return render.ph_window(card, view)


@register.simple_tag
def withdrawal_end(card):
    """When the card's fish may be harvested, beside the word on a fitted card (owner decision 16, 2026-11-16), in the
    product's one wording (farm.handling.withdrawal.harvest_from) with the day as day.month, a card's line having no
    room for a year: "harvest from 23.11", "harvest from about 23.11" when projected, "end unknown" when the day of
    one of its batches is not known. The day is the latest of its withdrawal blocks': every batch is free then."""
    blocks = list(card.withdrawal)
    if not blocks or any(block.until is None for block in blocks):
        return harvest_from(None)
    last = max(blocks, key=lambda block: block.until)
    return harvest_from(last.until, getattr(last, 'approximate', False), shown=lambda day: f'{day:%d.%m}')


@register.simple_tag
def opener(openers, card):
    """How the band's chip of a card opens its unit ({page, open, into}: monitoring/views.py _openers), or None when
    the screen's cards are not the kind that open a pane."""
    return (openers or {}).get(card.unit.pk)


@register.simple_tag
def water_rows(card, view=None):
    """Every value of the card's middle point as rows, in one or two columns (render.water_rows)."""
    return render.water_rows(card, view)


@register.simple_tag
def fold_reasons(state, fill=True):
    """What a fitted card folds of its reasons: a full-height card's (`fill`) or a Small card's (render.fold)."""
    return render.fold(state, 'big' if fill else 'small')


@register.simple_tag
def tiled(card, view, columns):
    """How many of the design's tiles to a line a full-height card's water stands in, 0 for rows (render.tiled)."""
    return render.tiled(card, view, columns)


@register.simple_tag
def shown_widgets(card, next_look):
    """The widgets a fitted card draws in this look (render.shown)."""
    return render.shown(card, next_look)


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
