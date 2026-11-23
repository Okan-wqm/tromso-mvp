"""Experiments (Research › Experiments): the design of a trial and the days each tank is booked to it.

An experiment stores only what no other record holds: the design (factors and their levels, groups and
controls), the replicates and the days each tank is booked to one (a placement), how the tanks were allocated,
and the team. Every figure (fish, feed, FCR, water, deaths) is read through the farm's own reads, bounded by the
placement's days (experiments/read.py); a diet is applied through the farm's own feeding-protocol assignments
(experiments/services.py). The app reads `farm` and nothing reads it.

Nothing the farm already knows is copied: no count, batch, biomass or feed, no system of a replicate (a
replicate's tanks are stored, a system is only a shortcut on the page, because `Tank.system` changes), no
end date (derived), no experiment id on any farm record.

The rules a row or a pair of rows can say are database constraints, so they hold whatever writes: one tank in
one experiment at a time (an exclusion constraint on the placements), one level per factor per group, a level
that belongs to its factor and a group to its experiment (composite foreign keys, made by the migration), a diet
level with a protocol, one diet factor, one lead, a started experiment with its day 0, hypothesis, endpoint and
allocation; and, by triggers (migration 0002), a started design that no writer can change. What PostgreSQL cannot
say without copying columns (a tank on the experiment's site, a window inside the experiment's span, a level for
every factor) is checked by `design.problems` and the services, and said so there."""
from datetime import timedelta

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import RangeOperators
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q, Value
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.translation import gettext, gettext_lazy as _

from core.models import AuditedModel, SealedManager
from farm.models import FeedingProtocol, Site, Species, System, Tank
from farm.models.feeding_protocol import DateRange

from .variables import ENDPOINTS, Endpoint

MAX_DURATION_DAYS = 1095
MAX_REPLICATE_NUMBER = 99
CODE_PATTERN = r'^E-[0-9]{4}-[0-9]{3,}$'
# The fields of an experiment's Details tab, which the activity log shows of a new one.
DETAIL_FIELDS = ['name', 'species', 'site', 'hypothesis', 'primary_endpoint', 'starts_on', 'duration_days', 'notes']


class Status(models.TextChoices):
    DRAFT = 'draft', _('Draft')
    RUNNING = 'running', _('Running')
    CLOSED = 'closed', _('Closed')


# The status machine, in one place (as farm/models/tank.py): from each status, the ones an experiment can move to.
# The lifecycle (closing with the record lock, reopening) extends it.
TRANSITIONS = {
    Status.DRAFT: (Status.RUNNING,),
    Status.RUNNING: (Status.CLOSED,),
    Status.CLOSED: (),
}


class Audience(models.TextChoices):
    """Who may read an experiment: its team and the people its lead shares a part with (sealed, the default), or
    everyone who may read experiments (open). Changed by the lead only, logged."""
    SEALED = 'sealed', _('Team and shares only')
    OPEN = 'open', _('Everyone who reads experiments')


class AllocationMethod(models.TextChoices):
    """How the replicates were given their tanks. Randomised: a seeded deal (experiments/allocation.py) whose
    method id is stored with the seed, so the same pool and seed give the same placements for ever."""
    NONE = '', _('Not allocated')
    RANDOMISED = 'sha256_v1', _('Randomised')
    MANUAL = 'manual', _('Placed by hand')


