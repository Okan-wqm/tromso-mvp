"""{% sensor_words as sw %}: the words of the sensors panels of their own (sensors/words.py) for a template."""
from django import template

from .. import words
from ..words import WORDS

register = template.Library()


@register.simple_tag
def sensor_words():
    return WORDS


@register.simple_tag
def fresh_for(channel):
    return words.fresh_for(channel)
