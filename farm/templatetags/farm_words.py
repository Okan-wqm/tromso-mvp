"""{% farm_words as fw %}: the words of the farm panels of their own (farm/words.py) for a template."""
from django import template

from .. import words
from ..words import WORDS

register = template.Library()


@register.simple_tag
def farm_words():
    return WORDS


@register.simple_tag
def sfr_at(temperature):
    return words.sfr_at(temperature)