class Experiment(AuditedModel):
    """A trial of one species on one site: its design, its allocation and its dates; also a template to copy.

    A draft is built freely and reserves its tanks (a booking nobody else can make for the same days). Starting it
    fixes the design for ever (pre-registration): the database refuses any change to a started experiment but its
    name, notes and status, and a placement can only be shortened. A template is a design without dates, tanks or
    allocation, copied into new experiments."""

    Status, AllocationMethod, Endpoint, Audience = Status, AllocationMethod, Endpoint, Audience

    # Generated on creation (experiments/forms.py, core.codes.next_code), never typed or changed, never reused.
    code = models.CharField(_('Experiment number'), max_length=20, editable=False)
    name = models.CharField(_('Name'), max_length=150)
    is_template = models.BooleanField(_('Template'), default=False)
    status = models.CharField(_('Status'), max_length=10, choices=Status.choices, default=Status.DRAFT)
    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name='experiments', verbose_name=_('Site'))
    species = models.ForeignKey(Species, on_delete=models.PROTECT, related_name='experiments',
                                verbose_name=_('Species'))
    hypothesis = models.CharField(_('Hypothesis'), max_length=4000, blank=True)
    primary_endpoint = models.CharField(_('Primary endpoint'), max_length=40, choices=ENDPOINTS, blank=True)
    # Day 0 is the baseline weighing; the last day (starts_on + duration_days) is the final weighing. Days are the
    # site's own (farm/stock/dates.py).
    starts_on = models.DateField(_('Starts on'), null=True, blank=True)
    duration_days = models.PositiveSmallIntegerField(
        _('Duration (days)'), validators=[MinValueValidator(1), MaxValueValidator(MAX_DURATION_DAYS)])
    allocation_method = models.CharField(_('Allocation'), max_length=10, choices=AllocationMethod.choices,
                                         blank=True, default=AllocationMethod.NONE)
    allocation_seed = models.BigIntegerField(_('Allocation seed'), null=True, blank=True)
    allocation_note = models.CharField(_('Reason for placing by hand'), max_length=500, blank=True)
    # The experiment this was copied from. A copy outlives a deleted source and keeps pointing at it (history, as
    # a unit's feeding records): setting it to nothing would change a started experiment.
    copied_from = models.ForeignKey('self', null=True, blank=True, on_delete=models.DO_NOTHING,
                                    related_name='copies', verbose_name=_('Copied from'))
    notes = models.CharField(_('Notes'), max_length=2000, blank=True)
    # Who may read it (core.sealing; sealed whatever writes the row, the database default too): a sealed experiment, its cells and everything on them do not exist for anyone
    # outside its team and its shares. Editable after the start, like the name (migration 0004).
    audience = models.CharField(_('Who may read it'), max_length=6, choices=Audience.choices, default=Audience.SEALED,
                                db_default=Audience.SEALED)
    # The animal-research approval it runs under (FOTS), shown on the card a person overseeing its tanks sees.
    approval_ref = models.CharField(_('Approval reference'), max_length=60, blank=True, default='', db_default='')
    approval_valid_until = models.DateField(_('Approval valid until'), null=True, blank=True)
    # Whom a night technician calls about a tank of it (the lead's phone): on the same card.
    contact_phone = models.CharField(_('Contact phone'), max_length=30, blank=True, default='', db_default='')

    kept_note = _('They stay as they are.')

    class Meta:
        db_table = 'experiments'
        ordering = ['-created_at']
        verbose_name = _('experiment')
        verbose_name_plural = _('experiments')
        # Oversee (the role matrix's column, offered by the Experiments area): the farm facts of every sealed cell
        # (stock, feeding, water, health, alarms, tasks), never its design or results; the experiment shown as a card.
        permissions = [('oversee_experiment', 'Can oversee the tanks of experiments')]
        constraints = [
            # Never reused, not even the number of a deleted experiment (as batches).
            models.UniqueConstraint(fields=['code'], name='uq_experiments_code'),
            models.CheckConstraint(condition=Q(code__regex=CODE_PATTERN), name='chk_experiments_code'),
            models.CheckConstraint(condition=Q(status__in=Status.values), name='chk_experiments_status'),
            models.CheckConstraint(condition=Q(audience__in=Audience.values), name='chk_experiments_audience'),
            models.CheckConstraint(condition=Q(approval_valid_until__isnull=True) | ~Q(approval_ref=''),
                                   name='chk_experiments_approval',
                                   violation_error_message=_("An approval's validity needs its reference.")),
            models.CheckConstraint(condition=Q(primary_endpoint__in=['', *Endpoint.values]),
                                   name='chk_experiments_endpoint'),
            models.CheckConstraint(condition=Q(duration_days__gte=1, duration_days__lte=MAX_DURATION_DAYS),
                                   name='chk_experiments_duration'),
            models.CheckConstraint(
                condition=Q(is_template=False) | Q(status=Status.DRAFT, starts_on__isnull=True,
                                                   allocation_method=AllocationMethod.NONE),
                name='chk_experiments_template',
                violation_error_message=_('A template is a draft design without a start day or an allocation.')),
            models.CheckConstraint(
                condition=Q(status=Status.DRAFT)
                | (Q(starts_on__isnull=False) & ~Q(hypothesis='') & ~Q(primary_endpoint='')
                   & ~Q(allocation_method=AllocationMethod.NONE)),
                name='chk_experiments_started',
                violation_error_message=_('A started experiment has its day 0, hypothesis, primary endpoint and '
                                          'allocation.')),
            # The method, its seed and its reason belong together: a seed only where the deal was seeded, a reason
            # only where it was done by hand.
            models.CheckConstraint(
                condition=Q(allocation_method=AllocationMethod.NONE, allocation_seed__isnull=True, allocation_note='')
                | Q(allocation_method=AllocationMethod.RANDOMISED, allocation_seed__isnull=False, allocation_note='')
                | (Q(allocation_method=AllocationMethod.MANUAL, allocation_seed__isnull=True)
                   & ~Q(allocation_note='')),
                name='chk_experiments_allocation',
                violation_error_message=_('A randomised allocation has its seed; one placed by hand has its reason.')),
        ]
        indexes = [models.Index(fields=['status'], name='idx_experiments_status')]

    def __str__(self):
        return f'{self.code} · {self.name}'

    @property
    def is_draft(self):
        return self.status == Status.DRAFT

    def delete_blockers(self):
        """Only a draft or a template is deleted; a started experiment is part of the record (the database's
        trigger holds it for any writer)."""
        if self.status != Status.DRAFT:
            return [gettext('It has started: it is kept as a record. Close it instead.')]
        return []


