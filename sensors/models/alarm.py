from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from core.models import AuditedModel, SealedManager

from .. import quantities
from .channel import Channel, finite


class AlarmKind(models.TextChoices):
    NO_DATA = 'no_data', _('No fresh value')
    DEVICE_OFFLINE = 'device_offline', _('Device offline')
    HIGH = 'high', _('Above')
    LOW = 'low', _('Below')
    RATE = 'rate', _('Changes faster than')


class Severity(models.TextChoices):
    WARNING = 'warning', _('Warning')
    CRITICAL = 'critical', _('Critical')


THRESHOLD_KINDS = (AlarmKind.HIGH, AlarmKind.LOW, AlarmKind.RATE)


class AlarmRule(AuditedModel):
    """When a channel needs a look: no fresh value, its device offline, above or below a threshold for a time, or a change
    faster than a rate over a time. On one channel, or on every channel of a quantity. Its events become alarms (Company ›
    Alarms, the alarms app), whose recipient rules say who is notified. A high or low rule on a water quantity is refused: the
    water limits of the species judge those (Water limits)."""

    channel = models.ForeignKey(Channel, null=True, blank=True, on_delete=models.CASCADE, related_name='alarm_rules',
                                verbose_name=_('Channel'))
    quantity = models.CharField(_('Every channel of'), max_length=30, choices=quantities.CHOICES, blank=True)
    kind = models.CharField(_('When'), max_length=20, choices=AlarmKind.choices)
    threshold = models.FloatField(_('Threshold'), null=True, blank=True)
    for_s = models.PositiveIntegerField(_('For (seconds)'), default=0)
    hysteresis = models.FloatField(_('Hysteresis'), default=0.0)
    severity = models.CharField(_('Severity'), max_length=10, choices=Severity.choices, default=Severity.WARNING)
    is_active = models.BooleanField(_('Active'), default=True)

    class Meta:
        db_table = 'sensors_alarm_rule'
        ordering = ['kind']
        verbose_name = _('alarm rule')
        verbose_name_plural = _('alarm rules')
        constraints = [
            models.CheckConstraint(condition=(Q(channel__isnull=False) & Q(quantity='')) | (Q(channel__isnull=True) & ~Q(quantity='')),
                                   name='chk_sensors_alarm_rule_scope',
                                   violation_error_message=_('A rule is on one channel or on every channel of a quantity.')),
            models.CheckConstraint(condition=Q(kind__in=AlarmKind.values), name='chk_sensors_alarm_rule_kind'),
            models.CheckConstraint(condition=Q(severity__in=Severity.values), name='chk_sensors_alarm_rule_severity'),
            models.CheckConstraint(condition=Q(quantity='') | Q(quantity__in=quantities.CODES),
                                   name='chk_sensors_alarm_rule_quantity'),
            models.CheckConstraint(
                condition=~Q(kind__in=THRESHOLD_KINDS) | (Q(threshold__isnull=False) & finite('threshold')),
                name='chk_sensors_alarm_rule_threshold',
                violation_error_message=_('Above, below and a rate need a threshold.')),
            models.CheckConstraint(condition=Q(for_s__gte=0, hysteresis__gte=0) & finite('hysteresis'),
                                   name='chk_sensors_alarm_rule_numbers'),
        ]

    def __str__(self):
        scope = str(self.channel) if self.channel_id else quantities.get(self.quantity).label
        return f'{scope}: {self.get_kind_display()}'

    @property
    def quantity_code(self):
        return self.channel.quantity if self.channel_id else self.quantity

    def clean(self):
        super().clean()
        code = self.quantity_code
        if self.kind in (AlarmKind.HIGH, AlarmKind.LOW) and code in quantities.WATER_CODES:
            raise ValidationError({'kind': _('The water limits judge a water value above or below: set them on the Water '
                                             'limits page, for the species.')})


class AlarmEvent(models.Model):
    """A time a rule held for a channel: when it opened and closed and the furthest value it reached. At most one open
    event per rule and channel. Written by the sensors' check (sensors/alarms.py); each event is an alarm of the alarms app
    (alarms.Alarm.sensor_event), which keeps who was notified and who acknowledged it.
    It belongs to the place the channel was bound to when it opened (`binding`): a move or taking the device out of the
    water closes it then (sensors/bindings.py), and a site's events are its places' (sensors/alarms.py `open_events`)."""

    rule = models.ForeignKey(AlarmRule, on_delete=models.CASCADE, related_name='events', verbose_name=_('Rule'))
    channel_no = models.IntegerField(_('Channel number'))
    binding = models.ForeignKey('sensors.Binding', null=True, blank=True, on_delete=models.SET_NULL,
                                related_name='alarm_events', verbose_name=_('Place (binding)'))
    opened_at = models.DateTimeField(_('Opened at'))
    closed_at = models.DateTimeField(_('Closed at'), null=True, blank=True)
    peak = models.FloatField(_('Furthest value'), null=True, blank=True)

    objects = SealedManager()

    class Meta:
        db_table = 'sensors_alarm_event'
        ordering = ['-opened_at']
        verbose_name = _('alarm event')
        verbose_name_plural = _('alarm events')
        constraints = [
            models.UniqueConstraint(fields=['rule', 'channel_no'], condition=Q(closed_at__isnull=True),
                                    name='uq_sensors_alarm_event_open'),
            models.CheckConstraint(condition=Q(closed_at__isnull=True) | Q(closed_at__gte=models.F('opened_at')),
                                   name='chk_sensors_alarm_event_period'),
        ]

    def __str__(self):
        return f'{self.rule} #{self.channel_no} {self.opened_at:%Y-%m-%d %H:%M}'
