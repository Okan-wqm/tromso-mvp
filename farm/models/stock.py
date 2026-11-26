"""The fish on the farm: batches and the stock ledger (Operations › Production units).

One fact, one place. A count or a weight is entered once, as a ledger line (`StockMovement`) of an
operation a person recorded (`StockOperation`); everything shown, a unit's fish, biomass, average,
density, capacity, survival, days stocked, is computed from the live lines (farm/stock/fold.py). No
column holds a number that can be computed from other rows, so nothing drifts and nothing needs a
reconcile job (the source kept a unit's count in six places and its biomass in seven, STK-01).

Nothing is edited or hard-deleted: an operation is voided (its soft delete, with a reason), and a
correction is a void and a new entry. The only writer is farm/stock/services.py, which locks, checks
the whole timeline of every batch it touches and keeps the unit statuses in step, in one transaction.
"""
from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower
from django.utils.translation import gettext, gettext_lazy as _, ngettext, ngettext_lazy

from core.models import AuditedModel

from .species import Species
from .supplier import Supplier, SupplierLink, SupplyCategory
from .tank import ON_A_SITE, Tank, on_a_site


# ---- the choices ---------------------------------------------------------------------------------
class InputStage(models.TextChoices):
    """The life stage of the fish when they came in (the source's BatchInputType, lower-case)."""
    EGGS = 'eggs', _('Eggs')
    LARVAE = 'larvae', _('Larvae')
    POST_LARVAE = 'post_larvae', _('Post-larvae')
    FRY = 'fry', _('Fry')
    FINGERLINGS = 'fingerlings', _('Fingerlings')
    JUVENILES = 'juveniles', _('Juveniles')
    SMOLT = 'smolt', _('Smolt')
    ADULTS = 'adults', _('Adults')
    BROODSTOCK = 'broodstock', _('Broodstock')


class Origin(models.TextChoices):
    PURCHASED = 'purchased', _('Bought from a supplier')
    OWN_HATCHERY = 'own_hatchery', _('Own hatchery')
    WILD = 'wild', _('Wild-caught')


YEAR_CLASS_MESSAGE = _('A year class is a year, e.g. 2026.')


class Provenance(models.TextChoices):
    """Where the fish come from as Mattilsynet's cleaner-fish report asks it (`opprinnelse`): farmed or caught in
    the wild. A batch of the own hatchery is farmed and one caught by the farm wild-caught; fish bought say which."""
    FARMED = 'farmed', _('Farmed')
    WILD_CAUGHT = 'wild_caught', _('Wild-caught')


# What the origin says of the provenance: fish of the own hatchery are farmed, fish the farm caught wild-caught.
PROVENANCE_OF_ORIGIN = {Origin.OWN_HATCHERY: Provenance.FARMED, Origin.WILD: Provenance.WILD_CAUGHT}


class OperationKind(models.TextChoices):
    """What a person did. Every kind has its dialog; a count adjustment is an escape's (its dialog), and a harvest
    that empties a unit writes one too (fish the book holds beyond the count)."""
    INPUT = 'input', _('Stocking')
    MORTALITY = 'mortality', _('Mortality')
    CULL = 'cull', _('Cull')
    TRANSFER = 'transfer', _('Transfer')
    GRADING = 'grading', _('Grading')
    WEIGHING = 'weighing', _('Weighing')
    HARVEST = 'harvest', _('Harvest')
    DELIVERY = 'delivery', _('Fish delivery')
    ADJUSTMENT = 'adjustment', _('Count adjustment')


class MovementKind(models.TextChoices):
    INPUT = 'input', _('Stocked')
    MORTALITY = 'mortality', _('Died')
    CULL = 'cull', _('Culled')
    TRANSFER_OUT = 'transfer_out', _('Moved out')
    TRANSFER_IN = 'transfer_in', _('Moved in')
    HARVEST = 'harvest', _('Harvested')
    DELIVERY = 'delivery', _('Delivered out')
    WEIGHING = 'weighing', _('Weighed')
    ADJUSTMENT = 'adjustment', _('Count adjusted')


