"""The one write path of the alarms: each row is written here, with its activity-log entry in the same transaction (core.
audit; the loop writes as 'system'). A pass writes set-based: its alarms, clearances, notifications and escalations, and
their log entries, each in one statement however many there are (alarm plan, defect 7). Nothing here decides whether a
condition holds (alarms/sources.py), who is notified (alarms/routing.py) or when (alarms/engine.py)."""
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from core import audit
from core.models import AuditLog
from sensors.models.alarm import Severity

from .health import OWN_HEALTH
from .models import (Acknowledgement, Alarm, AlarmClearance, AlarmShelve, AlarmShelveEnd, AlarmSubjectState,
                     AlarmWorkerStatus, DeliveryAttempt, Escalation, Notification, NotificationKind, Outcome,
                     OutboxEntry, Source, WorkerState)


def _fit(model, field, text):
    """`text` cut to the column's size."""
    return text[:model._meta.get_field(field).max_length]


def _severity(alarm):
    return AuditLog.Severity.CRITICAL if alarm.severity == Severity.CRITICAL else AuditLog.Severity.NORMAL


def _log(entries):
    AuditLog.objects.bulk_create(entries)


# ---- alarms -----------------------------------------------------------------------------------------------------------
def open_alarms(specs):
    """New alarms, one per spec ({at, severity, summary, site, production_department, source, and sensor_event, or point
    and parameter, or parameter}), each logged (a critical one critical): two statements for all of them."""
    alarms = Alarm.objects.bulk_create([
        Alarm(opened_at=spec['at'], summary=_fit(Alarm, 'summary', spec['summary']),
              **{key: value for key, value in spec.items() if key not in ('at', 'summary')}) for spec in specs])
    with audit.source_language():
        _log([audit.created(None, alarm, {str(_('Severity')): audit.message(alarm.get_severity_display()),
                                          str(_('What')): alarm.summary, str(_('Opened at')): alarm.opened_at.isoformat()},
                            label=alarm.summary, severity=_severity(alarm)) for alarm in alarms])
    return alarms


def open_alarm(**spec):
    """One new alarm, logged (`open_alarms`)."""
    return open_alarms([spec])[0]


def save_states(states, fields):
    """The subjects' timers as one pass left them (unsaved or changed AlarmSubjectState rows, `fields` written), one
    upsert: with `_set_open`, the one writer of the subjects' rows (the data-layering audit, L-4). Inside the pass's step
    transaction, under its lock (alarms/engine.py); `_set_open` is the compare-and-set of the open alarm, this the rest."""
    AlarmSubjectState.objects.bulk_create(states, update_conflicts=True, unique_fields=['key'], update_fields=fields)


class AlreadyOpen(Exception):
    """A raise for a subject whose alarm is open: nothing was written."""


def _set_open(pairs):
    """[(subject key, alarm)] made the subjects' open alarms in one compare-and-set statement: set only where none is open;
    AlreadyOpen (and nothing written: the caller's transaction rolls back) when one subject had one."""
    rows = ', '.join(['(%s, %s, now())'] * len(pairs))
    with connection.cursor() as cursor:
        cursor.execute(
            f'INSERT INTO alarm_subject_state (key, open_alarm_id, updated_at) VALUES {rows} '
            f'ON CONFLICT (key) DO UPDATE SET open_alarm_id = EXCLUDED.open_alarm_id, pending_since = NULL, '
            f'updated_at = now() WHERE alarm_subject_state.open_alarm_id IS NULL RETURNING key',
            [value for key, alarm in pairs for value in (key, alarm.pk)])
        done = {key for (key,) in cursor.fetchall()}
    missing = [key for key, _alarm in pairs if key not in done]
    if missing:
        raise AlreadyOpen(missing)


def raise_many(subjects):
    """[(subject key, spec)]: opens each alarm as its subject's open alarm, a compare-and-set on the subjects' rows
    (alarm plan, defect 6), all in four statements. Returns {key: alarm}."""
    if not subjects:
        return {}
    with transaction.atomic():
        alarms = open_alarms([spec for _key, spec in subjects])
        pairs = [(key, alarm) for (key, _spec), alarm in zip(subjects, alarms)]
        _set_open(pairs)
        return dict(pairs)


