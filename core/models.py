import uuid

from django.conf import settings
from django.db import models


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