class MortalityCause(models.TextChoices):
    """One list (the source had two that disagreed, STK-17): its superset."""
    DISEASE = 'disease', _('Disease')
    WATER_QUALITY = 'water_quality', _('Water quality')
    OXYGEN = 'oxygen', _('Low oxygen')
    TEMPERATURE = 'temperature', _('Temperature')
    AMMONIA = 'ammonia', _('Ammonia')
    STRESS = 'stress', _('Stress')
    HANDLING = 'handling', _('Handling')
    PREDATION = 'predation', _('Predation')
    CANNIBALISM = 'cannibalism', _('Cannibalism')
    STARVATION = 'starvation', _('Starvation')
    GENETIC = 'genetic', _('Genetic')
    # Deaths caused by a treatment or the handling around it (behandlingsdødelighet), counted apart from
    # the disease treated (health-maturity §2).
    TREATMENT = 'treatment', _('Treatment')
    UNKNOWN = 'unknown', _('Unknown')
    OTHER = 'other', _('Other')


class CullReason(models.TextChoices):
    """Why fish were culled. A cleaner fish is culled for one of Mattilsynet's six causes (the cleaner-fish report's
    `uttak`, its OpenAPI read 2026-11-03), a production fish for one of the others; the stock service holds which."""
    SMALL_SIZE = 'small_size', _('Small size')
    DEFORMED = 'deformed', _('Deformed')
    SICK = 'sick', _('Sick')
    POOR_GROWTH = 'poor_growth', _('Poor growth')
    GRADING = 'grading', _('Grading')
    QUALITY = 'quality', _('Quality')
    OTHER = 'other', _('Other')
    INJURED = 'injured', _('Injured')
    EMACIATED = 'emaciated', _('Emaciated')
    SALMON_HANDLING = 'salmon_handling', _('Healthy, before the salmon are handled')
    POOR_ENVIRONMENT = 'poor_environment', _('Healthy, before a poor environment')
    NOT_USED = 'not_used', _('Healthy, no longer to be used')


# The causes of a cleaner fish's cull (antallAvlivetSykdom … antallAvlivetSkalIkkeBrukes) and of a production fish's.
CLEANER_CULL_REASONS = (CullReason.SICK, CullReason.INJURED, CullReason.EMACIATED, CullReason.SALMON_HANDLING,
                        CullReason.POOR_ENVIRONMENT, CullReason.NOT_USED)
PRODUCTION_CULL_REASONS = (CullReason.SMALL_SIZE, CullReason.DEFORMED, CullReason.SICK, CullReason.POOR_GROWTH,
                           CullReason.GRADING, CullReason.QUALITY, CullReason.OTHER)


class TransferReason(models.TextChoices):
    DENSITY = 'density', _('Density management')
    SPLIT = 'split', _('Split')
    GRADING = 'grading', _('Grading')
    GROWTH_STAGE = 'growth_stage', _('Growth stage')
    WATER_QUALITY = 'water_quality', _('Water quality')
    HEALTH = 'health', _('Health')
    MAINTENANCE = 'maintenance', _('Maintenance')
    HARVEST_PREP = 'harvest_prep', _('Harvest preparation')
    OTHER = 'other', _('Other')


class AdjustmentReason(models.TextChoices):
    COUNT_CORRECTION = 'count_correction', _('Count correction')
    UNACCOUNTED_LOSS = 'unaccounted_loss', _('Unaccounted loss')
    ESCAPE = 'escape', _('Escape')
    OTHER = 'other', _('Other')


# The statuses a unit may be stocked in. A preparing or fallow unit becomes active when fish arrive;
# an active one takes a second batch of its species (owner decisions Q1 and Q5).
ARRIVAL_STATUSES = (Tank.Status.ACTIVE, Tank.Status.PREPARING, Tank.Status.FALLOW)
# The units that take fish: of such a status and on a live site (Tank ON_A_SITE), since a site's fish are counted
# only through its units (F-212). The form's list and the page's buttons ask this; the one write path asks both parts
# to say which one is missing.
TAKES_FISH = Q(status__in=ARRIVAL_STATUSES) & ON_A_SITE


