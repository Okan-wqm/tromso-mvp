from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from core.models import CODE, CODE_MESSAGE, AuditedModel, CodedMixin
from farm.models import Equipment, Site

from .connection import Connection
from .credential import Credential
from .format import PayloadFormat

INTERVAL_MIN, INTERVAL_MAX = 1, 86400
# A topic a device publishes on: no '#', not a system topic ('$...'), at most one '+' and only as a whole level.
TOPIC_RULES = (
    (~Q(topic=''), 'chk_sensors_device_topic_given', _('Give the topic the device publishes on.')),
    (~Q(topic__contains='#'), 'chk_sensors_device_topic_hash', _('A device’s topic has no “#”.')),
    (~Q(topic__startswith='$'), 'chk_sensors_device_topic_system', _('A topic starting with “$” is the broker’s own.')),
    (~Q(topic__regex=r'\+.*\+'), 'chk_sensors_device_topic_plus', _('A topic has at most one “+”.')),
    (~Q(topic__contains='+') | Q(topic__regex=r'(^|/)\+(/|$)'), 'chk_sensors_device_topic_level',
     _('A “+” stands for a whole level of the topic, between slashes.')),
)


class Device(CodedMixin, AuditedModel):
    """A field device that publishes on one topic of a connection: a probe, a PLC, a gateway for one instrument. Its
    channels are the values it sends. The topic may hold one '+' (a level the device fills, e.g. its serial number);
    the device is still this row. A device belongs to a site; it may be the instrument a piece of equipment lists, and
    then a deleted piece of equipment leaves the device in place, its history kept. A device that sends nothing for
    three times its expected interval is offline."""

    connection = models.ForeignKey(Connection, on_delete=models.CASCADE, related_name='devices',
                                   verbose_name=_('Connection'))
    payload_format = models.ForeignKey(PayloadFormat, on_delete=models.PROTECT, related_name='devices',
                                       verbose_name=_('Payload format'))
    credential = models.ForeignKey(Credential, null=True, blank=True, on_delete=models.PROTECT, related_name='devices',
                                   verbose_name=_('Credential'))
    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name='sensor_devices', verbose_name=_('Site'))
    equipment = models.ForeignKey(Equipment, null=True, blank=True, on_delete=models.DO_NOTHING,
                                  related_name='sensor_devices', verbose_name=_('Equipment'))
    code = models.CharField(_('Code'), max_length=60, validators=[RegexValidator(CODE, CODE_MESSAGE)])
    name = models.CharField(_('Name'), max_length=100)
    topic = models.CharField(_('Topic'), max_length=255)
    expected_interval_s = models.PositiveIntegerField(
        _('Sends every (seconds)'), validators=[MinValueValidator(INTERVAL_MIN), MaxValueValidator(INTERVAL_MAX)])
    manufacturer = models.CharField(_('Manufacturer'), max_length=100, blank=True)
    model = models.CharField(_('Model'), max_length=100, blank=True)
    note = models.TextField(_('Note'), blank=True)
    is_active = models.BooleanField(_('Active'), default=True)

    kept_note = _('They stay, out of sight while it is deleted, and come back when it is restored.')

    class Meta:
        db_table = 'sensors_device'
        ordering = ['code']
        verbose_name = _('device')
        verbose_name_plural = _('devices')
        constraints = [
            models.UniqueConstraint('connection', Lower('code'), condition=Q(is_deleted=False),
                                    name='uq_sensors_device_code_live',
                                    violation_error_message=_('Another device of this connection has this code.')),
            models.UniqueConstraint('connection', 'topic', condition=Q(is_deleted=False),
                                    name='uq_sensors_device_topic_live',
                                    violation_error_message=_('Another device of this connection publishes on this topic.')),
            models.CheckConstraint(condition=Q(code__regex=CODE), name='chk_sensors_device_code',
                                   violation_error_message=CODE_MESSAGE),
            models.CheckConstraint(condition=~Q(name=''), name='chk_sensors_device_name',
                                   violation_error_message=_('Give the device a name.')),
            models.CheckConstraint(condition=Q(expected_interval_s__gte=INTERVAL_MIN, expected_interval_s__lte=INTERVAL_MAX),
                                   name='chk_sensors_device_interval',
                                   violation_error_message=_('From 1 second to 1 day (86400 seconds).')),
            *[models.CheckConstraint(condition=condition, name=name, violation_error_message=message)
              for condition, name, message in TOPIC_RULES],
        ]

    def __str__(self):
        return f'{self.name} ({self.code})'
