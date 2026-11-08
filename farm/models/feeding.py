from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _

from core.models import AuditedModel

from .equipment import Equipment, EquipmentType
from .feed import Feed
from .tank import Tank

MIN_AMOUNT_KG = Decimal('0.001')    # 1 g: a fry ration
MAX_AMOUNT_KG = 100000              # 100 t a record, far above a day's feed of the largest sea cage
MAX_MEALS = 48                      # a meal every half hour


def feeders_for(unit):
    """The feeders a feeding of `unit` may name: live equipment of the Feeding category on the unit's
    site, or, for a unit whose production department has no site, in its production department."""
    site_id = unit.production_department.site_id
    department = unit.production_department
    place = Q(production_department__site_id=site_id) if site_id else Q(production_department=department)
    return Equipment.objects.filter(place, equipment_type__category=EquipmentType.Category.FEEDING)


class FeedTarget(models.TextChoices):
    """Whom a feeding is for: the unit's production fish, or the cleaner fish beside them (D-1). Its feed is split
    among the batches of its target only."""
    PRODUCTION = 'production', _('Production fish')
    CLEANER_FISH = 'cleaner_fish', _('Cleaner fish')


class FeedingRecord(AuditedModel):
    """Feed given to one unit on one day: the farm's feeding record. Source table: farm.feeding_records.

    A record is the unit, the day, the feed and its kilos, and optionally the time, the number of meals,
    the feeder and notes; several a day are fine (meals, a feed change). The batches fed are not stored:
    they are the batches the stock ledger has in the unit that day, the feed split between them by their
    book biomass at the start of the day (farm/feeding/fold.py), so a backdated stock operation can never
    leave a stored batch wrong (the source booked feed on whatever batch it was told, FDR-05, FDR-06). A
    feeding needs fish in its unit at the start or the end of its day, and the stock refuses an operation
    that would leave one without (farm/stock/services.py).

    Feed is never written into the stock: FCR, the last feeding and the feed rate are read from these rows
    and the ledger (farm/feeding/read.py); nothing is stored that can drift. Nothing is edited either: a
    record is voided with its reason (its soft delete, as a stock operation) and entered again. Feeding
    never waits for the feed store: no stock is drawn here (FDR-08).

    The links say what deleting the other record does (core.softdelete): a feed or a feeder with live
    records is not deleted (set it to discontinued, or decommissioned); the unit's records stay with a
    deleted unit, as its stock lines do (owner decision Q-F3: history does not block deleting an empty
    unit), and the database refuses a hard delete of a unit they name.

    Not ported: planned amount and variance, waste, cost and currency, method, environment, behaviour,
    duration, fed-by and verified-by (feeding-records §4.1), the meal links of the feeding plans."""

    # DO_NOTHING: kept as they are when their unit is deleted (core.softdelete), like the unit's stock
    # lines; the foreign key in the database still refuses a hard delete.
    unit = models.ForeignKey(Tank, on_delete=models.DO_NOTHING, related_name='feedings', verbose_name=_('Unit'))
    date = models.DateField(_('Date'))
    time = models.TimeField(_('Time'), null=True, blank=True)    # farm-local, as the date
    feed = models.ForeignKey(Feed, on_delete=models.PROTECT, related_name='feedings', verbose_name=_('Feed'))
    target = models.CharField(_('Fed to'), max_length=12, choices=FeedTarget.choices, default=FeedTarget.PRODUCTION)
    amount_kg = models.DecimalField(_('Feed given (kg)'), max_digits=10, decimal_places=3,
                                    validators=[MinValueValidator(MIN_AMOUNT_KG), MaxValueValidator(MAX_AMOUNT_KG)])
    meals = models.PositiveSmallIntegerField(_('Meals'), null=True, blank=True,
                                             validators=[MinValueValidator(1), MaxValueValidator(MAX_MEALS)])
    feeder = models.ForeignKey(
        Equipment, null=True, blank=True, on_delete=models.PROTECT, related_name='feedings', verbose_name=_('Feeder'),
        limit_choices_to={'is_deleted': False, 'equipment_type__category': EquipmentType.Category.FEEDING},
        error_messages={'invalid': _('Choose a feeder: equipment of the Feeding category.')},
    )
    notes = models.CharField(_('Notes'), max_length=2000, blank=True)
    # The person accepted a feeding above FEEDING_ACK_PERCENT of the book biomass a day (owner decision Q-F5).
    high_rate_ack = models.BooleanField(_('Above the usual feed rate, accepted'), default=False)
    void_reason = models.CharField(_('Reason for voiding'), max_length=500, blank=True)

    class Meta:
        db_table = 'feeding_records'
        # Newest first, a record without a time after those of its day with one, then the order of entry:
        # the same rows in the same order on every page (the source sorted by date only, FDR-27).
        ordering = ['-date', F('time').desc(nulls_last=True), '-created_at']
        verbose_name = _('feeding record')
        verbose_name_plural = _('feeding records')
        constraints = [
            models.CheckConstraint(condition=Q(amount_kg__gte=MIN_AMOUNT_KG, amount_kg__lte=MAX_AMOUNT_KG),
                                   name='chk_feeding_records_amount'),
            models.CheckConstraint(condition=Q(target__in=FeedTarget.values), name='chk_feeding_records_target'),
            models.CheckConstraint(condition=Q(meals__isnull=True) | Q(meals__gte=1, meals__lte=MAX_MEALS),
                                   name='chk_feeding_records_meals'),
            models.CheckConstraint(
                condition=Q(is_deleted=True, void_reason__gt='') | Q(is_deleted=False, void_reason=''),
                name='chk_feeding_records_void_reason',
            ),
        ]
        indexes = [models.Index(fields=['unit', 'date']), models.Index(fields=['date'])]

    def __str__(self):
        return f'{self.unit.code} {self.date.isoformat()} {self.amount_kg.normalize():f} kg'

    def clean(self):
        super().clean()
        if self.feeder_id and self.unit_id and not feeders_for(self.unit).filter(pk=self.feeder_id).exists():
            raise ValidationError({'feeder': _('Choose a feeder on the site of %(unit)s.') % {'unit': self.unit.code}})
