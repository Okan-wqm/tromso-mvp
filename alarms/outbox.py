"""The outbox's delivery (alarms.Notification, alarms.DeliveryAttempt): each queued notification handed to its channel's
transport (alarms/transports.py), outside any alarm pass, transaction or lock, so a slow or failing transport never
delays an alarm: the alarm worker's sender thread goes through the outbox every tick (alarms/worker.py), and
manage.py run_alarms after its one pass.

- **What, in which order.** The outbox's queue (alarms.OutboxEntry: what is still to be sent, written with each
  notification and removed once it is sent, covered or given up, so a round reads what waits, never the whole history):
  the critical ones first, then the oldest queued.
- **What is said.** Each notification goes with its `text`, in the person's language: the severity and the summary; a
  critical alarm that has cleared by the time it is sent (it came and went while the transport was down: an oxygen crash,
  a power cut) says it was critical and has cleared, when it opened and when it cleared. A warning whose alarm cleared
  before it was ever tried is given up instead, its attempt saying why.
- **A critical is never given up while it matters** (the review of the worker, F1). A critical alarm's notification is
  tried again until it is sent, or its alarm is acknowledged or cleared: the wait doubles from its severity's "Retry
  after" up to its severity's escalation time. Once its alarm is acknowledged or cleared it has its severity's
  delivery attempts like a warning's. A warning's has its attempts, its "Retry after" apart, then it is failed and its
  alarm's page says so (read.status). Given-up ones leave the queue (services.give_up).
- **Said when it cannot be delivered.** A critical notification of an open, unacknowledged alarm that has failed and
  waited longer than its severity's escalation time is undeliverable: the round counts them (`Delivery.undeliverable`,
  on the worker's row), the pages' notice and the health check say so (alarms/watch.py), and the pass raises a critical
  alarm of the alarm system (`undeliverable`, sources.supervise).
- **A critical is never behind a round of warnings** (F5). A round ends at its deadline (`round_seconds`), and before
  each warning's group it looks whether a critical was queued since it began: then it ends, and the next round, a tick
  later, starts with the critical. At worst a critical waits for the one send under way (`timeout`).
- **Snoozed.** A notification of an alarm that is snoozed waits, and goes out once the snooze ends; the word that it was
  snoozed goes out at once.
- **Floods.** The due notifications of one kind of alarm for one person go out as one flood message once they are a
  flood, and the next ones within the flood window are covered by it (alarms/floods.py). Words about a snooze go out
  each on its own.
- **Never lost; at worst twice.** A restart, a crash or a database outage finds the queue as it was and sends it. A
  process that dies after the transport took one and before its attempt was written sends it again when it runs again:
  at least once, never lost (the transport has the notification's id for the push service's collapse key, so a phone
  shows it once). A notification is never written "sent" twice (a unique constraint), and two senders (an operator's
  run_alarms beside the worker) never send one at the same moment: each claims it with an advisory lock and looks again
  whether it went before sending.
- **Bounded.** A send has `timeout` seconds (settings.ALARM_WORKER send_timeout for the worker); a transport that has
  not answered by then is a failed attempt ("no answer in N s"), tried again like any other. A transport that raises
  is a failed attempt with its error. A transport must not use the database (it runs on a thread of its own).
- **Channels.** Each notification goes to the transport of its own channel (settings.ALARM_TRANSPORTS); a second
  channel (e-mail, SMS) joins as a Channel value and a transport, and its notifications are queued, retried, grouped and
  given up by the same rules."""
import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from django.conf import settings
from django.db import connection
from django.db.models import Count, Exists, Max, Min, OuterRef, Q
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from sensors.models.alarm import Severity