class FactorKind(models.TextChoices):
    DIET = 'diet', _('Diet')
    OTHER = 'other', _('Other factor')


class Factor(AuditedModel):
    """A thing the groups differ in: the diet (each of its levels names a feeding protocol, which is how the
    farm applies it) or another factor (a temperature, a density) whose levels are labelled values. One diet
    factor at most per experiment."""

    Kind = FactorKind

    experiment = models.ForeignKey(Experiment, on_delete=models.CASCADE, related_name='factors',
                                   verbose_name=_('Experiment'))
    name = models.CharField(_('Name'), max_length=60)
    kind = models.CharField(_('Kind'), max_length=10, choices=FactorKind.choices, default=FactorKind.OTHER)
    # The unit of a quantitative factor's levels (°C, kg/m³); the diet's levels are protocols, not quantities.
    unit = models.CharField(_('Unit of its levels'), max_length=20, blank=True)
    position = models.PositiveSmallIntegerField(_('Position'), default=0)

    class Meta:
        db_table = 'experiment_factors'
        ordering = ['position', 'name']
        verbose_name = _('experiment factor')
        verbose_name_plural = _('experiment factors')
        constraints = [
            models.UniqueConstraint(Lower('name'), F('experiment'), condition=Q(is_deleted=False),
                                    name='uq_experiment_factors_name_live',
                                    violation_error_message=_('Another factor of this experiment has this name.')),
            models.UniqueConstraint(fields=['experiment'], condition=Q(kind=FactorKind.DIET, is_deleted=False),
                                    name='uq_experiment_factors_diet',
                                    violation_error_message=_('An experiment has one diet factor.')),
            # The targets of the composite keys: a level names its factor and its kind; a group's level of a
            # factor names the factor and the experiment (the migration makes the keys).
            models.UniqueConstraint(fields=['id', 'experiment'], name='uq_experiment_factors_id_experiment'),
            models.UniqueConstraint(fields=['id', 'kind'], name='uq_experiment_factors_id_kind'),
            models.CheckConstraint(condition=Q(kind__in=FactorKind.values), name='chk_experiment_factors_kind'),
            models.CheckConstraint(condition=Q(kind=FactorKind.OTHER) | Q(unit=''),
                                   name='chk_experiment_factors_diet_unit',
                                   violation_error_message=_('The diet has no unit: its levels are protocols.')),
        ]

    def __str__(self):
        return self.name