def takes_fish(unit):
    return unit.status in ARRIVAL_STATUSES and on_a_site(unit.production_department)


# Operations that bring fish into a unit: the ones the capacity acknowledgement can belong to.
ARRIVING_OPERATIONS = (OperationKind.INPUT, OperationKind.TRANSFER, OperationKind.GRADING,
                       OperationKind.ADJUSTMENT)
REMOVALS = (MovementKind.MORTALITY, MovementKind.CULL, MovementKind.TRANSFER_OUT, MovementKind.HARVEST,
            MovementKind.DELIVERY)
ARRIVALS = (MovementKind.INPUT, MovementKind.TRANSFER_IN)
PAIRED = (MovementKind.TRANSFER_OUT, MovementKind.TRANSFER_IN)
# The reason list of each kind of line that has one; the other kinds have none.
REASONS = {
    MovementKind.MORTALITY: MortalityCause,
    MovementKind.CULL: CullReason,
    MovementKind.TRANSFER_OUT: TransferReason,
    MovementKind.ADJUSTMENT: AdjustmentReason,
}


class Batch(AuditedModel):
    """A group of fish that came in together: its identity and origin, no counts. Source table:
    farm.batches_v2.

    How many fish came in, at what weight and into which units, are the lines of its input operation;
    how many are left is the sum of its lines. `input_date` is the one value kept here for lists, and
    the input operation's date is always the same day (the stock service writes both; check_stock
    compares them).

    Its status is derived, never stored: in stock while its lines add up to more than 0 fish, ended
    when they add up to 0. The source's hand-set statuses (quarantine, growing, closed...) stranded
    fish (STK-08, STK-34, STK-37, STK-38); quarantine is a unit status here. The number is generated
    on the input date's year and never reused, also after a void.

    Bought fish name their supplier (Purchasing › Suppliers), a supplier of live fish and eggs. The link
    is PROTECT: where fish came from is a fact the farm must be able to show for as long as it keeps
    their records (traceability), so a supplier fish were bought from is set inactive, not deleted, and
    keeps its live-fish category (SupplierLink). The source's supplierId had no foreign key.
    """

    code = models.CharField(_('Batch number'), max_length=30, editable=False)
    name = models.CharField(_('Name'), max_length=100, blank=True)
    species = models.ForeignKey(Species, on_delete=models.PROTECT, related_name='batches',
                                verbose_name=_('Species'))
    input_stage = models.CharField(_('Stage at input'), max_length=20, choices=InputStage.choices)
    origin = models.CharField(_('Origin'), max_length=20, choices=Origin.choices)
    supplier = SupplierLink(
        Supplier, null=True, blank=True, on_delete=models.PROTECT, related_name='batches',
        category=SupplyCategory.LIVE_FISH, verbose_name=_('Supplier'),
        error_messages={'invalid': _('Choose a supplier of live fish and eggs.')},
        kept=ngettext_lazy('%(count)d batch of fish was bought from it: keep “%(category)s” ticked.',
                           '%(count)d batches of fish were bought from it: keep “%(category)s” ticked.', 'count'),
    )
    supplier_batch_ref = models.CharField(_('Supplier’s batch number'), max_length=100, blank=True)
    provenance = models.CharField(_('Farmed or wild-caught'), max_length=12, blank=True, choices=Provenance.choices)
    # The year class (årsklasse) of the reports (akvakulturdriftsforskriften § 42, § 44; D-14): entered, never
    # defaulted, since fish stocked as eggs keep their batch through every move. Whether the authorities mean the
    # hatch year or the year the fish went to sea is unverified.
    year_class = models.PositiveSmallIntegerField(
        _('Year class'), null=True, blank=True,
        validators=[MinValueValidator(1980, YEAR_CLASS_MESSAGE), MaxValueValidator(2100, YEAR_CLASS_MESSAGE)])
    strain = models.CharField(_('Strain'), max_length=100, blank=True)
    input_date = models.DateField(_('Stocking date'))
    expected_harvest_date = models.DateField(_('Expected harvest'), null=True, blank=True)
    notes = models.CharField(_('Notes'), max_length=2000, blank=True)

    class Meta:
        db_table = 'batches'
        ordering = ['-input_date', '-code']
        verbose_name = _('batch')
        verbose_name_plural = _('batches')
        constraints = [
            # Never reused, not even the number of a voided batch: the history keeps pointing at one batch.
            models.UniqueConstraint(fields=['code'], name='uq_batches_code'),
            models.CheckConstraint(condition=Q(code__regex=r'^B-[0-9]{4}-[0-9]{3,}$'), name='chk_batches_code'),
            models.CheckConstraint(condition=Q(input_stage__in=InputStage.values), name='chk_batches_stage'),
            models.CheckConstraint(condition=Q(origin__in=Origin.values), name='chk_batches_origin'),
            models.CheckConstraint(
                condition=Q(origin=Origin.PURCHASED, supplier__isnull=False)
                | (~Q(origin=Origin.PURCHASED) & Q(supplier__isnull=True, supplier_batch_ref='')),
                name='chk_batches_supplier',
                violation_error_message=_('Bought fish have a supplier; fish of the own hatchery or caught in the '
                                          'wild have none.'),
            ),
            models.CheckConstraint(
                condition=Q(provenance='') | Q(provenance__in=Provenance.values), name='chk_batches_provenance'),
            # Fish of the own hatchery are farmed and fish caught by the farm wild-caught; bought fish say which.
            models.CheckConstraint(
                condition=Q(origin=Origin.PURCHASED) | Q(origin=Origin.OWN_HATCHERY, provenance=Provenance.FARMED)
                | Q(origin=Origin.WILD, provenance=Provenance.WILD_CAUGHT),
                name='chk_batches_origin_provenance',
                violation_error_message=_('Fish of the own hatchery are farmed, fish caught in the wild wild-caught.')),
            models.CheckConstraint(
                condition=Q(year_class__isnull=True) | Q(year_class__gte=1980, year_class__lte=2100),
                name='chk_batches_year_class', violation_error_message=YEAR_CLASS_MESSAGE),
            models.CheckConstraint(
                condition=Q(expected_harvest_date__isnull=True) | Q(expected_harvest_date__gt=F('input_date')),
                name='chk_batches_harvest_after_input',
                violation_error_message=_('The expected harvest comes after the stocking date.'),
            ),
        ]
        indexes = [models.Index(fields=['input_date'])]

    def __str__(self):
        return self.code

    def delete_blockers(self):
        # core.softdelete does not follow the plain StockMovement link, so say it here.
        if StockMovement.objects.filter(batch=self, operation__is_deleted=False).exists():
            return [gettext('It has stock operations: void them first.')]
        return []


