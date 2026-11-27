"""What a feeding protocol and a temperature profile share: a table for one species that is assigned to fish, and its
assignment rows (owner decision 16 of 2026-11-26: the same three targets, the same "most specific wins" rule, the same
constraints). One rule each, written once here:

- `Assignable`: a draft is built and changed freely; an active one takes assignments; a retired one keeps its past
  assignments and takes no new ones. Once it is assigned its table and the fields that shape what it gives are fixed
  (owner decision Q3): what it gave for past days never changes, and a change is made on a copy (Duplicate).
- `TargetedAssignment`: a row in force for a unit, a whole batch or a batch in one unit, from a day and optionally until
  a day (both included). One row per target; the database keeps one row in force per unit, per batch and per batch in
  a unit on any day (`assignment_constraints`: exclusion constraints among live rows); on read the most specific row
  wins (farm/feeding/resolve.py, the one resolver). Rows are history: before its first day a row may be changed or
  deleted; from its first day only its last day and notes change. A unit or a batch keeps its rows when it is deleted
  or voided (DO_NOTHING), and the database refuses a hard delete."""
import uuid

from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import RangeOperators
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q, Value
from django.utils import timezone
from django.utils.translation import gettext, gettext_lazy as _

from core.models import AuditedModel
from core.ranges import DateRange

from .site import zone_of


class ProtocolStatus(models.TextChoices):
    DRAFT = 'draft', _('Draft')
    ACTIVE = 'active', _('Active')
    RETIRED = 'retired', _('Retired')


class BetweenBands(models.TextChoices):
    """How a value of a table is read for fish between two of its weights (farm/feeding/growth.py, `between`)."""
    SMOOTH = 'smooth', _('Smooth between bands')
    STEP = 'step', _('Step at the band edge')


class Scope(models.TextChoices):
    """What an assignment row covers, from the most specific to the least: the order the rows are read in."""
    BATCH_IN_UNIT = 'batch_in_unit', _('Batch in unit')
    UNIT = 'unit', _('Unit')
    BATCH = 'batch', _('Whole batch')


class Assignable:
    """The status rules of a table that is assigned to fish (a feeding protocol, a temperature profile). A subclass
    names `FIXED` (its fields fixed once assigned) and the messages that name it, and says `has_table()`."""

    FIXED = ()
    NEEDS_TABLE = ''          # "Fill in its feeding table first: …"
    FIXED_MESSAGE = ''        # "Fixed: the protocol is assigned. Duplicate it to change it."

    def has_table(self):
        raise NotImplementedError

    def is_assigned(self):
        """Whether an assignment names it: from then on its table and its FIXED fields are fixed."""
        return self.pk is not None and self.assignments.exists()

    def clean(self):
        """The rules of its status and of an assigned table, each with its message on the field to change."""
        super().clean()
        errors = {}
        stored = None if self._state.adding else type(self).all_objects.filter(pk=self.pk).first()
        if self.status == ProtocolStatus.ACTIVE and (stored is None or not self.has_table()):
            errors['status'] = str(self.NEEDS_TABLE)
        if stored is not None and self.is_assigned():
            for name in self.FIXED:
                if getattr(self, name) != getattr(stored, name):
                    errors[name] = str(self.FIXED_MESSAGE)
            if self.status == ProtocolStatus.DRAFT:
                errors['status'] = gettext('It is assigned: it cannot go back to draft.')
        if self.status == ProtocolStatus.RETIRED and stored is not None and stored.status != ProtocolStatus.RETIRED:
            today = timezone.localdate(timezone=zone_of(None))
            if self.assignments.filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today)).exists():
                errors['status'] = gettext('It is assigned for today or later: end those assignments first.')
        if errors:
            raise ValidationError(errors)


def _period():
    return DateRange(F('valid_from'), F('valid_until'), Value('[]'))