class Level(AuditedModel):
    """A value of a factor. A diet level names the feeding protocol its groups are fed by (the protocol is
    protected: it cannot be deleted while a level names it); another level has a label and optionally a number
    (a dose, a setting) the dataset reads. A diet level has no label of its own: it is called what its protocol is
    called."""

    factor = models.ForeignKey(Factor, on_delete=models.CASCADE, related_name='levels', verbose_name=_('Factor'))
    # Copied from the factor in save(), and held by the composite key (factor, kind): a level of the wrong kind
    # cannot be stored.
    kind = models.CharField(_('Kind'), max_length=10, choices=FactorKind.choices, editable=False)
    label = models.CharField(_('Level'), max_length=60, blank=True)
    protocol = models.ForeignKey(FeedingProtocol, null=True, blank=True, on_delete=models.PROTECT,
                                 related_name='experiment_levels', verbose_name=_('Feeding protocol'))
    value = models.DecimalField(_('Value'), max_digits=12, decimal_places=4, null=True, blank=True)

    class Meta:
        db_table = 'experiment_levels'
        ordering = ['label', 'id']
        verbose_name = _('factor level')
        verbose_name_plural = _('factor levels')
        constraints = [
            models.UniqueConstraint(Lower('label'), F('factor'), condition=Q(is_deleted=False) & ~Q(label=''),
                                    name='uq_experiment_levels_label_live',
                                    violation_error_message=_('Another level of this factor has this label.')),
            models.UniqueConstraint(fields=['factor', 'protocol'],
                                    condition=Q(is_deleted=False, protocol__isnull=False),
                                    name='uq_experiment_levels_protocol_live',
                                    violation_error_message=_('Another level of this diet has this protocol.')),
            models.UniqueConstraint(fields=['id', 'factor'], name='uq_experiment_levels_id_factor'),
            models.CheckConstraint(condition=Q(kind__in=FactorKind.values), name='chk_experiment_levels_kind'),
            # A diet level feeds by a protocol and has no label or number; another level has a label and no
            # protocol. Else a start would silently skip a diet, or feed none.
            models.CheckConstraint(
                condition=Q(kind=FactorKind.DIET, protocol__isnull=False, value__isnull=True, label='')
                | (Q(kind=FactorKind.OTHER, protocol__isnull=True) & ~Q(label='')),
                name='chk_experiment_levels_by_kind',
                violation_error_message=_('A diet level names a protocol; another level has a label.')),
        ]

    def __str__(self):
        return self.label or (str(self.protocol) if self.protocol_id else '')

    def save(self, *args, **kwargs):
        self.kind = self.factor.kind
        super().save(*args, **kwargs)


class GroupRole(models.TextChoices):
    """A group's part in the design. Both kinds of control may exist (a negative and a positive one), so no
    uniqueness is asked."""
    TEST = 'test', _('Test group')
    CONTROL = 'control', _('Control group')
    NEGATIVE_CONTROL = 'negative_control', _('Negative control group')
    POSITIVE_CONTROL = 'positive_control', _('Positive control group')


CONTROLS = (GroupRole.CONTROL, GroupRole.NEGATIVE_CONTROL, GroupRole.POSITIVE_CONTROL)


