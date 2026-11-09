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
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext, gettext_lazy as _

from core.models import AuditedModel
from farm.models import ProductionDepartment, SamplingPoint, Site
from farm.water.parameters import LIMIT_CHOICES
from sensors.models import AlarmEvent
from sensors.models.alarm import Severity

# How serious a severity is, for "at least" (a rule's least severity).
RANK = {Severity.WARNING: 1, Severity.CRITICAL: 2}
LEVEL_BOUNDS = (0, 9)                       # level 0 is notified first; nine escalations at most
MAX_LEVEL = LEVEL_BOUNDS[1]


class Source(models.TextChoices):
    SENSOR_RULE = 'sensor_rule', _('Sensor alarm rule')
    WATER_LIMIT = 'water_limit', _('Water limit')
    SYSTEM = 'system', _('The alarm system itself')


class Channel(models.TextChoices):
    """How a notification reaches a person. Push first (the mobile app); a channel joins here and in
    settings.ALARM_TRANSPORTS (alarms/transports.py). There is no e-mail: it gets too little attention for an alarm."""
    PUSH = 'push', _('Push')


class ClearCause(models.TextChoices):
    RETURNED = 'returned', _('Back inside the limit')
    EVENT_CLOSED = 'event_closed', _('The sensor rule no longer holds')
    STRUCTURAL = 'structural', _('No longer judged (no fish or no limit)')
    RESTORED = 'restored', _('Restored')


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
                | (Q(source=Source.WATER_LIMIT, sensor_event__isnull=True, point__isnull=False) & ~Q(parameter=''))
                | (Q(source=Source.SYSTEM, sensor_event__isnull=True, point__isnull=True) & ~Q(parameter='')),
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
    cause = models.CharField(_('Why'), max_length=12, choices=ClearCause.choices, default=ClearCause.RETURNED)

    class Meta:
        db_table = 'alarm_clearances'
        verbose_name = _('alarm clearance')
        verbose_name_plural = _('alarm clearances')
        constraints = [models.CheckConstraint(condition=Q(cause__in=ClearCause.values), name='chk_alarm_clearances_cause')]

    def __str__(self):
        return f'{self.alarm} · {self.cleared_at:%Y-%m-%d %H:%M}'


class AlarmSubjectState(models.Model):
    """The one mutable row of an alarm subject (a unit's parameter at a level: `water:<point>:<slot>:<severity>`): the
    timers of its lifecycle, kept in the database so a restart loses none: since when the condition holds without an
    alarm yet (the on-delay, counted from the first offending value's time), since when it is over while the alarm is open
    (the off-delay), the time of the last value that held it, and the alarm open now. Not history: the alarms, their
    clearances and the activity log are."""

    key = models.CharField(primary_key=True, max_length=200)
    # Unique: an alarm is the open alarm of one subject at most; a raise sets it only where it is empty
    # (alarms.services.raise_for), so one subject never has two open alarms (alarm plan, defect 6).
    open_alarm = models.OneToOneField(Alarm, null=True, blank=True, on_delete=models.PROTECT, related_name='+',
                                      verbose_name=_('Open alarm'))
    pending_since = models.DateTimeField(null=True, blank=True)
    clear_since = models.DateTimeField(null=True, blank=True)
    last_bad_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'alarm_subject_state'
        verbose_name = _('alarm subject state')
        verbose_name_plural = _('alarm subject states')

    def __str__(self):
        return self.key


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


# ---- the rules: the user's reference data (owner, alarm plan §7c) ---------------------------------------------------
# What a row may hold, the database's refusal of nonsense; the values themselves are the user's (seeded by migration 0002
# with the owner's defaults, alarm plan §7a).
DELAY_BOUNDS = (0, 3600)            # seconds
ESCALATION_BOUNDS = (1, 1440)       # minutes
ATTEMPTS_BOUNDS = (1, 20)


