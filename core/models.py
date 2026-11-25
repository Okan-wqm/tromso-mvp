import uuid

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.validators import MaxValueValidator, MinValueValidator
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext, gettext_lazy as _

from .sealing import SealedMixin


class SealedManager(SealedMixin, models.Manager):
    """Every record, as far as the viewer of the moment may see it (core.sealing: a model with no filtering seal is
    not narrowed)."""


class ActiveManager(SealedMixin, models.Manager):
    """Hides soft-deleted records, and the records the viewer of the moment may not see (core.sealing)."""

    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class AuditedModel(models.Model):
    """Base of every farm record: author and time of creation and last change, an optimistic-lock
    version, and soft delete. `objects` shows live records only; `all_objects` shows everything; both leave out what
    the viewer of the moment may not see (core.sealing).

    How deleting one of these affects the records that point at it is not written per model: it
    follows each link's `on_delete` (see core.softdelete)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(_('Created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('Updated at'), auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
        verbose_name=_('Created by'),
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
        verbose_name=_('Updated by'),
    )
    version = models.PositiveIntegerField(_('Version'), default=1)
    is_deleted = models.BooleanField(_('Deleted'), default=False, db_index=True)
    deleted_at = models.DateTimeField(_('Deleted at'), null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
        verbose_name=_('Deleted by'),
    )

    objects = ActiveManager()
    all_objects = SealedManager()

    # What a delete's confirmation says of the records of this model that keep pointing at the deleted one
    # (their link is DO_NOTHING, core.softdelete): where they are while it is deleted.
    kept_note = _('They stay as they are, out of sight while this is deleted, and come back when it is restored.')

    class Meta:
        abstract = True

    def soft_delete(self, user):
        """Deletes the record its caller has locked (and maybe changed: a void's reason), writing it whole."""
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.deleted_by = user
        self.updated_by = user
        self.version += 1
        self.save()

    def mark_deleted(self, user, at):
        """Deletes a record a delete takes along (core.softdelete), stamped with the delete's moment `at`, which is
        how a restore finds what that delete took with it. Only the deletion's columns are written, the version
        counted up in the database: the record was read for the plan, not locked, and an edit saved meanwhile is
        neither overwritten nor taken for current (its editor's stale version is refused)."""
        self._write(user, is_deleted=True, deleted_at=at, deleted_by=user)

    def detach(self, link, user):
        """Clears the link to a deleted record; the change counts as an edit by `user` (written like
        mark_deleted, only the link's columns)."""
        self._write(user, **{link: None})

    def _write(self, user, **values):
        values.update(updated_by=user, updated_at=timezone.now())
        type(self).all_objects.filter(pk=self.pk).update(version=models.F('version') + 1, **values)
        for name, value in values.items():
            setattr(self, name, value)
        self.version = type(self).all_objects.values_list('version', flat=True).get(pk=self.pk)

    def delete_blockers(self):
        """Reasons this record cannot be deleted now (e.g. fish still in a tank); none by default."""
        return []

    @classmethod
    def deleted_with(cls, link, target):
        """Records of this model that point at `target` through `link`, a DO_NOTHING link, and are deleted
        with it all the same because they are only a plan, not history (a recurring task's planned tasks
        nobody has touched). None by default: what points at a record through DO_NOTHING is kept."""
        return cls.objects.none()


def violated_constraint(model, error):
    """The constraint of `model` a database refusal (`error`, an IntegrityError) names; None when it names none of its
    constraints (a fault, not a clash). A form shows its message on the field (core.crud), a restore as its reason."""
    name = getattr(getattr(error.__cause__, 'diag', None), 'constraint_name', None)
    return next((item for item in model._meta.constraints if item.name == name), None)


# A code as lists and reports show it: capital letters, digits, hyphens and underscores. A model that checks
# it uses both, in a RegexValidator and a database check (a species, a supplier).
CODE = r'^[A-Z0-9_-]+$'
CODE_MESSAGE = _('Use capital letters, digits, hyphens and underscores only.')


class CodedMixin:
    """Records known by a name and a short code: codes are stored upper-case, shown as "Name (CODE)".
    `name_field` is the field that holds the name: `name` for most records, `common_name` for a species."""

    name_field = 'name'

    def __str__(self):
        return f'{getattr(self, self.name_field)} ({self.code})'

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)


