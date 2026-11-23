"""The outbox's delivery (alarms.Notification, alarms.DeliveryAttempt): each queued notification handed to its channel's
transport (alarms/transports.py), outside any alarm pass, transaction or lock, so a slow or failing transport never
delays an alarm: the alarm worker's sender thread goes through the outbox every tick (alarms/worker.py), and
manage.py run_alarms after its one pass.

- **What, in which order.** Every notification not sent yet whose failures are fewer than its severity's delivery
  attempts (Alarm severity rules): the critical ones first, then the oldest queued. So a backlog after an outage goes
  out in that order, all of it in the first round once the transport answers.
- **Retries.** A failed attempt is tried again once its severity's "Retry after" has passed since it failed, until the
  attempts are used up; then the notification is failed, and the alarm's page says so (read.status).
- **Snoozed.** A notification of an alarm that is snoozed waits, and goes out once the snooze ends.
- **Floods.** The due notifications of one kind of alarm for one person go out as one flood message once they are a
  flood, and the next ones within the flood window are covered by it (alarms/floods.py).
- **Never lost; at worst twice.** The outbox is rows: a restart, a crash or a database outage finds every notification
  that has no "sent" attempt and sends it. A process that dies after the transport took one and before its attempt was
  written sends it again when it runs again: at least once, never lost (the transport has the notification's id for the
  push service's collapse key, so a phone shows it once). A notification is never written "sent" twice (a unique
  constraint), and two senders (an operator's run_alarms beside the worker) never send one at the same moment: each
  claims it with an advisory lock and looks again whether it went before sending.
- **Bounded.** A send has `timeout` seconds (settings.ALARM_WORKER send_timeout for the worker); a transport that has
  not answered by then is a failed attempt ("no answer in N s"), tried again like any other. A transport that raises
  is a failed attempt with its error. A transport must not use the database (it runs on a thread of its own)."""
import logging
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from django.db import connection
from django.db.models import Count, Exists, Max, OuterRef, Q
from django.utils import timezone

from sensors.models.alarm import Severity

from . import floods, read, rules as alarm_rules, services
from .models import RANK, DeliveryAttempt, Notification, Outcome
from .transports import Failed, Flood, transport_for

logger = logging.getLogger(__name__)
CLAIM = 426_160_720           # the advisory lock class of a notification being sent (with its id): an identity


@dataclass
class Delivery:
    """What one round through the outbox did."""

    sent: int = 0
    failed: int = 0
    waiting: int = 0            # no transport is connected for their channel
    retrying: int = 0           # failed before, tried again once their retry time has passed
    busy: int = 0               # another sender was sending them
    snoozed: int = 0            # their alarm is snoozed: they wait until the snooze ends
    grouped: int = 0            # covered by a flood message sent to the same person within the window
    floods: int = 0             # flood messages handed to a transport (each counts its notifications as sent or failed)
    backlog: int = 0            # all the notifications still to be sent when the round began
    oldest: datetime | None = field(default=None)

    def __str__(self):
        text = f'{self.sent} sent, {self.failed} failed'
        if self.floods or self.grouped:
            text += f' ({self.floods} flood messages, {self.grouped} covered by one)'
        if self.retrying:
            text += f', {self.retrying} to be tried again'
        if self.waiting:
            text += f'; {self.waiting} waiting, nothing sent: no transport is connected for their channel'
        return text


def backlog(rules):
    """The notifications still to be sent: none sent, fewer failures than their severity's attempts; the critical ones
    first, then the oldest queued. Each carries `failures` and `last_failed_at`."""
    most = max(rules.delivery_attempts(severity) for severity in Severity.values)
    rows = (Notification.objects.annotate(
        sent=Exists(DeliveryAttempt.objects.filter(notification=OuterRef('pk'),
                                                   outcome__in=[Outcome.SENT, Outcome.GROUPED])),
        failures=Count('attempts', filter=Q(attempts__outcome=Outcome.FAILED)),
        last_failed_at=Max('attempts__attempted_at', filter=Q(attempts__outcome=Outcome.FAILED)))
        .filter(sent=False, failures__lt=most).select_related('alarm', 'alarm__sensor_event', 'recipient'))
    rows = [row for row in rows if row.failures < rules.delivery_attempts(row.alarm.severity)]
    return sorted(rows, key=lambda row: (-RANK[row.alarm.severity], row.queued_at, row.pk))


