"""Water chemistry: the samples people take (Operations › Water chemistry) and the owner's limits per
species (Setup › Reference data › Water limits). Which parameters there are, with their units and
plausible ranges, is farm/water/parameters.py; how a value is judged is farm/water/evaluate.py, on read;
where a sample was taken is its sampling point (farm/models/water_point.py)."""
from functools import reduce
from operator import or_

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Round
from django.utils.translation import gettext, gettext_lazy as _

from core.models import ActiveManager, AuditedModel

from ..water import parameters
from ..water.evaluate import ANY_WATER
from ..water.parameters import COLUMNS, LIMIT_CHOICES, LIMITED, MEASURED
from .species import Species
from .tank import WaterType
from .water_point import SamplingPoint, live_owner, local_time


class Source(models.TextChoices):
    MANUAL = 'manual', _('Meter or test kit')
    LAB = 'lab', _('Laboratory')


# The samples of live points of live owners. A deleted unit, system or piece of equipment keeps its points, and
# a point its samples, out of sight, and they come back with the owner when it is restored (core.softdelete:
# the links keep them, DO_NOTHING).
LIVE_POINT = Q(point__is_deleted=False) & live_owner('point__')


class SampleManager(ActiveManager):
    """Live samples of live points of live owners (LIVE_POINT); a voided sample is out, as a deleted record is."""

    def get_queryset(self):
        return super().get_queryset().filter(LIVE_POINT)


def _any(conditions):
    return reduce(or_, conditions)


def _sample_checks():
    checks = [
        models.CheckConstraint(condition=_any(Q(**{f'{column}__isnull': False}) for column in COLUMNS),
                               name='chk_water_measurements_any_value',
                               violation_error_message=_('Enter at least one value.')),
        models.CheckConstraint(condition=Q(source__in=Source.values), name='chk_water_measurements_source'),
        models.CheckConstraint(condition=Q(is_deleted=True, void_reason__gt='') | Q(is_deleted=False, void_reason=''),
                               name='chk_water_measurements_void_reason'),
    ]
    for parameter in MEASURED:
        column = parameter.code
        checks.append(models.CheckConstraint(
            condition=Q(**{f'{column}__isnull': True}) | Q(**{f'{column}__gte': parameter.low,
                                                              f'{column}__lte': parameter.high}),
            name=f'chk_water_measurements_{column}'))
    oxygen = Q(oxygen_mg_l__isnull=False) | Q(oxygen_saturation_pct__isnull=False)
    for code, prefix in BASIS.items():
        parameter = parameters.get(code)
        value, source = BASIS_VALUE[code], f'{prefix}_source'
        checks.append(models.CheckConstraint(
            # a basis only beside an oxygen and never beside the sample's own value; its source with it, and in range
            condition=(Q(**{f'{value}__isnull': True, source: '', f'{prefix}_channel__isnull': True,
                            f'{prefix}_at__isnull': True})
                       | (oxygen & Q(**{f'{code}__isnull': True, f'{value}__gte': parameter.low,
                                        f'{value}__lte': parameter.high}) & ~Q(**{source: ''}))),
            name=f'chk_water_measurements_{prefix}'))
    return checks


# What an oxygen entered without its own temperature or salinity is worked out with (second cross review, finding 1):
# the PROVENANCE of the conversion, never a measurement of the sample: read only by the oxygen's conversion
# (farm/water/read.py), never as the point's temperature or salinity.
BASIS = {parameters.TEMPERATURE: 'oxygen_basis_temperature', parameters.SALINITY: 'oxygen_basis_salinity'}
BASIS_VALUE = {parameters.TEMPERATURE: 'oxygen_basis_temperature_c', parameters.SALINITY: 'oxygen_basis_salinity_ppt'}
BASIS_COLUMNS = [*BASIS_VALUE.values(),
                 *(f'{prefix}_{part}' for prefix in BASIS.values() for part in ('source', 'channel', 'at'))]


