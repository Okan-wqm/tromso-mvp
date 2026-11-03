"""How the task pages write a place, a person and a recurring task's rule."""
from django import template
from django.utils import formats
from django.utils.translation import gettext as _, ngettext

from .. import places, read
from ..models import Frequency, Weekday

register = template.Library()


@register.filter
def place_label(place):
    return places.label(place) if place is not None else '—'


@register.filter
def place_context(place):
    return places.context(place) if place is not None else ''


@register.filter
def place_kind(place):
    return places.kind_label(place) if place is not None else ''


@register.filter
def person(user):
    return read.person(user) if user is not None else ''


@register.filter
def people(users):
    """The people a task is for, by name, in one line."""
    return ', '.join(read.person(user) for user in users)


@register.filter
def rule_text(series):
    """A recurring task's rule in words: "Every 2 weeks on Monday, Thursday at 08:00"."""
    count = series.interval
    if series.frequency == Frequency.DAILY:
        text = ngettext('Every day', 'Every %(count)d days', count) % {'count': count}
    elif series.frequency == Frequency.WEEKLY:
        days = ', '.join(str(Weekday(day).label) for day in sorted(series.weekdays))
        text = ngettext('Every week on %(days)s', 'Every %(count)d weeks on %(days)s', count) % {
            'count': count, 'days': days}
    else:
        text = ngettext('Every month on day %(day)d', 'Every %(count)d months on day %(day)d', count) % {
            'count': count, 'day': series.day_of_month}
    if series.due_time is not None:
        text = _('%(rule)s at %(time)s') % {'rule': text, 'time': formats.time_format(series.due_time, 'H:i')}
    return text