def assignment_constraints(table, unit_taken, batch_taken, pair_taken):
    """The constraints of an assignment table: a target, a period, and one live row in force per unit, per batch and
    per batch in a unit on any day (each with the message that names what is assigned)."""
    return [
        models.CheckConstraint(condition=Q(unit__isnull=False) | Q(batch__isnull=False), name=f'chk_{table}_target',
                               violation_error_message=_('Choose a unit, a batch, or both.')),
        models.CheckConstraint(condition=Q(valid_until__isnull=True) | Q(valid_until__gte=F('valid_from')),
                               name=f'chk_{table}_period',
                               violation_error_message=_('The last day comes on or after the first day.')),
        ExclusionConstraint(
            name=f'excl_{table}_unit',
            expressions=[(F('unit'), RangeOperators.EQUAL), (_period(), RangeOperators.OVERLAPS)],
            condition=Q(batch__isnull=True, is_deleted=False), violation_error_message=unit_taken),
        ExclusionConstraint(
            name=f'excl_{table}_batch',
            expressions=[(F('batch'), RangeOperators.EQUAL), (_period(), RangeOperators.OVERLAPS)],
            condition=Q(unit__isnull=True, is_deleted=False), violation_error_message=batch_taken),
        ExclusionConstraint(
            name=f'excl_{table}_batch_in_unit',
            expressions=[(F('unit'), RangeOperators.EQUAL), (F('batch'), RangeOperators.EQUAL),
                         (_period(), RangeOperators.OVERLAPS)],
            condition=Q(unit__isnull=False, batch__isnull=False, is_deleted=False), violation_error_message=pair_taken),
    ]


class TargetedAssignment(AuditedModel):
    """A row in force for a unit, a whole batch or a batch in one unit (the module's rules). A subclass declares its
    `subject` foreign key under the name `SUBJECT` (protocol, profile), `unit` and `batch`, and the messages that name
    what it assigns."""

    Scope = Scope
    SUBJECT = ''
    ONLY_ACTIVE = ''          # "Only an active protocol can be assigned; this one is %(status)s."
    OTHER_SPECIES = ''        # "%(batch)s is %(species)s; the protocol is for %(protocol_species)s."
    STARTED = ''              # "It has started: set its last day instead. …"
    KEPT = ''                 # "The days before yesterday keep their protocol: …" (a started row's last day)

    valid_from = models.DateField(_('From'))
    valid_until = models.DateField(_('Until'), null=True, blank=True)
    # The rows one dialog wrote (several units at once), shown together.
    group_id = models.UUIDField(default=uuid.uuid4, editable=False)
    notes = models.CharField(_('Notes'), max_length=500, blank=True)

    class Meta:
        abstract = True

    @property
    def subject(self):
        return getattr(self, self.SUBJECT)

    @property
    def subject_id(self):
        return getattr(self, f'{self.SUBJECT}_id')

    def __str__(self):
        target = ' · '.join(part for part in (self.unit.code if self.unit_id else '',
                                               self.batch.code if self.batch_id else '') if part)
        return f'{self.subject} · {target} · {self.valid_from.isoformat()}'

    @property
    def scope(self):
        if self.unit_id and self.batch_id:
            return Scope.BATCH_IN_UNIT
        return Scope.UNIT if self.unit_id else Scope.BATCH

    def covers(self, day):
        return self.valid_from <= day and (self.valid_until is None or day <= self.valid_until)

    def today(self):
        """Today on the clock of the unit's site, else the company's."""
        site = self.unit.production_department.site if self.unit_id else None
        return timezone.localdate(timezone=zone_of(site))

    def started(self):
        return self.valid_from <= self.today()

    def delete_blockers(self):
        return [str(self.STARTED)] if self.started() else []

    def clean(self):
        """The rules a row can check on its own: an active table for a new row or a new table, of the batch's species.
        What may change once it has started is the form's rule; the overlaps are the exclusion constraints'."""
        super().clean()
        errors = {}
        if self.valid_until is not None and self.valid_from is not None and self.valid_until < self.valid_from:
            errors['valid_until'] = gettext('The last day comes on or after the first day.')
        if self.subject_id:
            subject = self.subject
            stored = None if self._state.adding else type(self).all_objects.filter(pk=self.pk).first()
            changed = stored is None or stored.subject_id != self.subject_id
            if changed and subject.status != ProtocolStatus.ACTIVE:
                errors[self.SUBJECT] = str(self.ONLY_ACTIVE) % {
                    'status': str(subject.get_status_display()).lower()}
            elif self.batch_id and self.batch.species_id != subject.species_id:
                errors['batch'] = str(self.OTHER_SPECIES) % {
                    'batch': self.batch.code, 'species': self.batch.species, 'protocol_species': subject.species}
        if errors:
            raise ValidationError(errors)