from . import floods, read, rules as alarm_rules, services
from .models import (RANK, Acknowledgement, AlarmClearance, Channel, DeliveryAttempt, Notification, NotificationKind,
                     Outcome, OutboxEntry)
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
    given_up: int = 0           # left the queue unsent: their attempts used up
    deferred: int = 0           # left for the next round: its deadline came, or a critical was queued meanwhile
    backlog: int = 0            # all the notifications still to be sent when the round began
    oldest: datetime | None = field(default=None)
    undeliverable: int = 0      # critical ones of open, unacknowledged alarms failing longer than the escalation time
    undeliverable_since: datetime | None = field(default=None)

    def __str__(self):
        text = f'{self.sent} sent, {self.failed} failed'
        if self.floods or self.grouped:
            text += f' ({self.floods} flood messages, {self.grouped} covered by one)'
        if self.retrying:
            text += f', {self.retrying} to be tried again'
        if self.given_up:
            text += f', {self.given_up} given up'
        if self.undeliverable:
            text += f'; {self.undeliverable} critical cannot be delivered'
        if self.waiting:
            text += f'; {self.waiting} waiting, nothing sent: no transport is connected for their channel'
        return text


def _connected():
    """The channels a transport is connected for (settings.ALARM_TRANSPORTS)."""
    return [channel for channel in Channel.values if transport_for(channel) is not None]


def _queued(channels=None):
    """The outbox's queue (entries that already have a sent or covered attempt left out: R2), only `channels` if given."""
    rows = Notification.objects.filter(pk__in=OutboxEntry.objects.values('notification')).exclude(
        Exists(DeliveryAttempt.objects.filter(notification=OuterRef('pk'), outcome__in=[Outcome.SENT, Outcome.GROUPED])))
    return rows if channels is None else rows.filter(channel__in=channels)


def _annotated(rows):
    return list(rows.annotate(
        failures=Count('attempts', filter=Q(attempts__outcome=Outcome.FAILED)),
        last_failed_at=Max('attempts__attempted_at', filter=Q(attempts__outcome=Outcome.FAILED)),
        cleared=Exists(AlarmClearance.objects.filter(alarm=OuterRef('alarm'))),
        acknowledged=Exists(Acknowledgement.objects.filter(alarm=OuterRef('alarm'))))
        .select_related('alarm', 'alarm__sensor_event', 'recipient'))


def backlog(channels=None):
    """The notifications in the outbox's queue (of `channels`, if given: a channel without a transport is left out in the
    database, so a queue that grows while nothing is connected costs a round nothing), the critical ones first, then the
    oldest queued. Each carries `failures`, `last_failed_at`, `cleared` and `alarm_closed` (acknowledged or cleared)."""
    rows = _annotated(_queued(channels))
    for row in rows:
        row.alarm_closed = row.cleared or row.acknowledged
    return sorted(rows, key=lambda row: (-RANK[row.alarm.severity], row.queued_at, row.pk))


def _persists(notification):
    """A critical alarm's notification while its alarm is open and unacknowledged: never given up."""
    return notification.alarm.severity == Severity.CRITICAL and not notification.alarm_closed


def exhausted(notification, rules):
    """Whether its attempts are used up (never while it persists: a critical of an open, unacknowledged alarm)."""
    return not _persists(notification) and notification.failures >= rules.delivery_attempts(notification.alarm.severity)


def retry_wait(notification, rules):
    """How long after its last failure it is tried again: its severity's retry time; a persisting critical's doubles
    with each failure, up to its severity's escalation time (never shorter than the retry time). Doubled step by step
    and stopped at the cap, so no count of failures overflows it (R1)."""
    wait = rules.retry_after(notification.alarm.severity)
    if not _persists(notification):
        return wait
    cap = max(wait, rules.escalation_after(notification.alarm.severity))
    for _failure in range(notification.failures - 1):
        if wait >= cap:
            break
        wait = min(cap, wait * 2)
    return wait


def is_due(notification, rules, now):
    """Whether a notification of the backlog is tried now: never tried, or its retry wait has passed since it failed."""
    return notification.last_failed_at is None or now - notification.last_failed_at >= retry_wait(notification, rules)


def undeliverable(rows, rules, now, snoozed=()):
    """The critical notifications of open, unacknowledged, unsnoozed alarms that have failed and waited longer than their
    severity's escalation time (nobody is reached about them, nor would the next level be)."""
    return [row for row in rows if _persists(row) and row.failures and row.alarm_id not in snoozed
            and now - row.queued_at > rules.escalation_after(row.alarm.severity)]


