"""The alarms (F-091; owner answer 2026-11-06: push notifications to everyone's phone through the coming mobile app,
everything logged). What holds an alarm is judged elsewhere: the water limits of the species (farm/water) and the sensor
alarm rules (sensors/alarms.py); this app keeps what follows, append-only:

- `Alarm`: one time a condition held, where and how severe; `AlarmClearance`: when it stopped holding;
- `Notification`: the outbox, one row per alarm, recipient, channel and level (0 first, then each escalation);
  `DeliveryAttempt`: each time a transport took it or failed; a notification is queued until one is sent;
- `Escalation`: the alarm went on to the next level because nobody acknowledged it in time;
- `Acknowledgement`: who said they saw it, when, from which device and app (the delay is computed, never stored).

A database trigger refuses UPDATE and DELETE on these six tables (migration 0001), as on the activity log: the history of
an alarm cannot be edited, not even by the platform admin. Who is notified is configuration (`RecipientRule`, an ordinary
tab: edited, soft-deleted, logged)."""
from django.conf import settings
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext, gettext_lazy as _

from core.models import AuditedModel
from farm.models import ProductionDepartment, SamplingPoint, Site
from sensors.models import AlarmEvent
from sensors.models.alarm import Severity

# How serious a severity is, for "at least" (a rule's least severity).
RANK = {Severity.WARNING: 1, Severity.CRITICAL: 2}
MAX_LEVEL = 9


class Source(models.TextChoices):
    SENSOR_RULE = 'sensor_rule', _('Sensor alarm rule')
    WATER_LIMIT = 'water_limit', _('Water limit')


class Channel(models.TextChoices):
    """How a notification reaches a person. Push first (the mobile app); a channel joins here and in
    settings.ALARM_TRANSPORTS (alarms/transports.py). There is no e-mail: it gets too little attention for an alarm."""
    PUSH = 'push', _('Push')


class Outcome(models.TextChoices):
    SENT = 'sent', _('Sent')
    FAILED = 'failed', _('Failed')


class Alarm(models.Model):
    """One time a condition held: a sensor rule's event (mirrored from sensors.AlarmEvent, which the sensors' check keeps),
    or a water value past a species' limit at a sampling point. `site` and `production_department` are where it is, set
    when it opens, for the recipient rules; `summary` says what it is, in English at rest (a value and a limit)."""

    id = models.BigAutoField(primary_key=True)
    source = models.CharField(_('Source'), max_length=12, choices=Source.choices)
    sensor_event = models.OneToOneField(AlarmEvent, null=True, blank=True, on_delete=models.PROTECT,
                                        related_name='alarm', verbose_name=_('Sensor alarm event'))
    point = models.ForeignKey(SamplingPoint, null=True, blank=True, on_delete=models.PROTECT, related_name='alarms',
                              verbose_name=_('Sampling point'))
    parameter = models.CharField(_('Parameter'), max_length=30, blank=True)
    severity = models.CharField(_('Severity'), max_length=10, choices=Severity.choices)
    site = models.ForeignKey(Site, null=True, blank=True, on_delete=models.PROTECT, related_name='alarms',
                             verbose_name=_('Site'))
    production_department = models.ForeignKey(ProductionDepartment, null=True, blank=True, on_delete=models.PROTECT,
                                              related_name='alarms', verbose_name=_('Production department'))
    opened_at = models.DateTimeField(_('Opened at'), db_index=True)
    summary = models.CharField(_('What'), max_length=300)

    class Meta:
        db_table = 'alarms'
        ordering = ['-opened_at', '-id']
        verbose_name = _('alarm')
        verbose_name_plural = _('alarms')
        constraints = [
            models.CheckConstraint(condition=Q(source__in=Source.values), name='chk_alarms_source'),
            models.CheckConstraint(condition=Q(severity__in=Severity.values), name='chk_alarms_severity'),
            models.CheckConstraint(
                condition=Q(source=Source.SENSOR_RULE, sensor_event__isnull=False, point__isnull=True, parameter='')
                | (Q(source=Source.WATER_LIMIT, sensor_event__isnull=True, point__isnull=False) & ~Q(parameter='')),
                name='chk_alarms_shape'),
        ]

    def __str__(self):
        return self.summary


