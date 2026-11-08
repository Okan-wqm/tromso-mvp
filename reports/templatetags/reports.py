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


@register.filter
def figure(value, zone=None):
    """A content value as the page says it (reports.labels.shown): a date dd.mm.yyyy, an instant on `zone`'s clock (the
    report's site; none: the company's), a number in the language's way, a dash for none."""
    from ..labels import shown
    return shown(value, zone or None)


@register.filter
def coded(value, kind):
    """A coded value of the content in words (reports.labels.CODES: 'method', 'loss_cause'); other text as written."""
    from ..labels import CODES, shown
    return shown(value, codes=CODES.get(kind))
