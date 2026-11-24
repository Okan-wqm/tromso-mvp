"""{% alarm_watch %}: whether the alarms are being checked and sent, said on the pages that show or promise alarms
(alarms/watch.py: one query). Nothing is said while they are;
- `promise=True` (the water page) also says what a warning or critical value does, and when they were last checked;
- `sent_note=True` (the monitoring wall, the Sensors overview) also says that nothing is sent while no transport is
  connected;
- `live=True` (the monitoring wall, left open for hours) has the notice asked for again every poll interval
  (frontend/poll.ts, alarms.views.alarm_watch_notice), so a worker that stops is said without a reload."""
from django import template
from django.conf import settings

from .. import read, watch

register = template.Library()


def notice(promise=False, sent_note=False):
    return {'watch': watch.state(), 'promise': promise, 'sent_note': sent_note,
            'connected': read.transport_connected('push')}


@register.inclusion_tag('alarms/_watch.html')
def alarm_watch(promise=False, sent_note=False, live=False):
    return {**notice(promise, sent_note), 'live': live, 'poll_seconds': settings.ALARM_WORKER['stale_after'] // 3}
