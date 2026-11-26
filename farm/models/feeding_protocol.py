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
import uuid
from decimal import Decimal

from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DecimalRangeField, RangeOperators
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Func, Q, Value
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.translation import gettext, gettext_lazy as _

from core.models import AuditedModel
from core.ranges import DateRange

from ..water import parameters
from .feed import MAX_WEIGHT_G, Feed
from .feeding import MAX_MEALS
from .site import zone_of
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


class ProtocolStatus(models.TextChoices):
    DRAFT = 'draft', _('Draft')
    ACTIVE = 'active', _('Active')
    RETIRED = 'retired', _('Retired')


# What a protocol's rations and growth are read from, beside its table: fixed once it is assigned (owner decision Q3).
FIXED_ONCE_ASSIGNED = ('species', 'expected_fcr', 'uneaten_pct', 'mortality_pct_month')


class FeedingProtocol(AuditedModel):
    """A feeding table for one species: weight bands with their feed, meals and expected FCR, and an SFR per band
    and temperature. Source table: farm.feeding_protocols_v2.

    A draft is built and changed freely; an active one takes assignments; a retired one keeps its past
    assignments and takes no new ones. Once a protocol is assigned its table, species, expected FCR, uneaten share
    and expected mortality are fixed (owner decision Q3): the rations computed from it for past days never change under the Records page,
    and a change is made on a copy (Duplicate). The expected FCR here is the fallback of every band that has
    none; it is the biological FCR, on the feed eaten: the growth is the feed given, less the uneaten share, divided
    by it (farm/feeding/growth.py). The uneaten share (empty: none) and the expected mortality a month (empty: none;
    read by the plan ahead only) are fallbacks of the bands in the same way. The FCR and the uneaten share are read
    between the bands' anchor weights without a jump (ration.Table).

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
    # Set once, by the migration that brought the interpolation (farm 0052), on the protocols that existed then: the
    # days before it keep each band's own FCR (owner decision Q3: what a protocol gave for past days never changes).
    # Empty on every protocol made since: read between the bands on every day.
    interpolated_from = models.DateField(_('FCR read between the bands from'), null=True, blank=True, editable=False)
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
        ]

    def __str__(self):
        return self.name

    def columns(self):
        """The temperature columns of its table, in order (read from the bands' cells, prefetched or not)."""
        return sorted({rate.temperature_c for band in self.bands.all() for rate in band.rates.all()})

    def is_assigned(self):
        """Whether an assignment names it: from then on its table, species and expected FCR are fixed."""
        return self.pk is not None and ProtocolAssignment.objects.filter(protocol=self).exists()

    def clean(self):
        """The rules of its status and of an assigned protocol, each with its message on the field to change."""
        super().clean()
        errors = {}
        stored = None if self._state.adding else FeedingProtocol.all_objects.filter(pk=self.pk).first()
        if self.status == ProtocolStatus.ACTIVE and (stored is None or not self.bands.exists()):
            errors['status'] = gettext('Fill in its feeding table first: a protocol without one cannot be active.')
        if stored is not None and self.is_assigned():
            fixed = gettext('Fixed: the protocol is assigned. Duplicate it to change it.')
            for name in FIXED_ONCE_ASSIGNED:
                if getattr(self, name) != getattr(stored, name):
                    errors[name] = fixed
            if self.status == ProtocolStatus.DRAFT:
                errors['status'] = gettext('It is assigned: it cannot go back to draft.')
        if self.status == ProtocolStatus.RETIRED and stored is not None and stored.status != ProtocolStatus.RETIRED:
            today = timezone.localdate(timezone=zone_of(None))
            if self.assignments.filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today)).exists():
                errors['status'] = gettext('It is assigned for today or later: end those assignments first.')
        if errors:
            raise ValidationError(errors)


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

    def contains(self, weight_g):
        """Whether fish of this average weight are in the band: from its lower weight up to, not including, its
        upper one."""
        return weight_g >= self.min_weight_g and (self.max_weight_g is None or weight_g < self.max_weight_g)


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


class Scope(models.TextChoices):
    """What an assignment row feeds, from the most specific to the least: the order the ration reads them in."""
    BATCH_IN_UNIT = 'batch_in_unit', _('Batch in unit')
    UNIT = 'unit', _('Unit')
    BATCH = 'batch', _('Whole batch')


def _period():
    return DateRange(F('valid_from'), F('valid_until'), Value('[]'))


