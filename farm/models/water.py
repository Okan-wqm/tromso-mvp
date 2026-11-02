"""Water chemistry: the samples people take (Operations › Water chemistry) and the owner's limits per
species (Setup › Reference data › Water limits). Which parameters there are, with their units and
plausible ranges, is farm/water/parameters.py; how a value is judged is farm/water/evaluate.py, on read."""
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
from .site import zone_of
from .species import Species
from .system import System
from .tank import Tank, WaterType


class Source(models.TextChoices):
    MANUAL = 'manual', _('Meter or test kit')
    LAB = 'lab', _('Laboratory')


def site_of(point):
    """The site of a unit (through its production department, which may have none) or of a system."""
    return point.site if isinstance(point, System) else point.production_department.site


def local_time(moment, point):
    """A moment on the clock of the point's site (farm.models.site.zone_of)."""
    return moment.astimezone(zone_of(site_of(point)))


# The samples of live points. A deleted unit or system keeps its samples, out of sight, and they come back
# with it when it is restored (core.softdelete: the link keeps them, DO_NOTHING).
LIVE_POINT = (Q(unit__isnull=True) | Q(unit__is_deleted=False)) & (Q(system__isnull=True) | Q(system__is_deleted=False))


class SampleManager(ActiveManager):
    """Live samples of live points (LIVE_POINT); a voided sample is out, as a deleted record is."""

    def get_queryset(self):
        return super().get_queryset().filter(LIVE_POINT)


def _any(conditions):
    return reduce(or_, conditions)


def _sample_checks():
    checks = [
        models.CheckConstraint(
            condition=Q(unit__isnull=False, system__isnull=True) | Q(unit__isnull=True, system__isnull=False),
            name='chk_water_measurements_one_point',
            violation_error_message=_('A sample is taken in a unit or in a system’s loop, one of the two.')),
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
    return checks


class WaterMeasurement(AuditedModel):
    """A water sample: what a person measured at one point, a unit or a system's loop, at one moment, with
    a typed column per parameter (empty when not measured). Source table: farm.water_quality_measurements.

    One row per sample (wide), not per parameter: each column keeps its own unit, precision and plausible
    range (a database check), and the values worked out from a sample, the un-ionised ammonia and the
    oxygen saturation, need its pH, temperature and salinity of the same moment (farm/water/chemistry.py).
    The source kept the values in a JSONB bag with no basis and no bounds (WQ-03, WQ-07). Nothing about
    the sample's status is stored: it is judged on read against the limits as they are (WQ-21). The fish
    it concerns are not stored either: they are the stock ledger's on that day.

    Never edited: a sample is voided (its soft delete, with a reason) and entered again, as a stock
    operation is. created_by is who recorded it (never a value from the form, WQ-11). The only writer is
    farm/water/services.py.

    The table is a TimescaleDB hypertable on `measured_at` (migration 0014), so its primary key in the
    database is (id, measured_at) while the model keeps `id`. That has rules:
    - every unique constraint includes `measured_at` (the form's key below does);
    - no foreign key points at this table;
    - an update by id alone (a void) looks in every chunk: cheap at a farm's volume."""

    Source = Source

    # A deleted unit or system keeps its samples (they come back with it): DO_NOTHING, read by SampleManager.
    unit = models.ForeignKey(Tank, null=True, blank=True, on_delete=models.DO_NOTHING, related_name='water_samples',
                             verbose_name=_('Unit'))
    system = models.ForeignKey(System, null=True, blank=True, on_delete=models.DO_NOTHING,
                               related_name='water_samples', verbose_name=_('System'))
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
        indexes = [models.Index(fields=['unit', '-measured_at'], name='water_meas_unit_time_idx'),
                   models.Index(fields=['system', '-measured_at'], name='water_meas_system_time_idx')]

    def __str__(self):
        return f'{self.point.code} · {local_time(self.measured_at, self.point):%Y-%m-%d %H:%M}'

    @property
    def point(self):
        """Where it was taken: the unit, or the system whose loop (sump) was sampled."""
        return self.unit if self.unit_id else self.system

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
