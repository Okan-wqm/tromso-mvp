"""{% task_words as tw %}: the words of the tasks panels of their own (tasks/words.py) for a template."""
from django import template

from ..words import WORDS

register = template.Library()


@register.simple_tag
def task_words():
    return WORDS
