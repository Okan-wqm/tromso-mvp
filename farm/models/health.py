"""Fish health: the medicines the farm uses (Setup › Reference data › Medicines) and what happens to the
fish's health (Operations › Health): treatments, health events and sea-lice counts. Typed columns and
database checks, no JSON (the source kept a treatment, its withdrawal and a lab result in five JSON blobs of
one wide row, health-maturity §1).

Nothing here stores a withdrawal end, a treated batch or a lice average: the medicine withdrawal of a batch
is worked out on read from its treatments, the stock ledger and the water temperature
(farm/health/withdrawal.py), and the averages from the counts (farm/health/read.py), so no stored value can
go stale (the source's withdrawal date started at the click and survived a resolved disease, HLT-01,
HLT-02). Treatments, events and counts are never hard-deleted: they are voided with a reason, like a stock
operation (farm.stock.services.voided); the only writer is farm/health/services.py."""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _, ngettext_lazy

from core.fields import ChoiceArrayField
from core.models import AuditedModel

from ..health import diseases
from .site import Site
from .species import Species
from .supplier import Supplier, SupplierLink, SupplyCategory
from .tank import Tank

MAX_WITHDRAWAL_DAYS = 1000          # a withdrawal far longer than any SPC states
MAX_WITHDRAWAL_DEGREE_DAYS = 10000  # 500 degree-days is the usual statutory minimum for off-label use
MAX_SAFETY_MARGIN_PCT = 200         # the farm's own margin on top of the label value
SAME_SPECIES_MESSAGE = _('Two rows are for the same species.')
PLANNED_DAYS = 28                   # a course's last day may be planned this far ahead
MAX_FISH_COUNTED = 1000             # fish examined in one lice count
MAX_LICE = 1000000                  # lice of one stage on the fish of one count


def _both_or_neither(value, unit):
    return Q(**{f'{value}__isnull': True, unit: ''}) | (Q(**{f'{value}__isnull': False}) & ~Q(**{unit: ''}))


def _pair_error(record, value, unit, message, errors):
    """A value and its unit, both or neither: the error on the one missing (the database checks it too)."""
    if (getattr(record, value) is None) != (not getattr(record, unit)):
        errors[unit if getattr(record, value) is not None else value] = ValidationError(message)


def _void_rule(table):
    """A voided record has its reason, a live one none (a stock operation's rule)."""
    return models.CheckConstraint(
        condition=Q(is_deleted=True, void_reason__gt='') | Q(is_deleted=False, void_reason=''),
        name=f'chk_{table}_void_reason')


# ---- medicines ----------------------------------------------------------------------------------------
class MedicineKind(models.TextChoices):
    LICE = 'lice', _('Sea-lice medicine')
    ANTIBACTERIAL = 'antibacterial', _('Antibacterial')
    ANTIPARASITIC = 'antiparasitic', _('Other antiparasitic')
    ANTIFUNGAL = 'antifungal', _('Antifungal')
    VACCINE = 'vaccine', _('Vaccine')
    ANAESTHETIC = 'anaesthetic', _('Anaesthetic')
    OTHER = 'other', _('Other')


class Administration(models.TextChoices):
    """How a medicine is given, the medicinal methods of a treatment."""
    BATH = 'bath', _('Bath')
    IN_FEED = 'in_feed', _('In feed')
    INJECTION = 'injection', _('Injection')
    DIP = 'dip', _('Dip')


class LiceSubstance(models.TextChoices):
    """Mattilsynet's value list of active substances in the weekly lice report (virkestoff), stored as the
    official value so a report can send it as it is (regulatory/mattilsynet-api.service.ts:167-177; the
    source's web report left three of them out, HLT-09)."""
    AZAMETHIPHOS = 'AZAMETHIPHOS', _('Azamethiphos')
    CYPERMETHRIN = 'CYPERMETHRIN', _('Cypermethrin')
    DELTAMETHRIN = 'DELTAMETHRIN', _('Deltamethrin')
    IMIDACLOPRID = 'IMIDAKLOPRID', _('Imidacloprid')
    HYDROGEN_PEROXIDE = 'HYDROGENPEROKSID', _('Hydrogen peroxide')
    DIFLUBENZURON = 'DIFLUBENZURON', _('Diflubenzuron')
    EMAMECTIN_BENZOATE = 'EMAMECTIN_BENZOAT', _('Emamectin benzoate')
    TEFLUBENZURON = 'TEFLUBENZURON', _('Teflubenzuron')
    OTHER = 'ANNET_VIRKESTOFF', _('Other active substance')


