"""Harvest: where harvested fish go (the slaughter facilities of Setup › Harvest and logistics), what a harvest
adds to its stock operation (HarvestRecord), and the plans (Operations › Harvest): a target weight per batch
(ProductionPlan) and the harvests and transports planned per unit (HandlingPlanItem).

One ledger, no second stock: a harvest is the stock operation `record_harvest` writes (farm/stock); its
count, round kilos and date stay on its line and the operation. Nothing here holds a count or kilos the
ledger holds; a plan holds intentions, and its actuals are read from the operation that fulfils it."""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils.translation import gettext, gettext_lazy as _, ngettext_lazy

from core.models import ActiveManager, AuditedModel
from core.softdelete import protected
from core.platform import correction_window_days

from .species import Species
from .stock import Batch, MovementKind, OperationKind, StockOperation
from .supplier import Supplier, SupplierLink, SupplyCategory
from .tank import Tank

# Mattilsynet's approval number of an establishment (godkjenningsnummer) as the source's report schemas
# take it: 1 to 6 letters or digits, stored in capitals. The official format is not verified.
APPROVAL_NUMBER = r'^[A-Z0-9]{1,6}$'
APPROVAL_NUMBER_MESSAGE = _('1 to 6 letters or digits, as Mattilsynet gives it.')


class FacilityStatus(models.TextChoices):
    ACTIVE = 'active', _('Active')
    INACTIVE = 'inactive', _('Inactive')


def _coordinates(prefix):
    return [
        models.CheckConstraint(condition=Q(latitude__isnull=True) | Q(latitude__gte=-90, latitude__lte=90),
                               name=f'chk_{prefix}_latitude'),
        models.CheckConstraint(condition=Q(longitude__isnull=True) | Q(longitude__gte=-180, longitude__lte=180),
                               name=f'chk_{prefix}_longitude'),
        models.CheckConstraint(
            condition=Q(latitude__isnull=True, longitude__isnull=True)
            | Q(latitude__isnull=False, longitude__isnull=False),
            name=f'chk_{prefix}_coordinates_paired',
            violation_error_message=_('Latitude and longitude must be provided together.')),
    ]


class SlaughterFacility(AuditedModel):
    """A slaughterhouse harvested fish go to: its name, Mattilsynet's approval number, where it is, the
    species it takes and its operator. Source table: regulatory.slaughter_facilities.

    Every harvest names its facility (HarvestRecord), so a report can be filed per facility; the source filed
    every harvest under one "default" facility (HRV-08) whose flag could disappear (HRV-09), and has none
    here. A facility harvests went to is not deleted: it is set inactive, and new harvests offer only active
    ones that take the batch's species (or that list no species)."""

    Status = FacilityStatus

    name = models.CharField(_('Name'), max_length=150)
    approval_number = models.CharField(_('Approval number'), max_length=6,
                                       validators=[RegexValidator(APPROVAL_NUMBER, APPROVAL_NUMBER_MESSAGE)])
    operator = SupplierLink(
        Supplier, null=True, blank=True, on_delete=models.PROTECT, related_name='slaughter_facilities',
        category=SupplyCategory.SLAUGHTER, verbose_name=_('Operator'),
        error_messages={'invalid': _('Choose a supplier of slaughter and processing.')},
        kept=ngettext_lazy('It operates %(count)d slaughter facility: keep “%(category)s” ticked.',
                           'It operates %(count)d slaughter facilities: keep “%(category)s” ticked.', 'count'),
    )
    # A deleted species keeps its link rows: the link comes back with the species (core.softdelete).
    species = models.ManyToManyField(Species, blank=True, related_name='slaughter_facilities',
                                     db_table='slaughter_facility_species', verbose_name=_('Species it takes'))
    address = models.CharField(_('Address'), max_length=255, blank=True)
    municipality = models.CharField(_('Municipality'), max_length=100, blank=True)
    latitude = models.DecimalField(_('Latitude'), max_digits=9, decimal_places=6, null=True, blank=True,
                                   validators=[MinValueValidator(-90), MaxValueValidator(90)])
    longitude = models.DecimalField(_('Longitude'), max_digits=9, decimal_places=6, null=True, blank=True,
                                    validators=[MinValueValidator(-180), MaxValueValidator(180)])
    capacity_tonnes_per_day = models.DecimalField(_('Capacity (t a day)'), max_digits=8, decimal_places=1,
                                                  null=True, blank=True,
                                                  validators=[MinValueValidator(Decimal('0.1'))])
    status = models.CharField(_('Status'), max_length=10, choices=FacilityStatus.choices,
                              default=FacilityStatus.ACTIVE)
    notes = models.CharField(_('Notes'), max_length=2000, blank=True)

    class Meta:
        db_table = 'slaughter_facilities'
        ordering = ['name']
        verbose_name = _('slaughter facility')
        verbose_name_plural = _('slaughter facilities')
        constraints = [
            models.UniqueConstraint(
                fields=['approval_number'], condition=Q(is_deleted=False), name='uq_slaughter_facilities_approval_live',
                violation_error_message=_('Another slaughter facility already has this approval number.')),
            models.UniqueConstraint(
                Lower('name'), condition=Q(is_deleted=False), name='uq_slaughter_facilities_name_live',
                violation_error_message=_('Another slaughter facility already has this name.')),
            models.CheckConstraint(condition=Q(approval_number__regex=APPROVAL_NUMBER),
                                   name='chk_slaughter_facilities_approval_number',
                                   violation_error_message=APPROVAL_NUMBER_MESSAGE),
            models.CheckConstraint(condition=Q(status__in=FacilityStatus.values),
                                   name='chk_slaughter_facilities_status'),
            models.CheckConstraint(
                condition=Q(capacity_tonnes_per_day__isnull=True) | Q(capacity_tonnes_per_day__gt=0),
                name='chk_slaughter_facilities_capacity'),
            *_coordinates('slaughter_facilities'),
        ]

    def __str__(self):
        return f'{self.name} ({self.approval_number})'

    def save(self, *args, **kwargs):
        self.approval_number = self.approval_number.strip().upper()
        super().save(*args, **kwargs)

    def delete_blockers(self):
        # A harvest's record is not a farm record of its own (core.softdelete does not follow it): say it here.
        count = HarvestRecord.objects.filter(facility=self).count()
        if count:
            return [protected(HarvestRecord, count) + ' ' + gettext('Set it inactive instead.')]
        return []