class StockOperation(AuditedModel):
    """One thing a person did to the stock (a stocking, a mortality, a weighing), the unit of void and
    of the activity log. created_by and created_at say who recorded it and when; `date` is the day it
    happened. A voided operation is soft-deleted with its reason: history shows it, the stock leaves
    it out."""

    kind = models.CharField(_('Operation'), max_length=12, choices=OperationKind.choices)
    date = models.DateField(_('Date'))
    notes = models.CharField(_('Notes'), max_length=2000, blank=True)
    # The person accepted that the fish arriving take a unit above its max density (owner decision Q4).
    over_capacity_ack = models.BooleanField(_('Above the max density, accepted'), default=False)
    # The person accepted that the fish arriving leave a unit holding batches of a species further apart in weight than
    # the species' size limit (Species.max_weight_ratio; the owner, 2026-11-09).
    size_mix_ack = models.BooleanField(_('Batches of different sizes, accepted'), default=False)
    # The health event the deaths or culls belong to (Operations › Health events), on a mortality or a cull
    # only; the event counts its deaths from these operations' lines.
    health_event = models.ForeignKey('HealthEvent', null=True, blank=True, on_delete=models.PROTECT,
                                     related_name='stock_operations', verbose_name=_('Health event'))
    void_reason = models.CharField(_('Reason for voiding'), max_length=500, blank=True)

    class Meta:
        db_table = 'stock_operations'
        ordering = ['-date', '-created_at']
        verbose_name = _('stock operation')
        verbose_name_plural = _('stock operations')
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=OperationKind.values), name='chk_stock_operations_kind'),
            models.CheckConstraint(
                condition=Q(is_deleted=True, void_reason__gt='') | Q(is_deleted=False, void_reason=''),
                name='chk_stock_operations_void_reason',
            ),
            models.CheckConstraint(
                condition=Q(over_capacity_ack=False) | Q(kind__in=ARRIVING_OPERATIONS),
                name='chk_stock_operations_ack_on_arrival',
            ),
            models.CheckConstraint(
                condition=Q(size_mix_ack=False) | Q(kind__in=ARRIVING_OPERATIONS),
                name='chk_stock_operations_size_mix_ack_on_arrival',
            ),
            models.CheckConstraint(
                condition=Q(health_event__isnull=True) | Q(kind__in=[OperationKind.MORTALITY, OperationKind.CULL]),
                name='chk_stock_operations_health_event',
            ),
        ]
        indexes = [models.Index(fields=['date'])]

    @property
    def escape(self):
        """Its escape record, or None: a count adjustment with one is an escape, and is named so wherever it is listed."""
        return getattr(self, 'escape_record', None)

    @property
    def opening(self):
        """Its opening balance, or None: a stocking with one is an opening balance, and is named so wherever it is listed."""
        return getattr(self, 'opening_balance', None)

    def kind_label(self):
        """Its kind as a list names it: a stocking with an opening balance is an opening balance."""
        return gettext('Opening balance') if self.opening is not None else self.get_kind_display()

    def __str__(self):
        if self.opening is not None:
            return f'{gettext("Opening balance")} {self.date.isoformat()}'
        if self.escape is not None:
            line = next(iter(self.movements.all()), None)
            if line is not None:
                return gettext('Escape of %(fish)d fish from %(unit)s, %(date)s') % {
                    'fish': abs(line.count_delta), 'unit': line.unit.code, 'date': self.date.isoformat()}
        return f'{self.get_kind_display()} {self.date.isoformat()}'