class StrengthUnit(models.TextChoices):
    """The report's units of a medicine's strength (STYRKE_ENHETER, mattilsynet-api.service.ts:140-146)."""
    MG_PER_G = 'MILLIGRAM_PER_GRAM', _('mg/g')
    MG_PER_ML = 'MILLIGRAM_PER_MILLILITER', _('mg/mL')
    G_PER_KG = 'GRAM_PER_KILO', _('g/kg')
    MG_PER_KG = 'MILLIGRAM_PER_KILO', _('mg/kg')
    PERCENT = 'PROSENT', _('%')


class MedicineStatus(models.TextChoices):
    ACTIVE = 'active', _('Active')
    INACTIVE = 'inactive', _('Inactive')


class Medicine(AuditedModel):
    """A medicine or vaccine the farm uses. Not the source's chemical master (a stock item filtered by type,
    whose withdrawal nothing read, HLT-08).

    Its withdrawal is not a column of the medicine: it is per species, the rows of MedicineWithdrawal (the SPC
    states it per species, and a farm that grows several wants its own margin on each). Nothing is seeded: the
    values come from the product's SPC, entered by the farm, checked by its vet.

    A sea-lice medicine names its active substance as Mattilsynet's list has it (`lice_report_code`); other
    medicines have none. The strength is a value with its unit, both or neither. The manufacturer is a live
    supplier of medicines and vaccines (a SupplierLink): such a supplier keeps that category while its
    medicines are registered and cannot be deleted while one names it (PROTECT), as a feed's manufacturer.
    A medicine a treatment used cannot be deleted either (PROTECT): set it inactive."""

    Kind, Administration, LiceSubstance, StrengthUnit, Status = (MedicineKind, Administration, LiceSubstance,
                                                                  StrengthUnit, MedicineStatus)

    name = models.CharField(_('Name'), max_length=150)
    marketing_authorisation = models.CharField(_('Marketing authorisation number'), max_length=50, blank=True)
    kind = models.CharField(_('Kind'), max_length=20, choices=MedicineKind.choices)
    administration = models.CharField(_('Administration'), max_length=20, choices=Administration.choices)
    active_substance = models.CharField(_('Active substance'), max_length=200)
    lice_report_code = models.CharField(_('Substance in the lice report'), max_length=30, blank=True,
                                        choices=LiceSubstance.choices)
    strength_value = models.DecimalField(_('Strength'), max_digits=10, decimal_places=3, null=True, blank=True,
                                         validators=[MinValueValidator(0)])
    strength_unit = models.CharField(_('Strength unit'), max_length=30, blank=True, choices=StrengthUnit.choices)
    prescription_only = models.BooleanField(_('Prescription only'), default=True)
    manufacturer = SupplierLink(
        Supplier, null=True, blank=True, on_delete=models.PROTECT, related_name='medicines',
        category=SupplyCategory.MEDICINES, verbose_name=_('Manufacturer'),
        error_messages={'invalid': _('Choose a supplier of medicines and vaccines.')},
        kept=ngettext_lazy('%(count)d medicine is made by it: keep “%(category)s” ticked.',
                           '%(count)d medicines are made by it: keep “%(category)s” ticked.', 'count'),
    )
    status = models.CharField(_('Status'), max_length=20, choices=MedicineStatus.choices,
                              default=MedicineStatus.ACTIVE)
    notes = models.CharField(_('Notes'), max_length=2000, blank=True)

    class Meta:
        db_table = 'medicines'
        ordering = ['name']
        verbose_name = _('medicine')
        verbose_name_plural = _('medicines')
        constraints = [
            models.UniqueConstraint(Lower('name'), condition=Q(is_deleted=False), name='uq_medicines_name_live',
                                    violation_error_message=_('Another medicine already has this name.')),
            models.CheckConstraint(condition=Q(kind__in=MedicineKind.values), name='chk_medicines_kind'),
            models.CheckConstraint(condition=Q(administration__in=Administration.values),
                                   name='chk_medicines_administration'),
            models.CheckConstraint(condition=Q(status__in=MedicineStatus.values), name='chk_medicines_status'),
            models.CheckConstraint(
                condition=Q(kind=MedicineKind.LICE, lice_report_code__in=LiceSubstance.values)
                | (~Q(kind=MedicineKind.LICE) & Q(lice_report_code='')),
                name='chk_medicines_lice_report_code',
                violation_error_message=_('A sea-lice medicine names its substance as the lice report has it; '
                                          'other medicines have none.')),
            models.CheckConstraint(condition=_both_or_neither('strength_value', 'strength_unit'),
                                   name='chk_medicines_strength',
                                   violation_error_message=_('A strength needs its unit, and a unit its strength.')),
            models.CheckConstraint(condition=Q(strength_value__isnull=True) | Q(strength_value__gte=0),
                                   name='chk_medicines_strength_positive'),
            models.CheckConstraint(condition=Q(strength_unit='') | Q(strength_unit__in=StrengthUnit.values),
                                   name='chk_medicines_strength_unit'),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        """The rules between fields, with the error on the field to change; the database checks them too."""
        super().clean()
        errors = {}
        if self.kind == MedicineKind.LICE and not self.lice_report_code:
            errors['lice_report_code'] = ValidationError(_('Choose the substance as the lice report names it.'))
        elif self.kind != MedicineKind.LICE and self.lice_report_code:
            errors['lice_report_code'] = ValidationError(_('Only a sea-lice medicine has a substance in the lice '
                                                           'report.'))
        _pair_error(self, 'strength_value', 'strength_unit', _('A strength needs its unit, and a unit its strength.'),
                    errors)
        if errors:
            raise ValidationError(errors)

    @property
    def is_vaccine(self):
        return self.kind == MedicineKind.VACCINE


class WithdrawalManager(models.Manager):
    """The rows of live species and the rows for every species. A deleted species keeps its rows in the table, out
    of sight, and they come back with it when it is restored; saving a medicine's list replaces only the rows it
    shows (as FeedSuitability's)."""

    def get_queryset(self):
        return super().get_queryset().filter(Q(species__isnull=True) | Q(species__is_deleted=False))


class MedicineWithdrawal(models.Model):
    """A medicine's withdrawal for one species, or for every species without a row of its own (no species):
    the days and the degree-days its SPC states, and the farm's safety margin on top. One row per medicine and
    species, and one per medicine for every species (the database checks both). Source: the two withdrawal
    columns of the medicine, which stated one value for every species.

    The rows of a medicine are saved as a whole list on its Withdrawal tab (core.crud.RowList), so they have no
    update or soft-delete columns, and they stay with their medicine when it is deleted and come back with it. The
    label values are stored as the label states them: the margin is the farm's own and is applied when a
    withdrawal is worked out, `used = value × (1 + margin ÷ 100)` rounded up (farm/health/withdrawal.py `Rule`).
    At least one of days and degree-days (a database check): "unknown" is not a value, 0 means none. Both given, the
    later end wins. A treatment with a medicine that has no row for the fish's species, nor one for every species,
    holds them with an unknown end until one is added: never silently no withdrawal."""

    medicine = models.ForeignKey(Medicine, on_delete=models.CASCADE, related_name='withdrawals',
                                 verbose_name=_('Medicine'))
    # PROTECT: a species' withdrawals are the farm's food-safety data; a hard delete of the species is refused.
    species = models.ForeignKey(Species, null=True, blank=True, on_delete=models.PROTECT,
                                related_name='medicine_withdrawals', limit_choices_to={'is_deleted': False},
                                verbose_name=_('Species'))
    degree_days = models.DecimalField(_('Withdrawal (degree-days)'), max_digits=7, decimal_places=1, null=True,
                                      blank=True, validators=[MinValueValidator(0),
                                                              MaxValueValidator(MAX_WITHDRAWAL_DEGREE_DAYS)])
    days = models.PositiveSmallIntegerField(_('Withdrawal (days)'), null=True, blank=True,
                                            validators=[MaxValueValidator(MAX_WITHDRAWAL_DAYS)])
    safety_margin_pct = models.DecimalField(_('Safety margin (%)'), max_digits=5, decimal_places=1, default=0,
                                            validators=[MinValueValidator(0), MaxValueValidator(MAX_SAFETY_MARGIN_PCT)])
    note = models.CharField(_('Note'), max_length=300, blank=True)
    created_at = models.DateTimeField(_('Created at'), auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
        verbose_name=_('Created by'),
    )

    objects = WithdrawalManager()
    all_objects = models.Manager()

    class Meta:
        db_table = 'medicine_withdrawals'
        ordering = ['medicine', models.F('species__common_name').asc(nulls_first=True)]
        verbose_name = _('medicine withdrawal')
        verbose_name_plural = _('medicine withdrawals')
        constraints = [
            # One row per medicine and species, and one per medicine for every species (NULL equal to NULL).
            models.UniqueConstraint(fields=['medicine', 'species'], nulls_distinct=False,
                                    name='uq_medicine_withdrawals_species',
                                    violation_error_message=SAME_SPECIES_MESSAGE),
            models.CheckConstraint(
                condition=Q(degree_days__isnull=False) | Q(days__isnull=False), name='chk_medicine_withdrawals_value',
                violation_error_message=_('Give the withdrawal in degree-days, in days or both, as the SPC states '
                                          'it (0 when it has none).')),
            models.CheckConstraint(
                condition=Q(degree_days__gte=0, degree_days__lte=MAX_WITHDRAWAL_DEGREE_DAYS),
                name='chk_medicine_withdrawals_degree_days'),
            models.CheckConstraint(condition=Q(days__gte=0, days__lte=MAX_WITHDRAWAL_DAYS),
                                   name='chk_medicine_withdrawals_days'),
            models.CheckConstraint(
                condition=Q(safety_margin_pct__gte=0, safety_margin_pct__lte=MAX_SAFETY_MARGIN_PCT),
                name='chk_medicine_withdrawals_margin'),
        ]

    def __str__(self):
        return f'{self.medicine} · {self.species.common_name if self.species_id else _("every species")}'

    def clean(self):
        """The rule between fields, with the error on the field to change; the database checks it too."""
        super().clean()
        if self.degree_days is None and self.days is None:
            raise ValidationError({'degree_days': ValidationError(
                _('Give the withdrawal in degree-days, in days or both, as the SPC states it (0 when it has none).'))})


# ---- treatments ---------------------------------------------------------------------------------------
class TreatmentMethod(models.TextChoices):
    """How the fish were treated: with a medicine (its administration), or without one. A medicinal method
    needs a medicine and a non-medicinal one has none (a database check)."""
    BATH = 'bath', _('Bath')
    IN_FEED = 'in_feed', _('In feed')
    INJECTION = 'injection', _('Injection')
    DIP = 'dip', _('Dip')
    THERMAL = 'thermal', _('Thermal delousing')
    MECHANICAL = 'mechanical', _('Mechanical delousing')
    FRESHWATER = 'freshwater', _('Freshwater bath')
    OTHER = 'other', _('Other, without a medicine')


MEDICINAL = (TreatmentMethod.BATH, TreatmentMethod.IN_FEED, TreatmentMethod.INJECTION, TreatmentMethod.DIP)


class TreatmentReason(models.TextChoices):
    SEA_LICE = 'sea_lice', _('Sea lice')
    PARASITES = 'parasites', _('Other parasites (e.g. AGD)')
    BACTERIAL = 'bacterial', _('Bacterial disease')
    FUNGAL = 'fungal', _('Fungal disease')
    VACCINATION = 'vaccination', _('Vaccination')
    SEDATION = 'sedation', _('Sedation')
    OTHER = 'other', _('Other')


class DoseUnit(models.TextChoices):
    MG_PER_KG_DAY = 'mg_kg_day', _('mg/kg biomass per day')
    MG_PER_L = 'mg_l', _('mg/L')
    ML_PER_FISH = 'ml_fish', _('mL per fish')


class AmountUnit(models.TextChoices):
    """The lice report's units of the amount of a substance used (MENGDE_ENHETER, mattilsynet-api.service.ts:
    151); the source always reported grams whatever was chosen (HLT-09)."""
    GRAM = 'GRAM', _('g')
    KILO = 'KILO', _('kg')
    TONNE = 'TONN', _('t')
    LITRE = 'LITER', _('L')


class Treatment(AuditedModel):
    """One course given to the fish of one or more units of a site: a bath, a medicated feed, an injection
    (a vaccination is a treatment with a vaccine), or a treatment without a medicine (thermal, mechanical,
    freshwater). Source tables: the `treatment` JSON of farm.health_events and farm.treatment_applications,
    one record here, so a treatment that holds a harvest is the one the lice report sends (HLT-03).

    No batch is stored: the treated batches are the ones the stock ledger has in its units from its first day
    to its last (farm/health/withdrawal.py), as a feeding's batches are, so a backdated stock operation never
    leaves a stored batch wrong. The withdrawal counts from the last day (`end_date`), never from the click
    (HLT-02); the last day may be planned up to PLANNED_DAYS ahead and changed later, logged.

    Nothing else is edited: a treatment is voided with a reason (its soft delete, as a stock operation) and
    recorded again; voiding it lifts its withdrawal. Who recorded it is created_by. The fast before it is the
    shared handling check's (farm/handling), which keeps its own acknowledgements. The links say what
    deleting the other record does: a medicine or vet a treatment names cannot be deleted (PROTECT, kept for
    traceability); a deleted unit keeps its treatments (the many-to-many rows stay, core.softdelete)."""

    Method, Reason, DoseUnit, AmountUnit = TreatmentMethod, TreatmentReason, DoseUnit, AmountUnit

    units = models.ManyToManyField(Tank, related_name='treatments', db_table='treatment_units',
                                   verbose_name=_('Units'))
    method = models.CharField(_('Method'), max_length=20, choices=TreatmentMethod.choices)
    medicine = models.ForeignKey(Medicine, null=True, blank=True, on_delete=models.PROTECT, related_name='treatments',
                                 verbose_name=_('Medicine'))
    reason = models.CharField(_('Reason'), max_length=20, choices=TreatmentReason.choices)
    start_date = models.DateField(_('First day'))
    end_date = models.DateField(_('Last day'))
    dose_value = models.DecimalField(_('Dose'), max_digits=10, decimal_places=3, null=True, blank=True,
                                     validators=[MinValueValidator(0)])
    dose_unit = models.CharField(_('Dose unit'), max_length=20, blank=True, choices=DoseUnit.choices)
    amount_value = models.DecimalField(_('Amount used'), max_digits=12, decimal_places=3, null=True, blank=True,
                                       validators=[MinValueValidator(0)])
    amount_unit = models.CharField(_('Amount unit'), max_length=10, blank=True, choices=AmountUnit.choices)
    bath_minutes = models.PositiveSmallIntegerField(_('Bath time (minutes)'), null=True, blank=True,
                                                    validators=[MinValueValidator(1), MaxValueValidator(24 * 60)])
    prescribed_by = models.CharField(_('Prescribed by'), max_length=150, blank=True)
    prescription_ref = models.CharField(_('Prescription number'), max_length=100, blank=True)
    vet = SupplierLink(
        Supplier, null=True, blank=True, on_delete=models.PROTECT, related_name='treatments',
        category=SupplyCategory.VETERINARY, verbose_name=_('Vet or fish-health service'),
        error_messages={'invalid': _('Choose a supplier of veterinary and fish health services.')},
        kept=ngettext_lazy('%(count)d treatment names it: keep “%(category)s” ticked.',
                           '%(count)d treatments name it: keep “%(category)s” ticked.', 'count'),
    )
    health_event = models.ForeignKey('HealthEvent', null=True, blank=True, on_delete=models.PROTECT,
                                     related_name='treatments', verbose_name=_('Health event'))
    notes = models.CharField(_('Notes'), max_length=2000, blank=True)
    void_reason = models.CharField(_('Reason for voiding'), max_length=500, blank=True)

    class Meta:
        db_table = 'treatments'
        ordering = ['-start_date', '-created_at']
        verbose_name = _('treatment')
        verbose_name_plural = _('treatments')
        constraints = [
            models.CheckConstraint(condition=Q(method__in=TreatmentMethod.values), name='chk_treatments_method'),
            models.CheckConstraint(condition=Q(reason__in=TreatmentReason.values), name='chk_treatments_reason'),
            models.CheckConstraint(
                condition=Q(method__in=MEDICINAL, medicine__isnull=False)
                | (~Q(method__in=MEDICINAL) & Q(medicine__isnull=True)),
                name='chk_treatments_medicine',
                violation_error_message=_('A bath, medicated feed, injection or dip names its medicine; a '
                                          'treatment without a medicine names none.')),
            models.CheckConstraint(condition=Q(end_date__gte=F('start_date')), name='chk_treatments_dates',
                                   violation_error_message=_('The last day cannot be before the first.')),
            models.CheckConstraint(condition=_both_or_neither('dose_value', 'dose_unit'), name='chk_treatments_dose',
                                   violation_error_message=_('A dose needs its unit, and a unit its dose.')),
            models.CheckConstraint(condition=_both_or_neither('amount_value', 'amount_unit'),
                                   name='chk_treatments_amount',
                                   violation_error_message=_('An amount needs its unit, and a unit its amount.')),
            models.CheckConstraint(condition=Q(dose_unit='') | Q(dose_unit__in=DoseUnit.values),
                                   name='chk_treatments_dose_unit'),
            models.CheckConstraint(condition=Q(amount_unit='') | Q(amount_unit__in=AmountUnit.values),
                                   name='chk_treatments_amount_unit'),
            models.CheckConstraint(condition=Q(bath_minutes__isnull=True) | Q(bath_minutes__gte=1,
                                                                               bath_minutes__lte=24 * 60),
                                   name='chk_treatments_bath_minutes'),
            models.CheckConstraint(condition=Q(dose_value__isnull=True) | Q(dose_value__gte=0),
                                   name='chk_treatments_dose_positive'),
            models.CheckConstraint(condition=Q(amount_value__isnull=True) | Q(amount_value__gte=0),
                                   name='chk_treatments_amount_positive'),
            _void_rule('treatments'),
        ]
        indexes = [models.Index(fields=['start_date']), models.Index(fields=['end_date'])]

    def __str__(self):
        what = self.medicine.name if self.medicine_id else self.get_method_display()
        return f'{what} {self.start_date.isoformat()}'

    def clean(self):
        """The rules between fields, with the error on the field to change; the database checks them too."""
        super().clean()
        errors = {}
        if self.method in MEDICINAL and self.medicine_id is None:
            errors['medicine'] = ValidationError(_('A bath, medicated feed, injection or dip names its medicine.'))
        elif self.method and self.method not in MEDICINAL and self.medicine_id is not None:
            errors['medicine'] = ValidationError(_('A treatment without a medicine names none.'))
        if self.start_date and self.end_date and self.end_date < self.start_date:
            errors['end_date'] = ValidationError(_('The last day cannot be before the first.'))
        _pair_error(self, 'dose_value', 'dose_unit', _('A dose needs its unit, and a unit its dose.'), errors)
        _pair_error(self, 'amount_value', 'amount_unit', _('An amount needs its unit, and a unit its amount.'),
                    errors)
        if errors:
            raise ValidationError(errors)

    @property
    def date(self):
        """The day the record is dated by, for the farm's date rule and its void: its first day."""
        return self.start_date

    @property
    def is_medicinal(self):
        return self.method in MEDICINAL


# ---- health events ------------------------------------------------------------------------------------
class EventKind(models.TextChoices):
    OBSERVATION = 'observation', _('Observation')
    VET_VISIT = 'vet_visit', _('Vet or fish-health visit')
    LAB_RESULT = 'lab_result', _('Lab result')
    MORTALITY = 'mortality', _('Increased mortality')


class Sign(models.TextChoices):
    REDUCED_APPETITE = 'reduced_appetite', _('Reduced appetite')
    ABNORMAL_SWIMMING = 'abnormal_swimming', _('Abnormal swimming')
    GASPING = 'gasping', _('Gasping at the surface')
    WOUNDS = 'wounds', _('Wounds or ulcers')
    FIN_DAMAGE = 'fin_damage', _('Fin damage')
    PALE_GILLS = 'pale_gills', _('Pale gills')
    HAEMORRHAGE = 'haemorrhage', _('Haemorrhage')
    SCALE_LOSS = 'scale_loss', _('Scale loss')
    EXOPHTHALMIA = 'exophthalmia', _('Exophthalmia')
    DEFORMITY = 'deformity', _('Deformity')
    INCREASED_MORTALITY = 'increased_mortality', _('Increased mortality')


class Confirmation(models.TextChoices):
    SUSPECTED = 'suspected', _('Suspected')
    CONFIRMED = 'confirmed', _('Confirmed')


class HealthEvent(AuditedModel):
    """A health observation, a vet or fish-health visit, a lab result or a rise in mortality on a site, in
    some of its units or the whole site. Source table: farm.health_events, without its JSON blobs: signs, a
    diagnosis from the reviewed catalogue (farm/health/diseases.py), the vet and the laboratory as
    suppliers, findings and recommendations are typed columns (HLT-07, HLT-15).

    A diagnosis is suspected or confirmed (both or neither, a database check). A notifiable one Mattilsynet has
    not been told of shows the "Notify Mattilsynet" banner (dyrehelseforskriften § 7: at once, on suspicion): that
    it was told is the filing of a disease notice, which the regulatory reports keep and farm/health/notices.py
    reads; the event has no column for it. Closing an event never lifts a medicine withdrawal: the withdrawal is the treatment's
    (HLT-01). Deaths recorded under the event are the mortality and cull operations that name it, counted
    from the stock ledger (StockOperation.health_event), never a number typed here.

    It is edited on its form (every change logged), and voided with a reason instead of deleted (HLT-04: the
    source's delete erased the medical record). A deleted site keeps its events, out of sight until it is
    restored (DO_NOTHING); a vet or laboratory an event names cannot be deleted (PROTECT)."""

    Kind, Sign, Confirmation = EventKind, Sign, Confirmation

    # DO_NOTHING: kept as they are when their site is deleted (core.softdelete), like a unit's stock lines.
    site = models.ForeignKey(Site, on_delete=models.DO_NOTHING, related_name='health_events', verbose_name=_('Site'))
    units = models.ManyToManyField(Tank, blank=True, related_name='health_events', db_table='health_event_units',
                                   verbose_name=_('Units'))
    date = models.DateField(_('Date'))
    kind = models.CharField(_('Kind'), max_length=20, choices=EventKind.choices)
    signs = ChoiceArrayField(models.TextField(choices=Sign.choices), verbose_name=_('Signs'), default=list,
                             blank=True)
    diagnosis = models.CharField(_('Diagnosis'), max_length=30, blank=True, choices=diseases.CHOICES)
    confirmation = models.CharField(_('Confirmation'), max_length=20, blank=True, choices=Confirmation.choices)
    examined_by = models.CharField(_('Examined by'), max_length=150, blank=True)
    vet = SupplierLink(
        Supplier, null=True, blank=True, on_delete=models.PROTECT, related_name='health_events',
        category=SupplyCategory.VETERINARY, verbose_name=_('Vet or fish-health service'),
        error_messages={'invalid': _('Choose a supplier of veterinary and fish health services.')},
        kept=ngettext_lazy('%(count)d health event names it: keep “%(category)s” ticked.',
                           '%(count)d health events name it: keep “%(category)s” ticked.', 'count'),
    )
    lab = SupplierLink(
        Supplier, null=True, blank=True, on_delete=models.PROTECT, related_name='lab_results',
        category=SupplyCategory.LABORATORY, verbose_name=_('Laboratory'),
        error_messages={'invalid': _('Choose a supplier of laboratory analyses.')},
        kept=ngettext_lazy(
            '%(count)d health event names it as the laboratory: keep “%(category)s” ticked.',
            '%(count)d health events name it as the laboratory: keep “%(category)s” ticked.', 'count'),
    )
    lab_reference = models.CharField(_('Laboratory reference'), max_length=100, blank=True)
    findings = models.CharField(_('Findings'), max_length=4000, blank=True)
    recommendations = models.CharField(_('Recommendations'), max_length=4000, blank=True)
    closed_on = models.DateField(_('Closed on'), null=True, blank=True)
    outcome = models.CharField(_('Outcome'), max_length=2000, blank=True)
    void_reason = models.CharField(_('Reason for voiding'), max_length=500, blank=True)

    class Meta:
        db_table = 'health_events'
        ordering = ['-date', '-created_at']
        verbose_name = _('health event')
        verbose_name_plural = _('health events')
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=EventKind.values), name='chk_health_events_kind'),
            models.CheckConstraint(condition=Q(signs__contained_by=Sign.values), name='chk_health_events_signs'),
            models.CheckConstraint(condition=Q(diagnosis='') | Q(diagnosis__in=[code for code, _l in diseases.CHOICES]),
                                   name='chk_health_events_diagnosis'),
            models.CheckConstraint(
                condition=Q(diagnosis='', confirmation='')
                | (~Q(diagnosis='') & Q(confirmation__in=Confirmation.values)),
                name='chk_health_events_confirmation',
                violation_error_message=_('A diagnosis is suspected or confirmed; without a diagnosis there is '
                                          'nothing to confirm.')),
            models.CheckConstraint(condition=Q(closed_on__isnull=True) | Q(closed_on__gte=F('date')),
                                   name='chk_health_events_closed_on',
                                   violation_error_message=_('An event is closed on or after its date.')),
            _void_rule('health_events'),
        ]
        indexes = [models.Index(fields=['date'])]

    def __str__(self):
        what = self.get_diagnosis_display() if self.diagnosis else self.get_kind_display()
        return f'{what} · {self.date.isoformat()}'

    def clean(self):
        """The rules between fields, with the error on the field to change; the database checks them too."""
        super().clean()
        errors = {}
        if self.diagnosis and not self.confirmation:
            errors['confirmation'] = ValidationError(_('Is the diagnosis suspected or confirmed?'))
        elif self.confirmation and not self.diagnosis:
            errors['confirmation'] = ValidationError(_('Without a diagnosis there is nothing to confirm.'))
        if self.closed_on and self.date and self.closed_on < self.date:
            errors['closed_on'] = ValidationError(_('An event is closed on or after its date.'))
        if errors:
            raise ValidationError(errors)

    def sign_labels(self):
        """The labels of the signs seen, in the order of the list."""
        return [Sign(value).label for value in self.signs]

    @property
    def disease(self):
        return diseases.get(self.diagnosis)

    @property
    def notifiable(self):
        disease = self.disease
        return disease is not None and disease.notifiable


