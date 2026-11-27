from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import ExpressionWrapper, F, Func, Q, Value
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import CODE, CODE_MESSAGE, AuditedModel, CodedMixin, SealedManager
from farm.models.water import NBS, PH_SCALE_CHOICES
from farm.water.parameters import PH

from .. import quantities
from .device import Device
from .format import POINTER

HEARTBEAT_MIN, HEARTBEAT_MAX = 10, 86400
# How many heartbeats without a good value before a channel's value is no longer fresh is the channel's own
# `fresh_heartbeats` (the user's, cross review F10; 3 is the value the code held): at least one, at most twenty.
FRESH_HEARTBEATS_BOUNDS = (1, 20)
INF = float('inf')
# The sequence channel numbers are drawn from (migration 0001): never reused, so a number names one channel for ever,
# its readings included.
CHANNEL_NO_SEQUENCE = 'sensors_channel_no_seq'


class Protocol(models.TextChoices):
    MQTT = 'mqtt', _('MQTT')
    MODBUS_TCP = 'modbus_tcp', _('Modbus TCP')
    MODBUS_RTU = 'modbus_rtu', _('Modbus RTU')
    OPCUA = 'opcua', _('OPC UA')
    S7 = 's7', _('Siemens S7')
    OTHER = 'other', _('Other')


# The keys a channel's `address` must have for each protocol (a PLC program will be generated from it later); MQTT and
# other: free.
ADDRESS_KEYS = {
    Protocol.MODBUS_TCP: ('unit_id', 'function', 'register'),
    Protocol.MODBUS_RTU: ('unit_id', 'function', 'register'),
    Protocol.S7: ('db', 'offset'),
    Protocol.OPCUA: ('node_id',),
}


class Reduction(models.TextChoices):
    ALL = quantities.ALL, _('Store every value')
    DEADBAND = quantities.DEADBAND, _('Store a value when it moves past the deadband')


class ChannelStatus(models.TextChoices):
    ACTIVE = 'active', _('Active')
    MAINTENANCE = 'maintenance', _('Maintenance')
    RETIRED = 'retired', _('Retired')


def finite(name):
    """The value is a real number: not NaN and not infinite (PostgreSQL's float8 holds both)."""
    return Q(**{f'{name}__lt': INF, f'{name}__gt': -INF})


def _address_rule():
    condition = ~Q(address_protocol__in=list(ADDRESS_KEYS))
    for protocol, keys in ADDRESS_KEYS.items():
        condition |= Q(address_protocol=protocol, address__has_keys=list(keys))
    return condition