class ExperimentGroup(AuditedModel):
    """A group of replicates that get the same level of every factor. One of the groups is usually the control."""

    Role = GroupRole

    experiment = models.ForeignKey(Experiment, on_delete=models.CASCADE, related_name='groups',
                                   verbose_name=_('Experiment'))
    name = models.CharField(_('Name'), max_length=60)
    role = models.CharField(_('Role'), max_length=20, choices=GroupRole.choices, default=GroupRole.TEST)
    position = models.PositiveSmallIntegerField(_('Position'), default=0)

    class Meta:
        db_table = 'experiment_groups'
        ordering = ['position', 'name']
        verbose_name = _('experiment group')
        verbose_name_plural = _('experiment groups')
        constraints = [
            models.UniqueConstraint(Lower('name'), F('experiment'), condition=Q(is_deleted=False),
                                    name='uq_experiment_groups_name_live',
                                    violation_error_message=_('Another group of this experiment has this name.')),
            models.UniqueConstraint(fields=['id', 'experiment'], name='uq_experiment_groups_id_experiment'),
            models.CheckConstraint(condition=Q(role__in=GroupRole.values), name='chk_experiment_groups_role'),
        ]

    def __str__(self):
        return self.name

    @property
    def is_control(self):
        return self.role in CONTROLS


class GroupLevel(models.Model):
    """The level a group has of a factor: one row per group and factor. A plain row of the design (it has no
    update or delete columns of its own: the design is saved whole and logged on the experiment). The database
    keeps it true by three composite keys the migration makes: the group and the factor are of one experiment, and
    the level is of that factor. A wrong row would put another trial's level in a group and corrupt every factor
    column of the dataset."""

    experiment = models.ForeignKey(Experiment, on_delete=models.CASCADE, related_name='group_levels',
                                   verbose_name=_('Experiment'))
    group = models.ForeignKey(ExperimentGroup, on_delete=models.CASCADE, related_name='levels',
                              verbose_name=_('Group'))
    factor = models.ForeignKey(Factor, on_delete=models.CASCADE, related_name='group_levels',
                               verbose_name=_('Factor'))
    level = models.ForeignKey(Level, on_delete=models.CASCADE, related_name='group_levels',
                              verbose_name=_('Level'))

    class Meta:
        db_table = 'experiment_group_levels'
        ordering = ['id']
        verbose_name = _('group level')
        verbose_name_plural = _('group levels')
        constraints = [
            # One level per factor per group.
            models.UniqueConstraint(fields=['group', 'factor'], name='uq_experiment_group_levels_group_factor'),
        ]

    def __str__(self):
        return f'{self.group} · {self.factor}: {self.level}'


class Replicate(AuditedModel):
    """One experimental unit of a group, numbered within it. It holds one or more tanks over the days (a
    placement each): a tank replaced during the trial is a second placement of the same replicate, so the number
    stays. A replicate without a placement is a design slot (a template has only slots)."""

    group = models.ForeignKey(ExperimentGroup, on_delete=models.CASCADE, related_name='replicates',
                              verbose_name=_('Group'))
    number = models.PositiveSmallIntegerField(_('Replicate'), validators=[MinValueValidator(1),
                                                                          MaxValueValidator(MAX_REPLICATE_NUMBER)])

    class Meta:
        db_table = 'experiment_replicates'
        ordering = ['number']
        verbose_name = _('replicate')
        verbose_name_plural = _('replicates')
        constraints = [
            models.UniqueConstraint(fields=['group', 'number'], condition=Q(is_deleted=False),
                                    name='uq_experiment_replicates_number_live',
                                    violation_error_message=_('Another replicate of this group has this number.')),
            models.CheckConstraint(condition=Q(number__gte=1, number__lte=MAX_REPLICATE_NUMBER),
                                   name='chk_experiment_replicates_number'),
        ]

    def __str__(self):
        return f'{self.group} R{self.number}'