class ProtocolAssignment(AuditedModel):
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

    Scope = Scope

    protocol = models.ForeignKey(FeedingProtocol, on_delete=models.PROTECT, related_name='assignments',
                                 verbose_name=_('Feeding protocol'))
    unit = models.ForeignKey(Tank, null=True, blank=True, on_delete=models.DO_NOTHING,
                             related_name='protocol_assignments', verbose_name=_('Unit'))
    batch = models.ForeignKey(Batch, null=True, blank=True, on_delete=models.DO_NOTHING,
                              related_name='protocol_assignments', verbose_name=_('Batch'))
    valid_from = models.DateField(_('From'))
    valid_until = models.DateField(_('Until'), null=True, blank=True)
    # The rows one dialog wrote (several units at once), shown together.
    group_id = models.UUIDField(default=uuid.uuid4, editable=False)
    notes = models.CharField(_('Notes'), max_length=500, blank=True)

    class Meta:
        db_table = 'protocol_assignments'
        ordering = ['-valid_from', '-created_at', 'group_id']
        verbose_name = _('protocol assignment')
        verbose_name_plural = _('protocol assignments')
        constraints = [
            models.CheckConstraint(condition=Q(unit__isnull=False) | Q(batch__isnull=False),
                                   name='chk_protocol_assignments_target',
                                   violation_error_message=_('Choose a unit, a batch, or both.')),
            models.CheckConstraint(condition=Q(valid_until__isnull=True) | Q(valid_until__gte=F('valid_from')),
                                   name='chk_protocol_assignments_period',
                                   violation_error_message=_('The last day comes on or after the first day.')),
            ExclusionConstraint(
                name='excl_protocol_assignments_unit',
                expressions=[(F('unit'), RangeOperators.EQUAL), (_period(), RangeOperators.OVERLAPS)],
                condition=Q(batch__isnull=True, is_deleted=False),
                violation_error_message=_('Another protocol is assigned to this unit on some of these days.')),
            ExclusionConstraint(
                name='excl_protocol_assignments_batch',
                expressions=[(F('batch'), RangeOperators.EQUAL), (_period(), RangeOperators.OVERLAPS)],
                condition=Q(unit__isnull=True, is_deleted=False),
                violation_error_message=_('Another protocol is assigned to this batch on some of these days.')),
            ExclusionConstraint(
                name='excl_protocol_assignments_batch_in_unit',
                expressions=[(F('unit'), RangeOperators.EQUAL), (F('batch'), RangeOperators.EQUAL),
                             (_period(), RangeOperators.OVERLAPS)],
                condition=Q(unit__isnull=False, batch__isnull=False, is_deleted=False),
                violation_error_message=_('Another protocol is assigned to this batch in this unit on some of these '
                                          'days.')),
        ]

    def __str__(self):
        target = ' · '.join(part for part in (self.unit.code if self.unit_id else '',
                                               self.batch.code if self.batch_id else '') if part)
        return f'{self.protocol} · {target} · {self.valid_from.isoformat()}'

    @property
    def scope(self):
        if self.unit_id and self.batch_id:
            return Scope.BATCH_IN_UNIT
        return Scope.UNIT if self.unit_id else Scope.BATCH

    def covers(self, day):
        return self.valid_from <= day and (self.valid_until is None or day <= self.valid_until)

    def today(self):
        """Today on the clock of the unit's site, else the company's."""
        site = self.unit.production_department.site if self.unit_id else None
        return timezone.localdate(timezone=zone_of(site))

    def started(self):
        return self.valid_from <= self.today()

    def delete_blockers(self):
        if self.started():
            return [gettext('It has started: set its last day instead. The days it fed keep their protocol.')]
        return []

    def clean(self):
        """The rules a row can check on its own: an active protocol for a new row or a new protocol, of the batch's
        species. What may change once it has started is the form's rule (farm/forms/feeding_protocol.py); the
        overlaps are the exclusion constraints'."""
        super().clean()
        errors = {}
        if self.valid_until is not None and self.valid_from is not None and self.valid_until < self.valid_from:
            errors['valid_until'] = gettext('The last day comes on or after the first day.')
        if self.protocol_id:
            protocol = self.protocol
            stored = None if self._state.adding else ProtocolAssignment.all_objects.filter(pk=self.pk).first()
            changed = stored is None or stored.protocol_id != self.protocol_id
            if changed and protocol.status != ProtocolStatus.ACTIVE:
                errors['protocol'] = gettext('Only an active protocol can be assigned; this one is %(status)s.') % {
                    'status': str(protocol.get_status_display()).lower()}
            elif self.batch_id and self.batch.species_id != protocol.species_id:
                errors['batch'] = gettext('%(batch)s is %(species)s; the protocol is for %(protocol_species)s.') % {
                    'batch': self.batch.code, 'species': self.batch.species, 'protocol_species': protocol.species}
        if errors:
            raise ValidationError(errors)
