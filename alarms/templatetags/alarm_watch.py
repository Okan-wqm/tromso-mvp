"""{% alarm_watch %}: whether the alarms are being checked, said on the pages that show or promise alarms (alarms/watch.py:
one query). Nothing is said while they are; `promise=True` (the water page) also says what a warning or critical value
does, and when the alarms were last checked."""
from django import template

from .. import read, watch

register = template.Library()


@register.inclusion_tag('alarms/_watch.html')
def alarm_watch(promise=False):
    return {'watch': watch.state(), 'promise': promise, 'connected': read.transport_connected('push')}
