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

from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext, gettext_lazy as _, ngettext_lazy

from core.models import AuditedModel

from .species import Species
from .supplier import Supplier, SupplierLink, SupplyCategory
from .tank import Tank


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


class OperationKind(models.TextChoices):
    """What a person did. Every kind has its dialog except the count adjustment, whose lines a harvest
    that empties a unit writes (fish the book holds beyond the count) and which a dialog can offer later."""
    INPUT = 'input', _('Stocking')
    MORTALITY = 'mortality', _('Mortality')
    CULL = 'cull', _('Cull')
    TRANSFER = 'transfer', _('Transfer')
    GRADING = 'grading', _('Grading')
    WEIGHING = 'weighing', _('Weighing')
    HARVEST = 'harvest', _('Harvest')
    ADJUSTMENT = 'adjustment', _('Count adjustment')


class MovementKind(models.TextChoices):
    INPUT = 'input', _('Stocked')
    MORTALITY = 'mortality', _('Died')
    CULL = 'cull', _('Culled')
    TRANSFER_OUT = 'transfer_out', _('Moved out')
    TRANSFER_IN = 'transfer_in', _('Moved in')
    HARVEST = 'harvest', _('Harvested')
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
    UNKNOWN = 'unknown', _('Unknown')
    OTHER = 'other', _('Other')


class CullReason(models.TextChoices):
    SMALL_SIZE = 'small_size', _('Small size')
    DEFORMED = 'deformed', _('Deformed')
    SICK = 'sick', _('Sick')
    POOR_GROWTH = 'poor_growth', _('Poor growth')
    GRADING = 'grading', _('Grading')
    QUALITY = 'quality', _('Quality')
    OTHER = 'other', _('Other')


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
# Operations that bring fish into a unit: the ones the capacity acknowledgement can belong to.
ARRIVING_OPERATIONS = (OperationKind.INPUT, OperationKind.TRANSFER, OperationKind.GRADING,
                       OperationKind.ADJUSTMENT)
REMOVALS = (MovementKind.MORTALITY, MovementKind.CULL, MovementKind.TRANSFER_OUT, MovementKind.HARVEST)
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
    void_reason = models.CharField(_('Reason for voiding'), max_length=500, blank=True)
    # The key of the form it was entered with (not a secret): the same form sent twice records it once.
    entry_key = models.UUIDField(null=True, blank=True, unique=True, editable=False)

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
        ]
        indexes = [models.Index(fields=['date'])]

    def __str__(self):
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
                                                           MovementKind.CULL])),
            _check('reason', _reason_rule()),
            _check('size_class', Q(size_class='') | Q(kind__in=PAIRED)),
            # A harvest is weighed: its kilos are the farm's own fact beside the book (STK-29, STK-30).
            _check('harvest_weighed', ~Q(kind=MovementKind.HARVEST) | Q(measured_weight_kg__isnull=False)),
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