class TreeMixin:
    """Records nested under another record of the same kind through a `parent` link (a system inside
    a system, a pump mounted on a skid). A record cannot be nested under itself or anything below it."""

    def self_and_ancestors(self):
        """This record, its parent, that one's parent, and so on up to the top."""
        seen, node = set(), self
        while node is not None and node.pk not in seen:
            seen.add(node.pk)
            yield node
            node = node.parent

    def nested_under_itself(self):
        """Whether the chosen parent is this record or sits somewhere below it."""
        return self.parent is not None and self.pk in {node.pk for node in self.parent.self_and_ancestors()}

    def descendants(self):
        """Every live record nested below this one, at any depth."""
        found, frontier = [], [self]
        while frontier:
            frontier = list(type(self).objects.filter(parent__in=frontier))
            found.extend(frontier)
        return found


def in_tree_order(records, wanted=None):
    """Nested records (TreeMixin) as a list shows them: `records` (every live record, in the order
    siblings are listed) with each one followed by the records nested under it, and `depth` set on
    each. `wanted` (a queryset) keeps only its records, in the same order and at their real depth."""
    children = {}
    for record in records:
        children.setdefault(record.parent_id, []).append(record)
    keep = None if wanted is None else {record.pk for record in wanted}
    ordered = []

    def walk(record, depth):
        record.depth = depth
        if keep is None or record.pk in keep:
            ordered.append(record)
        for child in children.get(record.pk, []):
            walk(child, depth + 1)

    for record in children.get(None, []):
        walk(record, 0)
    return ordered


class AuditSeverity(models.TextChoices):
    """How much an activity-log entry matters. Critical: someone went on past a warning that protects fish
    or food (a harvest during a medicine withdrawal, a handling after too short a fast; farm/handling). The
    alarms that come later read these entries."""
    NORMAL = 'normal', _('Normal')
    CRITICAL = 'critical', _('Critical')


class AuditLogManager(models.Manager):
    def bulk_create(self, objs, *args, **kwargs):
        """The entries stamped with their works first (core.audit.stamp), as `save` does for one."""
        from .audit import stamp
        objs = list(objs)
        stamp(objs)
        return super().bulk_create(objs, *args, **kwargs)


class AuditLog(models.Model):
    """Who did what to which record, with old and new values. Rows are append-only: a database
    trigger (migration 0003) refuses UPDATE and DELETE, so history cannot be edited, not even by
    the platform admin."""

    class Action(models.TextChoices):
        CREATE = 'create', _('Created')
        UPDATE = 'update', _('Changed')
        DELETE = 'delete', _('Deleted')
        RESTORE = 'restore', _('Restored')
        # An operation that stops counting, with its reason (farm stock operations): history keeps it.
        VOID = 'void', _('Voided')
        # A person sent their invitation, at first and each time again (core.resources.UserResource.invite): an
        # event with what became of it, not a change of a value.
        INVITE = 'invite', _('Invited')
        # A person set their password through the link of an invitation or a reset mail (core.views.SetPasswordView):
        # by them, with the address the link went to.
        PASSWORD = 'password', _('Password set')

    # Defined outside the class so that its Meta can name their values in the constraint.
    Severity = AuditSeverity

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    # No database-level foreign key: deleting a user would otherwise have to update these rows.
    # user_name keeps the name as it was when the action happened.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.DO_NOTHING,
        db_constraint=False, related_name='+',
    )
    user_name = models.CharField(max_length=150)
    action = models.CharField(max_length=10, choices=Action.choices)
    entity_type = models.CharField(max_length=50, db_index=True)
    entity_id = models.CharField(max_length=64)
    entity_label = models.CharField(max_length=255)
    # {field label: [old, new]}; on create old is None, on delete new is None. Labels are msgids; a value
    # is None, a person's text as written, {'msgid': ...} for an enumeration, or a list of those for several
    # choices, a private value ({'msgid': 'Private text', 'rev': digest, 'of': what it is}) or a list of lists (a
    # contact list: the parts of each contact) (see core.audit).
    changes = models.JSONField(default=dict, blank=True)
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.NORMAL)
    # The confidential works the record lay in when the entry was written (core.sealing.works_of; '*' when that could
    # not be read): stamped by `save` and the log's bulk_create (core.audit.stamp). The change token leaves out an entry
    # stamped with a work hidden from the person looking (core.audit.revision), and so does the log's reading
    # (core.audit.sealed_out), beside the seals read at read time: the entry's text may name what the record reached.
    works = ArrayField(models.CharField(max_length=64), default=list, blank=True, editable=False)

    objects = AuditLogManager()

    class Meta:
        db_table = 'audit_log'
        # Newest first, and one order for entries of the same moment (one transaction): never left to the plan, so a
        # list does not tell by its order what else a statement read (a narrowed read and a plain one alike).
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['entity_type', 'entity_id']),
            # The few critical entries, newest first, without reading the whole log.
            models.Index(fields=['-created_at'], condition=models.Q(severity=AuditSeverity.CRITICAL),
                         name='audit_log_critical_idx'),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(severity__in=AuditSeverity.values),
                                   name='chk_audit_log_severity'),
        ]
        # Not about audit rows: the one permission of the platform's own screens that no model owns
        # (core.database). It is not in the access matrix, so only the platform admin has it.
        permissions = [('browse_database', 'Can browse the database')]

    def __str__(self):
        return f'{self.user_name} {self.get_action_display().lower()} {self.entity_type} {self.entity_label}'

    def save(self, *args, **kwargs):
        if self._state.adding:
            from .audit import stamp
            stamp([self])
        super().save(*args, **kwargs)

    def shown_type(self):
        """The record type in the active language."""
        return gettext(self.entity_type)

    def shown_changes(self):
        """[(label, old, new)] in the active language. The stored rows stay in English. A private value is shown as
        its words ("Private text", "Email: Private text" when it says what it is), never with its digest: this is the
        one place a stored value becomes text on a page (the activity log and a record's History tab), so no page
        prints a digest. A list of lists (a contact list: the parts of each contact) is joined by "; "."""
        def shown(value):
            if isinstance(value, list):
                nested = bool(value) and all(isinstance(item, list) for item in value)
                return ('; ' if nested else ', ').join(shown(item) for item in value)
            if isinstance(value, dict):
                msgid, what = value['msgid'], value.get('of')      # by name: the catalog extraction reads a literal here
                return f'{gettext(what)}: {gettext(msgid)}' if what else gettext(msgid)
            return value
        return [(gettext(label), shown(old), shown(new)) for label, (old, new) in self.changes.items()]


