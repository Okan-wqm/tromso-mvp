"""Handling fish: the farm's fasting rules (Setup › Reference data › Handling rules) and the acknowledgements
people give when they go on past a handling warning (a medicine withdrawal before a harvest, too short a fast).
The check itself is farm/handling/; nothing here blocks anything (owner decision: warn, never block)."""
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from core.models import AuditedModel

from .species import Species
from .stock import Batch, OperationKind, StockOperation

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
    OperationKind.DELIVERY: HandlingKind.TRANSPORT,
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
    harvest's purging, the degree-days; the degree-days are both given or both empty. It names the feeding record the
    fast was counted from (`feeding`; empty on rows written before it was kept: flow fault S-01, where the feeding was
    of another unit and the row could not say so). A withdrawal row may name the batch
    and the withdrawal it was about (`batch`, `withdrawal_source`), kept since the cross-review so that check_withdrawal
    labels an acknowledgement per harvest and withdrawal; a fasting row names neither."""
    fasting = ('last_fed_at', 'fasted_hours', 'required_hours', 'rule', 'fasted_degree_days', 'required_degree_days',
               'feeding')
    no_fasting = {f'{name}__isnull': True for name in fasting}
    no_withdrawal = Q(withdrawal_until__isnull=True, withdrawal_approximate=False, withdrawal_reason='')
    unmet = (Q(required_hours__isnull=False, fasted_hours__lt=models.F('required_hours'))
             | Q(required_degree_days__isnull=False, fasted_degree_days__lt=models.F('required_degree_days')))
    both_or_neither = (Q(required_degree_days__isnull=True, fasted_degree_days__isnull=True)
                       | Q(required_degree_days__isnull=False, fasted_degree_days__isnull=False))
    return (Q(warning=AcknowledgedWarning.WITHDRAWAL, **no_fasting)
            | (Q(warning=AcknowledgedWarning.FASTING, last_fed_at__isnull=False, fasted_hours__isnull=False,
                 rule__isnull=False, batch__isnull=True, withdrawal_source='') & unmet & both_or_neither & no_withdrawal))


class HandlingAcknowledgement(models.Model):
    """One warning a person went on past when recording a handling (a harvest, a transfer, a grading, a
    treatment): a medicine withdrawal in force, or too short a fast; and, as a withdrawal row on the move that made it
    (a transfer, a split, a grading, or a stocking, which is no handling: `kind` is None there), the fish a move
    combined with held fish, which now wait with them (the owner's decision 8; farm.stock.integrity knows both). It
    keeps what they were shown, the
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
    # A withdrawal row's batch and withdrawal (its cause, WITHDRAWAL_SOURCE: "treatment:<id>" or "feeding:<id>"); empty on
    # rows written before they were kept, and on a fasting row.
    batch = models.ForeignKey(Batch, null=True, blank=True, on_delete=models.PROTECT, related_name='+',
                              verbose_name=_('Batch'))
    withdrawal_source = models.CharField(_('Withdrawal of'), max_length=80, blank=True)
    withdrawal_until = models.DateField(_('Withdrawal until'), null=True, blank=True)   # None: unknown
    withdrawal_approximate = models.BooleanField(_('Withdrawal end estimated'), default=False)
    withdrawal_reason = models.CharField(_('Withdrawal'), max_length=500, blank=True)
    last_fed_at = models.DateTimeField(_('Last fed'), null=True, blank=True)
    # The feeding record the fast was counted from (its unit is where the fish were fed: the unit handled, or the one
    # they came from). A voided feeding stays as a row, so the link never breaks.
    feeding = models.ForeignKey('farm.FeedingRecord', null=True, blank=True, on_delete=models.PROTECT, related_name='+',
                                verbose_name=_('Feeding counted from'))
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
        """The handling it was given for: the operation's kind, or a treatment; None on a stocking (the row of fish
        combined with held fish)."""
        if self.treatment_id:
            return HandlingKind.TREATMENT
        return KIND_OF_OPERATION.get(self.operation.kind)


class WithdrawalWarning(models.TextChoices):
    """What a change of a withdrawal does that a person must go on past (farm.health.withdrawal.guarded)."""
    HARVESTED = 'harvested', _('Harvest inside a withdrawal')
    DELIVERED = 'delivered', _('Live delivery inside a withdrawal')
    RELEASED = 'released', _('Fish freed from a withdrawal')
    HELD = 'held', _('Fish held again by a withdrawal')


# The warnings that name the operation whose fish left the farm inside the withdrawal (`harvest`), each with the kind of
# operation it names: a harvested row a harvest, a delivered row a live delivery. The database's CHECK holds only that an
# operation is named (a cross-table rule is no CHECK); farm.stock.integrity holds the kind (`check_stock`).
OPERATION_NAMED = {WithdrawalWarning.HARVESTED: OperationKind.HARVEST,
                   WithdrawalWarning.DELIVERED: OperationKind.DELIVERY}
NAMING_THE_HARVEST = tuple(OPERATION_NAMED)


class WithdrawalAcknowledgement(models.Model):
    """One warning a person went on past when a write changed a medicine withdrawal (the withdrawal guard,
    farm.health.withdrawal.guarded, which every such write goes through: a treatment, its last day or void, a medicated
    feeding or its void, a medicine's withdrawal rows, a water sample, a stock operation): a harvest already recorded now
    lies inside a withdrawal (`harvested`, naming the harvest), a live delivery already recorded does (`delivered`,
    naming the delivery in the same column: the owner's decision 13 of 19.11.2026, a live delivery is a harvest also
    after the fact), fish held today are freed by it (`released`), or fish
    that had been let go are held again by it (`held`: a longer ceiling for the ends without a rule). It
    names the write (`record_type`, `record_id`, `record_label`, as the activity log names records), the batch, the
    withdrawal (`source`: "treatment:<id>" or "feeding:<id>") and what was shown, and who went on and when. Append-only:
    the database refuses an edit or a delete (migration farm 0027); the write's log entry is critical."""

    id = models.BigAutoField(primary_key=True)
    created_at = models.DateTimeField(_('Acknowledged at'), auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+',
                                   verbose_name=_('Acknowledged by'))
    record_type = models.CharField(_('Record'), max_length=60)
    record_id = models.CharField(_('Record id'), max_length=64)
    record_label = models.CharField(_('Record name'), max_length=255)
    warning = models.CharField(_('Warning'), max_length=12, choices=WithdrawalWarning.choices)
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name='+', verbose_name=_('Batch'))
    harvest = models.ForeignKey(StockOperation, null=True, blank=True, on_delete=models.PROTECT,
                                related_name='withdrawal_findings', verbose_name=_('Harvest or live delivery'))
    source = models.CharField(_('Withdrawal of'), max_length=80)
    until = models.DateField(_('Withdrawal until'), null=True, blank=True)       # None: unknown
    approximate = models.BooleanField(_('Withdrawal end estimated'), default=False)
    reason = models.CharField(_('Withdrawal'), max_length=500, blank=True)

    class Meta:
        db_table = 'withdrawal_acknowledgements'
        ordering = ['id']
        verbose_name = _('withdrawal acknowledgement')
        verbose_name_plural = _('withdrawal acknowledgements')
        constraints = [
            models.CheckConstraint(condition=Q(warning__in=WithdrawalWarning.values),
                                   name='chk_withdrawal_acknowledgements_warning'),
            # A harvested row names the harvest inside the withdrawal, a delivered row the live delivery; a released and
            # a held row name none.
            models.CheckConstraint(
                condition=Q(warning__in=NAMING_THE_HARVEST, harvest__isnull=False)
                | Q(warning__in=[WithdrawalWarning.RELEASED, WithdrawalWarning.HELD], harvest__isnull=True),
                name='chk_withdrawal_acknowledgements_harvest'),
        ]
        indexes = [models.Index(fields=['harvest', 'batch'])]

    def __str__(self):
        return f'{self.get_warning_display()} · {self.record_label}'
