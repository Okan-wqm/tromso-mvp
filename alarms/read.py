"""Reading the alarms: whether one is open, acknowledged, at which level, whether anyone could be notified, a
notification's state, whether a transport is connected, who may acknowledge, and an alarm's history in time order. Every
state is read from the append-only rows, never stored."""
from dataclasses import dataclass

from django.db.models import Count, Exists, Max, OuterRef, Q, Subquery
from django.utils import timezone

from .models import (Acknowledgement, Alarm, AlarmClearance, AlarmShelve, Channel, DeliveryAttempt, Escalation,
                     Notification,
                     Outcome)
from .rules import current as current_rules
from .transports import transport_for

ACKNOWLEDGE = 'alarms.change_alarm'
SHELVE = 'alarms.add_alarmshelve'
QUEUED, SENT, FAILED = 'queued', 'sent', 'failed'


def is_open(alarm):
    return not AlarmClearance.objects.filter(alarm=alarm).exists()


def acknowledged(alarm):
    return Acknowledgement.objects.filter(alarm=alarm).exists()


def level(alarm):
    """The level the alarm is at: 0, or the last level it was escalated to."""
    return Escalation.objects.filter(alarm=alarm).aggregate(top=Max('level'))['top'] or 0


def nobody_notified(alarm):
    """Whether no notification was queued for it at all: nobody to notify (no recipient rule reaches it)."""
    return not Notification.objects.filter(alarm=alarm).exists()


def status(notification):
    """'sent' once a transport took it, 'failed' after its severity's delivery attempts failed, else 'queued'."""
    attempts = DeliveryAttempt.objects.filter(notification=notification)
    if attempts.filter(outcome__in=[Outcome.SENT, Outcome.GROUPED]).exists():
        return SENT
    failed = attempts.filter(outcome=Outcome.FAILED).count()
    return FAILED if failed >= current_rules().delivery_attempts(notification.alarm.severity) else QUEUED


def transport_connected(channel):
    return transport_for(channel) is not None


def connected():
    """{channel: whether a transport is connected for it}, for the pages' notice that nothing is sent."""
    return {channel.value: transport_connected(channel.value) for channel in Channel}


def may_acknowledge(user, alarm):
    """Who may say they saw an alarm: who holds Alarms: Edit, or a person one of its notifications went to."""
    return user.has_perm(ACKNOWLEDGE) or Notification.objects.filter(alarm=alarm, recipient=user).exists()


def _in_force(now):
    """The snoozes in force at `now`: begun, not past their `until`, not ended by then."""
    return (Q(shelved_at__lte=now, until__gt=now)
            & ~Q(pk__in=AlarmShelve.objects.filter(end__ended_at__lte=now).values('pk')))


def snoozes(alarm_ids, now):
    """{alarm id: its snooze in force at `now`}."""
    return {row.alarm_id: row for row in AlarmShelve.objects.filter(_in_force(now), alarm__in=alarm_ids)
            .select_related('user')}


def resumed(alarm_ids, now):
    """{alarm id: when its last snooze ended}, for the alarms a snooze of which has ended by `now` (its time out, or
    ended early): their escalation time is counted again from then."""
    found = {}
    for row in AlarmShelve.objects.filter(alarm__in=alarm_ids, shelved_at__lte=now).select_related('end'):
        end = row.ends_at()
        if end <= now:
            found[row.alarm_id] = max(end, found.get(row.alarm_id, end))
    return found


def may_snooze(user, alarm, now=None):
    """Whether `user` may snooze the alarm now (Alarm snoozes: Create; an open alarm with none in force)."""
    return (user.has_perm(SHELVE) and is_open(alarm)
            and alarm.pk not in snoozes([alarm.pk], now or timezone.now()))


def listing(state='open', now=None):
    """The alarms for the page, open ones first, each with its state annotated (and until when it is snoozed, if it
    is); `state` 'open' or 'all'."""
    now = now or timezone.now()
    alarms = Alarm.objects.select_related('site', 'production_department', 'point', 'clearance').annotate(
        is_cleared=Exists(AlarmClearance.objects.filter(alarm=OuterRef('pk'))),
        acknowledgements_count=Count('acknowledgements', distinct=True),
        notifications_count=Count('notifications', distinct=True),
        top_level=Max('escalations__level'),
        snoozed_until=Subquery(AlarmShelve.objects.filter(_in_force(now), alarm=OuterRef('pk')).values('until')[:1]))
    if state == 'open':
        alarms = alarms.filter(is_cleared=False)
    return alarms.order_by('is_cleared', '-opened_at', '-id')


@dataclass(frozen=True)
class Event:
    at: object
    kind: str            # opened, notified, delivered, escalated, acknowledged, snoozed, snooze_ended, cleared
    row: object
    state: str = ''      # a notification's: queued, sent or failed


def history(alarm):
    """Everything that happened to an alarm, in time order."""
    events = [Event(alarm.opened_at, 'opened', alarm)]
    for notification in alarm.notifications.select_related('recipient', 'rule').prefetch_related('attempts'):
        events.append(Event(notification.queued_at, 'notified', notification, status(notification)))
        events += [Event(attempt.attempted_at, 'delivered', attempt) for attempt in notification.attempts.all()]
    events += [Event(escalation.escalated_at, 'escalated', escalation) for escalation in alarm.escalations.all()]
    events += [Event(ack.acknowledged_at, 'acknowledged', ack)
               for ack in alarm.acknowledgements.select_related('user', 'notification')]
    for shelve in alarm.shelves.select_related('user', 'end', 'end__user'):
        events.append(Event(shelve.shelved_at, 'snoozed', shelve))
        if getattr(shelve, 'end', None) is not None:
            events.append(Event(shelve.end.ended_at, 'snooze_ended', shelve.end))
    clearance = AlarmClearance.objects.filter(alarm=alarm).first()
    if clearance is not None:
        events.append(Event(clearance.cleared_at, 'cleared', clearance))
    order = ['opened', 'notified', 'delivered', 'escalated', 'acknowledged', 'snoozed', 'snooze_ended', 'cleared']
    return sorted(events, key=lambda event: (event.at, order.index(event.kind)))
