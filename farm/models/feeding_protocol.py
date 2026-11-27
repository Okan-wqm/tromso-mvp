"""Feeding protocols and where they apply (Operations › Feeding › Protocols and Assignments).

A protocol is a feeding table for one species: weight bands, each with its feed, its meals a day and
optionally its expected FCR, and per band a specific feeding rate (SFR, % of the body weight a day) at
each temperature column of the table. Nothing in it is a ration: the ration is computed on read from the
stock, the projected weight, the unit's temperature and this table (farm/feeding/ration.py), so nothing
stored can drift. The source kept the bands, the schedules and the temperature multipliers in JSON, with
no checks and no foreign keys (FP-29); here every rule a row can say is a database check, and the bands of a
protocol cannot overlap (an exclusion constraint, btree_gist).

An assignment says which protocol feeds which fish from which day: a unit, a whole batch (wherever it is,
through transfers and splits), or a batch in one unit. One row per target, so the database keeps one
protocol in force per unit, per batch and per batch in a unit (three exclusion constraints); the most
specific row wins on read (batch in unit, then unit, then whole batch)."""
from decimal import Decimal

from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DecimalRangeField, RangeOperators
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Func, Q, Value
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from core.models import AuditedModel
from core.ranges import DateRange  # noqa: F401 (older migrations name it here: experiments 0001)

from ..water import parameters
from .feed import MAX_WEIGHT_G, Feed
from .feeding import MAX_MEALS
from .assignment import (  # noqa: F401 (the names this module has always given)
    Assignable, BetweenBands, ProtocolStatus, Scope, TargetedAssignment, assignment_constraints,
)
from .species import Species
from .stock import Batch
from .tank import Tank

# Expected FCR: salmonid fry convert at about 0.7, marine species in poor conditions at about 2.5; the source's
# 5.0 only lets a typo through.
MIN_FCR, MAX_FCR = Decimal('0.50'), Decimal('3.00')
# A specific feeding rate in % of the body weight a day; 0 is "do not feed at this temperature". 15 % covers
# first-feeding fry.
MAX_SFR = 15
# The temperature columns span the temperature parameter's plausible range (farm/water/parameters.py).
TEMPERATURE = parameters.get(parameters.TEMPERATURE)
FCR = [MinValueValidator(MIN_FCR), MaxValueValidator(MAX_FCR)]
# The share of the feed given that is not eaten, in %: above a half the table itself is wrong, not the appetite.
MAX_UNEATEN = Decimal('50.0')
UNEATEN = [MinValueValidator(0), MaxValueValidator(MAX_UNEATEN)]
# An expected mortality in % a month for the plan ahead; above 30 % a month is a disease outbreak, not a plan.
MAX_MORTALITY = Decimal('30.00')
MORTALITY = [MinValueValidator(0), MaxValueValidator(MAX_MORTALITY)]

FCR_MESSAGE = _('An expected FCR is between 0.50 and 3.00.')
UNEATEN_MESSAGE = _('The uneaten share of the feed is between 0 and 50 %%.')
MORTALITY_MESSAGE = _('An expected mortality is between 0 and 30 %% a month.')
BAND_MESSAGE = _('The upper weight must be above the lower weight.')
OVERLAP_MESSAGE = _('Two weight bands of this protocol overlap.')


class NumRange(Func):
    """numrange(lower, upper, bounds): a weight band as PostgreSQL compares it."""
    function = 'numrange'
    output_field = DecimalRangeField()


# What a protocol's rations and growth are read from, beside its table: fixed once it is assigned (owner decision Q3).
FIXED_ONCE_ASSIGNED = ('species', 'expected_fcr', 'uneaten_pct', 'mortality_pct_month', 'fcr_between',
                       'uneaten_between', 'sfr_between')


BETWEEN_FIELDS = ('fcr_between', 'uneaten_between', 'sfr_between')


def _between(label):
    return models.CharField(label, max_length=6, choices=BetweenBands.choices, default=BetweenBands.SMOOTH)