def _sign_rule():
    """+ into the unit, − out of it, 0 for a weighing, either way (never 0) for an adjustment."""
    return (Q(kind__in=ARRIVALS, count_delta__gt=0) | Q(kind__in=REMOVALS, count_delta__lt=0)
            | Q(kind=MovementKind.WEIGHING, count_delta=0) | (Q(kind=MovementKind.ADJUSTMENT) & ~Q(count_delta=0)))


def _reason_rule():
    rule = Q(~Q(kind__in=list(REASONS)), reason='')
    for kind, reasons in REASONS.items():
        rule |= Q(kind=kind, reason__in=reasons.values)
    return rule


def _sample_rule():
    """No sample, or a weighing's sample: fish weighed and their total weight, the average their quotient
    to 0.0001 g."""
    exact = F('sample_weight_kg') * 1000 / F('sample_count')
    half = Decimal('0.00005')
    return (Q(sample_count__isnull=True, sample_weight_kg__isnull=True)
            | Q(kind=MovementKind.WEIGHING, sample_count__gt=0, sample_weight_kg__gt=0,
                avg_weight_g__gte=exact - half, avg_weight_g__lte=exact + half))


class WeightSource(AuditedModel):
    """How an average weight was measured: reference data (Setup › Reference data › Weight sources). Every weighing
    line names its source, so "the measured points of a batch in a unit" are read one way whatever measured them
    (farm/feeding/read.py, `measured_points`): a sample weighed by hand today (the seeded source, code `manual`, which
    a weighing takes when it names none), a camera's biomass estimate later, as one more row here and no second path.

    The seeded source is kept (it is what a weighing without a source means), and a source weighings name is not
    deleted: the ledger's lines are history."""

    MANUAL = 'manual'

    name = models.CharField(_('Name'), max_length=100)
    code = models.SlugField(_('Code'), max_length=30)
    notes = models.CharField(_('Notes'), max_length=500, blank=True)

    class Meta:
        db_table = 'weight_sources'
        ordering = ['name']
        verbose_name = _('weight source')
        verbose_name_plural = _('weight sources')
        constraints = [
            models.UniqueConstraint(Lower('name'), condition=Q(is_deleted=False), name='uq_weight_sources_name_live',
                                    violation_error_message=_('Another weight source already has this name.')),
            models.UniqueConstraint(fields=['code'], name='uq_weight_sources_code',
                                    violation_error_message=_('Another weight source already has this code.')),
            # The source a weighing takes when it names none is never deleted (migration 0052 makes it).
            models.CheckConstraint(condition=~Q(code='manual') | Q(is_deleted=False), name='chk_weight_sources_manual_kept'),
        ]

    def __str__(self):
        return self.name

    @classmethod
    def manual(cls):
        """The source of a weighing that names none: a sample weighed by hand."""
        return cls.objects.get(code=cls.MANUAL)

    def delete_blockers(self):
        if self.code == self.MANUAL:
            return [gettext('It is the source of a weighing that names none: it is kept.')]
        count = self.weighings.count()
        return [ngettext('%(count)d weighing names it: it is kept with them.',
                         '%(count)d weighings name it: it is kept with them.', count) % {'count': count}] if count else []