def offered_facilities(species=None):
    """The facilities a new harvest or plan can name: active ones that take the species, or list none."""
    facilities = SlaughterFacility.objects.filter(status=FacilityStatus.ACTIVE)
    if species is not None:
        facilities = facilities.filter(Q(species=species) | Q(species__isnull=True)).distinct()
    return facilities.order_by('name')


# ---- what a harvest adds to its operation -----------------------------------------------------------
class LiveHarvests(models.Manager):
    """The records of harvests that count: their operation is not voided."""

    def get_queryset(self):
        return super().get_queryset().filter(operation__is_deleted=False)


class HarvestRecord(models.Model):
    """Where a harvest went: the slaughter facility (required) and, when someone else carried the fish, the
    transport supplier and the wellboat or vehicle. One per harvest operation (its primary key), written with
    it by the stock service, never edited: voiding the harvest voids it with it (every read goes through
    the live operation). It holds no count, kilos or date: those are the operation's and its line's.

    It is not an operation's column because seven kinds of operation have no destination; it is the place the
    slaughterhouse's result (gutted kilos per quality class) attaches to later."""

    operation = models.OneToOneField(StockOperation, primary_key=True, on_delete=models.PROTECT,
                                     related_name='harvest_record', limit_choices_to={'kind': OperationKind.HARVEST},
                                     verbose_name=_('Operation'))
    facility = models.ForeignKey(SlaughterFacility, on_delete=models.PROTECT, related_name='harvests',
                                 verbose_name=_('Slaughter facility'))
    transport = SupplierLink(
        Supplier, null=True, blank=True, on_delete=models.PROTECT, related_name='harvest_transports',
        category=SupplyCategory.TRANSPORT, verbose_name=_('Transport'),
        error_messages={'invalid': _('Choose a supplier of wellboat and transport.')},
        kept=ngettext_lazy('It carried %(count)d harvest: keep “%(category)s” ticked.',
                           'It carried %(count)d harvests: keep “%(category)s” ticked.', 'count'),
    )
    vessel = models.CharField(_('Wellboat or vehicle'), max_length=100, blank=True)

    objects = LiveHarvests()
    all_objects = models.Manager()

    class Meta:
        db_table = 'harvest_records'
        base_manager_name = 'all_objects'
        verbose_name = _('harvest record')
        verbose_name_plural = _('harvest records')

    def __str__(self):
        return f'{self.operation} → {self.facility}'

    def clean(self):
        """A new harvest goes to an active facility that takes the harvested batch's species."""
        super().clean()
        line = self.operation.movements.filter(kind=MovementKind.HARVEST).select_related('batch__species').first()
        if line is not None and self.facility_id and \
                not offered_facilities(line.batch.species).filter(pk=self.facility_id).exists():
            raise ValidationError({'facility': gettext(
                'Choose an active slaughter facility that takes %(species)s.') % {'species': line.batch.species}})