class BasisSource(models.TextChoices):
    """Where a basis came from: the origins of the water's latest values (read.Origin), or fresh water's 0."""
    MANUAL = 'manual', _('manual')
    LAB = 'lab', _('lab')
    SENSOR = 'sensor', _('sensor')
    SYSTEM_SENSOR = 'system_sensor', _('system sensor')
    FRESH_WATER = 'fresh_water', _('fresh water')


class WaterMeasurement(AuditedModel):
    """A water sample: what a person measured at one sampling point (a place on a unit, on a system's loop or
    on a piece of equipment) at one moment, with a typed column per parameter (empty when not measured). Source
    table: farm.water_quality_measurements.

    One row per sample (wide), not per parameter: each column keeps its own unit, precision and plausible
    range (a database check), and the values worked out from a sample, the un-ionised ammonia and the
    oxygen saturation, need its pH, temperature and salinity of the same moment (farm/water/chemistry.py).
    The source kept the values in a JSONB bag with no basis and no bounds (WQ-03, WQ-07). Nothing about
    the sample's status is stored: it is judged on read against the limits as they are (WQ-21). The fish
    it concerns are not stored either: they are the stock ledger's on that day.

    Never edited: a sample is voided (its soft delete, with a reason) and entered again, as a stock
    operation is. created_by is who recorded it (never a value from the form, WQ-11). The only writer is
    farm/water/services.py.

    The unit, the system or the equipment a sample belongs to is not stored on it: it is the point's owner
    (`point.owner`), so the two can never disagree (the source kept a column for each of a tank, a pond, an
    equipment and a system, WQ-48). A sample has exactly one point, a required foreign key.

    The table is a TimescaleDB hypertable on `measured_at` (migration 0014), so its primary key in the
    database is (id, measured_at) while the model keeps `id`. That has rules:
    - every unique constraint includes `measured_at` (the form's key below does);
    - no foreign key points at this table;
    - an update by id alone (a void) looks in every chunk: cheap at a farm's volume."""

    Source = Source

    # A point keeps its samples (they come back with it, and with its owner): DO_NOTHING, read by SampleManager.
    # No index of its own: the one on (point, -measured_at) serves it.
    point = models.ForeignKey(SamplingPoint, on_delete=models.DO_NOTHING, related_name='samples', db_index=False,
                              verbose_name=_('Sampling point'))
    measured_at = models.DateTimeField(_('Measured at'))
    source = models.CharField(_('Source'), max_length=10, choices=Source.choices)
    temperature_c = parameters.get('temperature_c').field()
    oxygen_mg_l = parameters.get('oxygen_mg_l').field()
    oxygen_saturation_pct = parameters.get('oxygen_saturation_pct').field()
    ph = parameters.get('ph').field()
    alkalinity_mg_l = parameters.get('alkalinity_mg_l').field()
    co2_mg_l = parameters.get('co2_mg_l').field()
    tan_mg_l = parameters.get('tan_mg_l').field()
    nitrite_n_mg_l = parameters.get('nitrite_n_mg_l').field()
    nitrate_n_mg_l = parameters.get('nitrate_n_mg_l').field()
    tgp_pct = parameters.get('tgp_pct').field()
    salinity_ppt = parameters.get('salinity_ppt').field()
    turbidity_ntu = parameters.get('turbidity_ntu').field()
    # The provenance of an oxygen entered without its own temperature or salinity (BASIS): the value the server found
    # fresh at the sample's point and time when it was written (farm/water/read.oxygen_basis), where it came from (the
    # sensor's channel, or the time of the sample it was), and when it was measured; never a measurement of this sample.
    oxygen_basis_temperature_c = models.DecimalField(
        _('Temperature the oxygen is worked out with (°C)'), max_digits=parameters.get('temperature_c').max_digits,
        decimal_places=parameters.get('temperature_c').decimals, null=True, blank=True)
    oxygen_basis_temperature_source = models.CharField(_('Source of the oxygen’s temperature'), max_length=20, blank=True,
                                                       choices=BasisSource.choices)
    oxygen_basis_temperature_channel = models.PositiveIntegerField(_('Sensor channel of the oxygen’s temperature'), null=True, blank=True)
    oxygen_basis_temperature_at = models.DateTimeField(_('When the oxygen’s temperature was measured'), null=True, blank=True)
    oxygen_basis_salinity_ppt = models.DecimalField(
        _('Salinity the oxygen is worked out with (‰)'), max_digits=parameters.get('salinity_ppt').max_digits,
        decimal_places=parameters.get('salinity_ppt').decimals, null=True, blank=True)
    oxygen_basis_salinity_source = models.CharField(_('Source of the oxygen’s salinity'), max_length=20, blank=True,
                                                    choices=BasisSource.choices)
    oxygen_basis_salinity_channel = models.PositiveIntegerField(_('Sensor channel of the oxygen’s salinity'), null=True, blank=True)
    oxygen_basis_salinity_at = models.DateTimeField(_('When the oxygen’s salinity was measured'), null=True, blank=True)
    notes = models.CharField(_('Notes'), max_length=500, blank=True)
    void_reason = models.CharField(_('Reason for voiding'), max_length=500, blank=True)
    # The key of the form it was entered with (not a secret): the same form sent twice records once.
    entry_key = models.UUIDField(null=True, blank=True, editable=False)

    objects = SampleManager()
    all_objects = models.Manager()

    class Meta:
        db_table = 'water_measurements'
        ordering = ['-measured_at', '-created_at']
        verbose_name = _('water sample')
        verbose_name_plural = _('water samples')
        constraints = [
            *_sample_checks(),
            # A hypertable's unique constraints include its time column; the form posts its time with its key.
            models.UniqueConstraint(fields=['entry_key', 'measured_at'], name='uq_water_measurements_entry'),
        ]
        indexes = [models.Index(fields=['point', '-measured_at'], name='water_meas_point_time_idx')]

    def __str__(self):
        return f'{self.point} · {local_time(self.measured_at, self.point):%Y-%m-%d %H:%M}'

    def values(self):
        """{code: value} of the parameters measured."""
        return {code: getattr(self, code) for code in COLUMNS if getattr(self, code) is not None}