def _check(name, condition):
    return models.CheckConstraint(condition=condition, name=f'chk_stock_movements_{name}')


class StockMovement(models.Model):
    """A line of the stock ledger: fish of one batch into (+) or out of (−) one unit, or weighed there
    (0), as part of an operation. Lines are never edited: their operation is voided instead.

    `avg_weight_g` is a measured average: the fish stocked, the fish weighed, or fish of a stated size
    taken out (grading). Empty on a removal, the fish leave at the share's average; empty on a
    transfer in, they arrive as they left the source. Biomass is never stored: it is the fold of the
    lines in date order. Grams to 0.0001 g, so eggs and larvae keep their weight (STK-51)."""

    id = models.BigAutoField(primary_key=True)   # the order of entry, which orders lines within a day
    operation = models.ForeignKey(StockOperation, on_delete=models.CASCADE, related_name='movements',
                                  verbose_name=_('Operation'))
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name='movements', verbose_name=_('Batch'))
    unit = models.ForeignKey(Tank, on_delete=models.PROTECT, related_name='movements', verbose_name=_('Unit'))
    kind = models.CharField(_('Line'), max_length=12, choices=MovementKind.choices)
    count_delta = models.IntegerField(_('Fish'))
    avg_weight_g = models.DecimalField(_('Average weight (g)'), max_digits=12, decimal_places=4, null=True,
                                       blank=True)
    # A weighed total, a separate fact from the book: the dead fish of a mortality, a harvest's catch.
    measured_weight_kg = models.DecimalField(_('Weighed (kg)'), max_digits=14, decimal_places=3, null=True,
                                             blank=True)
    pair = models.PositiveSmallIntegerField(null=True, blank=True)   # transfer out ↔ in of one operation
    reason = models.CharField(_('Reason'), max_length=20, blank=True)
    size_class = models.CharField(_('Size class'), max_length=30, blank=True)
    sample_count = models.PositiveIntegerField(_('Fish weighed'), null=True, blank=True)
    sample_weight_kg = models.DecimalField(_('Their weight (kg)'), max_digits=12, decimal_places=4, null=True,
                                           blank=True)
    # How a weighing's average was measured (reference data): every weighing line has one, no other line does.
    weight_source = models.ForeignKey(WeightSource, null=True, blank=True, on_delete=models.PROTECT,
                                      related_name='weighings', verbose_name=_('Weight source'))

    class Meta:
        db_table = 'stock_movements'
        ordering = ['id']
        verbose_name = _('stock line')
        verbose_name_plural = _('stock lines')
        constraints = [
            _check('kind', Q(kind__in=MovementKind.values)),
            _check('sign', _sign_rule()),
            _check('weight_positive', Q(avg_weight_g__isnull=True) | Q(avg_weight_g__gt=0)),
            _check('weight_required', ~Q(kind__in=[MovementKind.INPUT, MovementKind.WEIGHING])
                   | Q(avg_weight_g__isnull=False)),
            _check('weight_inherited', ~Q(kind=MovementKind.TRANSFER_IN) | Q(avg_weight_g__isnull=True)),
            _check('pair', Q(kind__in=PAIRED, pair__isnull=False) | (~Q(kind__in=PAIRED) & Q(pair__isnull=True))),
            _check('measured', Q(measured_weight_kg__isnull=True)
                   | Q(measured_weight_kg__gt=0, kind__in=[MovementKind.HARVEST, MovementKind.MORTALITY,
                                                           MovementKind.CULL, MovementKind.DELIVERY])),
            _check('reason', _reason_rule()),
            # An escape takes fish out of the book: a count adjustment up is a recount, never an escape.
            _check('escape_removes', ~Q(kind=MovementKind.ADJUSTMENT, reason=AdjustmentReason.ESCAPE)
                   | Q(count_delta__lt=0)),
            _check('size_class', Q(size_class='') | Q(kind__in=PAIRED)),
            # A harvest is weighed: its kilos are the farm's own fact beside the book (STK-29, STK-30).
            _check('harvest_weighed', ~Q(kind=MovementKind.HARVEST) | Q(measured_weight_kg__isnull=False)),
            # A weighing says how it was measured, and only a weighing does (farm.WeightSource).
            _check('weight_source', Q(kind=MovementKind.WEIGHING, weight_source__isnull=False)
                   | (~Q(kind=MovementKind.WEIGHING) & Q(weight_source__isnull=True))),
            _check('sample', _sample_rule()),
            models.UniqueConstraint(fields=['operation', 'unit', 'batch', 'kind', 'pair'], nulls_distinct=False,
                                    name='uq_stock_movements_line'),
        ]
        indexes = [models.Index(fields=['unit', 'batch']), models.Index(fields=['batch'])]

    def __str__(self):
        return f'{self.unit.code} {self.batch.code} {self.count_delta:+d}'

    def reason_label(self):
        """The reason as its list names it (a mortality's cause, a cull's reason...)."""
        choices = REASONS.get(self.kind)
        return choices(self.reason).label if choices and self.reason else self.reason