def is_due(notification, rules, now):
    """Whether a notification of the backlog is tried now: never tried, or its retry time has passed since it failed."""
    return (notification.last_failed_at is None
            or now - notification.last_failed_at >= rules.retry_after(notification.alarm.severity))


def _claim(notification):
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_try_advisory_lock(%s, hashtext(%s))', [CLAIM, str(notification.pk)])
        return cursor.fetchone()[0]


def _release(notification):
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_unlock(%s, hashtext(%s))', [CLAIM, str(notification.pk)])


def _call(transport, notification, timeout, flood=None):
    """The transport's answer, within `timeout` seconds (None: as long as it takes); a raise is a Failed. `flood`: the
    notification is the first of a flood message (alarms/floods.py)."""
    answer = {}

    def send():
        try:
            answer['result'] = transport.send(notification, flood=flood) if flood else transport.send(notification)
        except Exception as error:
            logger.exception('The %s transport raised for notification %s.', notification.channel, notification.pk)
            answer['result'] = Failed(f'{type(error).__name__}: {error}')
    if timeout is None:
        send()
        return answer['result']
    thread = threading.Thread(target=send, name=f'alarm-send-{notification.pk}', daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        logger.error('The %s transport gave no answer for notification %s in %s s.', notification.channel,
                     notification.pk, timeout)
        return Failed(f'no answer in {timeout:g} s')
    return answer['result']


def _sendable(notification):
    """Claimed for this sender and not sent (or covered) by another since the round read the outbox."""
    if not _claim(notification):
        return False
    if DeliveryAttempt.objects.filter(notification=notification, outcome__in=[Outcome.SENT, Outcome.GROUPED]).exists():
        _release(notification)
        return False
    return True


def _count(delivery, rows):
    for row in rows:
        if row.outcome == Outcome.SENT:
            delivery.sent += 1
        elif row.outcome == Outcome.GROUPED:
            delivery.grouped += 1
        else:
            delivery.failed += 1


def send_due(now=None, timeout=None, stop=None):
    """One round through the outbox: every notification that is due is handed to its transport (on its own, in a flood
    message, or covered by one: alarms/floods.py), its attempt written. `now` is the round's moment for the tests (each
    attempt is stamped with it); by default each attempt's own. `stop()` true ends the round before the next group (the
    worker is stopping)."""
    rules = alarm_rules.current()
    moment = (lambda: now) if now is not None else timezone.now
    queue = backlog(rules)
    delivery = Delivery(backlog=len(queue), oldest=min((row.queued_at for row in queue), default=None))
    snoozed = read.snoozes({row.alarm_id for row in queue}, moment())
    groups, transports = defaultdict(list), {}
    for notification in queue:
        if notification.alarm_id in snoozed:
            delivery.snoozed += 1
        elif not is_due(notification, rules, moment()):
            delivery.retrying += 1
        else:
            transport = transports.setdefault(notification.channel, transport_for(notification.channel))
            if transport is None:
                delivery.waiting += 1
            else:
                groups[(notification.recipient_id, notification.channel, floods.key(notification.alarm))].append(
                    notification)
    found = floods.recent(groups, moment(), rules)
    for group, members in groups.items():
        if stop is not None and stop():
            break
        transport, kind = transports[group[1]], group[2]
        how = floods.plan(members, found[group], moment(), rules)
        mine = [notification for notification in members if _sendable(notification)]
        delivery.busy += len(members) - len(mine)
        try:
            if how == floods.COVERED:
                note = Failed(f'covered by the flood message sent at {found[group].last_flood_at:%H:%M:%S} UTC')
                _count(delivery, [services.attempt(notification, note, moment(), flood_key=kind, grouped=True)
                                  for notification in mine])
            elif how == floods.FLOOD and mine:
                size = found[group].count + len(mine)
                flood = Flood(size, min(notification.alarm.opened_at for notification in mine), mine[0].alarm.summary)
                result = _call(transport, mine[0], timeout, flood)
                delivery.floods += 1
                _count(delivery, [services.attempt(notification, result, moment(), flood_key=kind, flood_size=size)
                                  for notification in mine])
            else:
                _count(delivery, [services.attempt(notification, _call(transport, notification, timeout), moment(),
                                                   flood_key=kind) for notification in mine])
        finally:
            for notification in mine:
                _release(notification)
    return delivery
