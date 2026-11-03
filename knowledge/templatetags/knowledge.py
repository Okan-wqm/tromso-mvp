from django import template

from .. import search

register = template.Library()


@register.filter
def highlight(passage):
    """A search passage (knowledge.search) as HTML: the text escaped, the words found in <mark>."""
    return search.highlight(passage)