# ---- sea-lice counts ----------------------------------------------------------------------------------
class LiceCount(AuditedModel):
    """A sea-lice count in one unit (a cage) on one day, as lakselusforskriften's Vedlegg 1 asks: the fish
    examined and the lice of each stage found on them, in total. Source table: farm.lice_counts, which kept
    rounded averages per fish and the ISO week as columns; here the averages and the week are worked out on
    read (farm/health/read.py), so they are never rounded twice or out of step with the date.

    One live count per unit and day (a database constraint). A correction is a void and a new count, never
    an overwrite (HLT-19). A deleted unit keeps its counts (DO_NOTHING), like its feeding records."""

    unit = models.ForeignKey(Tank, on_delete=models.DO_NOTHING, related_name='lice_counts', verbose_name=_('Unit'))
    date = models.DateField(_('Date'))
    fish_counted = models.PositiveSmallIntegerField(
        _('Fish examined'), validators=[MinValueValidator(1), MaxValueValidator(MAX_FISH_COUNTED)])
    adult_females = models.PositiveIntegerField(_('Adult female lice'), validators=[MaxValueValidator(MAX_LICE)])
    mobile = models.PositiveIntegerField(_('Mobile lice'), validators=[MaxValueValidator(MAX_LICE)])
    attached = models.PositiveIntegerField(_('Attached lice'), validators=[MaxValueValidator(MAX_LICE)])
    notes = models.CharField(_('Notes'), max_length=2000, blank=True)
    void_reason = models.CharField(_('Reason for voiding'), max_length=500, blank=True)

    class Meta:
        db_table = 'lice_counts'
        ordering = ['-date', '-created_at']
        verbose_name = _('sea-lice count')
        verbose_name_plural = _('sea-lice counts')
        constraints = [
            models.UniqueConstraint(fields=['unit', 'date'], condition=Q(is_deleted=False),
                                    name='uq_lice_counts_unit_day',
                                    violation_error_message=_('This unit already has a count on this day: void it '
                                                              'first to correct it.')),
            models.CheckConstraint(condition=Q(fish_counted__gte=1, fish_counted__lte=MAX_FISH_COUNTED),
                                   name='chk_lice_counts_fish'),
            models.CheckConstraint(
                condition=Q(adult_females__gte=0, adult_females__lte=MAX_LICE)
                & Q(mobile__gte=0, mobile__lte=MAX_LICE) & Q(attached__gte=0, attached__lte=MAX_LICE),
                name='chk_lice_counts_lice'),
            _void_rule('lice_counts'),
        ]
        indexes = [models.Index(fields=['unit', 'date']), models.Index(fields=['date'])]

    def __str__(self):
        return f'{self.unit.code} {self.date.isoformat()}'

    def per_fish(self, stage):
        """The average of a stage per fish examined (Vedlegg 1 point 6), unrounded."""
        return Decimal(getattr(self, stage)) / self.fish_counted


