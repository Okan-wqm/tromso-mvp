"""One alarm pass at a moment (the alarm worker's, alarms/worker.py; manage.py run_alarms once), in order:

1. the sensor rules are checked (sensors/alarms.py `evaluate`) and their events mirrored (alarms/sources.py);
2. the water limits open and clear their alarms (alarms/sources.py);
3. each device's clock is judged against the platform's (alarms/clock.py);
4. every open alarm nobody has acknowledged or snoozed gets the notifications of its level (rules added since reach it
   too), and goes on to the next level with a rule that reaches it when its level was notified at least the platform
   owner's escalation time ago (or since its snooze ended), or at once when nobody could be notified at its level;
5. the alarm system supervises itself (alarms/sources.py supervise): a step that failed and its own configuration (a
   missing rule row) are critical alarms of their own.
Each step runs in its own transaction under a transaction-level advisory lock, so two passes never queue or escalate
twice, and a step that fails rolls back alone, is logged and counted, and the others still run (alarm plan, defect 5).
A pass only queues: handing the notifications to a transport is the outbox's (alarms/outbox.py), outside any pass,
transaction or lock, so a transport never delays an alarm."""
import logging
from collections import defaultdict
from dataclasses import dataclass, field

from django.db import connection, transaction
from django.db.models import Max
from django.utils import timezone

from farm.water import freshness
from sensors import alarms as sensor_alarms

from . import read, routing, rules as alarm_rules, services, sources
from .models import (Acknowledgement, Alarm, AlarmClearance, Channel, Escalation, Notification, NotificationKind,
                     Severity, Source)

logger = logging.getLogger(__name__)
LOCK = 4_261_607_201          # the alarm loop's advisory lock key (any constant no other code takes)


@dataclass
class Summary:
    opened: int = 0
    cleared: int = 0
    queued: int = 0
    escalated: int = 0
    failed_steps: list = field(default_factory=list)

    def __str__(self):
        text = f'{self.opened} opened, {self.cleared} cleared, {self.queued} queued, {self.escalated} escalated'
        if self.failed_steps:
            text += f'; {len(self.failed_steps)} step failed: {", ".join(self.failed_steps)}'
        return text


def _lock():
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(%s)', [LOCK])


def _route(alarms, now, summary, rules, resumed=None):
    """Step 3 for every open, unacknowledged, unsuppressed alarm, set-based (alarm plan, defect 7): its level and what its
    levels were sent are read in two queries, the rules once (routing.Router), and the new notifications and escalations
    are written in one statement each. An alarm gets the notifications of its level (rules added since reach it too),
    and goes on to the next level with a rule that reaches it once its level was first notified the severity's escalation
    time ago, or at once when nobody could be notified at its level. `resumed` ({alarm id: when its snooze ended}): the
    escalation time is counted from then when that is later."""
    if not alarms:
        return
    resumed = resumed or {}
    router = routing.Router(now)
    router.prepare(alarms)
    ids = [alarm.pk for alarm in alarms]
    levels = dict(Escalation.objects.filter(alarm__in=ids).values('alarm').annotate(top=Max('level'))
                  .values_list('alarm', 'top'))
    sent, first = defaultdict(set), {}
    for alarm_id, level, recipient_id, channel, queued_at in Notification.objects.filter(
            alarm__in=ids, kind=NotificationKind.ALARM).values_list('alarm', 'level', 'recipient', 'channel', 'queued_at'):
        sent[(alarm_id, level)].add((recipient_id, channel))
        first[(alarm_id, level)] = min(queued_at, first.get((alarm_id, level), queued_at))
    queued, escalated = [], []
    for alarm in alarms:
        level = levels.get(alarm.pk, 0)
        while True:
            key = (alarm.pk, level)
            for user, rule in router.recipients(alarm, level):
                channel = rule.channel if rule is not None else Channel.PUSH     # a keeper of a sealed cell's fish
                if (user.pk, channel) not in sent[key]:
                    sent[key].add((user.pk, channel))
                    first.setdefault(key, now)
                    queued.append(Notification(alarm=alarm, recipient=user, channel=channel, level=level, rule=rule,
                                               queued_at=now))
            if key in first and now - max(first[key], resumed.get(alarm.pk, first[key])) < rules.escalation_after(
                    alarm.severity):
                break
            following = router.next_level(alarm, level)
            if following is None:
                break
            escalated.append(Escalation(alarm=alarm, level=following, escalated_at=now))
            level = following
    summary.queued += len(services.queue_many(queued))
    summary.escalated += len(services.escalate_many(escalated))