# ---- limits ----------------------------------------------------------------------------------------------
BOUNDS = ['critical_low', 'warning_low', 'warning_high', 'critical_high']   # in the order they must go up
# A limit row for any water (ANY_WATER, farm.water.evaluate), or for one water type: a stored value, so one
# unique constraint keeps one live row per species, parameter and water type.
WATER_CHOICES = [(ANY_WATER, _('Any water')), *WaterType.choices]
ORDER_MESSAGE = _('The bounds go up: critical below ≤ warning below ≤ warning above ≤ critical above.')


def _bound_checks():
    """Each bound inside its parameter's plausible range and at its precision (WQ-22); the bounds in order."""
    checks = []
    for bound in BOUNDS:
        fits = _any(Q(parameter=parameter.code, **{f'{bound}__gte': parameter.low, f'{bound}__lte': parameter.high},
                      **{bound: Round(F(bound), parameter.decimals)})
                    for parameter in LIMITED)
        checks.append(models.CheckConstraint(condition=Q(**{f'{bound}__isnull': True}) | fits,
                                             name=f'chk_water_limits_{bound}'))
    ordered = Q()
    for index, lower in enumerate(BOUNDS):
        for upper in BOUNDS[index + 1:]:
            ordered &= (Q(**{f'{lower}__isnull': True}) | Q(**{f'{upper}__isnull': True})
                        | Q(**{f'{lower}__lte': F(upper)}))
    checks.append(models.CheckConstraint(condition=ordered, name='chk_water_limits_order',
                                         violation_error_message=ORDER_MESSAGE))
    return checks


