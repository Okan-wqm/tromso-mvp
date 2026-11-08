"""The store: where the farm keeps feed (later medicines, chemicals and consumables), the lots it holds and
what came in and went out (Operations › Storage; Company › Facility › Storage locations).

One fact, one place, as in the fish stock (farm/models/stock.py). What arrived, left, moved or was counted
is entered once, as the lines (`InventoryLine`) of an operation a person recorded (`InventoryOperation`);
what is on hand is computed from the live lines and the feeding records (inventory/fold.py). No column
holds a quantity that can be computed, so nothing drifts and nothing needs a reconcile job (the source kept
the stock three times, a projection, a log and a total on each product, and the forms wrote the total,
STR-08). Nothing is edited: an operation is voided with its reason and entered again. The only writer is
inventory/services.py.

Every reference is a link: the site and the feeder of a location, the feed of an item, the item of a lot,
the supplier of a delivery or a return, the lot and the location of a line. The source linked items,
locations and sites by bare ids and kept the supplier as typed text (STR-12, STR-13). The one free text of
a delivery is the supplier's own document number (`reference`), a number, not a link to our data.

Feeding never waits for the store (FDR-08, STR-01): the feed given is read from the feeding records on
read, never drawn here, and a feeding the store's book cannot cover is shown, never refused.
"""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Case, F, Q, Value, When
from django.db.models.functions import Lower, Upper
from django.utils.translation import gettext, gettext_lazy as _, ngettext_lazy

from core.models import CODE, CODE_MESSAGE, AuditedModel, CodedMixin
from farm.models import Equipment, EquipmentType, Feed, Site, Supplier
from farm.models.feed import CURRENCY, CURRENCY_MESSAGE
from farm.models.supplier import SupplierLink, SupplyCategory

# Quantities to the gram, as a feeding record's kilos (FeedingRecord.amount_kg).
QUANTITY = {'max_digits': 14, 'decimal_places': 3}


class LocationKind(models.TextChoices):
    WAREHOUSE = 'warehouse', _('Warehouse')
    SILO = 'silo', _('Silo')
    COLD_ROOM = 'cold_room', _('Cold room')
    CHEMICAL_STORE = 'chemical_store', _('Chemical store')
    MEDICINE_CABINET = 'medicine_cabinet', _('Medicine cabinet')
    OUTDOOR = 'outdoor', _('Outdoor store')


class LocationStatus(models.TextChoices):
    ACTIVE = 'active', _('Active')
    INACTIVE = 'inactive', _('Inactive')


class Unit(models.TextChoices):
    """What an item is counted in, and what a location's capacity is given in (owner decision Q-S2): mass,
    or things counted (packs, bottles, doses). Feed is in kg."""
    KG = 'kg', _('kg')
    UNITS = 'units', _('units')