class AlarmClearance(models.Model):
    """When an alarm stopped holding: the sensor rule's event closed, or a fresh water value is back inside the limits
    (a value that only goes stale never clears it). An alarm is open while it has none."""

    alarm = models.OneToOneField(Alarm, primary_key=True, on_delete=models.PROTECT, related_name='clearance',
                                 verbose_name=_('Alarm'))
    cleared_at = models.DateTimeField(_('Cleared at'))

    class Meta:
        db_table = 'alarm_clearances'
        verbose_name = _('alarm clearance')
        verbose_name_plural = _('alarm clearances')

    def __str__(self):
        return f'{self.alarm} · {self.cleared_at:%Y-%m-%d %H:%M}'


class RecipientRule(AuditedModel):
    """Who is notified of which alarms: on a site (or every site) and a production department (or every one), of at least
    a severity, at a level (0 is notified when the alarm opens; level 1 when nobody acknowledged level 0 in the platform
    owner's escalation time, and so on), one role or one person, through a channel, and only while on shift when ticked
    (the HR roster: a person without an employee record is never on shift)."""

    site = models.ForeignKey(Site, null=True, blank=True, on_delete=models.CASCADE, related_name='alarm_recipients',
                             verbose_name=_('Site'))
    production_department = models.ForeignKey(ProductionDepartment, null=True, blank=True, on_delete=models.CASCADE,
                                              related_name='alarm_recipients', verbose_name=_('Production department'))
    min_severity = models.CharField(_('At least'), max_length=10, choices=Severity.choices, default=Severity.WARNING)
    level = models.PositiveSmallIntegerField(_('Level'), default=0, validators=[MaxValueValidator(MAX_LEVEL)])
    role = models.ForeignKey(Group, null=True, blank=True, on_delete=models.PROTECT, related_name='alarm_rules',
                             verbose_name=_('Role'))
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                             related_name='alarm_rules', verbose_name=_('Person'))
    on_shift_only = models.BooleanField(_('Only while on shift'), default=False)
    channel = models.CharField(_('Channel'), max_length=10, choices=Channel.choices, default=Channel.PUSH)
    is_active = models.BooleanField(_('Active'), default=True)

    class Meta:
        db_table = 'alarm_recipient_rules'
        ordering = ['level', 'site__name', 'production_department__name']
        verbose_name = _('alarm recipient rule')
        verbose_name_plural = _('alarm recipient rules')
        constraints = [
            models.CheckConstraint(condition=Q(role__isnull=False, user__isnull=True)
                                   | Q(role__isnull=True, user__isnull=False), name='chk_alarm_recipient_rules_who',
                                   violation_error_message=_('Choose a role or a person.')),
            models.CheckConstraint(condition=Q(level__lte=MAX_LEVEL), name='chk_alarm_recipient_rules_level'),
            models.CheckConstraint(condition=Q(min_severity__in=Severity.values),
                                   name='chk_alarm_recipient_rules_severity'),
            models.CheckConstraint(condition=Q(channel__in=Channel.values), name='chk_alarm_recipient_rules_channel'),
        ]

    def __str__(self):
        who = self.role or self.user
        where = self.production_department or self.site or gettext('every site')
        return f'{who} · {where} · {gettext("level")} {self.level}'

    def clean(self):
        super().clean()
        if self.production_department_id and self.site_id and self.production_department.site_id != self.site_id:
            raise ValidationError({'production_department': _('This production department is not on the site.')})


class Notification(models.Model):
    """The outbox: one alarm for one person through one channel at one level, queued by the alarm loop. It is sent when a
    transport for its channel took it (a DeliveryAttempt `sent`); with no transport connected it waits here."""

    id = models.BigAutoField(primary_key=True)
    alarm = models.ForeignKey(Alarm, on_delete=models.PROTECT, related_name='notifications', verbose_name=_('Alarm'))
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='alarm_notifications',
                                  verbose_name=_('Recipient'))
    channel = models.CharField(_('Channel'), max_length=10, choices=Channel.choices)
    level = models.PositiveSmallIntegerField(_('Level'))
    rule = models.ForeignKey(RecipientRule, null=True, blank=True, on_delete=models.PROTECT,
                             related_name='notifications', verbose_name=_('Recipient rule'))
    queued_at = models.DateTimeField(_('Queued at'))

    class Meta:
        db_table = 'alarm_notifications'
        ordering = ['queued_at', 'id']
        verbose_name = _('alarm notification')
        verbose_name_plural = _('alarm notifications')
        constraints = [
            models.UniqueConstraint(fields=['alarm', 'recipient', 'channel', 'level'],
                                    name='uq_alarm_notifications_once'),
            models.CheckConstraint(condition=Q(channel__in=Channel.values), name='chk_alarm_notifications_channel'),
            models.CheckConstraint(condition=Q(level__lte=MAX_LEVEL), name='chk_alarm_notifications_level'),
        ]

    def __str__(self):
        return f'{self.alarm} → {self.recipient} ({self.channel}, {self.level})'