# ---- what an escape and a delivery add to their operation -------------------------------------------------
class LiveOperations(models.Manager):
    """The records whose operation counts: it is not voided."""

    def get_queryset(self):
        return super().get_queryset().filter(operation__is_deleted=False)


class EscapeRecord(models.Model):
    """What a line cannot say of an escape (akvakulturdriftsforskriften § 38, § 41 c, § 57 b): the cause, whether it is
    only suspected, the time it was found (the day is the operation's), the health status of the fish and the fish
    recaptured, as known when it is recorded. One per escape operation (its primary key), written with it by the stock
    service, never edited: voiding the escape voids it with it. The fish escaped, their species, unit and average
    weight are the operation's line and the fold's; the notice to Fiskeridirektoratet is a regulatory report that reads
    this record (Production › Reports). An escape from several units is recorded for each."""

    operation = models.OneToOneField(StockOperation, primary_key=True, on_delete=models.PROTECT,
                                     related_name='escape_record', limit_choices_to={'kind': OperationKind.ADJUSTMENT},
                                     verbose_name=_('Operation'))
    found_time = models.TimeField(_('Time found'), null=True, blank=True)    # on the site's clock
    suspected = models.BooleanField(_('Only suspected'), default=False)
    cause = models.CharField(_('Cause'), max_length=2000)
    health_status = models.CharField(_('Health status of the fish'), max_length=1000, blank=True)
    recaptured = models.PositiveIntegerField(_('Fish recaptured'), null=True, blank=True)

    objects = LiveOperations()
    all_objects = models.Manager()

    class Meta:
        db_table = 'escape_records'
        base_manager_name = 'all_objects'
        verbose_name = _('escape record')
        verbose_name_plural = _('escape records')
        constraints = [models.CheckConstraint(condition=~Q(cause=''), name='chk_escape_records_cause')]

    def __str__(self):
        return str(self.operation)