def raise_for(key, make):
    """Opens the alarm `make()` writes as subject `key`'s open alarm (the same compare-and-set); returns it."""
    with transaction.atomic():
        alarm = make()
        _set_open([(key, alarm)])
        return alarm


def clear_many(clearances):
    """[(alarm, at, cause)] or [(alarm, at, cause, detail)]: each alarm stopped holding at `at` for `cause` (ClearCause),
    logged as a change of the alarm with the `detail` ({label: text}: what changed, e.g. the limit row removed and by
    whom) where there is one; two statements for all of them."""
    clearances = [(alarm, at, cause, next(iter(detail), None)) for alarm, at, cause, *detail in clearances]
    rows = AlarmClearance.objects.bulk_create([AlarmClearance(alarm=alarm, cleared_at=max(at, alarm.opened_at), cause=cause)
                                               for alarm, at, cause, _detail in clearances])
    with audit.source_language():
        _log([audit.entry(None, AuditLog.Action.UPDATE, row.alarm, {
            str(_('Cleared at')): [None, row.cleared_at.isoformat()],
            str(_('Why')): [None, audit.message(row.get_cause_display())],
            **{str(label): [None, text] for label, text in (detail or {}).items()}}, label=row.alarm.summary)
            for row, (_alarm, _at, _cause, detail) in zip(rows, clearances)])
    return rows


def clear(alarm, at, cause):
    """One alarm stopped holding (`clear_many`)."""
    return clear_many([(alarm, at, cause)])[0]


# ---- notifications and escalations -------------------------------------------------------------------------------------
def queue_many(notifications):
    """Unsaved Notifications queued (and put in the outbox's queue), each logged; three statements for all of them."""
    made = Notification.objects.bulk_create(notifications)
    OutboxEntry.objects.bulk_create([OutboxEntry(notification=notification) for notification in made])
    with audit.source_language():
        _log([audit.created(None, notification, {
            str(_('Recipient')): notification.recipient.get_username(),
            str(_('Channel')): audit.message(notification.get_channel_display()), str(_('Level')): str(notification.level),
            **({str(_('Kind')): audit.message(notification.get_kind_display())}
               if notification.kind != NotificationKind.ALARM else {})},
            label=f'{notification.alarm.summary} → {notification.recipient.get_username()}') for notification in made])
    return made


def give_up_said(notifications, detail, now):
    """The notifications leave the outbox's queue unsent, each with a failed attempt saying `detail` and its log entry:
    one transaction, three statements however many. The outbox hands it one chunk a round (outbox.GIVE_UP_CHUNK), so
    a failure between two chunks leaves the queue consistent and the next round goes on."""
    with transaction.atomic():
        made = DeliveryAttempt.objects.bulk_create([
            DeliveryAttempt(notification=notification, attempted_at=now, outcome=Outcome.FAILED,
                            detail=_fit(DeliveryAttempt, 'detail', detail)) for notification in notifications])
        OutboxEntry.objects.filter(notification__in=notifications).delete()
        with audit.source_language():
            _log([audit.entry(None, AuditLog.Action.UPDATE, notification,
                              {str(_('Delivery')): [None, f'{Outcome.FAILED}: {row.detail}']},
                              label=f'{notification.alarm.summary} → {notification.recipient.get_username()}')
                  for notification, row in zip(notifications, made)])
    return made


def give_up(notifications):
    """The notifications leave the outbox's queue unsent (their attempts are used up, or their critical alarm was
    acknowledged or cleared and its attempts are used up): their attempts say why (read.status)."""
    OutboxEntry.objects.filter(notification__in=notifications).delete()


def enqueue(alarm, level, recipients, now):
    """The notifications of `level` for [(user, rule)] not queued yet; returns the new ones, each logged."""
    queued = set(Notification.objects.filter(alarm=alarm, level=level).values_list('recipient_id', 'channel'))
    fresh = {}
    for user, rule in recipients:
        if (user.pk, rule.channel) not in queued:
            fresh.setdefault((user.pk, rule.channel), Notification(alarm=alarm, recipient=user, channel=rule.channel,
                                                                   level=level, rule=rule, queued_at=now))
    return queue_many(list(fresh.values()))


