"""{% experiment_words as ew %}: the words of the experiments panels of their own (experiments/words.py) for a template."""
from django import template

from .. import words
from ..words import WORDS

register = template.Library()


@register.simple_tag
def experiment_words():
    return WORDS


@register.simple_tag
def booked_for(span, error_df):
    return words.booked_for(span, error_df)