# ---- plans --------------------------------------------------------------------------------------------
class LivePlans(ActiveManager):
    """Live plans of batches that exist: a batch whose stocking was voided takes its plans out of sight."""

    def get_queryset(self):
        return super().get_queryset().filter(batch__is_deleted=False)


class ProductionPlan(AuditedModel):
    """A batch's target: the average weight it is grown to for harvest. When it is reached is worked out on
    read from the feeding protocols' projection, never stored; the farm's own wished date is the batch's
    expected harvest, entered when it was stocked (one fact, one place). One live plan per batch."""

    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name='production_plans',
                              verbose_name=_('Batch'))
    target_weight_g = models.DecimalField(_('Target weight (g)'), max_digits=12, decimal_places=4,
                                          validators=[MinValueValidator(Decimal('0.0001'))])
    notes = models.CharField(_('Notes'), max_length=2000, blank=True)

    objects = LivePlans()

    class Meta:
        db_table = 'production_plans'
        ordering = ['batch__code']
        verbose_name = _('production plan')
        verbose_name_plural = _('production plans')
        constraints = [
            models.UniqueConstraint(fields=['batch'], condition=Q(is_deleted=False), name='uq_production_plans_batch',
                                    violation_error_message=_('This batch already has a production plan.')),
            models.CheckConstraint(condition=Q(target_weight_g__gt=0), name='chk_production_plans_target'),
        ]

    def __str__(self):
        return f'{self.batch.code} · {self.target_weight_g.normalize():f} g'


class PlanKind(models.TextChoices):
    """A planned harvest, fulfilled by a harvest operation, or a planned transport, by a transfer."""
    HARVEST = 'harvest', _('Harvest')
    TRANSPORT = 'transport', _('Transport')


# The stock operation that fulfils each kind of plan item.
FULFILLED_BY = {PlanKind.HARVEST: OperationKind.HARVEST, PlanKind.TRANSPORT: OperationKind.TRANSFER}


class PlanStatus(models.TextChoices):
    """Derived, never stored (HandlingPlanItem.status)."""
    PLANNED = 'planned', _('Planned')
    OVERDUE = 'overdue', _('Overdue')
    DONE = 'done', _('Done')
    CANCELLED = 'cancelled', _('Cancelled')


class LivePlanItems(LivePlans):
    """Live plan items of live units: a deleted unit hides its items, and they come back with it."""

    def get_queryset(self):
        return super().get_queryset().filter(unit__is_deleted=False)


