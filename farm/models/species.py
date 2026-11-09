from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _, pgettext_lazy

from core.models import CODE, CODE_MESSAGE, AuditedModel, CodedMixin

from .. import species_catalog

# Genus and species, optionally a subspecies, as written after normalise_scientific_name: "Salmo salar".
# Genus-level names ("Labrus sp.") are not accepted: reports and the catalogue work per species.
SCIENTIFIC_NAME = r'^[A-Z][a-z]+( [a-z]{2,}){1,2}$'
OFFICIAL_CODE = r'^[A-Z]{3}$'

SCIENTIFIC_NAME_MESSAGE = _('Write the genus and the species in Latin letters, e.g. Salmo salar; a subspecies '
                            'may follow as a third word.')
OFFICIAL_CODE_MESSAGE = _('The official code is three capital letters, e.g. SAL.')
WATER_MESSAGE = _('Tick at least one water environment.')
MAX_WITHDRAWAL_TEMPERATURE_C = 40       # far above any water a farm holds fish in: a typing slip, not an assumption
# The size limit's bounds: 1 (only batches of the same average) to 1000 (a typing slip beyond it, never a farm's rule).
MIN_WEIGHT_RATIO, MAX_WEIGHT_RATIO = 1, 1000


def normalise_scientific_name(text):
    """'  salmo   SALAR ' as 'Salmo salar': spaces collapsed, the genus capitalised, the rest in lower case."""
    words = (text or '').split()
    return ' '.join([words[0].capitalize(), *(word.lower() for word in words[1:])]) if words else ''


class SpeciesCategory(models.TextChoices):
    FISH = 'fish', _('Fish')
    SHRIMP = 'shrimp', _('Shrimp')
    PRAWN = 'prawn', _('Prawn')
    CRAB = 'crab', _('Crab')
    LOBSTER = 'lobster', _('Lobster')
    MOLLUSK = 'mollusk', _('Mollusc')
    SEAWEED = 'seaweed', _('Seaweed')
    OTHER = 'other', _('Other')


class SpeciesStatus(models.TextChoices):
    ACTIVE = 'active', _('Active')
    INACTIVE = 'inactive', _('Inactive')
    EXPERIMENTAL = 'experimental', _('Experimental')
    DISCONTINUED = 'discontinued', _('Discontinued')


# The species whose weekly sea-lice report a sea site owes: Mattilsynet's own "Laks, Ørret, Regnbueørret" (salmon, trout,
# rainbow trout; D-11). By official code, so a species with no code is named where it is missed (reports/due.py).
SALMONID_CODES = ('SAL', 'TRS', 'TRR')


class CleanerFishType(models.TextChoices):
    NONE = '', _('Not a cleaner fish')
    LUMPFISH = 'lumpfish', _('Lumpfish')
    WRASSE = 'wrasse', _('Wrasse')


