from decimal import Decimal
from functools import reduce
from operator import add

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import F, Q, Value
from django.db.models.functions import Coalesce, Lower
from django.db.models.lookups import LessThanOrEqual
from django.utils.translation import gettext_lazy as _, ngettext, ngettext_lazy

from core.models import CODE, CODE_MESSAGE, AuditedModel, CodedMixin

from .species import Species
from .stock import InputStage
from .supplier import Supplier, SupplierLink, SupplyCategory

# The proximate analysis of a feed as fed, in % of the feed as delivered: protein, fat, carbohydrate (the
# nitrogen-free extract, NFE), fibre, ash and moisture are the parts of the whole feed, so together they
# are at most 100 %. Phosphorus is a mineral inside the ash, so it is not one of the parts.
FRACTIONS = ('protein_pct', 'fat_pct', 'nfe_pct', 'fibre_pct', 'ash_pct', 'moisture_pct')
PERCENTAGES = (*FRACTIONS, 'phosphorus_pct')
ENERGIES = ('gross_energy_mj_kg', 'digestible_energy_mj_kg')
# The most energy a feed can hold: pure fat has about 39.5 MJ/kg.
MAX_ENERGY = 40
PERCENT = [MinValueValidator(0), MaxValueValidator(100)]
ENERGY = [MinValueValidator(0), MaxValueValidator(MAX_ENERGY)]
# Pellet sizes as a feeder's calibrations write them (FeederCalibration.feed_size_mm): the same column
# and bounds, so a feed's size finds a feeder's calibration by equality.
PELLET_SIZE = [MinValueValidator(Decimal('0.01')), MaxValueValidator(100)]
# The heaviest fish a feed can be given for: 1 tonne, far above any farmed fish.
MAX_WEIGHT_G = 1000000
CURRENCY = r'^[A-Z]{3}$'

FRACTIONS_MESSAGE = _('Protein, fat, carbohydrate, fibre, ash and moisture are parts of the feed as fed: together '
                      'they cannot add up to more than 100 per cent.')
PHOSPHORUS_MESSAGE = _('Phosphorus is part of the ash: it cannot be more than the ash.')
DIGESTIBLE_MESSAGE = _('The digestible energy cannot be more than the gross energy.')
CURRENCY_MESSAGE = _('The currency is a three-letter code, e.g. NOK or EUR.')
PRICE_CURRENCY_MESSAGE = _('A price needs its currency, and a currency needs a price.')
WEIGHT_BAND_MESSAGE = _('The lower weight must be below the upper weight.')
SAME_STAGE_MESSAGE = _('Two rows have the same species and life stage.')


class FeedType(models.TextChoices):
    """What the feed is made for, the source's FeedType."""
    LARVAL = 'larval', _('Larval feed')
    STARTER = 'starter', _('Starter feed')
    FRY = 'fry', _('Fry feed')
    GROWER = 'grower', _('Grower feed')
    FINISHER = 'finisher', _('Finisher feed')
    BROODSTOCK = 'broodstock', _('Broodstock feed')
    MEDICATED = 'medicated', _('Medicated feed')
    OTHER = 'other', _('Other')


class Buoyancy(models.TextChoices):
    """How the pellet behaves in the water: floating feed stays at the surface (tanks, where uneaten feed
    is seen), sinking and slow-sinking feed is for sea cages and deep tanks."""
    FLOATING = 'floating', _('Floating')
    SLOW_SINKING = 'slow_sinking', _('Slow sinking')
    SINKING = 'sinking', _('Sinking')


class FeedStatus(models.TextChoices):
    ACTIVE = 'active', _('Active')
    INACTIVE = 'inactive', _('Inactive')
    DISCONTINUED = 'discontinued', _('Discontinued')


# The life stage of the fish a feed suits: "every stage" (when the weight band alone says it) and the
# stages a batch is stocked at (InputStage, one list of life stages for the farm), without eggs, which are
# not fed. A batch's stage and a suitability row's stage compare by value.
GrowthStage = models.TextChoices('GrowthStage', [
    ('ALL', ('all', _('Every stage'))),
    *[(stage.name, (stage.value, stage.label)) for stage in InputStage if stage is not InputStage.EGGS],
])


def _fractions_total():
    """The sum of the analysis' parts, a blank part counting as 0."""
    return reduce(add, [Coalesce(F(name), Value(Decimal('0'))) for name in FRACTIONS])