def escalate_many(escalations):
    """Unsaved Escalations written, each logged; two statements for all of them."""
    made = Escalation.objects.bulk_create(escalations)
    with audit.source_language():
        _log([audit.created(None, escalation, {str(_('Level')): str(escalation.level)},
                            label=f'{escalation.alarm.summary} → {escalation.level}', severity=_severity(escalation.alarm))
              for escalation in made])
    return made


def escalate(alarm, level, now):
    """The alarm goes on to `level`: nobody acknowledged it in time at the level before (or nobody could be notified
    there)."""
    return escalate_many([Escalation(alarm=alarm, level=level, escalated_at=now)])[0]


# ---- delivery and acknowledgement --------------------------------------------------------------------------------------
def drop_delivered():
    """The queue's entries of notifications that were sent or covered by a flood message leave it: `attempt` removes its
    own in the same transaction, so this finds only one an earlier round left (a round drops it before it reads)."""
    OutboxEntry.objects.filter(notification__attempts__outcome__in=[Outcome.SENT, Outcome.GROUPED]).delete()


def worker_running(name, **fields):
    """The alarm worker `name` took the lock and runs: its row (alarms.AlarmWorkerStatus, made the first time) says so
    with `fields`. The worker's row is written by the worker it describes only, through here and `worker_status`; it is
    the worker's heartbeat, not history, so no activity-log entry (alarms/watch.py reads it)."""
    AlarmWorkerStatus.objects.update_or_create(name=name, defaults={'state': WorkerState.RUNNING, **fields})


def worker_status(name, **fields):
    """The alarm worker `name`'s row takes `fields` (a heartbeat, a pass, a failure, a stop, the outbox's round)."""
    AlarmWorkerStatus.objects.filter(name=name).update(**fields)


def attempt(notification, result, now, *, flood_key='', flood_size=None, grouped=False):
    """What a transport did with a notification (alarms.transports Sent or Failed), or that a flood message covered it
    (`grouped`), logged on the notification; `flood_key` its kind of alarm, `flood_size` the alarms of the flood message
    it was part of."""
    from .transports import Sent
    outcome = Outcome.GROUPED if grouped else Outcome.SENT if isinstance(result, Sent) else Outcome.FAILED
    with transaction.atomic():                 # the attempt, the queue's entry and the log together, or none (R2)
        row = DeliveryAttempt.objects.create(notification=notification, attempted_at=now, outcome=outcome,
                                             detail=_fit(DeliveryAttempt, 'detail', result.detail or ''),
                                             flood_key=_fit(DeliveryAttempt, 'flood_key', flood_key),
                                             flood_size=flood_size)
        if outcome != Outcome.FAILED:
            OutboxEntry.objects.filter(notification=notification).delete()
        with audit.source_language():
            audit.record(None, AuditLog.Action.UPDATE, notification,
                         {str(_('Delivery')): [None, f'{outcome}: {row.detail}' if row.detail else outcome]},
                         label=f'{notification.alarm.summary} → {notification.recipient.get_username()}')
    return row


def acknowledge(alarm, user, *, at=None, device='', app='console', notification=None):
    """`user` saw the alarm: once per person; `notification`, the one they answered, must be theirs (without one, the
    person's own latest, as the console's button means). The first one stops the escalation (alarms/engine.py). Who may
    is asked here, by the one rule (read.may_acknowledge: Alarms: Edit, or a person it was sent to), whoever calls: the
    alarm pages, the sensor events page, the mobile app (the data-layering audit, L-5). PermissionDenied otherwise."""
    from . import read
    if not read.may_acknowledge(user, alarm):
        raise PermissionDenied
    at = at or timezone.now()
    with transaction.atomic():
        alarm = Alarm.objects.select_for_update().get(pk=alarm.pk)
        if notification is None:
            notification = alarm.notifications.filter(recipient=user).order_by('-level', '-queued_at').first()
        elif notification and (notification.alarm_id != alarm.pk or notification.recipient_id != user.pk):
            raise ValidationError(_('This notification is not yours.'))
        if Acknowledgement.objects.filter(alarm=alarm, user=user).exists():
            raise ValidationError(_('You have already acknowledged this alarm.'))
        ack = Acknowledgement.objects.create(alarm=alarm, user=user, acknowledged_at=at,
                                             device=_fit(Acknowledgement, 'device', device),
                                             app=_fit(Acknowledgement, 'app', app), notification=notification)
        with audit.source_language():
            audit.record_create(user, ack, {str(_('Device')): device or None, str(_('App')): app,
                                            str(_('Delay')): str(ack.delay)}, label=alarm.summary)
        return ack


