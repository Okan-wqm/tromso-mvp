"""{% knowledge_words as kw %}: the words of the knowledge panels of their own (knowledge/words.py) for a template."""
from django import template

from .. import words
from ..words import WORDS

register = template.Library()


@register.simple_tag
def knowledge_words():
    return WORDS


@register.simple_tag
def reviewed_by(entry):
    return words.reviewed_by(entry)
