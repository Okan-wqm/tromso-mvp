"""`{% day_input "from" value %}`: a list's date filter as the forms' date (core.widgets.DayInput), typed and shown in the
person's language, read back by core.dates.read_day; never a browser date box."""
from django import template

from ..widgets import DayInput

register = template.Library()


@register.simple_tag
def day_input(name, value='', **attrs):
    """The input; `attrs` become its attributes (id, data-autosubmit=True)."""
    attrs = {key.replace('_', '-'): ('' if item is True else item) for key, item in attrs.items()}
    return DayInput(attrs=attrs).render(name, value or None)