def stuck(rules, now):
    """`undeliverable` read on its own, for the pass's supervision: only the critical notifications of the queue that
    have failed and wait longer than the escalation time are read, however long the queue (R4, R5)."""
    since = now - rules.escalation_after(Severity.CRITICAL)
    rows = _annotated(_queued().filter(alarm__severity=Severity.CRITICAL, queued_at__lt=since).filter(
        Exists(DeliveryAttempt.objects.filter(notification=OuterRef('pk'), outcome=Outcome.FAILED))))
    for row in rows:
        row.alarm_closed = row.cleared or row.acknowledged
    return undeliverable(rows, rules, now, read.snoozes({row.alarm_id for row in rows}, now))


def _claim(notification):
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_try_advisory_lock(%s, hashtext(%s))', [CLAIM, str(notification.pk)])
        return cursor.fetchone()[0]


def _release(notification):
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_unlock(%s, hashtext(%s))', [CLAIM, str(notification.pk)])


def text(notification):
    """What the person is told, in their language (their profile's, else the platform's), on the company's clock: the
    alarm's severity and summary; a critical alarm that has cleared by the time it is sent says it was critical and has
    cleared, when it opened and when it cleared (the decision of 2026-11-24: a critical that came and went while the
    transport was down is still said); a word about a snooze says so."""
    from core.templatetags.dates import on, zone_for
    alarm = notification.alarm
    language = getattr(getattr(notification.recipient, 'profile', None), 'language', '') or settings.LANGUAGE_CODE
    clearance = AlarmClearance.objects.filter(alarm=alarm).first()
    moment = (lambda at: on(at, zone_for(alarm.site)).strftime('%d.%m.%Y %H:%M'))
    with translation.override(language):
        if notification.kind == NotificationKind.SNOOZED:
            return _('Snoozed: %(summary)s') % {'summary': alarm.summary}
        if notification.kind == NotificationKind.RESUMED:
            return _('Still open after its snooze: %(summary)s') % {'summary': alarm.summary}
        if alarm.severity == Severity.CRITICAL and clearance is not None:
            return _('Critical, now cleared: %(summary)s. Opened %(opened)s, cleared %(cleared)s.') % {
                'summary': alarm.summary, 'opened': moment(alarm.opened_at), 'cleared': moment(clearance.cleared_at)}
        return _('%(severity)s: %(summary)s') % {'severity': alarm.get_severity_display(), 'summary': alarm.summary}


def _call(transport, notification, timeout, flood=None):
    """The transport's answer, within `timeout` seconds (None: as long as it takes); a raise is a Failed. `flood`: the
    notification is the first of a flood message (alarms/floods.py). The notification carries its `text`."""
    answer = {}
    notification.text = text(notification)

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


def _person_kind(group):
    """(recipient, channel, kind of alarm) of a round's group key (recipient, channel, kind, its own id or 0)."""
    recipient, channel, kind, _apart = group
    return recipient, channel, kind


def _critical_since(seen, channels):
    """Whether a critical notification of `channels` joined the queue since the round read it (`seen`: the ids it read),
    whatever time it is stamped with: a pass stamps its notifications with its start and commits them at its end (R3)."""
    return OutboxEntry.objects.filter(notification__alarm__severity=Severity.CRITICAL,
                                      notification__channel__in=channels).exclude(notification_id__in=seen).exists()