class Feed(CodedMixin, AuditedModel):
    """A feed the farm uses: its maker, what it is made for, its pellet and its analysis, and the species
    and fish weights it suits. Source table: farm.feeds.

    The manufacturer is a live supplier of feed (Purchasing › Suppliers), as a SupplierLink: such a
    supplier keeps the feed category while its feeds are registered, and cannot be deleted while a live
    feed names it (PROTECT): the manufacturer is part of what the feed is, for its declaration and its
    traceability, so the supplier is set inactive or blocked instead, or the feed is given another
    manufacturer first.

    The analysis is as fed, in % of the feed as delivered: protein, fat, carbohydrate (NFE), fibre, ash and
    moisture add up to at most 100 %, phosphorus is at most the ash, the digestible energy at most the
    gross energy; every rule is a database check too. Which species, life stages and fish weights the feed
    suits are rows of their own (FeedSuitability), saved as a list on the feed's Suitable for tab.

    The status is the product's, not the stock's: stock levels come from the stock records.

    Differences from the source: the manufacturer is a link to a supplier of feed (the source had a free
    text, a brand and a link to any supplier); the analysis is typed columns instead of a JSON object read
    under two names (`energy` and `grossEnergy`); the suitability rows are written and read on this tab
    (the source accepted them on create only and never returned them); the weight band is per species
    and stage (the source also had one per feed, and dropped its upper end); no stock or expiry status.
    Not ported: brand, description, pellet size label, product stage text, ingredients text, unit size
    and unit price, the storage conditions, shelf life and expiry date (the stock tab), the documents,
    the environmental impact, the feeding curves and tables (the feeding tables tab), the sites, and the
    second status flag `isActive`."""

    # Defined outside the class so that its Meta can name their values in the constraints.
    Type, Buoyancy, Status = FeedType, Buoyancy, FeedStatus

    name = models.CharField(_('Name'), max_length=255)
    code = models.CharField(_('Code'), max_length=50, validators=[RegexValidator(CODE, CODE_MESSAGE)])
    manufacturer = SupplierLink(
        Supplier, null=True, blank=True, on_delete=models.PROTECT, related_name='feeds',
        category=SupplyCategory.FEED, verbose_name=_('Manufacturer'),
        error_messages={'invalid': _('Choose a supplier of feed.')},
        kept=ngettext_lazy(
            '%(count)d feed is made by it: keep “%(category)s” ticked, or choose another manufacturer for it '
            'first.',
            '%(count)d feeds are made by it: keep “%(category)s” ticked, or choose another manufacturer for them '
            'first.', 'count'),
    )
    feed_type = models.CharField(_('Feed type'), max_length=20, choices=FeedType.choices)
    pellet_size_mm = models.DecimalField(_('Pellet size (mm)'), max_digits=5, decimal_places=2, null=True,
                                         blank=True, validators=PELLET_SIZE)
    buoyancy = models.CharField(_('Buoyancy'), max_length=20, blank=True, choices=Buoyancy.choices)
    status = models.CharField(_('Status'), max_length=20, choices=FeedStatus.choices, default=FeedStatus.ACTIVE)
    protein_pct = models.DecimalField(_('Crude protein (%)'), max_digits=5, decimal_places=2, null=True,
                                      blank=True, validators=PERCENT)
    fat_pct = models.DecimalField(_('Crude fat (%)'), max_digits=5, decimal_places=2, null=True, blank=True,
                                  validators=PERCENT)
    nfe_pct = models.DecimalField(_('Carbohydrate, NFE (%)'), max_digits=5, decimal_places=2, null=True,
                                  blank=True, validators=PERCENT)
    fibre_pct = models.DecimalField(_('Crude fibre (%)'), max_digits=5, decimal_places=2, null=True, blank=True,
                                    validators=PERCENT)
    ash_pct = models.DecimalField(_('Ash (%)'), max_digits=5, decimal_places=2, null=True, blank=True,
                                  validators=PERCENT)
    moisture_pct = models.DecimalField(_('Moisture (%)'), max_digits=5, decimal_places=2, null=True, blank=True,
                                       validators=PERCENT)
    phosphorus_pct = models.DecimalField(_('Phosphorus (%)'), max_digits=5, decimal_places=2, null=True,
                                         blank=True, validators=PERCENT)
    gross_energy_mj_kg = models.DecimalField(_('Gross energy (MJ/kg)'), max_digits=5, decimal_places=2, null=True,
                                             blank=True, validators=ENERGY)
    digestible_energy_mj_kg = models.DecimalField(_('Digestible energy (MJ/kg)'), max_digits=5, decimal_places=2,
                                                  null=True, blank=True, validators=ENERGY)
    price_per_kg = models.DecimalField(_('Price per kg'), max_digits=10, decimal_places=2, null=True, blank=True,
                                       validators=[MinValueValidator(Decimal('0.01')), MaxValueValidator(100000)])
    currency = models.CharField(_('Currency'), max_length=3, blank=True,
                                validators=[RegexValidator(CURRENCY, CURRENCY_MESSAGE)])
    notes = models.CharField(_('Notes'), max_length=2000, blank=True)
    # The species it suits, through the suitability rows. A deleted species keeps its rows, out of sight:
    # they come back with the species (core.softdelete, FeedSuitability.objects).
    species = models.ManyToManyField(Species, through='FeedSuitability', related_name='feeds', blank=True,
                                     verbose_name=_('Suitable for'))

    class Meta:
        db_table = 'feeds'
        ordering = ['name']
        verbose_name = _('feed')
        verbose_name_plural = _('feeds')
        constraints = [
            models.UniqueConstraint(
                fields=['code'], condition=Q(is_deleted=False), name='uq_feeds_code_live',
                violation_error_message=_('Another feed already uses this code.'),
            ),
            models.UniqueConstraint(
                Lower('name'), condition=Q(is_deleted=False), name='uq_feeds_name_live',
                violation_error_message=_('Another feed already has this name.'),
            ),
            models.CheckConstraint(condition=Q(code__regex=CODE), name='chk_feeds_code',
                                   violation_error_message=CODE_MESSAGE),
            models.CheckConstraint(condition=Q(feed_type__in=FeedType.values), name='chk_feeds_feed_type'),
            models.CheckConstraint(condition=Q(buoyancy='') | Q(buoyancy__in=Buoyancy.values), name='chk_feeds_buoyancy'),
            models.CheckConstraint(condition=Q(status__in=FeedStatus.values), name='chk_feeds_status'),
            models.CheckConstraint(condition=Q(pellet_size_mm__gte=Decimal('0.01'), pellet_size_mm__lte=100),
                                   name='chk_feeds_pellet_size'),
            *[models.CheckConstraint(condition=Q(**{f'{name}__gte': 0, f'{name}__lte': 100}),
                                     name=f'chk_feeds_{name}') for name in PERCENTAGES],
            *[models.CheckConstraint(condition=Q(**{f'{name}__gte': 0, f'{name}__lte': MAX_ENERGY}),
                                     name=f'chk_feeds_{name}') for name in ENERGIES],
            models.CheckConstraint(condition=LessThanOrEqual(_fractions_total(), 100), name='chk_feeds_fractions',
                                   violation_error_message=FRACTIONS_MESSAGE),
            models.CheckConstraint(condition=Q(phosphorus_pct__lte=F('ash_pct')), name='chk_feeds_phosphorus_in_ash',
                                   violation_error_message=PHOSPHORUS_MESSAGE),
            models.CheckConstraint(condition=Q(digestible_energy_mj_kg__lte=F('gross_energy_mj_kg')),
                                   name='chk_feeds_digestible_energy', violation_error_message=DIGESTIBLE_MESSAGE),
            models.CheckConstraint(condition=Q(price_per_kg__gte=Decimal('0.01'), price_per_kg__lte=100000),
                                   name='chk_feeds_price'),
            models.CheckConstraint(
                condition=Q(price_per_kg__isnull=True, currency='')
                | Q(price_per_kg__isnull=False, currency__regex=CURRENCY),
                name='chk_feeds_price_currency', violation_error_message=PRICE_CURRENCY_MESSAGE,
            ),
        ]
        indexes = [models.Index(fields=['feed_type']), models.Index(fields=['status'])]

    def clean(self):
        """The rules between fields, with the error on the field to change; the database checks them too."""
        super().clean()
        errors = {}
        filled = [name for name in FRACTIONS if getattr(self, name) is not None]
        if sum((getattr(self, name) for name in filled), Decimal(0)) > 100:
            errors[filled[-1]] = ValidationError(FRACTIONS_MESSAGE)
        if self.phosphorus_pct is not None and self.ash_pct is not None and self.phosphorus_pct > self.ash_pct:
            errors['phosphorus_pct'] = ValidationError(PHOSPHORUS_MESSAGE)
        if (self.digestible_energy_mj_kg is not None and self.gross_energy_mj_kg is not None
                and self.digestible_energy_mj_kg > self.gross_energy_mj_kg):
            errors['digestible_energy_mj_kg'] = ValidationError(DIGESTIBLE_MESSAGE)
        if (self.price_per_kg is None) != (not self.currency):
            errors['currency' if self.price_per_kg is not None else 'price_per_kg'] = ValidationError(
                PRICE_CURRENCY_MESSAGE)
        if errors:
            raise ValidationError(errors)

    def delete_blockers(self):
        # A band of a feeding protocol's table is a plain row of its protocol, which core.softdelete does not
        # follow (as a batch's stock lines), so the link's PROTECT is said here: the rations of the protocol's
        # past days are read with this feed.
        names = sorted(set(self.protocol_bands.filter(protocol__is_deleted=False)
                           .values_list('protocol__name', flat=True)))
        if not names:
            return []
        return [ngettext('The feeding table of %(count)d feeding protocol uses it: %(names)s.',
                         'The feeding tables of %(count)d feeding protocols use it: %(names)s.', len(names))
                % {'count': len(names), 'names': ', '.join(names)}]

    def save(self, *args, **kwargs):
        self.currency = self.currency.strip().upper()
        super().save(*args, **kwargs)