class HandlingPlanItem(AuditedModel):
    """A harvest or a transport planned for the fish of one batch in one unit on a day: the fish and round
    kilos meant, where they go (a slaughter facility for a harvest, a unit for a transport), who carries them.

    Its status is derived, never set: cancelled when it has a reason for that, done when the operation that
    fulfils it counts, overdue when its day has passed, planned otherwise. Recording the harvest or the
    transfer from it links the operation in the same transaction (farm/stock/services.py); voiding that
    operation makes it planned again, with nothing to change on the item. Planned against actual: the actual
    fish and kilos are read from the linked operation's lines.

    A deleted unit keeps its items, out of sight, and they come back with it (DO_NOTHING, as its feeding
    records and water samples); a cleared destination is logged by the delete plan."""

    Kind, Status = PlanKind, PlanStatus

    kind = models.CharField(_('Plan'), max_length=10, choices=PlanKind.choices)
    date = models.DateField(_('Date'))
    unit = models.ForeignKey(Tank, on_delete=models.DO_NOTHING, related_name='plan_items', verbose_name=_('Unit'))
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name='plan_items', verbose_name=_('Batch'))
    planned_count = models.PositiveIntegerField(_('Planned fish'), null=True, blank=True,
                                                validators=[MinValueValidator(1)])
    planned_kg = models.DecimalField(_('Planned round weight (kg)'), max_digits=14, decimal_places=3, null=True,
                                     blank=True, validators=[MinValueValidator(Decimal('0.001'))])
    facility = models.ForeignKey(SlaughterFacility, null=True, blank=True, on_delete=models.PROTECT,
                                 related_name='plan_items', verbose_name=_('Slaughter facility'))
    destination_unit = models.ForeignKey(Tank, null=True, blank=True, on_delete=models.SET_NULL,
                                         related_name='planned_arrivals', verbose_name=_('To unit'))
    transport = SupplierLink(
        Supplier, null=True, blank=True, on_delete=models.PROTECT, related_name='planned_transports',
        category=SupplyCategory.TRANSPORT, verbose_name=_('Transport'),
        error_messages={'invalid': _('Choose a supplier of wellboat and transport.')},
        kept=ngettext_lazy('%(count)d planned harvest or transport names it: keep “%(category)s” ticked.',
                           '%(count)d planned harvests or transports name it: keep “%(category)s” ticked.', 'count'),
    )
    vessel = models.CharField(_('Wellboat or vehicle'), max_length=100, blank=True)
    operation = models.ForeignKey(StockOperation, null=True, blank=True, on_delete=models.PROTECT, editable=False,
                                  related_name='plan_items', verbose_name=_('Recorded as'))
    cancelled_reason = models.CharField(_('Cancelled because'), max_length=500, blank=True)
    notes = models.CharField(_('Notes'), max_length=2000, blank=True)

    objects = LivePlanItems()

    class Meta:
        db_table = 'handling_plan_items'
        ordering = ['-date', '-created_at']
        verbose_name = _('planned harvest or transport')
        verbose_name_plural = _('planned harvests and transports')
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=PlanKind.values), name='chk_handling_plan_items_kind'),
            models.CheckConstraint(
                condition=Q(kind=PlanKind.HARVEST, facility__isnull=False, destination_unit__isnull=True)
                | Q(kind=PlanKind.TRANSPORT, facility__isnull=True),
                name='chk_handling_plan_items_destination',
                violation_error_message=_('A harvest goes to a slaughter facility, a transport to a unit.')),
            models.CheckConstraint(condition=Q(planned_count__isnull=True) | Q(planned_count__gt=0),
                                   name='chk_handling_plan_items_count'),
            models.CheckConstraint(condition=Q(planned_kg__isnull=True) | Q(planned_kg__gt=0),
                                   name='chk_handling_plan_items_kg'),
            models.CheckConstraint(condition=~Q(destination_unit=models.F('unit')),
                                   name='chk_handling_plan_items_other_unit',
                                   violation_error_message=_('The fish go to another unit.')),
            # One live item per operation: an operation fulfils one plan.
            models.UniqueConstraint(fields=['operation'], condition=Q(is_deleted=False, operation__isnull=False),
                                    name='uq_handling_plan_items_operation'),
        ]
        indexes = [models.Index(fields=['unit', 'date'], name='plan_items_unit_date_idx')]

    def __str__(self):
        return f'{self.get_kind_display()} · {self.unit.code} · {self.batch.code} · {self.date.isoformat()}'

    @property
    def done(self):
        """Whether the operation that fulfils it counts."""
        return self.operation_id is not None and not self.operation.is_deleted

    def status_on(self, today):
        if self.cancelled_reason:
            return PlanStatus.CANCELLED
        if self.done:
            return PlanStatus.DONE
        return PlanStatus.OVERDUE if self.date < today else PlanStatus.PLANNED

    @property
    def is_open(self):
        """Planned or overdue: not done and not cancelled."""
        return not self.cancelled_reason and not self.done

    def clean(self):
        """What the database cannot check: a done item is not cancelled (void its operation first); a new or
        moved plan names fish that are in the unit now, a day inside the backdating window at the earliest,
        and a slaughter facility that is active and takes the batch's species."""
        from farm.stock.dates import earliest
        from farm.stock.read import fish_of_batch
        super().clean()
        stored = (type(self).all_objects.filter(pk=self.pk).values('unit_id', 'batch_id', 'date', 'facility_id')
                  .first() or {})
        changed = lambda *names: any(stored.get(name) != getattr(self, name) for name in names)
        errors = {}
        if self.cancelled_reason.strip() and self.done:
            errors['cancelled_reason'] = gettext('It is done: void the operation that recorded it first.')
        moved = self.unit_id and self.batch_id and changed('unit_id', 'batch_id')
        if moved and not fish_of_batch(self.batch_id).get(self.unit_id):
            errors['batch'] = gettext('No fish of %(batch)s are in %(unit)s now.') % {
                'batch': self.batch.code, 'unit': self.unit.code}
        if self.unit_id and self.date and changed('date') and self.date < earliest(self.unit):
            errors['date'] = gettext('A plan can be dated at most %(days)d days back.') % {
                'days': correction_window_days()}
        chosen = self.facility_id and self.batch_id and changed('facility_id', 'batch_id')
        if chosen and not offered_facilities(self.batch.species).filter(pk=self.facility_id).exists():
            errors['facility'] = gettext('Choose an active slaughter facility that takes %(species)s.') % {
                'species': self.batch.species}
        if errors:
            raise ValidationError(errors)