def send_due(now=None, timeout=None, stop=None, round_seconds=None, clock=time.monotonic):
    """One round through the outbox: every notification that is due is handed to its transport (on its own, in a flood
    message, or covered by one: alarms/floods.py), its attempt written; what is used up leaves the queue. `now` is the
    round's moment for the tests (each attempt is stamped with it); by default each attempt's own. `stop()` true ends the
    round before the next group (the worker is stopping); so does `round_seconds` passed on `clock`, or a critical
    queued since the round began, before a warning's group. One notification that cannot be handled (an error of its
    own) is logged and left for the next round; the others go on (R1)."""
    rules = alarm_rules.current()
    moment = (lambda: now) if now is not None else timezone.now
    began, started = moment(), clock()
    OutboxEntry.objects.filter(notification__attempts__outcome__in=[Outcome.SENT, Outcome.GROUPED]).delete()
    # A warning (or another notification) whose alarm cleared before it was ever tried is given up, said why (R4); a
    # critical one is still delivered, saying it was critical and has cleared (`text`; the decision of 2026-11-24).
    late = list(_queued().filter(Exists(AlarmClearance.objects.filter(alarm=OuterRef('alarm')))).exclude(
        Exists(DeliveryAttempt.objects.filter(notification=OuterRef('pk')))).exclude(
        alarm__severity=Severity.CRITICAL).select_related('alarm', 'recipient'))
    if late:
        services.give_up_said(late, 'not sent: its alarm had cleared before the first attempt', moment())
    channels = _connected()
    unsent = _queued()
    elsewhere = unsent.exclude(channel__in=channels).aggregate(count=Count('pk'), oldest=Min('queued_at'))
    queue = backlog(channels)
    seen = [row.pk for row in queue if row.alarm.severity == Severity.CRITICAL]
    spent, live = [], []
    for row in queue:
        try:
            (spent if exhausted(row, rules) else live).append(row)
        except Exception:
            logger.exception('Notification %s could not be judged in this round; it waits for the next.', row.pk)
    if spent:
        services.give_up(spent)
    snoozed = read.snoozes({row.alarm_id for row in live}, began)
    stuck_rows = undeliverable(live, rules, began, snoozed)
    delivery = Delivery(backlog=len(live) + elsewhere['count'], waiting=elsewhere['count'],
                        oldest=min([row.queued_at for row in live] + ([elsewhere['oldest']] if elsewhere['oldest'] else []),
                                   default=None),
                        given_up=len(spent) + len(late), undeliverable=len(stuck_rows),
                        undeliverable_since=min((row.queued_at for row in stuck_rows), default=None))
    groups, transports = defaultdict(list), {}
    for notification in live:
        try:
            if notification.alarm_id in snoozed and notification.kind == NotificationKind.ALARM:
                delivery.snoozed += 1                 # a word about the snooze goes out at once
            elif not is_due(notification, rules, moment()):
                delivery.retrying += 1
            else:
                transports.setdefault(notification.channel, transport_for(notification.channel))
                kind = floods.key(notification.alarm)
                apart = notification.kind != NotificationKind.ALARM
                groups[(notification.recipient_id, notification.channel, kind, notification.pk if apart else 0)].append(
                    notification)
        except Exception:
            logger.exception('Notification %s could not be judged in this round; it waits for the next.',
                             notification.pk)
    found = floods.recent({_person_kind(group): members for group, members in groups.items() if not group[-1]},
                          moment(), rules)
    for index, (group, members) in enumerate(groups.items()):
        warning = members[0].alarm.severity != Severity.CRITICAL
        if ((stop is not None and stop()) or (round_seconds is not None and clock() - started >= round_seconds)
                or (warning and _critical_since(seen, channels))):
            delivery.deferred += sum(len(rest) for rest in list(groups.values())[index:])
            break
        try:
            _send_group(delivery, group, members, transports, found, rules, moment, timeout)
        except Exception:
            logger.exception('The notifications %s could not be sent in this round; they wait for the next.',
                             [notification.pk for notification in members])
    return delivery


def _send_group(delivery, group, members, transports, found, rules, moment, timeout):
    transport, kind = transports[group[1]], group[2]
    how = floods.plan(members, found[_person_kind(group)], moment(), rules) if not group[-1] else floods.EACH
    mine = [notification for notification in members if _sendable(notification)]
    delivery.busy += len(members) - len(mine)
    try:
        if how == floods.COVERED:
            note = Failed(f'covered by the flood message sent at {found[_person_kind(group)].last_flood_at:%H:%M:%S} UTC')
            _count(delivery, [services.attempt(notification, note, moment(), flood_key=kind, grouped=True)
                              for notification in mine])
        elif how == floods.FLOOD and mine:
            size = found[_person_kind(group)].count + len(mine)
            flood = Flood(size, min(notification.alarm.opened_at for notification in mine), mine[0].alarm.summary)
            result = _call(transport, mine[0], timeout, flood)
            delivery.floods += 1
            _count(delivery, [services.attempt(notification, result, moment(), flood_key=kind, flood_size=size)
                              for notification in mine])
        else:
            for notification in mine:
                _count(delivery, [services.attempt(notification, _call(transport, notification, timeout), moment(),
                                                   flood_key=kind)])
    finally:
        for notification in mine:
            _release(notification)
