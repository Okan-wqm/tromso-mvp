from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from core.models import AuditedModel

# A JSON pointer (RFC 6901): empty, or '/' and the keys.
POINTER = r'^(/([^~]|~[01])*)*$'


class Encoding(models.TextChoices):
    JSON = 'json', _('JSON')


class Shape(models.TextChoices):
    OBJECT = 'object', _('One object, a value per channel at its own path')
    ARRAY = 'array', _('A list of items, each naming its channel')


class TimeUnit(models.TextChoices):
    ISO8601 = 'iso8601', _('ISO 8601 text')
    EPOCH_S = 'epoch_s', _('Seconds since 1970')
    EPOCH_MS = 'epoch_ms', _('Milliseconds since 1970')


class PayloadFormat(AuditedModel):
    """How the messages of a kind of device are written: one row shared by every device that writes the same way (a
    vendor's probes). The ingest service decodes a message by it: where the device time is and how it is written (no
    path: the receive time is used and the reading is flagged), where the sequence number is, and whether the message is
    one object with a value per channel or a list of items that each name their channel. Paths are JSON pointers."""

    name = models.CharField(_('Name'), max_length=100)
    encoding = models.CharField(_('Encoding'), max_length=10, choices=Encoding.choices, default=Encoding.JSON)
    shape = models.CharField(_('Shape'), max_length=10, choices=Shape.choices, default=Shape.OBJECT)
    time_path = models.CharField(_('Time path'), max_length=200, blank=True)
    time_unit = models.CharField(_('Time is written as'), max_length=10, choices=TimeUnit.choices,
                                 default=TimeUnit.ISO8601)
    seq_path = models.CharField(_('Sequence path'), max_length=200, blank=True)
    items_path = models.CharField(_('Items path'), max_length=200, blank=True)
    name_key = models.CharField(_('Name key'), max_length=100, blank=True)
    value_key = models.CharField(_('Value key'), max_length=100, blank=True)

    class Meta:
        db_table = 'sensors_payload_format'
        ordering = ['name']
        verbose_name = _('payload format')
        verbose_name_plural = _('payload formats')
        constraints = [
            models.UniqueConstraint(Lower('name'), condition=Q(is_deleted=False), name='uq_sensors_payload_format_name_live',
                                    violation_error_message=_('Another payload format already has this name.')),
            models.CheckConstraint(condition=~Q(name=''), name='chk_sensors_payload_format_name',
                                   violation_error_message=_('Give the format a name.')),
            models.CheckConstraint(condition=Q(encoding__in=Encoding.values), name='chk_sensors_payload_format_encoding'),
            models.CheckConstraint(condition=Q(shape__in=Shape.values), name='chk_sensors_payload_format_shape'),
            models.CheckConstraint(condition=Q(time_unit__in=TimeUnit.values), name='chk_sensors_payload_format_time_unit'),
            models.CheckConstraint(
                condition=Q(shape=Shape.OBJECT) | (~Q(name_key='') & ~Q(value_key='')),
                name='chk_sensors_payload_format_array_keys',
                violation_error_message=_('A list of items needs the key that names the channel and the key of the value.')),
            *[models.CheckConstraint(condition=Q(**{f'{path}__regex': POINTER}), name=f'chk_sensors_payload_format_{path}',
                                     violation_error_message=_('A JSON pointer: empty, or starting with “/”.'))
              for path in ('time_path', 'seq_path', 'items_path')],
        ]

    def __str__(self):
        return self.name