class DeliveryAttempt(models.Model):
    """A transport took a notification (sent) or failed to (failed, with what it said)."""

    id = models.BigAutoField(primary_key=True)
    notification = models.ForeignKey(Notification, on_delete=models.PROTECT, related_name='attempts',
                                     verbose_name=_('Notification'))
    attempted_at = models.DateTimeField(_('Attempted at'))
    outcome = models.CharField(_('Outcome'), max_length=10, choices=Outcome.choices)
    detail = models.CharField(_('Detail'), max_length=300, blank=True)

    class Meta:
        db_table = 'alarm_delivery_attempts'
        ordering = ['attempted_at', 'id']
        verbose_name = _('alarm delivery attempt')
        verbose_name_plural = _('alarm delivery attempts')
        constraints = [
            models.CheckConstraint(condition=Q(outcome__in=Outcome.values), name='chk_alarm_delivery_attempts_outcome'),
            # Sent once: a notification a transport took is never sent again.
            models.UniqueConstraint(fields=['notification'], condition=Q(outcome=Outcome.SENT),
                                    name='uq_alarm_delivery_attempts_sent_once'),
        ]

    def __str__(self):
        return f'{self.notification} · {self.outcome}'


class Escalation(models.Model):
    """The alarm went on to `level` because nobody had acknowledged it in the platform owner's escalation time after the
    level before was notified (or at once, when nobody could be notified there)."""

    id = models.BigAutoField(primary_key=True)
    alarm = models.ForeignKey(Alarm, on_delete=models.PROTECT, related_name='escalations', verbose_name=_('Alarm'))
    level = models.PositiveSmallIntegerField(_('Level'))
    escalated_at = models.DateTimeField(_('Escalated at'))

    class Meta:
        db_table = 'alarm_escalations'
        ordering = ['escalated_at', 'id']
        verbose_name = _('alarm escalation')
        verbose_name_plural = _('alarm escalations')
        constraints = [
            models.UniqueConstraint(fields=['alarm', 'level'], name='uq_alarm_escalations_level'),
            models.CheckConstraint(condition=Q(level__gte=1, level__lte=MAX_LEVEL), name='chk_alarm_escalations_level'),
        ]

    def __str__(self):
        return f'{self.alarm} → {self.level}'


class Acknowledgement(models.Model):
    """A person said they saw an alarm: when, from which device (the id the app sends; empty from the console) and app
    ('console' from the web pages; the app's name and version later), and the notification they answered, if any. Once
    per person and alarm; the first one stops the escalation. `user` is empty only on an acknowledgement carried over
    from the sensors' page whose person's account had been removed."""

    id = models.BigAutoField(primary_key=True)
    alarm = models.ForeignKey(Alarm, on_delete=models.PROTECT, related_name='acknowledgements', verbose_name=_('Alarm'))
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                             related_name='alarm_acknowledgements', verbose_name=_('Acknowledged by'))
    acknowledged_at = models.DateTimeField(_('Acknowledged at'))
    device = models.CharField(_('Device'), max_length=100, blank=True)
    app = models.CharField(_('App'), max_length=100)
    notification = models.ForeignKey(Notification, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name='acknowledgements', verbose_name=_('Notification answered'))

    class Meta:
        db_table = 'alarm_acknowledgements'
        ordering = ['acknowledged_at', 'id']
        verbose_name = _('alarm acknowledgement')
        verbose_name_plural = _('alarm acknowledgements')
        constraints = [
            models.UniqueConstraint(fields=['alarm', 'user'], name='uq_alarm_acknowledgements_once'),
            models.CheckConstraint(condition=~Q(app=''), name='chk_alarm_acknowledgements_app'),
        ]

    def __str__(self):
        return f'{self.alarm} · {self.user or "—"} · {self.acknowledged_at:%Y-%m-%d %H:%M}'

    @property
    def delay(self):
        """How long after the alarm opened it was acknowledged."""
        return self.acknowledged_at - self.alarm.opened_at


# The tables a database trigger keeps append-only (migration 0001).
APPEND_ONLY = ('alarms', 'alarm_clearances', 'alarm_notifications', 'alarm_delivery_attempts', 'alarm_escalations',
               'alarm_acknowledgements')
