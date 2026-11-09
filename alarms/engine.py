"""The alarm loop (manage.py run_alarms): one pass at a moment, in order:

1. the sensor rules are checked (sensors/alarms.py `evaluate`) and their events mirrored (alarms/sources.py);
2. the water limits open and clear their alarms (alarms/sources.py);
3. every open alarm nobody has acknowledged gets the notifications of its level (rules added since reach it too), and
   goes on to the next level with a rule that reaches it when its level was notified at least the platform owner's
   escalation time ago, or at once when nobody could be notified at its level;
4. every queued notification whose channel has a transport is handed to it (alarms/transports.py). None is connected
   today: nothing is sent, and the outbox waits.
Each step runs in its own transaction under a transaction-level advisory lock, so two loops never queue, escalate or send
twice, and a step that fails rolls back alone, is logged and counted, and the others still run (alarm plan, defect 5)."""
import logging
from collections import defaultdict
from dataclasses import dataclass, field

from django.db import connection, transaction
from django.db.models import Max
from django.utils import timezone

from sensors import alarms as sensor_alarms

from . import read, routing, rules as alarm_rules, services, sources
from .models import Acknowledgement, Alarm, AlarmClearance, Escalation, Notification, Severity, Source
from .transports import transport_for

logger = logging.getLogger(__name__)
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
    failed_steps: list = field(default_factory=list)

    def __str__(self):
        text = (f'{self.opened} opened, {self.cleared} cleared, {self.queued} queued, {self.escalated} escalated, '
                f'{self.sent} sent, {self.failed} failed')
        if self.waiting:
            text += f'; {self.waiting} waiting, nothing sent: no transport is connected for their channel'
        if self.failed_steps:
            text += f'; {len(self.failed_steps)} step failed: {", ".join(self.failed_steps)}'
        return text


def _lock():
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(%s)', [LOCK])


def _route(alarms, now, summary, rules):
    """Step 3 for every open, unacknowledged, unsuppressed alarm, set-based (alarm plan, defect 7): its level and what its
    levels were sent are read in two queries, the rules once (routing.Router), and the new notifications and escalations
    are written in one statement each. An alarm gets the notifications of its level (rules added since reach it too),
    and goes on to the next level with a rule that reaches it once its level was first notified the severity's escalation
    time ago, or at once when nobody could be notified at its level."""
    if not alarms:
        return
    router = routing.Router(now)
    ids = [alarm.pk for alarm in alarms]
    levels = dict(Escalation.objects.filter(alarm__in=ids).values('alarm').annotate(top=Max('level'))
                  .values_list('alarm', 'top'))
    sent, first = defaultdict(set), {}
    for alarm_id, level, recipient_id, channel, queued_at in Notification.objects.filter(alarm__in=ids).values_list(
            'alarm', 'level', 'recipient', 'channel', 'queued_at'):
        sent[(alarm_id, level)].add((recipient_id, channel))
        first[(alarm_id, level)] = min(queued_at, first.get((alarm_id, level), queued_at))
    queued, escalated = [], []
    for alarm in alarms:
        level = levels.get(alarm.pk, 0)
        while True:
            key = (alarm.pk, level)
            for user, rule in router.recipients(alarm, level):
                if (user.pk, rule.channel) not in sent[key]:
                    sent[key].add((user.pk, rule.channel))
                    first.setdefault(key, now)
                    queued.append(Notification(alarm=alarm, recipient=user, channel=rule.channel, level=level, rule=rule,
                                               queued_at=now))
            if key in first and now - first[key] < rules.escalation_after(alarm.severity):
                break
            following = router.next_level(alarm, level)
            if following is None:
                break
            escalated.append(Escalation(alarm=alarm, level=following, escalated_at=now))
            level = following
    summary.queued += len(services.queue_many(queued))
    summary.escalated += len(services.escalate_many(escalated))


def _unsuppressed(alarms):
    """The alarms whose people are notified: all but a water warning while the same parameter's critical alarm is open
    (ISA-18.2: the low level under the low-low one); it is still raised and recorded, and notified once the critical
    clears with the warning still open."""
    critical = {(alarm.point_id, sources.slot_of(alarm.parameter)) for alarm in alarms
                if alarm.source == Source.WATER_LIMIT and alarm.severity == Severity.CRITICAL}
    return [alarm for alarm in alarms if not (alarm.source == Source.WATER_LIMIT and alarm.severity == Severity.WARNING
                                              and (alarm.point_id, sources.slot_of(alarm.parameter)) in critical)]


def _step(name, summary, work):
    """Runs one step of a pass in its own transaction under the loop's lock; a failure rolls back that step alone, is
    logged with its traceback and counted, and the next step runs (alarm plan, defect 5)."""
    try:
        with transaction.atomic():
            _lock()
            work()
    except Exception:
        logger.exception('The alarm step %r failed; the pass went on with the others.', name)
        summary.failed_steps.append(name)


def run_once(now=None):
    """One pass of the loop at `now`; returns its Summary."""
    now = now or timezone.now()
    summary = Summary()
    rules = alarm_rules.current()

    def count(found):
        summary.opened += found[0]
        summary.cleared += found[1]

    def notify():
        waiting = list(Alarm.objects.exclude(pk__in=AlarmClearance.objects.values('alarm'))
                       .exclude(pk__in=Acknowledgement.objects.values('alarm')).order_by('opened_at', 'id'))
        _route(_unsuppressed(waiting), now, summary, rules)

    def send():
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

    _step('sensor rules', summary, lambda: sensor_alarms.evaluate(now))
    _step('sensor events', summary, lambda: count(sources.sensor_events()))
    _step('water', summary, lambda: count(sources.water(now, rules)))
    _step('notify', summary, notify)
    _step('send', summary, send)
    return summary
