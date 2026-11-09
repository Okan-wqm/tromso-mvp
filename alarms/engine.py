"""The alarm loop (manage.py run_alarms): one pass at a moment, in order:

1. the sensor rules are checked (sensors/alarms.py `evaluate`) and their events mirrored (alarms/sources.py);
2. the water limits open and clear their alarms (alarms/sources.py);
3. every open alarm nobody has acknowledged gets the notifications of its level (rules added since reach it too), and
   goes on to the next level with a rule that reaches it when its level was notified at least the platform owner's
   escalation time ago, or at once when nobody could be notified at its level;
4. every queued notification whose channel has a transport is handed to it (alarms/transports.py). None is connected
   today: nothing is sent, and the outbox waits.
Steps 1 to 3 run in one transaction under a transaction-level advisory lock, step 4 in another under the same lock, so
two loops never queue, escalate or send twice."""
from dataclasses import dataclass

from django.db import connection, transaction
from django.db.models import Min
from django.utils import timezone

from sensors import alarms as sensor_alarms

from . import read, routing, rules as alarm_rules, services, sources
from .models import Acknowledgement, Alarm, AlarmClearance, Notification, Severity, Source
from .transports import transport_for

LOCK = 4_261_607_201          # the alarm loop's advisory lock key (any constant no other code takes)


@dataclass
class Summary:
    opened: int = 0
    cleared: int = 0
    queued: int = 0
    escalated: int = 0
    sent: int = 0
    failed: int = 0
    waiting: int = 0          # queued notifications whose channel has no transport

    def __str__(self):
        text = (f'{self.opened} opened, {self.cleared} cleared, {self.queued} queued, {self.escalated} escalated, '
                f'{self.sent} sent, {self.failed} failed')
        if self.waiting:
            text += f'; {self.waiting} waiting, nothing sent: no transport is connected for their channel'
        return text


def _lock():
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(%s)', [LOCK])


def _advance(alarm, now, summary, rules):
    """Step 3 for one alarm."""
    level = read.level(alarm)
    while True:
        summary.queued += len(services.enqueue(alarm, level, routing.recipients(alarm, level, now), now))
        started = Notification.objects.filter(alarm=alarm, level=level).aggregate(first=Min('queued_at'))['first']
        if started is not None and now - started < rules.escalation_after(alarm.severity):
            return
        following = routing.next_level(alarm, level)
        if following is None:
            return
        services.escalate(alarm, following, now)
        summary.escalated += 1
        level = following


def _unsuppressed(alarms):
    """The alarms whose people are notified: all but a water warning while the same parameter's critical alarm is open
    (ISA-18.2: the low level under the low-low one); it is still raised and recorded, and notified once the critical
    clears with the warning still open."""
    critical = {(alarm.point_id, sources.slot_of(alarm.parameter)) for alarm in alarms
                if alarm.source == Source.WATER_LIMIT and alarm.severity == Severity.CRITICAL}
    return [alarm for alarm in alarms if not (alarm.source == Source.WATER_LIMIT and alarm.severity == Severity.WARNING
                                              and (alarm.point_id, sources.slot_of(alarm.parameter)) in critical)]


def run_once(now=None):
    """One pass of the loop at `now`; returns its Summary."""
    now = now or timezone.now()
    summary = Summary()
    rules = alarm_rules.current()
    with transaction.atomic():
        _lock()
        sensor_alarms.evaluate(now)
        for opened, cleared in (sources.sensor_events(), sources.water(now, rules)):
            summary.opened += opened
            summary.cleared += cleared
        waiting = list(Alarm.objects.exclude(pk__in=AlarmClearance.objects.values('alarm'))
                       .exclude(pk__in=Acknowledgement.objects.values('alarm')).order_by('opened_at', 'id'))
        for alarm in _unsuppressed(waiting):
            _advance(alarm, now, summary, rules)
    with transaction.atomic():
        _lock()
        for notification in read.pending(rules):
            transport = transport_for(notification.channel)
            if transport is None:
                summary.waiting += 1
                continue
            row = services.attempt(notification, transport.send(notification), now)
            if row.outcome == 'sent':
                summary.sent += 1
            else:
                summary.failed += 1
    return summary