# ---- snoozing ---------------------------------------------------------------------------------------------------------
def shelve(alarm, user, minutes, reason, *, at=None):
    """`user` snoozes an open alarm for `minutes`, saying why: nobody is notified of it and it is not escalated until then
    (alarms/engine.py, alarms/outbox.py); it is still raised, kept, shown and cleared. One at a time; all the snoozes of
    one alarm together at most its severity's longest snooze (Alarm severity rules), so a snooze is never renewed past
    it; never a critical alarm of the alarm system itself (it says the alarms are not working). The people notified of
    the alarm (but the snoozer) are told who snoozed it, until when and why. Logged, critical for a critical alarm. Who
    may is asked by the caller (read.SHELVE)."""
    from .read import snoozes
    from .rules import current
    at = at or timezone.now()
    reason = ' '.join(str(reason or '').split())
    with transaction.atomic():
        alarm = Alarm.objects.select_for_update().get(pk=alarm.pk)
        if AlarmClearance.objects.filter(alarm=alarm).exists():
            raise ValidationError(_('This alarm has cleared: there is nothing to snooze.'))
        if alarm.source == Source.SYSTEM and alarm.parameter in OWN_HEALTH:
            raise ValidationError(_('An alarm about the alarm system\'s own health is never snoozed: it says the alarms '
                                    'are not working as they should.'))
        longest = current().shelve_max(alarm.severity)
        if not isinstance(minutes, int) or minutes < 1 or timedelta(minutes=minutes) > longest:
            raise ValidationError(_('A %(severity)s alarm is snoozed for 1 to %(minutes)d minutes.') % {
                'severity': alarm.get_severity_display().lower(), 'minutes': longest // timedelta(minutes=1)})
        used = sum((min(row.ends_at(), at) - row.shelved_at for row in alarm.shelves.select_related('end')
                    if row.shelved_at <= at), timedelta())
        if used + timedelta(minutes=minutes) > longest:
            raise ValidationError(_('This alarm has been snoozed for %(used)d of its %(minutes)d minutes already: at '
                                    'most %(left)d more.') % {
                'used': used // timedelta(minutes=1), 'minutes': longest // timedelta(minutes=1),
                'left': max(0, (longest - used) // timedelta(minutes=1))})
        if not reason:
            raise ValidationError(_('Say why the alarm is snoozed.'))
        if alarm.pk in snoozes([alarm.pk], at):
            raise ValidationError(_('This alarm is snoozed already.'))
        row = AlarmShelve.objects.create(alarm=alarm, user=user, shelved_at=at, until=at + timedelta(minutes=minutes),
                                         reason=_fit(AlarmShelve, 'reason', reason))
        with audit.source_language():
            audit.record_create(user, row, {str(_('Snoozed until')): row.until.isoformat(), str(_('Why')): row.reason},
                                label=alarm.summary, severity=_severity(alarm))
        told = {}
        for notification in (alarm.notifications.filter(kind=NotificationKind.ALARM).exclude(recipient=user)
                             .select_related('recipient', 'rule').order_by('level')):
            told[(notification.recipient_id, notification.channel)] = notification
        queue_many([Notification(alarm=alarm, recipient=notification.recipient, channel=notification.channel,
                                 level=notification.level, rule=notification.rule, queued_at=at,
                                 kind=NotificationKind.SNOOZED, shelve=row) for notification in told.values()])
        return row


def unshelve(alarm, user, *, at=None):
    """`user` ends the alarm's snooze before its time: notification and escalation go on from now. Logged."""
    from .read import snoozes
    at = at or timezone.now()
    with transaction.atomic():
        alarm = Alarm.objects.select_for_update().get(pk=alarm.pk)
        row = snoozes([alarm.pk], at).get(alarm.pk)
        if row is None:
            raise ValidationError(_('This alarm is not snoozed.'))
        end = AlarmShelveEnd.objects.create(shelve=row, user=user, ended_at=at)
        with audit.source_language():
            audit.record(user, AuditLog.Action.UPDATE, row, {str(_('Ended at')): [None, at.isoformat()]},
                         label=alarm.summary)
        return end