SITE_NUMBER = [MinValueValidator(10000), MaxValueValidator(99999)]


class DeliveryRecord(models.Model):
    """Where live fish were delivered out of the company (a customer's site, a sale of smolt): who received them and, when
    it has one, the receiving site's lokalitetsnummer. One per delivery operation (its primary key), written with it by
    the stock service, never edited, voided with it. It is the smolt report's fish moved out of the site and the monthly
    biomass report's fish moved to another site (docs/regulatory-reports.md, D-10)."""

    operation = models.OneToOneField(StockOperation, primary_key=True, on_delete=models.PROTECT,
                                     related_name='delivery_record', limit_choices_to={'kind': OperationKind.DELIVERY},
                                     verbose_name=_('Operation'))
    destination = models.CharField(_('Delivered to'), max_length=200)
    destination_site_number = models.PositiveIntegerField(_('Receiving site’s lokalitetsnummer'), null=True,
                                                          blank=True, validators=SITE_NUMBER)

    objects = LiveOperations()
    all_objects = models.Manager()

    class Meta:
        db_table = 'delivery_records'
        base_manager_name = 'all_objects'
        verbose_name = _('delivery record')
        verbose_name_plural = _('delivery records')
        constraints = [
            models.CheckConstraint(condition=~Q(destination=''), name='chk_delivery_records_destination'),
            models.CheckConstraint(
                condition=Q(destination_site_number__isnull=True)
                | Q(destination_site_number__gte=10000, destination_site_number__lte=99999),
                name='chk_delivery_records_site_number'),
        ]

    def __str__(self):
        return f'{self.operation} → {self.destination}'


class OpeningBalance(models.Model):
    """What makes a stocking the opening balance of fish the farm already had when it started using the platform (F-197):
    the source document the counts come from. One per such stocking (its primary key), written with it by the stock service
    on the platform owner's right (record_opening_balance), never edited, voided with it.

    The stocking is dated the takeover day, inside the correction window, with the count and the average weight of that
    day; its batch's stocking date is the real one, any day before (beyond the window by design), and its year class is
    given. Every read of the ledger takes the fish as stock that was already there: their stay starts on the real stocking
    date (days stocked), their average counts as measured on the takeover day, and the reports never count them as fish
    stocked. A stocking with one is an opening balance, and is named so wherever it is listed."""

    operation = models.OneToOneField(StockOperation, primary_key=True, on_delete=models.PROTECT,
                                     related_name='opening_balance', limit_choices_to={'kind': OperationKind.INPUT},
                                     verbose_name=_('Operation'))
    document = models.CharField(_('Source document'), max_length=300)

    objects = LiveOperations()
    all_objects = models.Manager()

    class Meta:
        db_table = 'opening_balances'
        base_manager_name = 'all_objects'
        verbose_name = _('opening balance')
        verbose_name_plural = _('opening balances')
        constraints = [models.CheckConstraint(condition=~Q(document=''), name='chk_opening_balances_document')]

    def __str__(self):
        return str(self.operation)
