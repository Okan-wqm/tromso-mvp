import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    version = models.PositiveIntegerField(default=1)
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )

    objects = ActiveManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True

    def soft_delete(self, user):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.deleted_by = user
        self.updated_by = user
        self.version += 1
        self.save()

    def detach(self, link, user):
        """Clears the link to a deleted record; the change counts as an edit by `user`."""
        setattr(self, link, None)
        self.updated_by = user
        self.version += 1
        self.save(update_fields=[link, 'updated_by', 'version', 'updated_at'])

    def delete_blockers(self):
        """Reasons this record cannot be deleted now (e.g. fish still in a tank); none by default."""
        return []


class CodedMixin:
    """Records known by a name and a short code: codes are stored upper-case, shown as "Name (CODE)"."""

    def __str__(self):
        return f'{self.name} ({self.code})'

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)


class AuditLog(models.Model):
    """Who did what to which record, with old and new values. Rows are append-only: a database
    trigger (migration 0003) refuses UPDATE and DELETE, so history cannot be edited, not even by
    the platform admin."""

    class Action(models.TextChoices):
        CREATE = 'create', 'Created'
        UPDATE = 'update', 'Changed'
        DELETE = 'delete', 'Deleted'
        RESTORE = 'restore', 'Restored'

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
    # {field label: [old, new]}; on create old is None, on delete new is None.
    changes = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'audit_log'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['entity_type', 'entity_id'])]

    def __str__(self):
        return f'{self.user_name} {self.get_action_display().lower()} {self.entity_type} {self.entity_label}'