class FeedingProtocol(Assignable, AuditedModel):
    """A feeding table for one species: weight bands with their feed, meals and expected FCR, and an SFR per band
    and temperature. Source table: farm.feeding_protocols_v2.

    A draft is built and changed freely; an active one takes assignments; a retired one keeps its past
    assignments and takes no new ones. Once a protocol is assigned its table, species, expected FCR, uneaten share,
    expected mortality and between-band rules are fixed (owner decision Q3): the rations computed from it for past days never change under the Records page,
    and a change is made on a copy (Duplicate). The expected FCR here is the fallback of every band that has
    none; it is the biological FCR, on the feed eaten: the growth is the feed given, less the uneaten share, divided
    by it (farm/feeding/growth.py). The uneaten share (empty: none) and the expected mortality a month (empty: none;
    read by the plan ahead only) are fallbacks of the bands in the same way. For fish between two bands the FCR,
    the uneaten share and the SFR each follow the protocol's own rule: smooth (read between the bands' anchor weights
    without a jump) or a step at the band's edge (ration.Table).

    Differences from the source: the temperature response is a column of the table, per band (the source had
    one multiplier for every fish size, FP-28), interpolated between columns and never extrapolated; a fish
    outside the bands has no ration (the source fed the first or last band, FP-03); one expected FCR per band or
    the protocol's (no matrix stored transposed, FP-18); a species is required. Not ported: meal times and
    schedules, rate clamps and adjustments, hysteresis and manual band pins, the default flag, settings no input
    could set (FP-19, FP-26)."""

    Status = ProtocolStatus

    name = models.CharField(_('Name'), max_length=100)
    species = models.ForeignKey(Species, on_delete=models.PROTECT, related_name='feeding_protocols',
                                limit_choices_to={'is_deleted': False}, verbose_name=_('Species'))
    status = models.CharField(_('Status'), max_length=10, choices=ProtocolStatus.choices, default=ProtocolStatus.DRAFT)
    expected_fcr = models.DecimalField(_('Expected FCR'), max_digits=4, decimal_places=2, validators=FCR)
    uneaten_pct = models.DecimalField(_('Uneaten feed (%)'), max_digits=3, decimal_places=1, null=True, blank=True,
                                      validators=UNEATEN)
    mortality_pct_month = models.DecimalField(_('Expected mortality (%/month)'), max_digits=4, decimal_places=2,
                                              null=True, blank=True, validators=MORTALITY)
    # How each quantity is read for fish between two bands (owner decision 14, 2026-11-26): smooth, or a step at the
    # band's edge. The protocols that existed before the rule have `step` (migration 0053): they behave as they did.
    fcr_between = _between(_('FCR between bands'))
    uneaten_between = _between(_('Uneaten feed between bands'))
    sfr_between = _between(_('SFR between bands'))
    notes = models.CharField(_('Notes'), max_length=2000, blank=True)

    class Meta:
        db_table = 'feeding_protocols'
        ordering = ['name']
        verbose_name = _('feeding protocol')
        verbose_name_plural = _('feeding protocols')
        constraints = [
            models.UniqueConstraint(
                Lower('name'), condition=Q(is_deleted=False), name='uq_feeding_protocols_name_live',
                violation_error_message=_('Another feeding protocol already has this name.')),
            models.CheckConstraint(condition=Q(status__in=ProtocolStatus.values), name='chk_feeding_protocols_status'),
            models.CheckConstraint(condition=Q(expected_fcr__gte=MIN_FCR, expected_fcr__lte=MAX_FCR),
                                   name='chk_feeding_protocols_expected_fcr', violation_error_message=FCR_MESSAGE),
            models.CheckConstraint(condition=Q(uneaten_pct__isnull=True) | Q(uneaten_pct__gte=0, uneaten_pct__lte=MAX_UNEATEN),
                                   name='chk_feeding_protocols_uneaten', violation_error_message=UNEATEN_MESSAGE),
            models.CheckConstraint(condition=Q(mortality_pct_month__isnull=True)
                                   | Q(mortality_pct_month__gte=0, mortality_pct_month__lte=MAX_MORTALITY),
                                   name='chk_feeding_protocols_mortality', violation_error_message=MORTALITY_MESSAGE),
            *(models.CheckConstraint(condition=Q(**{f'{name}__in': BetweenBands.values}),
                                     name=f'chk_feeding_protocols_{name}') for name in BETWEEN_FIELDS),
        ]

    def __str__(self):
        return self.name

    def columns(self):
        """The temperature columns of its table, in order (read from the bands' cells, prefetched or not)."""
        return sorted({rate.temperature_c for band in self.bands.all() for rate in band.rates.all()})

    FIXED = FIXED_ONCE_ASSIGNED
    NEEDS_TABLE = _('Fill in its feeding table first: a protocol without one cannot be active.')
    FIXED_MESSAGE = _('Fixed: the protocol is assigned. Duplicate it to change it.')

    def has_table(self):
        return self.bands.exists()


