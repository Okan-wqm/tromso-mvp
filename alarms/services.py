"""The one write path of the alarms: each row is written here, with its activity-log entry in the same transaction (core.
audit; the loop writes as 'system'). Nothing here decides whether a condition holds (alarms/sources.py), who is notified
(alarms/routing.py) or when (alarms/engine.py)."""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from core import audit
from core.models import AuditLog
from sensors.models.alarm import Severity

from .models import (Acknowledgement, Alarm, AlarmClearance, DeliveryAttempt, Escalation, Notification, Outcome)



def _fit(model, field, text):
    """`text` cut to the column's size."""
    return text[:model._meta.get_field(field).max_length]


def _severity(alarm):
    return AuditLog.Severity.CRITICAL if alarm.severity == Severity.CRITICAL else AuditLog.Severity.NORMAL


def open_alarm(*, at, severity, summary, site=None, production_department=None, **source):
    """A new alarm (`source`: source and sensor_event, or source, point and parameter), logged; a critical one critical."""
    alarm = Alarm.objects.create(opened_at=at, severity=severity, summary=_fit(Alarm, 'summary', summary), site=site,
                                 production_department=production_department, **source)
    with audit.source_language():
        audit.record_create(None, alarm, {str(_('Severity')): audit.message(alarm.get_severity_display()),
                                          str(_('What')): alarm.summary, str(_('Opened at')): at.isoformat()},
                            label=alarm.summary, severity=_severity(alarm))
    return alarm


def clear(alarm, at, cause):
    """The alarm stopped holding at `at` for `cause` (ClearCause); logged as a change of the alarm."""
    clearance = AlarmClearance.objects.create(alarm=alarm, cleared_at=max(at, alarm.opened_at), cause=cause)
    with audit.source_language():
        audit.record(None, AuditLog.Action.UPDATE, alarm, {
            str(_('Cleared at')): [None, clearance.cleared_at.isoformat()],
            str(_('Why')): [None, audit.message(clearance.get_cause_display())]}, label=alarm.summary)
    return clearance


def enqueue(alarm, level, recipients, now):
    """The notifications of `level` for [(user, rule)] not queued yet; returns the new ones, each logged."""
    queued = set(Notification.objects.filter(alarm=alarm, level=level).values_list('recipient_id', 'channel'))
    made = []
    for user, rule in recipients:
        if (user.pk, rule.channel) in queued:
            continue
        queued.add((user.pk, rule.channel))
        notification = Notification.objects.create(alarm=alarm, recipient=user, channel=rule.channel, level=level,
                                                   rule=rule, queued_at=now)
        with audit.source_language():
            audit.record_create(None, notification, {str(_('Recipient')): user.get_username(),
                                                     str(_('Channel')): audit.message(notification.get_channel_display()),
                                                     str(_('Level')): str(level)},
                                label=f'{alarm.summary} → {user.get_username()}')
        made.append(notification)
    return made


def escalate(alarm, level, now):
    """The alarm goes on to `level`: nobody acknowledged it in time at the level before (or nobody could be notified
    there)."""
    escalation = Escalation.objects.create(alarm=alarm, level=level, escalated_at=now)
    with audit.source_language():
        audit.record_create(None, escalation, {str(_('Level')): str(level)}, label=f'{alarm.summary} → {level}',
                            severity=_severity(alarm))
    return escalation


def attempt(notification, result, now):
    """What a transport did with a notification (alarms.transports Sent or Failed), logged on the notification."""
    from .transports import Sent
    outcome = Outcome.SENT if isinstance(result, Sent) else Outcome.FAILED
    row = DeliveryAttempt.objects.create(notification=notification, attempted_at=now, outcome=outcome,
                                         detail=_fit(DeliveryAttempt, 'detail', result.detail or ''))
    with audit.source_language():
        audit.record(None, AuditLog.Action.UPDATE, notification,
                     {str(_('Delivery')): [None, f'{outcome}: {row.detail}' if row.detail else outcome]},
                     label=f'{notification.alarm.summary} → {notification.recipient.get_username()}')
    return row


def acknowledge(alarm, user, *, at=None, device='', app='console', notification=None):
    """`user` saw the alarm: once per person; `notification`, the one they answered, must be theirs. The first one stops
    the escalation (alarms/engine.py). Who may is asked by the caller (read.may_acknowledge)."""
    at = at or timezone.now()
    with transaction.atomic():
        alarm = Alarm.objects.select_for_update().get(pk=alarm.pk)
        if notification is not None and (notification.alarm_id != alarm.pk or notification.recipient_id != user.pk):
            raise ValidationError(_('This notification is not yours.'))
        if Acknowledgement.objects.filter(alarm=alarm, user=user).exists():
            raise ValidationError(_('You have already acknowledged this alarm.'))
        ack = Acknowledgement.objects.create(alarm=alarm, user=user, acknowledged_at=at, device=_fit(Acknowledgement, 'device', device),
                                             app=_fit(Acknowledgement, 'app', app), notification=notification)
        with audit.source_language():
            audit.record_create(user, ack, {str(_('Device')): device or None, str(_('App')): app,
                                            str(_('Delay')): str(ack.delay)}, label=alarm.summary)
        return ack