class StorageLocation(CodedMixin, AuditedModel):
    """A place on a site where the farm keeps stock: a feed warehouse, a silo, a cold room, a medicine
    cabinet. Source table: farm.storage_locations.

    It belongs to a site chosen once, at creation: a location is a place, and its stock and its feeding
    pool would move with it (the source let the site be edited, STR-21). A silo is a location, not
    equipment: lots, deliveries, moves and counts attach to it. It may name the feeder it fills (live
    equipment of the Feeding category on the same site); a later phase can draw a feeder's feeding from
    its silo first. The capacity is optional, in kg or in units counted (owner decision Q-S2): above it the
    overview warns, nothing is refused. An inactive location takes no new arrivals; what it holds still
    shows and can leave. It cannot be deleted while it holds stock, so neither can its site.

    Not ported: temperature and humidity ranges (nothing would read them yet), `used_capacity` (never
    written, STR-20), the `hazmat` kind (with chemicals)."""

    # Defined outside the class so that its Meta can name their values in the constraints.
    Kind, Status = LocationKind, LocationStatus

    # Deleting a site takes its locations with it: refused while one holds stock (delete_blockers).
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='storage_locations',
                             verbose_name=_('Site'))
    name = models.CharField(_('Name'), max_length=100)
    code = models.CharField(_('Code'), max_length=20, validators=[RegexValidator(CODE, CODE_MESSAGE)])
    kind = models.CharField(_('Kind'), max_length=20, choices=Kind.choices)
    # A link of its configuration, not history: deleting the feeder leaves the silo without one, logged.
    feeder = models.ForeignKey(
        Equipment, null=True, blank=True, on_delete=models.SET_NULL, related_name='silos', verbose_name=_('Feeder'),
        limit_choices_to={'is_deleted': False, 'equipment_type__category': EquipmentType.Category.FEEDING},
        error_messages={'invalid': _('Choose a feeder: equipment of the Feeding category.')},
    )
    capacity = models.DecimalField(_('Capacity'), max_digits=14, decimal_places=3, null=True, blank=True,
                                   validators=[MinValueValidator(0)])
    capacity_unit = models.CharField(_('Capacity in'), max_length=10, choices=Unit.choices, blank=True)
    status = models.CharField(_('Status'), max_length=20, choices=Status.choices, default=Status.ACTIVE)
    notes = models.CharField(_('Notes'), max_length=2000, blank=True)

    class Meta:
        db_table = 'storage_locations'
        ordering = ['code']
        verbose_name = _('storage location')
        verbose_name_plural = _('storage locations')
        constraints = [
            models.UniqueConstraint(
                fields=['code'], condition=Q(is_deleted=False), name='uq_storage_locations_code_live',
                violation_error_message=_('Another storage location already uses this code.'),
            ),
            models.UniqueConstraint(
                F('site'), Lower('name'), condition=Q(is_deleted=False), name='uq_storage_locations_name_live',
                violation_error_message=_('Another storage location of this site already has this name.'),
            ),
            models.CheckConstraint(condition=Q(code__regex=CODE), name='chk_storage_locations_code',
                                   violation_error_message=CODE_MESSAGE),
            models.CheckConstraint(condition=Q(kind__in=LocationKind.values), name='chk_storage_locations_kind'),
            models.CheckConstraint(condition=Q(status__in=LocationStatus.values), name='chk_storage_locations_status'),
            models.CheckConstraint(
                condition=Q(feeder__isnull=True) | Q(kind=LocationKind.SILO), name='chk_storage_locations_feeder',
                violation_error_message=_('Only a silo fills a feeder.'),
            ),
            models.CheckConstraint(
                condition=Q(capacity__isnull=True, capacity_unit='')
                | Q(capacity__gte=0, capacity_unit__in=Unit.values),
                name='chk_storage_locations_capacity',
                violation_error_message=_('A capacity needs its unit, and a unit its capacity.'),
            ),
        ]
        indexes = [models.Index(fields=['site'])]

    def clean(self):
        super().clean()
        errors = {}
        if self.feeder_id and self.site_id:
            feeder = Equipment.all_objects.select_related('production_department').get(pk=self.feeder_id)
            if feeder.production_department.site_id != self.site_id:
                errors['feeder'] = _('Choose a feeder on the site of the location.')
        if self.feeder_id and self.kind != LocationKind.SILO:
            errors['feeder'] = _('Only a silo fills a feeder: clear the feeder, or make the location a silo.')
        if (self.capacity is None) != (not self.capacity_unit):
            errors['capacity_unit' if self.capacity is not None else 'capacity'] = _(
                'A capacity needs its unit, and a unit its capacity.')
        if errors:
            raise ValidationError(errors)

    def delete_blockers(self):
        from .read import holds_stock
        if holds_stock(self):
            return [gettext('It holds stock: move it to another location or write it off first.')]
        return []