class ProtocolBand(models.Model):
    """A weight band of a protocol's feeding table: fish from the lower weight up to, not including, the upper
    one (an empty upper weight: no upper end), the feed they get (its pellet is the feed's), their meals a day
    their expected FCR, their uneaten share of the feed and their expected mortality a month (each empty: the
    protocol's). Source: the `bands` JSON of farm.feeding_protocols_v2.

    The table is saved as a whole (the protocol's Feeding table tab), replacing the stored bands and their
    rates, so these rows have no update or soft-delete columns; the change is logged on the protocol. The bands
    of a protocol meet without gaps (checked when the table is saved) and never overlap (the database)."""

    protocol = models.ForeignKey(FeedingProtocol, on_delete=models.CASCADE, related_name='bands',
                                 verbose_name=_('Feeding protocol'))
    min_weight_g = models.DecimalField(_('From (g)'), max_digits=10, decimal_places=2,
                                       validators=[MinValueValidator(0), MaxValueValidator(MAX_WEIGHT_G)])
    max_weight_g = models.DecimalField(_('Up to (g)'), max_digits=10, decimal_places=2, null=True, blank=True,
                                       validators=[MinValueValidator(Decimal('0.01')), MaxValueValidator(MAX_WEIGHT_G)])
    # A feed the table names is not deleted while the protocol is live (Feed.delete_blockers).
    feed = models.ForeignKey(Feed, on_delete=models.PROTECT, related_name='protocol_bands', verbose_name=_('Feed'))
    meals_per_day = models.PositiveSmallIntegerField(_('Meals a day'),
                                                     validators=[MinValueValidator(1), MaxValueValidator(MAX_MEALS)])
    expected_fcr = models.DecimalField(_('Expected FCR'), max_digits=4, decimal_places=2, null=True, blank=True,
                                       validators=FCR)
    uneaten_pct = models.DecimalField(_('Uneaten feed (%)'), max_digits=3, decimal_places=1, null=True, blank=True,
                                      validators=UNEATEN)
    mortality_pct_month = models.DecimalField(_('Expected mortality (%/month)'), max_digits=4, decimal_places=2,
                                              null=True, blank=True, validators=MORTALITY)

    class Meta:
        db_table = 'feeding_protocol_bands'
        ordering = ['protocol', 'min_weight_g']
        verbose_name = _('feeding table band')
        verbose_name_plural = _('feeding table bands')
        constraints = [
            models.CheckConstraint(condition=Q(min_weight_g__gte=0, min_weight_g__lte=MAX_WEIGHT_G),
                                   name='chk_feeding_protocol_bands_min_weight'),
            models.CheckConstraint(condition=Q(max_weight_g__isnull=True)
                                   | Q(max_weight_g__gt=F('min_weight_g'), max_weight_g__lte=MAX_WEIGHT_G),
                                   name='chk_feeding_protocol_bands_band', violation_error_message=BAND_MESSAGE),
            models.CheckConstraint(condition=Q(meals_per_day__gte=1, meals_per_day__lte=MAX_MEALS),
                                   name='chk_feeding_protocol_bands_meals'),
            models.CheckConstraint(condition=Q(expected_fcr__isnull=True)
                                   | Q(expected_fcr__gte=MIN_FCR, expected_fcr__lte=MAX_FCR),
                                   name='chk_feeding_protocol_bands_expected_fcr', violation_error_message=FCR_MESSAGE),
            models.CheckConstraint(condition=Q(uneaten_pct__isnull=True) | Q(uneaten_pct__gte=0, uneaten_pct__lte=MAX_UNEATEN),
                                   name='chk_feeding_protocol_bands_uneaten', violation_error_message=UNEATEN_MESSAGE),
            models.CheckConstraint(condition=Q(mortality_pct_month__isnull=True)
                                   | Q(mortality_pct_month__gte=0, mortality_pct_month__lte=MAX_MORTALITY),
                                   name='chk_feeding_protocol_bands_mortality',
                                   violation_error_message=MORTALITY_MESSAGE),
            models.UniqueConstraint(fields=['protocol', 'min_weight_g'], name='uq_feeding_protocol_bands_start'),
            ExclusionConstraint(
                name='excl_feeding_protocol_bands_overlap',
                expressions=[(F('protocol'), RangeOperators.EQUAL),
                             (NumRange(F('min_weight_g'), F('max_weight_g'), Value('[)')), RangeOperators.OVERLAPS)],
                violation_error_message=OVERLAP_MESSAGE),
        ]

    def __str__(self):
        upper = f'{self.max_weight_g.normalize():f}' if self.max_weight_g is not None else '…'
        return f'{self.min_weight_g.normalize():f}–{upper} g'