class Channel(CodedMixin, AuditedModel):
    """One value a device sends: what it measures (a quantity of sensors/quantities.py), where it is in the message (a
    JSON pointer in an object, or the item's name in a list), the conversion from the instrument's unit to the
    quantity's (`unit_factor`, `unit_offset`; calibration is applied first), and how it is stored: every value, or a
    value when it moves past the deadband, and at least once per heartbeat. Its `channel_no`, drawn from a sequence and
    never reused, is the key its readings are stored under. A value is fresh for its `fresh_heartbeats` heartbeats (`fresh_s`).

    In maintenance its values are stored flagged and used nowhere; retired, the ingest ignores it. Deleting it keeps its
    readings (they are history)."""

    channel_no = models.IntegerField(
        _('Channel number'), unique=True, editable=False,
        db_default=Func(Value(CHANNEL_NO_SEQUENCE), function='nextval', output_field=models.IntegerField()))
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='channels', verbose_name=_('Device'))
    code = models.CharField(_('Code'), max_length=60, validators=[RegexValidator(CODE, CODE_MESSAGE)])
    name = models.CharField(_('Name'), max_length=100)
    quantity = models.CharField(_('Quantity'), max_length=30, choices=quantities.CHOICES)
    is_water = models.GeneratedField(
        expression=ExpressionWrapper(Q(quantity__in=quantities.WATER_CODES), output_field=models.BooleanField()),
        output_field=models.BooleanField(), db_persist=True, verbose_name=_('Water quantity'))
    unit = models.CharField(_('Instrument unit'), max_length=20, blank=True)
    unit_factor = models.FloatField(_('Unit factor'), default=1.0)
    unit_offset = models.FloatField(_('Unit offset'), default=0.0)
    value_path = models.CharField(_('Value path'), max_length=200, blank=True)
    item_name = models.CharField(_('Item name'), max_length=200, blank=True)
    address_protocol = models.CharField(_('Protocol'), max_length=20, choices=Protocol.choices, default=Protocol.MQTT)
    address = models.JSONField(_('Address'), default=dict, blank=True)
    reduction = models.CharField(_('Storing'), max_length=10, choices=Reduction.choices, default=Reduction.DEADBAND)
    deadband = models.FloatField(_('Deadband'), default=0.0, validators=[MinValueValidator(0)])
    heartbeat_s = models.PositiveIntegerField(
        _('Heartbeat (seconds)'), validators=[MinValueValidator(HEARTBEAT_MIN), MaxValueValidator(HEARTBEAT_MAX)])
    fresh_heartbeats = models.PositiveSmallIntegerField(
        _('Fresh for (heartbeats)'), default=3,
        validators=[MinValueValidator(FRESH_HEARTBEATS_BOUNDS[0]), MaxValueValidator(FRESH_HEARTBEATS_BOUNDS[1])],
        help_text=_('How many heartbeats a value stays fresh without a new one; then the place shows no recent data.'))
    fresh_s = models.GeneratedField(expression=F('heartbeat_s') * F('fresh_heartbeats'), output_field=models.IntegerField(),
                                    db_persist=True, verbose_name=_('Fresh for (seconds)'))
    range_min = models.FloatField(_('Range from'), null=True, blank=True)
    range_max = models.FloatField(_('Range to'), null=True, blank=True)
    state = models.CharField(_('State'), max_length=12, choices=ChannelStatus.choices, default=ChannelStatus.ACTIVE)
    note = models.TextField(_('Note'), blank=True)
    # A pH channel's scale (owner decision 1 of 2026-11-17; the water-chemistry audit of 2026-11-19, F1): what its
    # probe's calibration puts its values on. Stored as sent; put on the NBS scale where the water is read
    # (farm/water/read.py Context.sensor_ph). NBS for every other quantity.
    ph_scale = models.CharField(_('Scale the pH is measured on'), max_length=5, choices=PH_SCALE_CHOICES, default=NBS, db_default=NBS)
    # When the channel's pH scale was last changed (`save`): its values from before are on a scale not known any more
    # and are used nowhere. None: the scale holds since the channel was made.
    ph_scale_from = models.DateTimeField(_('When the pH scale was changed'), null=True, blank=True, editable=False)

    class Meta:
        db_table = 'sensors_channel'
        ordering = ['device__code', 'code']
        verbose_name = _('channel')
        verbose_name_plural = _('channels')
        constraints = [
            models.UniqueConstraint('device', Lower('code'), condition=Q(is_deleted=False), name='uq_sensors_channel_code_live',
                                    violation_error_message=_('Another channel of this device has this code.')),
            models.CheckConstraint(condition=Q(code__regex=CODE), name='chk_sensors_channel_code',
                                   violation_error_message=CODE_MESSAGE),
            models.CheckConstraint(condition=~Q(name=''), name='chk_sensors_channel_name',
                                   violation_error_message=_('Give the channel a name.')),
            models.CheckConstraint(condition=Q(quantity__in=quantities.CODES), name='chk_sensors_channel_quantity'),
            models.CheckConstraint(condition=~Q(unit_factor=0) & finite('unit_factor'), name='chk_sensors_channel_unit_factor',
                                   violation_error_message=_('The unit factor is a number other than 0.')),
            models.CheckConstraint(condition=finite('unit_offset'), name='chk_sensors_channel_unit_offset'),
            models.CheckConstraint(condition=Q(fresh_heartbeats__gte=FRESH_HEARTBEATS_BOUNDS[0],
                                               fresh_heartbeats__lte=FRESH_HEARTBEATS_BOUNDS[1]),
                                   name='chk_sensors_channel_fresh_heartbeats'),
            models.CheckConstraint(condition=(Q(value_path='') & ~Q(item_name='')) | (~Q(value_path='') & Q(item_name='')),
                                   name='chk_sensors_channel_source',
                                   violation_error_message=_('Give either the value’s path or the item’s name, one of the two.')),
            models.CheckConstraint(condition=Q(value_path__regex=POINTER), name='chk_sensors_channel_value_path',
                                   violation_error_message=_('A JSON pointer: empty, or starting with “/”.')),
            models.CheckConstraint(condition=Q(address_protocol__in=Protocol.values), name='chk_sensors_channel_protocol'),
            models.CheckConstraint(condition=_address_rule(), name='chk_sensors_channel_address',
                                   violation_error_message=_('The address lacks a key its protocol needs.')),
            models.CheckConstraint(condition=Q(reduction__in=Reduction.values), name='chk_sensors_channel_reduction'),
            models.CheckConstraint(condition=Q(deadband__gte=0) & finite('deadband') & (Q(reduction=Reduction.ALL) | Q(deadband__gt=0)),
                                   name='chk_sensors_channel_deadband',
                                   violation_error_message=_('A deadband above 0, unless every value is stored.')),
            models.CheckConstraint(condition=Q(heartbeat_s__gte=HEARTBEAT_MIN, heartbeat_s__lte=HEARTBEAT_MAX),
                                   name='chk_sensors_channel_heartbeat',
                                   violation_error_message=_('A heartbeat from 10 seconds to 1 day (86400 seconds).')),
            models.CheckConstraint(
                condition=Q(range_min__isnull=True, range_max__isnull=True)
                | (Q(range_min__isnull=False, range_max__isnull=False, range_min__lt=F('range_max'))
                   & finite('range_min') & finite('range_max')),
                name='chk_sensors_channel_range',
                violation_error_message=_('Give both ends of the range, the first below the second, or neither.')),
            models.CheckConstraint(condition=Q(state__in=ChannelStatus.values), name='chk_sensors_channel_state'),
            models.CheckConstraint(
                condition=Q(ph_scale__in=[code for code, _label in PH_SCALE_CHOICES])
                & (Q(quantity=PH) | Q(ph_scale=NBS, ph_scale_from__isnull=True)),
                name='chk_sensors_channel_ph_scale',
                violation_error_message=_('Only a pH channel has a pH scale other than NBS.')),
        ]

    def __str__(self):
        return f'{self.device.code} › {self.code}'

    def save(self, *args, **kwargs):
        """Saved with the moment its pH scale changed (`ph_scale_from`), whichever door it is saved through: the values
        its probe measured before are on the old scale, which a value does not carry, so they are used nowhere after
        (farm/water/read.py)."""
        if not self._state.adding and self.quantity == PH:
            stored = type(self).all_objects.filter(pk=self.pk).values_list('ph_scale', flat=True).first()
            if stored is not None and stored != self.ph_scale:
                self.ph_scale_from = timezone.now()
                if kwargs.get('update_fields') is not None:
                    kwargs['update_fields'] = {*kwargs['update_fields'], 'ph_scale_from'}
        super().save(*args, **kwargs)

    @property
    def ph_scale_said(self):
        """A pH channel's scale as the pages say it ('' for any other channel)."""
        return self.get_ph_scale_display() if self.quantity == PH else ''

    @property
    def quantity_info(self):
        return quantities.get(self.quantity)


