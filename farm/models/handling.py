"""Handling fish: the farm's fasting rules (Setup › Reference data › Handling rules) and the acknowledgements
people give when they go on past a handling warning (a medicine withdrawal before a harvest, too short a fast).
The check itself is farm/handling/; nothing here blocks anything (owner decision: warn, never block)."""
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from core.models import AuditedModel

from .species import Species
from .stock import OperationKind, StockOperation

MAX_FASTING_HOURS = 720     # 30 days: a rule above it is a typing slip, not a fast
MAX_FASTING_DEGREE_DAYS = 1000   # a purge of more degree-days is a typing slip, too
HOURS_MESSAGE = _('At most 720 hours (30 days).')
FAST_MESSAGE = _('Give the fast in hours or days, in degree-days, or both.')
HARVEST_ONLY_MESSAGE = _('Degree-days are for the harvest only: fish that are moved or graded are not purged.')


class HandlingKind(models.TextChoices):
    """What is done to the fish that a fast comes before. A transfer is a transport; a grading moves the fish
    too, so it is checked against both its own rule and the transport rule (the longer wins, owner)."""
    HARVEST = 'harvest', _('Harvest')
    TRANSPORT = 'transport', _('Transport')
    GRADING = 'grading', _('Grading')
    TREATMENT = 'treatment', _('Treatment')


# The handling kind of each stock operation the check runs for; a treatment is the health tab's.
KIND_OF_OPERATION = {
    OperationKind.HARVEST: HandlingKind.HARVEST,
    OperationKind.TRANSFER: HandlingKind.TRANSPORT,
    OperationKind.GRADING: HandlingKind.GRADING,
}


class HandlingRule(AuditedModel):
    """How long the fish must have been without feed before they are handled: one row per kind of handling, for
    one species or for every species (no species). The species' row wins over the row for every species; with
    neither, the fast is not checked and the dialog says so (no default is assumed).

    The fast is in hours, stored in the one hours column (a form enters hours or days, 5 days is 120 hours, and
    shows a rule of whole days back as days), and, **for a harvest only**, in degree-days: the purging of fish that
    are sent to the factory, held without feed in clean water so that any off-flavour clears (the sum of the daily
    mean water temperatures of the full days since the last feeding, farm/water/degree_days.py). A rule has the one
    or the other or both (a database check) and, with both, each must be reached. Hours stay required for every
    other kind.

    These are the farm's own rules: the starting values the migration writes (0017) are to be checked with
    the farm's veterinarian, and each says where it comes from. Too short a fast is a warning; going on
    stores an acknowledgement and logs it as critical (farm/handling)."""

    Kind = HandlingKind

    kind = models.CharField(_('Handling'), max_length=12, choices=HandlingKind.choices)
    # CASCADE: a species' rules go with it, as its water limits do (core.softdelete lists them).
    species = models.ForeignKey(Species, null=True, blank=True, on_delete=models.CASCADE,
                                related_name='handling_rules', verbose_name=_('Species'))
    min_fasting_hours = models.PositiveSmallIntegerField(
        _('Fasting before it (hours)'), null=True, blank=True,
        validators=[MaxValueValidator(MAX_FASTING_HOURS, message=HOURS_MESSAGE)])
    min_fasting_degree_days = models.DecimalField(
        _('Purging before it (degree-days)'), max_digits=6, decimal_places=1, null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(MAX_FASTING_DEGREE_DAYS)])
    note = models.CharField(_('Source of the value'), max_length=500, blank=True)

    class Meta:
        db_table = 'handling_rules'
        ordering = ['kind', models.F('species__common_name').asc(nulls_first=True)]
        verbose_name = _('handling rule')
        verbose_name_plural = _('handling rules')
        constraints = [
            # One live rule per kind and species, and one per kind for every species (NULL equal to NULL).
            models.UniqueConstraint(
                fields=['kind', 'species'], condition=Q(is_deleted=False), nulls_distinct=False,
                name='uq_handling_rules_live',
                violation_error_message=_('There is already a rule for this handling and species.')),
            models.CheckConstraint(condition=Q(kind__in=HandlingKind.values), name='chk_handling_rules_kind'),
            models.CheckConstraint(condition=Q(min_fasting_hours__lte=MAX_FASTING_HOURS),
                                   name='chk_handling_rules_hours', violation_error_message=HOURS_MESSAGE),
            models.CheckConstraint(
                condition=Q(min_fasting_degree_days__gte=0, min_fasting_degree_days__lte=MAX_FASTING_DEGREE_DAYS),
                name='chk_handling_rules_degree_days'),
            models.CheckConstraint(
                condition=Q(min_fasting_hours__isnull=False) | Q(min_fasting_degree_days__isnull=False),
                name='chk_handling_rules_fast', violation_error_message=FAST_MESSAGE),
            models.CheckConstraint(
                condition=Q(kind=HandlingKind.HARVEST) | Q(min_fasting_degree_days__isnull=True),
                name='chk_handling_rules_degree_days_harvest', violation_error_message=HARVEST_ONLY_MESSAGE),
        ]

    def __str__(self):
        species = self.species.common_name if self.species_id else _('every species')
        return f'{self.get_kind_display()} · {species}'

    def clean(self):
        """The rules between fields, with the error on the field to change; the database checks them too."""
        super().clean()
        errors = {}
        if self.min_fasting_degree_days is not None and self.kind != HandlingKind.HARVEST:
            errors['min_fasting_degree_days'] = ValidationError(HARVEST_ONLY_MESSAGE)
        elif self.min_fasting_hours is None and self.min_fasting_degree_days is None:
            errors['min_fasting_hours'] = ValidationError(FAST_MESSAGE)
        if errors:
            raise ValidationError(errors)