class InventoryItem(AuditedModel):
    """What the store keeps, one row per product: exactly one link, to a feed now (to a medicine once the
    health module's Medicine is in; chemicals and consumables when their records are ported). One ledger,
    one fold and one write path serve every kind; the rule "exactly one link" lives here, once, and lots,
    lines and the reorder levels link to the item.

    The person never picks an item: they pick a feed, and the write path finds or makes its item. The item
    holds no quantity and no status: the feed's status is the product's (STR-15), the quantity the fold's.
    `category` is the supply category of what it links (feed → feed, a medicine → medicines), worked out
    by the database, so a delivery's supplier can be checked against it and keeps that category."""

    feed = models.ForeignKey(Feed, null=True, blank=True, on_delete=models.PROTECT, related_name='inventory_items',
                             verbose_name=_('Feed'))
    # medicine = models.ForeignKey('farm.Medicine', ...): the second link, added with the health module
    # (see README, Storage): the exactly-one check and `category` then name it too.
    unit = models.CharField(_('Unit'), max_length=10, choices=Unit.choices)
    category = models.GeneratedField(
        expression=Case(When(feed__isnull=False, then=Value(SupplyCategory.FEED.value)), default=Value('')),
        output_field=models.CharField(max_length=20), db_persist=True, verbose_name=_('Category'),
    )

    class Meta:
        db_table = 'inventory_items'
        ordering = ['feed__name']
        verbose_name = _('inventory item')
        verbose_name_plural = _('inventory items')
        constraints = [
            # Exactly one link (one today; with the medicine: feed xor medicine).
            models.CheckConstraint(condition=Q(feed__isnull=False), name='chk_inventory_items_one_link'),
            models.UniqueConstraint(fields=['feed'], condition=Q(is_deleted=False, feed__isnull=False),
                                    name='uq_inventory_items_feed_live'),
            models.CheckConstraint(condition=Q(unit__in=Unit.values), name='chk_inventory_items_unit'),
            # Feed is weighed.
            models.CheckConstraint(condition=Q(feed__isnull=True) | Q(unit=Unit.KG), name='chk_inventory_items_feed_kg'),
        ]

    def __str__(self):
        return str(self.product)

    @property
    def product(self):
        """The feed (later the medicine) this item is."""
        return self.feed


class InventoryLot(AuditedModel):
    """A lot of an item: its number and expiry as printed on the bag or box. Lot number and expiry are
    optional for feed and required for medicines (owner decision Q-S5). A lot is made by the delivery (or
    the count) that first names it and chosen from a list everywhere after; a delivery naming a known lot
    reuses it, and a different expiry for the same lot is refused. Feed without a printed number is
    kept in one lot per expiry date (a lot with no number).

    A lot names no supplier: the deliveries that brought it say who delivered it, so the fact is stored
    once. A lot whose every line is voided goes with them (soft-deleted, logged)."""

    item = models.ForeignKey(InventoryItem, on_delete=models.PROTECT, related_name='lots', verbose_name=_('Item'))
    number = models.CharField(_('Lot number'), max_length=100, blank=True)
    expiry_date = models.DateField(_('Expiry date'), null=True, blank=True)

    class Meta:
        db_table = 'inventory_lots'
        ordering = [F('expiry_date').asc(nulls_last=True), 'number']
        verbose_name = _('lot')
        verbose_name_plural = _('lots')
        constraints = [
            models.UniqueConstraint(
                F('item'), Upper('number'), condition=Q(is_deleted=False) & ~Q(number=''),
                name='uq_inventory_lots_number_live',
                violation_error_message=_('This item already has a lot with this number.'),
            ),
            models.UniqueConstraint(
                fields=['item', 'expiry_date'], condition=Q(is_deleted=False, number=''), nulls_distinct=False,
                name='uq_inventory_lots_unnumbered_live',
            ),
        ]

    def __str__(self):
        return self.number or gettext('No lot number')


class OperationKind(models.TextChoices):
    RECEIPT = 'receipt', _('Delivery')
    ISSUE = 'issue', _('Issue')
    WRITE_OFF = 'write_off', _('Write-off')
    RETURN = 'return', _('Return to supplier')
    TRANSFER = 'transfer', _('Transfer')
    COUNT = 'count', _('Count')


class WriteOffReason(models.TextChoices):
    EXPIRED = 'expired', _('Expired')
    DAMAGED = 'damaged', _('Damaged')
    CONTAMINATED = 'contaminated', _('Contaminated')
    SPILLED = 'spilled', _('Spilled')
    OTHER = 'other', _('Other')


class IssueReason(models.TextChoices):
    """Taken out of the store for a use other than feeding (the feeding records say what was fed)."""
    TREATMENT = 'treatment', _('Treatment')
    SAMPLES = 'samples', _('Samples and analyses')
    MAINTENANCE = 'maintenance', _('Maintenance')
    OTHER = 'other', _('Other')


# The operations with a supplier (and the supplier's document number), and the reason list of each kind
# that has one.
WITH_SUPPLIER = (OperationKind.RECEIPT, OperationKind.RETURN)
REASONS = {OperationKind.WRITE_OFF: WriteOffReason, OperationKind.ISSUE: IssueReason}