class Calibration(models.Model):
    """A channel's calibration from a moment on: value = gain × raw + offset, applied by the ingest at the device time of
    each value, before the unit conversion. Stored values are calibrated; a later calibration never rewrites them. The
    rows are edited as one list on the channel's Calibration tab (logged on the channel); the earliest one also covers
    the time before it, so a channel with a calibration is never read uncalibrated."""

    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name='calibrations',
                                verbose_name=_('Channel'))
    valid_from = models.DateTimeField(_('From'))
    gain = models.FloatField(_('Gain'), default=1.0)
    offset = models.FloatField(_('Offset'), default=0.0)
    performed_by = models.CharField(_('Calibrated by'), max_length=100, blank=True)
    note = models.CharField(_('Note'), max_length=300, blank=True)
    created_at = models.DateTimeField(_('Created at'), auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+', verbose_name=_('Created by'))

    objects = SealedManager()

    class Meta:
        db_table = 'sensors_calibration'
        ordering = ['valid_from']
        verbose_name = _('calibration')
        verbose_name_plural = _('calibrations')
        constraints = [
            models.UniqueConstraint(fields=['channel', 'valid_from'], name='uq_sensors_calibration_from',
                                    violation_error_message=_('The channel already has a calibration from this moment.')),
            models.CheckConstraint(condition=~Q(gain=0) & finite('gain'), name='chk_sensors_calibration_gain',
                                   violation_error_message=_('The gain is a number other than 0.')),
            models.CheckConstraint(condition=finite('offset'), name='chk_sensors_calibration_offset'),
        ]

    def __str__(self):
        return f'{self.valid_from:%Y-%m-%d %H:%M}: × {self.gain} + {self.offset}'