class ReplicateUnit(AuditedModel):
    """A tank booked to a replicate for a range of days, both included, on the site's clock: day 0 is the
    experiment's `starts_on` (the baseline weighing), the last day `starts_on + duration_days` (the final
    weighing). A tank is in one experiment at a time: the exclusion constraint refuses two live placements of one
    tank on overlapping days, drafts included (a draft reserves its tanks). A placement ends on a day, never open:
    an open end would book the tank for ever. Once the experiment has started a placement can only be shortened
    (a tank released or replaced); the trigger holds it."""

    replicate = models.ForeignKey(Replicate, on_delete=models.CASCADE, related_name='placements',
                                  verbose_name=_('Replicate'))
    # A tank that was ever in a trial is never deleted: it is set inactive (owner decision).
    unit = models.ForeignKey(Tank, on_delete=models.PROTECT, related_name='experiment_placements',
                             verbose_name=_('Unit'))
    from_on = models.DateField(_('From'))
    until_on = models.DateField(_('Until'))
    left_reason = models.CharField(_('Reason it left'), max_length=500, blank=True)
    # The whole-system booking this placement is a tank of (ReplicateSystem); none for a tank booked by itself.
    booking = models.ForeignKey('ReplicateSystem', null=True, blank=True, on_delete=models.PROTECT,
                                related_name='placements', verbose_name=_('System booking'))

    class Meta:
        db_table = 'experiment_replicate_units'
        ordering = ['from_on', 'id']
        verbose_name = _('experiment placement')
        verbose_name_plural = _('experiment placements')
        constraints = [
            models.CheckConstraint(condition=Q(until_on__gte=F('from_on')), name='chk_experiment_placements_period',
                                   violation_error_message=_('The last day comes on or after the first day.')),
            # The twin of the feeding assignments' exclusion (farm/models/feeding_protocol.py): the tank is the
            # only equality operand, so a missing value cannot defeat it.
            ExclusionConstraint(
                name='excl_replicate_units_unit',
                expressions=[(F('unit'), RangeOperators.EQUAL),
                             (DateRange(F('from_on'), F('until_on'), Value('[]')), RangeOperators.OVERLAPS)],
                condition=Q(is_deleted=False),
                violation_error_message=_('This unit is booked to another experiment on some of these days.')),
        ]
        indexes = [models.Index(fields=['unit', 'from_on'], name='idx_experiment_placements_unit')]

    def __str__(self):
        return f'{self.replicate} · {self.unit.code} · {self.from_on.isoformat()}'


class MemberRole(models.TextChoices):
    LEAD = 'lead', _('Lead')
    RESEARCHER = 'researcher', _('Researcher')
    STUDENT = 'student', _('Student')
    TECHNICIAN = 'technician', _('Technician')
    ADVISOR = 'advisor', _('Advisor')
    # A visitor from outside the company: present and observing, for the days of their window.
    GUEST = 'guest', _('Guest')


