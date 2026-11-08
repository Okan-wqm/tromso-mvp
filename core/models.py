import uuid

from django.conf import settings
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext, gettext_lazy as _


class ActiveManager(models.Manager):
    """Hides soft-deleted records."""

    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class AuditedModel(models.Model):
    """Base of every farm record: author and time of creation and last change, an optimistic-lock
    version, and soft delete. `objects` shows live records only; `all_objects` shows everything.

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
    all_objects = models.Manager()

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
    # choices (see core.audit).
    changes = models.JSONField(default=dict, blank=True)
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.NORMAL)

    class Meta:
        db_table = 'audit_log'
        ordering = ['-created_at']
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

    def shown_type(self):
        """The record type in the active language."""
        return gettext(self.entity_type)

    def shown_changes(self):
        """[(label, old, new)] in the active language. The stored rows stay in English."""
        def shown(value):
            if isinstance(value, list):
                return ', '.join(shown(item) for item in value)
            if isinstance(value, dict):
                msgid = value['msgid']
                return gettext(msgid)
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