def _reason_rule():
    rule = Q(~Q(kind__in=list(REASONS)), reason='')
    for kind, reasons in REASONS.items():
        rule |= Q(kind=kind, reason__in=reasons.values)
    return rule


class InventoryOperation(AuditedModel):
    """One thing a person did in the store, the unit of void and of the activity log: a delivery (lines of
    lots into locations, with the supplier), an issue, a write-off or a return to the supplier (a lot out of
    a location), a transfer (a lot from one location to another, on any site, owner decision Q-S6) or a
    count (one location counted at the end of its day). created_by and created_at say who recorded it and
    when; `date` is the day it happened, on the clock of the sites of its locations.

    A count counts its whole location (`location`): every lot it lists is set to the counted quantity at
    the end of the day, and anything else the book has there to 0. Its variance is computed on read
    against the book of the end of that day, never stored (owner decision Q-S7; the source froze an
    expected quantity at the start and booked a stale variance, STR-05). One person records it; there is no
    approval step in the MVP.

    A return takes stock out (the source's return added it, STR-03). The source's "adjustment", which
    moved the same quantity out and back in, is not ported (STR-02): a count corrects the book."""

    kind = models.CharField(_('Operation'), max_length=12, choices=OperationKind.choices)
    date = models.DateField(_('Date'))
    # The counted location, for a count only. DO_NOTHING: a deleted location keeps its counts, as its lines.
    location = models.ForeignKey(StorageLocation, null=True, blank=True, on_delete=models.DO_NOTHING,
                                 related_name='counts', verbose_name=_('Counted location'))
    supplier = SupplierLink(
        Supplier, null=True, blank=True, on_delete=models.PROTECT, related_name='inventory_operations',
        category_field='lines__lot__item__category', verbose_name=_('Supplier'),
        kept=ngettext_lazy(
            '%(count)d delivery or return of the store names it for “%(category)s”: keep it ticked.',
            '%(count)d deliveries and returns of the store name it for “%(category)s”: keep it ticked.', 'count'),
    )
    # The supplier's own document number (delivery note, invoice, return note): a number, not a link.
    reference = models.CharField(_('Supplier’s document number'), max_length=100, blank=True)
    reason = models.CharField(_('Reason'), max_length=20, blank=True)
    notes = models.CharField(_('Notes'), max_length=2000, blank=True)
    void_reason = models.CharField(_('Reason for voiding'), max_length=500, blank=True)

    class Meta:
        db_table = 'inventory_operations'
        ordering = ['-date', '-created_at']
        verbose_name = _('inventory operation')
        verbose_name_plural = _('inventory operations')
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=OperationKind.values), name='chk_inventory_operations_kind'),
            models.CheckConstraint(
                condition=Q(is_deleted=True, void_reason__gt='') | Q(is_deleted=False, void_reason=''),
                name='chk_inventory_operations_void_reason',
            ),
            models.CheckConstraint(
                condition=Q(kind__in=WITH_SUPPLIER, supplier__isnull=False)
                | (~Q(kind__in=WITH_SUPPLIER) & Q(supplier__isnull=True, reference='')),
                name='chk_inventory_operations_supplier',
            ),
            models.CheckConstraint(condition=_reason_rule(), name='chk_inventory_operations_reason'),
            models.CheckConstraint(
                condition=Q(kind=OperationKind.COUNT, location__isnull=False)
                | (~Q(kind=OperationKind.COUNT) & Q(location__isnull=True)),
                name='chk_inventory_operations_count_location',
            ),
        ]
        indexes = [models.Index(fields=['date'])]

    def __str__(self):
        return f'{self.get_kind_display()} {self.date.isoformat()}'

    def reason_label(self):
        """The reason as its list names it."""
        choices = REASONS.get(self.kind)
        return choices(self.reason).label if choices and self.reason else ''


class LineKind(models.TextChoices):
    IN = 'in', _('Delivered')
    OUT = 'out', _('Taken out')
    TRANSFER_OUT = 'transfer_out', _('Moved out')
    TRANSFER_IN = 'transfer_in', _('Moved in')
    COUNT = 'count', _('Counted')


ARRIVALS = (LineKind.IN, LineKind.TRANSFER_IN)
DEPARTURES = (LineKind.OUT, LineKind.TRANSFER_OUT)
PAIRED = (LineKind.TRANSFER_OUT, LineKind.TRANSFER_IN)