class Member(models.Model):
    """A person of the experiment's team, with their part. A plain row (a list saved whole on the Team tab, logged
    on the experiment). Exactly one lead: the creator at first; per-experiment rights come with the permissions
    plan, which reads this."""

    Role = MemberRole

    experiment = models.ForeignKey(Experiment, on_delete=models.CASCADE, related_name='members',
                                   verbose_name=_('Experiment'))
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='experiment_memberships',
                             verbose_name=_('Person'))
    role = models.CharField(_('Role'), max_length=12, choices=MemberRole.choices, default=MemberRole.RESEARCHER)
    # The member's window, read at each request (no job): an empty end is open.
    valid_from = models.DateTimeField(_('From'), null=True, blank=True)
    valid_until = models.DateTimeField(_('Until'), null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+', verbose_name=_('Created by'))

    objects = SealedManager()

    class Meta:
        db_table = 'experiment_members'
        ordering = ['role', 'id']
        verbose_name = _('experiment member')
        verbose_name_plural = _('experiment members')
        constraints = [
            models.UniqueConstraint(fields=['experiment', 'user'], name='uq_experiment_members_user',
                                    violation_error_message=_('This person is already in the team.')),
            models.UniqueConstraint(fields=['experiment'], condition=Q(role=MemberRole.LEAD),
                                    name='uq_experiment_members_lead',
                                    violation_error_message=_('An experiment has one lead.')),
            models.CheckConstraint(condition=Q(role__in=MemberRole.values), name='chk_experiment_members_role'),
            models.CheckConstraint(condition=Q(valid_from__isnull=True) | Q(valid_until__isnull=True)
                                   | Q(valid_until__gt=F('valid_from')), name='chk_experiment_members_window',
                                   violation_error_message=_('The window ends after it begins.')),
        ]

    def __str__(self):
        return f'{self.user.get_full_name() or self.user.get_username()} ({self.get_role_display()})'


class SharePart(models.TextChoices):
    """What a share opens of an experiment (the owner's five). Closure is read at read time (experiments/sealing.py):
    the results and the data come with the design and the systems; the water with the systems."""
    DESIGN = 'design', _('Design')
    RESULTS = 'results', _('Results')
    SYSTEMS = 'systems', _('Systems and tanks')
    DATA = 'data', _('Data')
    WATER = 'water', _('Water')


# The longest a share lasts: a grant is renewed, never left open.
MAX_SHARE_DAYS = 730


class ExperimentShare(models.Model):
    """A part of an experiment given by its lead to a person or a role outside its team, for a time and with a reason.
    The one grant table for people who are not in the team. A row is never deleted or edited: a revoke sets who and when,
    a new share is a new row, so the history of who could read what stays. Logged on the experiment."""

    Part = SharePart

    experiment = models.ForeignKey(Experiment, on_delete=models.CASCADE, related_name='shares',
                                   verbose_name=_('Experiment'))
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                             related_name='experiment_shares', verbose_name=_('Person'))
    group = models.ForeignKey('auth.Group', null=True, blank=True, on_delete=models.PROTECT,
                              related_name='experiment_shares', verbose_name=_('Role'))
    part = models.CharField(_('Part'), max_length=8, choices=SharePart.choices)
    valid_from = models.DateTimeField(_('From'), default=timezone.now)
    valid_until = models.DateTimeField(_('Until'))
    reason = models.CharField(_('Reason'), max_length=300)
    revoked_at = models.DateTimeField(_('Revoked at'), null=True, blank=True)
    revoked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name='+', verbose_name=_('Revoked by'))
    created_at = models.DateTimeField(_('Created at'), auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+', verbose_name=_('Created by'))

    objects = SealedManager()

    class Meta:
        db_table = 'experiment_shares'
        ordering = ['-valid_from', 'id']
        verbose_name = _('experiment share')
        verbose_name_plural = _('experiment shares')
        constraints = [
            models.CheckConstraint(condition=Q(user__isnull=False, group__isnull=True)
                                   | Q(user__isnull=True, group__isnull=False), name='chk_experiment_shares_grantee',
                                   violation_error_message=_('A share is for one person or one role.')),
            models.CheckConstraint(condition=Q(part__in=SharePart.values), name='chk_experiment_shares_part'),
            models.CheckConstraint(condition=Q(valid_until__gt=F('valid_from')), name='chk_experiment_shares_period',
                                   violation_error_message=_('A share ends after it begins.')),
            models.CheckConstraint(
                condition=Q(valid_until__lte=F('valid_from') + timedelta(days=MAX_SHARE_DAYS)),
                name='chk_experiment_shares_length',
                violation_error_message=_('A share lasts at most two years: renew it when it ends.')),
            models.CheckConstraint(condition=~Q(reason=''), name='chk_experiment_shares_reason',
                                   violation_error_message=_('Say why it is shared.')),
            models.CheckConstraint(condition=Q(revoked_at__isnull=True, revoked_by__isnull=True)
                                   | Q(revoked_at__isnull=False, revoked_by__isnull=False),
                                   name='chk_experiment_shares_revoked'),
            models.UniqueConstraint(fields=['experiment', 'user', 'part'],
                                    condition=Q(revoked_at__isnull=True, user__isnull=False),
                                    name='uq_experiment_shares_user_part',
                                    violation_error_message=_('This person already holds this part.')),
            models.UniqueConstraint(fields=['experiment', 'group', 'part'],
                                    condition=Q(revoked_at__isnull=True, group__isnull=False),
                                    name='uq_experiment_shares_group_part',
                                    violation_error_message=_('This role already holds this part.')),
        ]
        indexes = [models.Index(fields=['user', 'valid_until'], name='idx_experiment_shares_user'),
                   models.Index(fields=['group', 'valid_until'], name='idx_experiment_shares_group')]

    def __str__(self):
        grantee = self.user or self.group
        return f'{grantee} · {self.get_part_display()}'

    def is_live(self, at=None):
        at = at or timezone.now()
        return self.revoked_at is None and self.valid_from <= at < self.valid_until


class ReplicateSystem(AuditedModel):
    """A whole system booked to a replicate for a range of days, both included: the intent ("this loop is replicate 2")
    and the window for what is kept by system (its sampling points, its sensor bindings, its tasks). Its tanks are
    booked too, each a placement (ReplicateUnit) tagged with this booking, written in the same save
    (experiments.services.save_places). A system is in one experiment at a time (the exclusion constraint, the twin of
    the tanks'); a nested system is booked as a row of its own. While a booking is live, the database refuses to move a
    tank into or out of the system, or the system under another parent (migration 0004): the tanks' rows stay what the
    system held."""

    replicate = models.ForeignKey(Replicate, on_delete=models.CASCADE, related_name='system_bookings',
                                  verbose_name=_('Replicate'))
    # A system that was ever booked is never deleted, as a booked tank.
    system = models.ForeignKey(System, on_delete=models.PROTECT, related_name='experiment_bookings',
                               verbose_name=_('System'))
    from_on = models.DateField(_('From'))
    until_on = models.DateField(_('Until'))
    left_reason = models.CharField(_('Reason it left'), max_length=500, blank=True)

    class Meta:
        db_table = 'experiment_replicate_systems'
        ordering = ['from_on', 'id']
        verbose_name = _('system booking')
        verbose_name_plural = _('system bookings')
        constraints = [
            models.CheckConstraint(condition=Q(until_on__gte=F('from_on')), name='chk_experiment_bookings_period',
                                   violation_error_message=_('The last day comes on or after the first day.')),
            ExclusionConstraint(
                name='excl_replicate_systems_system',
                expressions=[(F('system'), RangeOperators.EQUAL),
                             (DateRange(F('from_on'), F('until_on'), Value('[]')), RangeOperators.OVERLAPS)],
                condition=Q(is_deleted=False),
                violation_error_message=_('This system is booked on some of these days.')),
        ]
        indexes = [models.Index(fields=['system', 'from_on'], name='idx_experiment_bookings_system')]

    def __str__(self):
        return f'{self.replicate} · {self.system.code} · {self.from_on.isoformat()}'


class SealedCell(models.Model):
    """A sealed cell: a tank or a system booked to a sealed experiment for a range of days (the database view
    `experiment_cells`, migration 0004: the live placements and system bookings of live experiments whose audience is
    sealed, drafts included). Read only; the seal (core.sealing) is the one place that reads it."""

    id = models.UUIDField(primary_key=True)
    unit = models.ForeignKey(Tank, null=True, on_delete=models.DO_NOTHING, db_constraint=False, related_name='+')
    system = models.ForeignKey(System, null=True, on_delete=models.DO_NOTHING, db_constraint=False, related_name='+')
    from_on = models.DateField()
    until_on = models.DateField()
    work = models.UUIDField(db_column='experiment_id')

    class Meta:
        managed = False
        db_table = 'experiment_cells'
        verbose_name = _('sealed cell')
        verbose_name_plural = _('sealed cells')
