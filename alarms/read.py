"""Reading the alarms: whether one is open, acknowledged, at which level, whether anyone could be notified, a
notification's state, whether a transport is connected, who may acknowledge, and an alarm's history in time order. Every
state is read from the append-only rows, never stored."""
from dataclasses import dataclass

from django.db.models import Count, Exists, Max, OuterRef

from .models import (Acknowledgement, Alarm, AlarmClearance, Channel, DeliveryAttempt, Escalation, Notification,
                     Outcome)
from .rules import current as current_rules
from .transports import transport_for

ACKNOWLEDGE = 'alarms.change_alarm'
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
    if attempts.filter(outcome=Outcome.SENT).exists():
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


def listing(state='open'):
    """The alarms for the page, open ones first, each with its state annotated; `state` 'open' or 'all'."""
    alarms = Alarm.objects.select_related('site', 'production_department', 'point', 'clearance').annotate(
        is_cleared=Exists(AlarmClearance.objects.filter(alarm=OuterRef('pk'))),
        acknowledgements_count=Count('acknowledgements', distinct=True),
        notifications_count=Count('notifications', distinct=True),
        top_level=Max('escalations__level'))
    if state == 'open':
        alarms = alarms.filter(is_cleared=False)
    return alarms.order_by('is_cleared', '-opened_at', '-id')


@dataclass(frozen=True)
class Event:
    at: object
    kind: str            # opened, notified, delivered, escalated, acknowledged, cleared
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
    clearance = AlarmClearance.objects.filter(alarm=alarm).first()
    if clearance is not None:
        events.append(Event(clearance.cleared_at, 'cleared', clearance))
    order = ['opened', 'notified', 'delivered', 'escalated', 'acknowledged', 'cleared']
    return sorted(events, key=lambda event: (event.at, order.index(event.kind)))