class Profile(models.Model):
    """What the platform keeps about a person beyond Django's account. Today that is their language;
    it lives here because the user model is Django's own."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    # One of settings.LANGUAGES; empty until the person (or the admin who invited them) chooses one.
    language = models.CharField(max_length=10, blank=True)

    class Meta:
        db_table = 'profiles'

    def __str__(self):
        return str(self.user)


class AccountMail(models.Model):
    """The account e-mails the platform sends: the invitation a new person gets, each time the admin sends it again,
    and every password reset. One row per mail, and the outbox core.accountmail works from: what causes a mail writes
    its row as waiting, in its own transaction; the mail is sent after that has committed, and the row then says when
    it went out (`sent_at`) or why it did not (`error`). A row with neither is waiting, or never finished. Who it is
    for, the address, who asked for it; never the link or its token. The users tab shows what became of a person's
    last invitation, and the reset form counts an account's mails of the last hour."""

    class Kind(models.TextChoices):
        INVITATION = 'invitation', _('Invitation')
        RESET = 'reset', _('Password reset')

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='account_mails')
    kind = models.CharField(max_length=10, choices=Kind.choices)
    # The account's address when the mail was written: the link holds it, so a later change of address ends the link.
    address = models.EmailField()
    # The admin who invited the person; empty for a reset, which the person asks for themselves (signed out).
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    # The server process that queued the mail (core.accountmail.WORKER): its queue is in that process's memory, so
    # only it can send the mail. While the mail waits, the owner keeps saying that it still has it (`alive_at`); a
    # waiting mail whose owner has stopped saying so is closed as interrupted (accountmail.sweep).
    owner = models.CharField(max_length=64, blank=True)
    alive_at = models.DateTimeField(default=timezone.now)
    # When the mail server took it; empty while the mail waits to be sent, and for one that did not go out.
    sent_at = models.DateTimeField(null=True, blank=True)
    # Why the mail did not go out (the mail server's words, or the platform's own); empty otherwise.
    error = models.CharField(max_length=500, blank=True)

    class Meta:
        db_table = 'account_mails'
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['user', 'kind', '-created_at'], name='account_mails_recent_idx'),
            # the few that wait, by when their owner last had them (accountmail.sweep, on every look at the users tab)
            models.Index(fields=['alive_at'], condition=models.Q(sent_at__isnull=True, error=''),
                         name='account_mails_waiting_idx'),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(kind__in=['invitation', 'reset']), name='chk_account_mails_kind'),
        ]

    def __str__(self):
        return f'{self.get_kind_display()}: {self.address}'