class SeverityPolicy(AuditedModel):
    """How an alarm of a severity behaves, one row per severity (a person with the right edits them, every change logged):
    how long a condition must hold before the alarm is raised and how long it must be over before it clears (in data
    time, so a restart loses nothing), how long a level waits for an acknowledgement before the next level is notified,
    and how many times a failing transport is tried with one notification."""

    severity = models.CharField(_('Severity'), max_length=10, choices=Severity.choices, editable=False)
    on_delay_seconds = models.PositiveIntegerField(
        _('Raise after (seconds)'), validators=[MinValueValidator(DELAY_BOUNDS[0]), MaxValueValidator(DELAY_BOUNDS[1])])
    off_delay_seconds = models.PositiveIntegerField(
        _('Clear after (seconds)'), validators=[MinValueValidator(DELAY_BOUNDS[0]), MaxValueValidator(DELAY_BOUNDS[1])])
    escalation_minutes = models.PositiveIntegerField(
        _('Escalate after (minutes)'),
        validators=[MinValueValidator(ESCALATION_BOUNDS[0]), MaxValueValidator(ESCALATION_BOUNDS[1])])
    delivery_attempts = models.PositiveIntegerField(
        _('Delivery attempts'), validators=[MinValueValidator(ATTEMPTS_BOUNDS[0]), MaxValueValidator(ATTEMPTS_BOUNDS[1])])

    class Meta:
        db_table = 'alarm_severity_policies'
        ordering = ['severity']
        verbose_name = _('alarm severity rule')
        verbose_name_plural = _('alarm severity rules')
        constraints = [
            models.UniqueConstraint(fields=['severity'], name='uq_alarm_severity_policies_severity'),
            models.CheckConstraint(condition=Q(severity__in=Severity.values), name='chk_alarm_severity_policies_severity'),
            models.CheckConstraint(condition=Q(on_delay_seconds__gte=DELAY_BOUNDS[0], on_delay_seconds__lte=DELAY_BOUNDS[1],
                                               off_delay_seconds__gte=DELAY_BOUNDS[0],
                                               off_delay_seconds__lte=DELAY_BOUNDS[1]),
                                   name='chk_alarm_severity_policies_delays'),
            models.CheckConstraint(condition=Q(escalation_minutes__gte=ESCALATION_BOUNDS[0],
                                               escalation_minutes__lte=ESCALATION_BOUNDS[1]),
                                   name='chk_alarm_severity_policies_escalation'),
            models.CheckConstraint(condition=Q(delivery_attempts__gte=ATTEMPTS_BOUNDS[0],
                                               delivery_attempts__lte=ATTEMPTS_BOUNDS[1]),
                                   name='chk_alarm_severity_policies_attempts'),
            # A severity's rule is never deleted (cross review F6): it is changed. A database trigger refuses DELETE too
            # (migration 0006); a row lost all the same is the evaluation's to survive (alarms/rules.py).
            models.CheckConstraint(condition=Q(is_deleted=False), name='chk_alarm_severity_policies_kept'),
        ]

    def __str__(self):
        return str(self.get_severity_display())

    def soft_delete(self, user):
        raise ValidationError(_('A severity’s alarm rule is changed, never deleted: the alarms of that severity need it.'))

    def mark_deleted(self, user, at):
        self.soft_delete(user)

    def delete(self, *args, **kwargs):
        self.soft_delete(None)


class ParameterDeadband(AuditedModel):
    """How far past its limit a water value must come back before an alarm on it clears (in the parameter's unit), so a
    value at the limit does not raise and clear over and over: the limit is judged on the value moved by the deadband
    toward danger, by the same judgement (farm/water/evaluate.py). A parameter without a row has none."""

    parameter = models.CharField(_('Parameter'), max_length=30, choices=LIMIT_CHOICES)
    deadband = models.DecimalField(_('Deadband'), max_digits=8, decimal_places=4)

    class Meta:
        db_table = 'alarm_deadbands'
        ordering = ['parameter']
        verbose_name = _('alarm deadband')
        verbose_name_plural = _('alarm deadbands')
        constraints = [
            models.UniqueConstraint(fields=['parameter'], condition=Q(is_deleted=False),
                                    name='uq_alarm_deadbands_parameter_live',
                                    violation_error_message=_('This parameter has a deadband already.')),
            models.CheckConstraint(condition=Q(parameter__in=[code for code, _label in LIMIT_CHOICES]),
                                   name='chk_alarm_deadbands_parameter'),
            models.CheckConstraint(condition=Q(deadband__gte=0), name='chk_alarm_deadbands_not_negative',
                                   violation_error_message=_('A deadband is not negative.')),
        ]

    def __str__(self):
        return str(self.get_parameter_display())

    def clean(self):
        super().clean()
        from farm.water import parameters
        if self.parameter in parameters.BY_CODE and self.deadband is not None:
            measure = parameters.get(self.parameter)
            if self.deadband > measure.high - measure.low:
                raise ValidationError({'deadband': _('Wider than the parameter’s whole range.')})


# The tables a database trigger keeps append-only (migration 0001).
APPEND_ONLY = ('alarms', 'alarm_clearances', 'alarm_notifications', 'alarm_delivery_attempts', 'alarm_escalations',
               'alarm_acknowledgements')