class Species(CodedMixin, AuditedModel):
    """A species the farm grows or stocks, with its names, codes and the water it lives in. Source
    table: farm.species.

    The official code is the artskode the Norwegian reports send. Report code must use it and never
    fall back to the internal `code` (the source sent the internal code when the official one was
    missing, SPC-02): a reportable species without an official code is a report that cannot be filed.

    The assumed water temperature for a medicine withdrawal (`withdrawal_temperature_c`, 0 to 40 °C, a database
    check; empty: none given) is the farm's own assumption, reference data like the handling rules: the degree-days
    a past day without a measured water temperature adds to a batch of this species, and what a withdrawal is
    projected at when no temperature was measured at all (farm/health/withdrawal.py). Empty counts a missing day
    as 0 °C and leaves a projection without a temperature unknown. The catalogue never fills it in.

    The size limit (`max_weight_ratio`, 1 to 1000, a database check; empty: no check) is the farm's own rule too, the
    owner's "fish of very different weights of the same species must not be in the same tank": how many times heavier,
    on average, one batch of the species may be than another sharing a unit with it. A stocking, transfer or grading
    beyond it asks for an acknowledgement, and a unit holding such a mix says so (farm/stock/services.py, read.py).
    Migration 0034 gave every species there 2; a new species is offered 2 on its form, never given one by the code.

    Status: "active" and "experimental" species are the ones offered for new batches (the batches
    tab); "inactive" and "discontinued" ones are not. There is no second flag `isActive`.

    Delete: the feeds that suit it keep their suitability rows for it (FeedSuitability, a many-to-many
    link of the feed, CASCADE): the rows stop showing and come back with the species when it is restored.
    The batches tab will link to it with on_delete=PROTECT, so a species with batches is set to
    discontinued instead of deleted.

    Differences from the source: one status (no `isActive`); the water environment is three flags,
    since salmon and trout live in fresh and in sea water; the genus is derived from the scientific
    name, not stored; the cleaner-fish type can be set here (the source had it in seeders only); the
    scientific name is normalised and checked as a binomial, unique among live species whatever its
    case; the codes are checked by the database. Not ported: tags, the species-level supplier,
    market and breeding information, documents, the image, the light regime and the JSON blobs of
    water limits and growth figures (those come back as typed tables of their own tabs)."""

    # Defined outside the class so that its Meta can name their values in the constraints.
    Category, Status, CleanerFishType = SpeciesCategory, SpeciesStatus, CleanerFishType

    # The water environments, in the order forms and lists show them.
    WATER_FIELDS = ('freshwater', 'brackish', 'saltwater')

    name_field = 'common_name'

    common_name = models.CharField(_('Common name'), max_length=100)
    local_name = models.CharField(_('Local name'), max_length=100, blank=True)
    scientific_name = models.CharField(
        _('Scientific name'), max_length=100,
        validators=[RegexValidator(SCIENTIFIC_NAME, SCIENTIFIC_NAME_MESSAGE)],
    )
    code = models.CharField(_('Code'), max_length=20, validators=[RegexValidator(CODE, CODE_MESSAGE)])
    official_code = models.CharField(
        _('Official code'), max_length=3, blank=True,
        validators=[RegexValidator(OFFICIAL_CODE, OFFICIAL_CODE_MESSAGE)],
    )
    description = models.CharField(_('Description'), max_length=1000, blank=True)
    category = models.CharField(_('Category'), max_length=20, choices=Category.choices, default=Category.FISH)
    freshwater = models.BooleanField(_('Fresh water'), default=False)
    brackish = models.BooleanField(_('Brackish water'), default=False)
    saltwater = models.BooleanField(_('Sea water'), default=False)
    family = models.CharField(_('Family'), max_length=100, blank=True)
    status = models.CharField(_('Status'), max_length=20, choices=Status.choices, default=Status.ACTIVE)
    cleaner_fish_type = models.CharField(
        _('Cleaner fish'), max_length=20, blank=True, choices=CleanerFishType.choices, default=CleanerFishType.NONE,
    )
    withdrawal_temperature_c = models.DecimalField(
        _('Assumed water temperature for withdrawal (°C)'), max_digits=4, decimal_places=1, null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(MAX_WITHDRAWAL_TEMPERATURE_C)],
    )
    max_weight_ratio = models.DecimalField(
        _('Max weight ratio of batches in one unit'), max_digits=6, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(MIN_WEIGHT_RATIO), MaxValueValidator(MAX_WEIGHT_RATIO)],
    )
    notes =models.CharField(_('Notes'), max_length=2000, blank=True)

    class Meta:
        db_table = 'species'
        ordering = ['common_name', 'scientific_name']
        verbose_name = _('species')
        verbose_name_plural = pgettext_lazy('plural', 'species')
        constraints = [
            models.UniqueConstraint(
                fields=['code'], condition=Q(is_deleted=False), name='uq_species_code_live',
                violation_error_message=_('Another species already uses this code.'),
            ),
            models.UniqueConstraint(
                Lower('scientific_name'), condition=Q(is_deleted=False), name='uq_species_scientific_name_live',
                violation_error_message=_('Another species already has this scientific name.'),
            ),
            models.CheckConstraint(
                condition=Q(scientific_name__regex=SCIENTIFIC_NAME), name='chk_species_scientific_name',
                violation_error_message=SCIENTIFIC_NAME_MESSAGE,
            ),
            models.CheckConstraint(
                condition=Q(code__regex=CODE), name='chk_species_code', violation_error_message=CODE_MESSAGE,
            ),
            models.CheckConstraint(
                condition=Q(official_code='') | Q(official_code__regex=OFFICIAL_CODE), name='chk_species_official_code',
                violation_error_message=OFFICIAL_CODE_MESSAGE,
            ),
            models.CheckConstraint(
                condition=Q(category__in=SpeciesCategory.values), name='chk_species_category',
            ),
            models.CheckConstraint(
                condition=Q(status__in=SpeciesStatus.values), name='chk_species_status',
            ),
            models.CheckConstraint(
                condition=Q(cleaner_fish_type__in=CleanerFishType.values), name='chk_species_cleaner_fish_type',
            ),
            models.CheckConstraint(
                condition=Q(withdrawal_temperature_c__gte=0, withdrawal_temperature_c__lte=MAX_WITHDRAWAL_TEMPERATURE_C),
                name='chk_species_withdrawal_temperature',      # empty passes: a check on NULL is unknown, not false
            ),
            models.CheckConstraint(
                condition=Q(max_weight_ratio__gte=MIN_WEIGHT_RATIO, max_weight_ratio__lte=MAX_WEIGHT_RATIO),
                name='chk_species_max_weight_ratio',            # empty passes: no check
            ),
            models.CheckConstraint(
                condition=Q(freshwater=True) | Q(brackish=True) | Q(saltwater=True), name='chk_species_water',
                violation_error_message=WATER_MESSAGE,
            ),
        ]
        indexes = [models.Index(fields=['category']), models.Index(fields=['status'])]

    @property
    def genus(self):
        """The first word of the scientific name."""
        return self.scientific_name.split(' ', 1)[0]

    @property
    def is_cleaner_fish(self):
        return bool(self.cleaner_fish_type)

    def water_environments(self):
        """The labels of the water environments ticked, e.g. [Fresh water, Sea water]."""
        return [self._meta.get_field(name).verbose_name for name in self.WATER_FIELDS if getattr(self, name)]

    def withdrawal_blockers(self):
        """Why the species is not deleted or restored now: its assumed water temperature counts the degree-days of its
        batches on a day without a measured one, so a withdrawal that holds one waits
        (farm.health.withdrawal.held_reached; the withdrawal gate's rule, farm/apps.py)."""
        from ..health.withdrawal import held_reached
        return held_reached(species=self)

    def delete_blockers(self):
        return self.withdrawal_blockers()

    def clean(self):
        super().clean()
        errors = {}
        if not any(getattr(self, name) for name in self.WATER_FIELDS):
            errors['freshwater'] = ValidationError(WATER_MESSAGE)
        stored = None if self._state.adding else Species.all_objects.filter(pk=self.pk).values_list(
            'cleaner_fish_type', flat=True).first()
        if stored is not None and bool(stored) != bool(self.cleaner_fish_type) and self.batches(
                manager='all_objects').exists():
            # Every read takes the flag live: it would turn the species' stocked fish, their feeding and their
            # reports into the other kind's. Lumpfish to wrasse (both cleaner fish) may change.
            errors['cleaner_fish_type'] = ValidationError(
                _('Fixed: fish of this species have been stocked, so whether it is a cleaner fish cannot change.'))
        entry = species_catalog.find(self.scientific_name)
        if entry and entry.official_code_verified and self.official_code not in ('', entry.official_code):
            errors['official_code'] = ValidationError(
                _('The official code of %(name)s is %(code)s.'),
                params={'name': entry.scientific_name, 'code': entry.official_code})
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.scientific_name = normalise_scientific_name(self.scientific_name)
        self.official_code = self.official_code.strip().upper()
        super().save(*args, **kwargs)