class FloorOrigin(models.TextChoices):
    LANDING = 'landing', _('A change of the rule')
    CLOSING = 'closing', _('A probe day closed')
    WRITE = 'write', _('A write nobody could be asked about')


class WithdrawalFloor(models.Model):
    """A day before which one batch's withdrawal from one treatment does NOT end, whatever the days add up to: a
    recorded decision, not a stored end (the withdrawal is still worked out on read, and ends at the later of the two:
    `until = max(worked out, floor)`, said in its text). `not_before` empty: the end stays unknown until the floor is
    lifted.

    It is how an end is kept from moving EARLIER without a question (the independent review of 2026-11-26, B-4): when
    the rule changes at a landing (`manage.py withdrawal_ends`) or the daily job closes a probe day that would move an
    end earlier (farm/water/services.py), nobody is there to be asked, so the end that was shown stays as a floor. A
    person lifts it through the withdrawal guard (farm/health/services.py `lift_floor`), which asks the Released
    question; a floor whose day has passed holds nobody. Never edited: lifted (who, when, why) and, if needed, set
    again. A withdrawal input: written inside the withdrawal guard only (farm/withdrawal_gate.py)."""

    id = models.BigAutoField(primary_key=True)
    created_at = models.DateTimeField(_('Set at'), auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name='+', verbose_name=_('Set by'))          # empty: a job or a command
    treatment = models.ForeignKey(Treatment, on_delete=models.PROTECT, related_name='floors',
                                  verbose_name=_('Treatment'))
    batch = models.ForeignKey('farm.Batch', on_delete=models.PROTECT, related_name='+', verbose_name=_('Batch'))
    not_before = models.DateField(_('Not before'), null=True, blank=True)      # None: unknown until lifted
    origin = models.CharField(_('Why it was set'), max_length=10, choices=FloorOrigin.choices)
    reason = models.CharField(_('Reason'), max_length=500)
    lifted_at = models.DateTimeField(_('Lifted at'), null=True, blank=True)
    lifted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                  related_name='+', verbose_name=_('Lifted by'))
    lift_reason = models.CharField(_('Reason for lifting'), max_length=500, blank=True)

    class Meta:
        db_table = 'withdrawal_floors'
        ordering = ['id']
        verbose_name = _('withdrawal floor')
        verbose_name_plural = _('withdrawal floors')
        constraints = [
            models.CheckConstraint(condition=Q(origin__in=FloorOrigin.values), name='chk_withdrawal_floors_origin'),
            models.CheckConstraint(condition=~Q(reason=''), name='chk_withdrawal_floors_reason'),
            models.CheckConstraint(condition=Q(lifted_at__isnull=True, lifted_by__isnull=True, lift_reason='')
                                   | (Q(lifted_at__isnull=False, lifted_by__isnull=False) & ~Q(lift_reason='')),
                                   name='chk_withdrawal_floors_lift'),
        ]
        indexes = [models.Index(fields=['treatment', 'batch'], condition=Q(lifted_at__isnull=True),
                                name='withdrawal_floors_live_idx')]

    def __str__(self):
        day = f'{self.not_before:%Y-%m-%d}' if self.not_before else 'unknown'
        return f'{self.treatment_id} · {self.batch_id}: not before {day}'
