"""`{% day_input "from" value %}`: a list's date filter as the forms' date (core.widgets.DayInput), typed and shown in the
person's language, read back by core.dates.read_day; never a browser date box. `|company_clock`: a moment as the
company's wall clock shows it (core.dates.company_zone), for a page with no site's clock (the activity log, a record's
history)."""
from django import template
from django.utils import timezone

from ..dates import company_zone
from ..widgets import DayInput

register = template.Library()


@register.simple_tag
def day_input(name, value='', **attrs):
    """The input; `attrs` become its attributes (id, data-autosubmit=True)."""
    attrs = {key.replace('_', '-'): ('' if item is True else item) for key, item in attrs.items()}
    return DayInput(attrs=attrs).render(name, value or None)


@register.filter
def company_clock(value):
    """The moment on the company's clock, naive on purpose: the template engine would bring an aware time back to the
    server's zone before `date` formats it."""
    return value if value is None else timezone.make_naive(value, company_zone())