class WaterLimit(AuditedModel):
    """The water a species is kept in: for one parameter, the bounds outside which a value is a warning
    and outside which it is critical, per water type or for any water, with where the values come from.
    Source table: the limit columns of farm.water_quality_parameter_configs and their speciesLimits JSON,
    which nothing wrote or read (WQ-01).

    The unit is the parameter's (farm/water/parameters.py), never a field of its own (WQ-23). Any bound
    may be left open; the ones given go up: critical below ≤ warning below ≤ warning above ≤ critical
    above (WQ-22). None is seeded: the source's seed judged a freshwater hatchery by sea-water salmon limits
    (WQ-24). One live row per species, parameter and water type; a row for the unit's water type wins over
    the row for any water (farm/water/evaluate.py)."""

    species = models.ForeignKey(Species, on_delete=models.CASCADE, related_name='water_limits',
                                verbose_name=_('Species'))
    parameter = models.CharField(_('Parameter'), max_length=30, choices=LIMIT_CHOICES)
    water_type = models.CharField(_('Water type'), max_length=20, choices=WATER_CHOICES, default=ANY_WATER)
    critical_low = models.DecimalField(_('Critical below'), max_digits=8, decimal_places=4, null=True, blank=True)
    warning_low = models.DecimalField(_('Warning below'), max_digits=8, decimal_places=4, null=True, blank=True)
    warning_high = models.DecimalField(_('Warning above'), max_digits=8, decimal_places=4, null=True, blank=True)
    critical_high = models.DecimalField(_('Critical above'), max_digits=8, decimal_places=4, null=True, blank=True)
    reference = models.CharField(_('Source of the values'), max_length=300, blank=True)

    class Meta:
        db_table = 'water_limits'
        ordering = ['species__common_name', 'parameter', 'water_type']
        verbose_name = _('water limit')
        verbose_name_plural = _('water limits')
        constraints = [
            models.UniqueConstraint(
                fields=['species', 'parameter', 'water_type'], condition=Q(is_deleted=False),
                name='uq_water_limits_live',
                violation_error_message=_('This species already has limits for this parameter and water type.')),
            models.CheckConstraint(condition=Q(parameter__in=[code for code, _label in LIMIT_CHOICES]),
                                   name='chk_water_limits_parameter'),
            models.CheckConstraint(condition=Q(water_type__in=[value for value, _label in WATER_CHOICES]),
                                   name='chk_water_limits_water_type'),
            models.CheckConstraint(condition=_any(Q(**{f'{bound}__isnull': False}) for bound in BOUNDS),
                                   name='chk_water_limits_any_bound',
                                   violation_error_message=_('Give at least one bound.')),
            *_bound_checks(),
        ]

    def __str__(self):
        return f'{self.species} · {self.get_parameter_display()} · {self.get_water_type_display()}'

    @property
    def measure(self):
        return parameters.get(self.parameter)

    def clean(self):
        """The rules of the checks, with the message on the bound to change."""
        if self.parameter not in parameters.BY_CODE:
            return
        measure, errors = self.measure, {}
        for bound in BOUNDS:
            value = getattr(self, bound)
            if value is None:
                continue
            if not measure.plausible(value):
                errors[bound] = gettext('Between %(low)s and %(high)s for this parameter.') % {
                    'low': measure.low, 'high': measure.high}
            elif not measure.precise(value):
                errors[bound] = gettext('At most %(decimals)d decimals for this parameter.') % {
                    'decimals': measure.decimals}
        given = [bound for bound in BOUNDS if getattr(self, bound) is not None and bound not in errors]
        for index, upper in enumerate(given):
            if any(getattr(self, lower) > getattr(self, upper) for lower in given[:index]):
                errors[upper] = ORDER_MESSAGE
        if errors:
            raise ValidationError(errors)