# The bounds of the platform owner's settings: the database holds them (PlatformSettings' checks) and the form says them.
WINDOW_DAYS = (1, 3650)           # a day back at least; ten years at most, which keeps every date's arithmetic sane
CLOCK_TOLERANCE = (0, 3600)          # seconds: at most the sensors' ingest contract's hour
UNKNOWN_WITHDRAWAL_DAYS = (1, 3650)  # a day at least; ten years at most, as the correction window


class PlatformSettings(AuditedModel):
    """The rules the platform owner (the customer the platform is given to) sets for their whole company, one row (a
    database check keeps it one), changed on Company › Administration › Platform settings by who holds Platform settings:
    Edit, every change in the activity log. Nothing reads these columns but core.platform.

    - The correction window: how many days back a daily record (a stock operation, a feeding, a water sample, a movement
      of the store, a plan, a treatment) may be dated, and how old a record may be voided (owner decisions Q3 and Q-F4,
      31 days until the owner sets another). A record older than that stays as it is.
    - Whether a second person must approve the acknowledgement of a medicine-withdrawal warning before what it was given
      for counts (F-164); other critical acknowledgements may join it.
    - How long a medicine withdrawal whose END IS UNKNOWN for want of a rule (no withdrawal row, medicated feed with no
      treatment; never a degree-day withdrawal) holds fish (the owner's decision of 17.11.2026): the days
      after the course's last day (or the medicated feeding's day), 180 until the owner sets another. After them the
      fish are not held and the course is listed as unresolved (farm/health/withdrawal.py, rule 8). A change of it
      goes through the withdrawal guard, which asks when it would free fish held today.
    The alarms' rules (delays, escalation, deadbands) are the alarms app's own reference data, per severity and per
    parameter (alarms.SeverityPolicy, alarms.ParameterDeadband)."""

    singleton = models.BooleanField(default=True, editable=False)
    correction_window_days = models.PositiveSmallIntegerField(
        _('Correction window (days)'), default=31,
        validators=[MinValueValidator(WINDOW_DAYS[0]), MaxValueValidator(WINDOW_DAYS[1])])
    second_approval_withdrawal = models.BooleanField(
        _('A second person approves a withdrawal warning acknowledgement'), default=False)
    unknown_withdrawal_days = models.PositiveSmallIntegerField(
        _('An unknown withdrawal end holds for (days)'), default=180,
        validators=[MinValueValidator(UNKNOWN_WITHDRAWAL_DAYS[0]), MaxValueValidator(UNKNOWN_WITHDRAWAL_DAYS[1])])
    # How far ahead of the server's clock a value may be stamped and still count as fresh (farm/water/freshness.py): at
    # most the sensors' ingest contract's hour (evaluate.MAX_AHEAD). 300 s is the value the code held (cross review F10).
    clock_tolerance_seconds = models.PositiveIntegerField(
        _('Clock tolerance (seconds)'), default=300,
        validators=[MinValueValidator(CLOCK_TOLERANCE[0]), MaxValueValidator(CLOCK_TOLERANCE[1])])

    class Meta:
        db_table = 'platform_settings'
        verbose_name = _('platform settings')
        verbose_name_plural = _('platform settings')
        constraints = [
            models.UniqueConstraint(fields=['singleton'], name='uq_platform_settings_singleton'),
            models.CheckConstraint(condition=models.Q(singleton=True), name='chk_platform_settings_singleton'),
            models.CheckConstraint(
                condition=models.Q(correction_window_days__gte=WINDOW_DAYS[0], correction_window_days__lte=WINDOW_DAYS[1]),
                name='chk_platform_settings_window'),
            models.CheckConstraint(
                condition=models.Q(clock_tolerance_seconds__gte=CLOCK_TOLERANCE[0],
                                   clock_tolerance_seconds__lte=CLOCK_TOLERANCE[1]),
                name='chk_platform_settings_clock_tolerance'),
            models.CheckConstraint(
                condition=models.Q(unknown_withdrawal_days__gte=UNKNOWN_WITHDRAWAL_DAYS[0],
                                   unknown_withdrawal_days__lte=UNKNOWN_WITHDRAWAL_DAYS[1]),
                name='chk_platform_settings_unknown_withdrawal'),
        ]

    def __str__(self):
        return str(_('Platform settings'))

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        from . import platform
        platform.forget()                 # the request that saved it reads the new row from now on

    @classmethod
    def get(cls):
        """The one row (made by the migration; made again here if a restore left none)."""
        return cls.objects.first() or cls.objects.create()