class AcknowledgedWarning(models.TextChoices):
    WITHDRAWAL = 'withdrawal', _('Medicine withdrawal')
    FASTING = 'fasting', _('Fasting')


def _shape():
    """A withdrawal row keeps what the person saw of the withdrawal, a fasting row what they saw of the fast;
    the other's columns stay empty. A fasting row has its last feeding, the hours fasted and the rule, and at least
    one of the two things the rule asked for not reached: the hours (`fasted_hours < required_hours`) or, for a
    harvest's purging, the degree-days; the degree-days are both given or both empty."""
    fasting = ('last_fed_at', 'fasted_hours', 'required_hours', 'rule', 'fasted_degree_days', 'required_degree_days')
    no_withdrawal = Q(withdrawal_until__isnull=True, withdrawal_approximate=False, withdrawal_reason='')
    unmet = (Q(required_hours__isnull=False, fasted_hours__lt=models.F('required_hours'))
             | Q(required_degree_days__isnull=False, fasted_degree_days__lt=models.F('required_degree_days')))
    both_or_neither = (Q(required_degree_days__isnull=True, fasted_degree_days__isnull=True)
                       | Q(required_degree_days__isnull=False, fasted_degree_days__isnull=False))
    return (Q(warning=AcknowledgedWarning.WITHDRAWAL, **{f'{name}__isnull': True for name in fasting})
            | (Q(warning=AcknowledgedWarning.FASTING, last_fed_at__isnull=False, fasted_hours__isnull=False,
                 rule__isnull=False) & unmet & both_or_neither & no_withdrawal))


class HandlingAcknowledgement(models.Model):
    """One warning a person went on past when recording a handling (a harvest, a transfer, a grading, a
    treatment): a medicine withdrawal in force, or too short a fast. It keeps what they were shown, the
    withdrawal's end and reason, or the hours (and for a harvest's purging the degree-days) fasted against what the
    rule asked for, so the record says
    what was known at the time. It belongs to the stock operation or to the treatment it was given for, exactly
    one (a database check). Who and when are that record's (it is written in the same transaction); its
    activity-log entry is critical. Rows are never edited; voiding the record leaves them as history."""

    id = models.BigAutoField(primary_key=True)
    operation = models.ForeignKey(StockOperation, null=True, blank=True, on_delete=models.PROTECT,
                                  related_name='acknowledgements', verbose_name=_('Operation'))
    treatment = models.ForeignKey('Treatment', null=True, blank=True, on_delete=models.PROTECT,
                                  related_name='acknowledgements', verbose_name=_('Treatment'))
    warning = models.CharField(_('Warning'), max_length=12, choices=AcknowledgedWarning.choices)
    withdrawal_until = models.DateField(_('Withdrawal until'), null=True, blank=True)   # None: unknown
    withdrawal_approximate = models.BooleanField(_('Withdrawal end estimated'), default=False)
    withdrawal_reason = models.CharField(_('Withdrawal'), max_length=500, blank=True)
    last_fed_at = models.DateTimeField(_('Last fed'), null=True, blank=True)
    fasted_hours = models.DecimalField(_('Hours fasted'), max_digits=6, decimal_places=1, null=True, blank=True)
    required_hours = models.PositiveSmallIntegerField(_('Hours the rule asks for'), null=True, blank=True)
    fasted_degree_days = models.DecimalField(_('Degree-days fasted'), max_digits=6, decimal_places=1, null=True,
                                             blank=True)
    required_degree_days = models.DecimalField(_('Degree-days the rule asks for'), max_digits=6, decimal_places=1,
                                               null=True, blank=True)
    rule = models.ForeignKey(HandlingRule, null=True, blank=True, on_delete=models.PROTECT,
                             related_name='acknowledgements', verbose_name=_('Handling rule'))

    class Meta:
        db_table = 'handling_acknowledgements'
        ordering = ['id']
        verbose_name = _('handling acknowledgement')
        verbose_name_plural = _('handling acknowledgements')
        constraints = [
            models.CheckConstraint(condition=Q(warning__in=AcknowledgedWarning.values),
                                   name='chk_handling_acknowledgements_warning'),
            models.CheckConstraint(condition=_shape(), name='chk_handling_acknowledgements_shape'),
            models.CheckConstraint(condition=Q(fasted_hours__isnull=True) | Q(fasted_hours__gte=0),
                                   name='chk_handling_acknowledgements_fasted'),
            models.CheckConstraint(condition=Q(fasted_degree_days__isnull=True) | Q(fasted_degree_days__gte=0),
                                   name='chk_handling_acknowledgements_fasted_degree_days'),
            models.CheckConstraint(
                condition=Q(operation__isnull=False, treatment__isnull=True)
                | Q(operation__isnull=True, treatment__isnull=False),
                name='chk_handling_acknowledgements_one_record'),
            # A handling has one fast: the fish's last feeding against the longest rule that applies.
            models.UniqueConstraint(fields=['operation'], condition=Q(warning=AcknowledgedWarning.FASTING),
                                    name='uq_handling_acknowledgements_one_fast'),
        ]

    def __str__(self):
        return f'{self.get_warning_display()} · {self.operation if self.operation_id else self.treatment}'

    @property
    def kind(self):
        """The handling it was given for: the operation's kind, or a treatment."""
        if self.treatment_id:
            return HandlingKind.TREATMENT
        return KIND_OF_OPERATION.get(self.operation.kind)
