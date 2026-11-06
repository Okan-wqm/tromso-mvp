"""Template filters of the reports pages."""
from urllib.parse import urlencode

from django import template

register = template.Library()


@register.filter
def urlencode_query(query):
    """A dict as a query string: kind=smolt&site=…&period=2026-10."""
    return urlencode(query)


@register.filter
def named(labels, path):
    """A path of a report's content as the page names it (`differences.labels`, reports/labels.py)."""
    return labels.get(path, path) if labels else path