def _remind(alarms, now, summary, ended):
    """A snooze ended with its alarm still open and unacknowledged (`alarms`, not snoozed now; `ended`: {alarm id: its
    last ended snooze}): the people of the alarm's level now are told again, once per snooze (the coordinator's call of
    2026-11-23 on the review, F9)."""
    alarms = [alarm for alarm in alarms if alarm.pk in ended]
    if not alarms:
        return
    told = set(Notification.objects.filter(shelve__in=[ended[alarm.pk] for alarm in alarms],
                                           kind=NotificationKind.RESUMED).values_list('shelve', 'recipient', 'channel'))
    router = routing.Router(now)
    levels = dict(Escalation.objects.filter(alarm__in=[alarm.pk for alarm in alarms]).values('alarm')
                  .annotate(top=Max('level')).values_list('alarm', 'top'))
    queued = []
    for alarm in alarms:
        shelve, level = ended[alarm.pk], levels.get(alarm.pk, 0)
        for user, rule in router.recipients(alarm, level):
            if (shelve.pk, user.pk, rule.channel) not in told:
                told.add((shelve.pk, user.pk, rule.channel))
                queued.append(Notification(alarm=alarm, recipient=user, channel=rule.channel, level=level, rule=rule,
                                           queued_at=now, kind=NotificationKind.RESUMED, shelve=shelve))
    summary.queued += len(services.queue_many(queued))


def _unsuppressed(alarms):
    """The alarms whose people are notified: all but a warning level while the same subject's critical level is open (a
    unit's quantity, a device's clock)
    (ISA-18.2: the low level under the low-low one); it is still raised and recorded, and notified once the critical
    clears with the warning still open."""
    def subject(alarm):
        """The subject of a level, or None for an alarm that has no levels: a unit's quantity (cross review F7: the
        unit, never the point that stood for it), or a device's clock."""
        if alarm.source == Source.WATER_LIMIT:
            return 'water', alarm.point.unit_id, sources.slot_of(alarm.parameter)
        if alarm.parameter == sources.DEVICE_CLOCK:
            return 'clock', alarm.device_id
        return None
    critical = {subject(alarm) for alarm in alarms if alarm.severity == Severity.CRITICAL} - {None}
    return [alarm for alarm in alarms if not (alarm.severity == Severity.WARNING and subject(alarm) in critical)]


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


def run_once(now=None, outside=None, unchecked=None):
    """One pass at `now`; returns its Summary. `outside`: {name: whether it failed} of the alarm system's steps that run
    outside the pass (the worker's sender, 'send'): supervised with the pass's own, and a failed one is in the
    Summary's failed steps. `unchecked` (from, to): the worker's first pass after a stretch with none (sources.supervise
    raises it)."""
    now = now or timezone.now()
    summary = Summary()
    freshness.forget()          # the water's staleness rules as they are now (farm/water/freshness.py)
    rules = alarm_rules.current()

    def count(found):
        summary.opened += found[0]
        summary.cleared += found[1]

    def notify():
        waiting = list(Alarm.objects.exclude(pk__in=AlarmClearance.objects.values('alarm'))
                       .exclude(pk__in=Acknowledgement.objects.values('alarm')).select_related('point')
                       .order_by('opened_at', 'id'))
        ids = [alarm.pk for alarm in waiting]
        snoozed = read.snoozes(ids, now)               # raised and kept, never notified nor escalated while snoozed
        ended = read.ended(ids, now)
        told = [alarm for alarm in _unsuppressed(waiting) if alarm.pk not in snoozed]
        _route(told, now, summary, rules, {alarm_id: row.ends_at() for alarm_id, row in ended.items()})
        _remind(told, now, summary, ended)

    steps = [('sensor rules', lambda: sensor_alarms.evaluate(now)),
             ('sensor events', lambda: count(sources.sensor_events())),
             ('water', lambda: count(sources.water(now, rules))),
             ('device clocks', lambda: count(sources.device_clocks(now, rules))),
             ('notify', notify)]
    for name, work in steps:
        _step(name, summary, work)
    # Last, after the steps whose failure it alarms: a failed step's alarm is on the page at once, and notified on the
    # next pass (this pass's notify step has run).
    outside = outside or {}
    summary.failed_steps += [name for name, failed in outside.items() if failed]
    _step('supervision', summary, lambda: count(sources.supervise(now, rules, [name for name, _work in steps]
                                                                  + list(outside), list(summary.failed_steps),
                                                                  unchecked)))
    return summary