class EntryKey(models.Model):
    """The key a new-record form carries (core.crud.ENTRY_KEY) and the record its first sending created, for every
    kind of record (F-232): the same form sent twice, by a double click, a retried request or two sendings at once,
    creates one record, and the second sending opens it. The key is the primary key, so of two sendings at once the
    second one's insert waits for the first one's transaction and is then refused. Written in the transaction that
    creates the record; not a secret, and nothing else reads it."""

    key = models.UUIDField(primary_key=True)
    entity_type = models.CharField(max_length=100)    # the record's model, as app_label.model_name
    entity_id = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'entry_keys'

    @classmethod
    def note(cls, key, record):
        """Stores `key` with `record`. A key that already stands for a record of another kind (a form's key sent with
        another form: tampering or a broken client) is refused with a reason (cross review F7c); one of the same kind
        is the same form sent twice at once, and its insert waits for the other and is refused by the primary key,
        which the caller answers by opening the other's record."""
        label = record._meta.label_lower
        if cls.objects.filter(key=key).exclude(entity_type=label).exists():
            raise ValidationError({NON_FIELD_ERRORS: gettext(
                'This form was sent before for another record: open it again and send it anew.')})
        cls.objects.create(key=key, entity_type=label, entity_id=str(record.pk))

    @classmethod
    def record_of(cls, key, model):
        """The record of `model` the form with `key` created; None when none did."""
        entity_id = (cls.objects.filter(key=key, entity_type=model._meta.label_lower)
                     .values_list('entity_id', flat=True).first())
        return None if entity_id is None else model._base_manager.filter(pk=entity_id).first()


class Rev(models.Model):
    """The revision of one (scope, key): moved by the database whenever a tracked row changes (core.rev), read by a
    stored figure to prove it is still valid. Derived, written by the system, safe to rebuild (`manage.py
    core_rev_rebuild`)."""

    pk = models.CompositePrimaryKey('scope', 'key')
    scope = models.CharField(max_length=40)
    key = models.CharField(max_length=64, db_default='0')
    rev = models.BigIntegerField(db_default=0)
    dirty_epoch = models.BigIntegerField(db_default=0)
    dirty_from = models.DateField(null=True)

    class Meta:
        db_table = 'core_rev'
        constraints = [models.CheckConstraint(condition=models.Q(rev__gte=0), name='chk_core_rev_rev')]

    def __str__(self):
        return f'{self.scope}:{self.key}:{self.rev}'


class AccessKind(models.TextChoices):
    """Why a confidential record was read (core.sealing.log_access)."""
    VIEW = 'view', _('Viewed')
    EXPORT = 'export', _('Exported')
    DENIED = 'denied', _('Refused')
    OVERSEE = 'oversee', _('Oversaw')
    SUPPORT = 'support', _('Support read')


class AccessEvent(models.Model):
    """Who read which confidential record, when and how: the one read log (the activity log is for changes). Rows are
    append-only, as the activity log's: a database trigger (migration 0015) refuses UPDATE and DELETE. The person is
    kept by id and by the name they had, with no database link, so the row outlives an account."""

    Kind = AccessKind

    id = models.BigAutoField(primary_key=True)
    at = models.DateTimeField(_('When'), default=timezone.now)
    user_id = models.IntegerField(_('Person id'), null=True, blank=True)
    user_name = models.CharField(_('Person'), max_length=150)
    kind = models.CharField(_('Kind'), max_length=8, choices=AccessKind.choices)
    entity_type = models.CharField(_('Record type'), max_length=64)
    entity_id = models.CharField(_('Record'), max_length=64)
    part = models.CharField(_('Part'), max_length=8, blank=True)
    route = models.CharField(_('Page'), max_length=120, blank=True)
    # Why, where the person had to say it (an export of the database viewer).
    reason = models.CharField(_('Reason'), max_length=300, blank=True)

    class Meta:
        db_table = 'core_access_events'
        ordering = ['-at', '-id']
        verbose_name = _('read of a confidential record')
        verbose_name_plural = _('reads of confidential records')
        indexes = [models.Index(fields=['entity_type', 'entity_id', 'at'], name='idx_access_events_entity'),
                   models.Index(fields=['user_name', 'at'], name='idx_access_events_user')]
        constraints = [models.CheckConstraint(condition=models.Q(kind__in=AccessKind.values),
                                              name='chk_access_events_kind')]

    def __str__(self):
        return f'{self.user_name} {self.get_kind_display().lower()} {self.entity_type} {self.entity_id}'