class SuitabilityManager(models.Manager):
    """The rows of live species. A deleted species keeps its rows in the table, out of sight, and they come
    back with it when it is restored; saving a feed's list replaces only the rows it shows."""

    def get_queryset(self):
        return super().get_queryset().filter(species__is_deleted=False)


class FeedSuitability(models.Model):
    """A species and life stage a feed suits, and the fish weights it suits them at. Source table:
    farm.feed_type_species (rows of a feed, despite the name).

    The rows of a feed are saved as a whole list on its Suitable for tab (core.crud.RowList), so they have
    no update or soft-delete columns. One row per feed, species and stage. The weight band is in grams,
    from the lower weight up to, not including, the upper one, so the bands of a feed range (0–5, 5–20 g)
    meet without overlapping; either end can be open.

    Not ported: the recommendation level and the priority (a row says the feed suits; which of the feeds
    that suit a fish is given is the feeding plan's choice), the feeding rate and frequency, the JSON of
    rates per temperature and of expected performance (the feeding tables tab), metadata and `isActive`."""

    # Defined outside the class so that its Meta can name their values in the constraints.
    GrowthStage = GrowthStage

    feed = models.ForeignKey(Feed, on_delete=models.CASCADE, related_name='suitability', verbose_name=_('Feed'))
    # Deleting a species keeps these rows (a many-to-many link of the feed, core.softdelete): they stop
    # showing and come back with the species.
    species = models.ForeignKey(Species, on_delete=models.CASCADE, related_name='feed_suitability',
                                limit_choices_to={'is_deleted': False}, verbose_name=_('Species'))
    growth_stage = models.CharField(_('Life stage'), max_length=20, choices=GrowthStage.choices)
    min_weight_g = models.DecimalField(_('From (g)'), max_digits=10, decimal_places=2, null=True, blank=True,
                                       validators=[MinValueValidator(0), MaxValueValidator(MAX_WEIGHT_G)])
    max_weight_g = models.DecimalField(_('Up to (g)'), max_digits=10, decimal_places=2, null=True, blank=True,
                                       validators=[MinValueValidator(Decimal('0.01')), MaxValueValidator(MAX_WEIGHT_G)])
    notes = models.CharField(_('Notes'), max_length=500, blank=True)
    created_at = models.DateTimeField(_('Created at'), auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
        verbose_name=_('Created by'),
    )

    objects = SuitabilityManager()
    all_objects = models.Manager()

    class Meta:
        db_table = 'feed_suitability'
        ordering = ['species__common_name', 'min_weight_g', 'growth_stage']
        verbose_name = _('feed suitability')
        verbose_name_plural = _('feed suitability')
        constraints = [
            models.UniqueConstraint(fields=['feed', 'species', 'growth_stage'], name='uq_feed_suitability_stage',
                                    violation_error_message=SAME_STAGE_MESSAGE),
            models.CheckConstraint(condition=Q(growth_stage__in=GrowthStage.values),
                                   name='chk_feed_suitability_growth_stage'),
            models.CheckConstraint(condition=Q(min_weight_g__gte=0, min_weight_g__lte=MAX_WEIGHT_G),
                                   name='chk_feed_suitability_min_weight'),
            models.CheckConstraint(condition=Q(max_weight_g__gte=Decimal('0.01'), max_weight_g__lte=MAX_WEIGHT_G),
                                   name='chk_feed_suitability_max_weight'),
            models.CheckConstraint(condition=Q(min_weight_g__lt=F('max_weight_g')), name='chk_feed_suitability_band',
                                   violation_error_message=WEIGHT_BAND_MESSAGE),
        ]

    def __str__(self):
        return f'{self.species} · {self.get_growth_stage_display()}'

    def suits(self, weight_g):
        """Whether a fish of `weight_g` grams is in the band: from the lower weight up to, not including,
        the upper one; an open end does not limit."""
        return ((self.min_weight_g is None or weight_g >= self.min_weight_g)
                and (self.max_weight_g is None or weight_g < self.max_weight_g))

    def clean(self):
        if self.min_weight_g is not None and self.max_weight_g is not None and self.min_weight_g >= self.max_weight_g:
            raise ValidationError({'max_weight_g': WEIGHT_BAND_MESSAGE})