def _check(name, condition, message=None):
    kwargs = {'violation_error_message': message} if message else {}
    return models.CheckConstraint(condition=condition, name=f'chk_inventory_lines_{name}', **kwargs)


class InventoryLine(models.Model):
    """A line of the store's ledger: a quantity of one lot into (+) or out of (−) one location, or counted
    there (the quantity found), as part of an operation. Lines are never edited: their operation is voided
    instead. A delivered line may carry what one unit of it cost, with the currency; on hand × that cost
    is the value the overview shows per currency, never added across currencies (STR-20)."""

    id = models.BigAutoField(primary_key=True)   # the order of entry, which orders lines within a day
    operation = models.ForeignKey(InventoryOperation, on_delete=models.CASCADE, related_name='lines',
                                  verbose_name=_('Operation'))
    lot = models.ForeignKey(InventoryLot, on_delete=models.PROTECT, related_name='lines', verbose_name=_('Lot'))
    location = models.ForeignKey(StorageLocation, on_delete=models.PROTECT, related_name='lines',
                                 verbose_name=_('Location'))
    kind = models.CharField(_('Line'), max_length=12, choices=LineKind.choices)
    quantity = models.DecimalField(_('Quantity'), **QUANTITY)
    pair = models.PositiveSmallIntegerField(null=True, blank=True)   # transfer out ↔ in of one operation
    unit_cost = models.DecimalField(_('Unit cost'), max_digits=14, decimal_places=4, null=True, blank=True)
    currency = models.CharField(_('Currency'), max_length=3, blank=True,
                                validators=[RegexValidator(CURRENCY, CURRENCY_MESSAGE)])

    class Meta:
        db_table = 'inventory_lines'
        ordering = ['id']
        verbose_name = _('inventory line')
        verbose_name_plural = _('inventory lines')
        constraints = [
            _check('kind', Q(kind__in=LineKind.values)),
            _check('sign', Q(kind__in=ARRIVALS, quantity__gt=0) | Q(kind__in=DEPARTURES, quantity__lt=0)
                   | Q(kind=LineKind.COUNT, quantity__gte=0)),
            _check('pair', Q(kind__in=PAIRED, pair__isnull=False) | (~Q(kind__in=PAIRED) & Q(pair__isnull=True))),
            _check('cost', Q(unit_cost__isnull=True, currency='')
                   | Q(kind=LineKind.IN, unit_cost__isnull=False, unit_cost__gte=0, currency__regex=CURRENCY),
                   _('A unit cost needs its currency, and a currency a unit cost.')),
            models.UniqueConstraint(fields=['operation', 'lot', 'location', 'kind', 'pair'], nulls_distinct=False,
                                    name='uq_inventory_lines_line'),
        ]
        indexes = [models.Index(fields=['lot', 'location']), models.Index(fields=['location'])]

    def __str__(self):
        return f'{self.location.code} {self.lot} {self.quantity.normalize():f}'


class ReorderLevel(models.Model):
    """Below this quantity of an item in a location the overview says "low stock" (owner decision Q-S4): a
    row of the location's Reorder levels list, saved as a whole list (core.crud.RowList), so it has no
    update or soft-delete columns. What a later purchasing agent reads to propose an order."""

    location = models.ForeignKey(StorageLocation, on_delete=models.CASCADE, related_name='reorder_levels',
                                 verbose_name=_('Location'))
    item = models.ForeignKey(InventoryItem, on_delete=models.PROTECT, related_name='reorder_levels',
                             verbose_name=_('Item'))
    level = models.DecimalField(_('Reorder level'), validators=[MinValueValidator(Decimal('0.001'))], **QUANTITY)
    created_at = models.DateTimeField(_('Created at'), auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
        verbose_name=_('Created by'),
    )

    class Meta:
        db_table = 'inventory_reorder_levels'
        ordering = ['item__feed__name']
        verbose_name = _('reorder level')
        verbose_name_plural = _('reorder levels')
        constraints = [
            models.UniqueConstraint(fields=['location', 'item'], name='uq_inventory_reorder_levels_item',
                                    violation_error_message=_('One reorder level per item.')),
            models.CheckConstraint(condition=Q(level__gt=0), name='chk_inventory_reorder_levels_level'),
        ]

    def __str__(self):
        return f'{self.item}: {self.level.normalize():f} {self.item.unit}'
