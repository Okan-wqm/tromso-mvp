"""Handling fish: the farm's fasting rules (Setup › Reference data › Handling rules) and the acknowledgements
people give when they go on past a handling warning (a medicine withdrawal, too short a fast). The check
itself is farm/handling/; nothing here blocks anything (owner decision: warn, never block)."""
from django.core.validators import MaxValueValidator
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from core.models import AuditedModel

from .species import Species
from .stock import OperationKind, StockOperation

MAX_FASTING_HOURS = 720     # 30 days: a rule above it is a typing slip, not a fast


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
    """How many hours the fish must have been without feed before they are handled: one row per kind of
    handling, for one species or for every species (no species). The species' row wins over the row for
    every species; with neither, the fast is not checked and the dialog says so (no default is assumed).

    These are the farm's own rules: the starting values the migration writes (0016) are to be checked with
    the farm's veterinarian, and each says where it comes from. Too short a fast is a warning; going on
    stores an acknowledgement and logs it as critical (farm/handling)."""

    Kind = HandlingKind

    kind = models.CharField(_('Handling'), max_length=12, choices=HandlingKind.choices)
    # CASCADE: a species' rules go with it, as its water limits do (core.softdelete lists them).
    species = models.ForeignKey(Species, null=True, blank=True, on_delete=models.CASCADE,
                                related_name='handling_rules', verbose_name=_('Species'))
    min_fasting_hours = models.PositiveSmallIntegerField(_('Fasting before it (hours)'),
                                                         validators=[MaxValueValidator(MAX_FASTING_HOURS)])
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
                                   name='chk_handling_rules_hours',
                                   violation_error_message=_('At most 720 hours (30 days).')),
        ]

    def __str__(self):
        species = self.species.common_name if self.species_id else _('every species')
        return f'{self.get_kind_display()} · {species}'


class AcknowledgedWarning(models.TextChoices):
    WITHDRAWAL = 'withdrawal', _('Medicine withdrawal')
    FASTING = 'fasting', _('Fasting')


def _shape():
    """A withdrawal row keeps what the person saw of the withdrawal, a fasting row what they saw of the fast;
    the other's columns stay empty."""
    fasting = ('last_fed_at', 'fasted_hours', 'required_hours', 'rule')
    no_withdrawal = Q(withdrawal_until__isnull=True, withdrawal_approximate=False, withdrawal_reason='')
    return (Q(warning=AcknowledgedWarning.WITHDRAWAL, **{f'{name}__isnull': True for name in fasting})
            | (Q(warning=AcknowledgedWarning.FASTING, fasted_hours__lt=models.F('required_hours'),
                 **{f'{name}__isnull': False for name in fasting}) & no_withdrawal))


class HandlingAcknowledgement(models.Model):
    """One warning a person went on past when recording a handling (a harvest, a transfer, a grading): a
    medicine withdrawal in force, or too short a fast. It keeps what they were shown, the withdrawal's end
    and reason, or the hours fasted against the hours the rule asked for, so the record says what was known
    at the time. Who and when are the operation's (it is written in the same transaction); the operation's
    activity-log entry is critical. Rows are never edited; voiding the operation leaves them as history."""

    id = models.BigAutoField(primary_key=True)
    operation = models.ForeignKey(StockOperation, on_delete=models.PROTECT, related_name='acknowledgements',
                                  verbose_name=_('Operation'))
    warning = models.CharField(_('Warning'), max_length=12, choices=AcknowledgedWarning.choices)
    withdrawal_until = models.DateField(_('Withdrawal until'), null=True, blank=True)   # None: unknown
    withdrawal_approximate = models.BooleanField(_('Withdrawal end estimated'), default=False)
    withdrawal_reason = models.CharField(_('Withdrawal'), max_length=500, blank=True)
    last_fed_at = models.DateTimeField(_('Last fed'), null=True, blank=True)
    fasted_hours = models.DecimalField(_('Hours fasted'), max_digits=6, decimal_places=1, null=True, blank=True)
    required_hours = models.PositiveSmallIntegerField(_('Hours the rule asks for'), null=True, blank=True)
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
            # A handling has one fast: the fish's last feeding against the longest rule that applies.
            models.UniqueConstraint(fields=['operation'], condition=Q(warning=AcknowledgedWarning.FASTING),
                                    name='uq_handling_acknowledgements_one_fast'),
        ]

    def __str__(self):
        return f'{self.get_warning_display()} · {self.operation}'

    @property
    def kind(self):
        """The handling it was given for: the operation's kind."""
        return KIND_OF_OPERATION.get(self.operation.kind)