class ProtocolRate(models.Model):
    """One cell of a feeding table: the SFR (% of the body weight a day) of a band at a temperature column.
    Every band of a protocol has a cell in every column (the table is saved whole). Source: the protocol's
    `temperatureAdjustments` multipliers, which applied one factor to every fish size (FP-28)."""

    band = models.ForeignKey(ProtocolBand, on_delete=models.CASCADE, related_name='rates', verbose_name=_('Band'))
    temperature_c = models.DecimalField(_('Temperature (°C)'), max_digits=3, decimal_places=1,
                                        validators=[MinValueValidator(TEMPERATURE.low),
                                                    MaxValueValidator(TEMPERATURE.high)])
    sfr_pct = models.DecimalField(_('SFR (% a day)'), max_digits=5, decimal_places=3,
                                  validators=[MinValueValidator(0), MaxValueValidator(MAX_SFR)])

    class Meta:
        db_table = 'feeding_protocol_rates'
        ordering = ['band', 'temperature_c']
        verbose_name = _('feeding table cell')
        verbose_name_plural = _('feeding table cells')
        constraints = [
            models.CheckConstraint(condition=Q(temperature_c__gte=TEMPERATURE.low, temperature_c__lte=TEMPERATURE.high),
                                   name='chk_feeding_protocol_rates_temperature'),
            models.CheckConstraint(condition=Q(sfr_pct__gte=0, sfr_pct__lte=MAX_SFR),
                                   name='chk_feeding_protocol_rates_sfr'),
            models.UniqueConstraint(fields=['band', 'temperature_c'], name='uq_feeding_protocol_rates_cell'),
        ]

    def __str__(self):
        return f'{self.temperature_c} °C: {self.sfr_pct.normalize():f} %'


class ProtocolAssignment(TargetedAssignment):
    """A protocol in force for a unit, a whole batch or a batch in one unit, from a day and optionally until a
    day (both included). Source table: farm.feeding_protocol_assignments.

    One row per target: the dialog writes a row per unit chosen, all with one `group_id`. The database keeps one
    row in force per unit, per batch and per batch in a unit on any day (exclusion constraints among live rows);
    on read the most specific row wins (batch in unit, then unit, then whole batch), so a whole-batch row follows
    the batch into every unit it is moved to, while a unit's row stays with the unit.

    Rows are history: the rations of past days are read from them. Before its first day a row may be changed or
    deleted; from its first day only its last day and notes change (a row is ended, not deleted). A unit or a
    batch keeps its rows when it is deleted or voided, as it keeps its feeding records (DO_NOTHING): they come back
    with it, and the database refuses a hard delete.

    Differences from the source: a batch and a batch in a unit are rows of their own (the source copied a batch
    assignment onto its units once and never followed a transfer, FP-06); the dates are read (the source ignored
    them, FP-07); no paused state, overrides or suspensions."""

    SUBJECT = 'protocol'
    ONLY_ACTIVE = _('Only an active protocol can be assigned; this one is %(status)s.')
    OTHER_SPECIES = _('%(batch)s is %(species)s; the protocol is for %(protocol_species)s.')
    STARTED = _('It has started: set its last day instead. The days it fed keep their protocol.')
    KEPT = _('The days before yesterday keep their protocol: the last day is yesterday at the earliest.')

    protocol = models.ForeignKey(FeedingProtocol, on_delete=models.PROTECT, related_name='assignments',
                                 verbose_name=_('Feeding protocol'))
    unit = models.ForeignKey(Tank, null=True, blank=True, on_delete=models.DO_NOTHING,
                             related_name='protocol_assignments', verbose_name=_('Unit'))
    batch = models.ForeignKey(Batch, null=True, blank=True, on_delete=models.DO_NOTHING,
                              related_name='protocol_assignments', verbose_name=_('Batch'))

    class Meta:
        db_table = 'protocol_assignments'
        ordering = ['-valid_from', '-created_at', 'group_id']
        verbose_name = _('protocol assignment')
        verbose_name_plural = _('protocol assignments')
        constraints = assignment_constraints(
            'protocol_assignments', _('Another protocol is assigned to this unit on some of these days.'),
            _('Another protocol is assigned to this batch on some of these days.'),
            _('Another protocol is assigned to this batch in this unit on some of these days.'))
