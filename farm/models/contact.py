import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

# The message of each list's "at most one primary contact" constraint.
ONE_PRIMARY = _('Only one contact can be the primary contact.')


class Contact(models.Model):
    """A person to contact, one row of a record's contact list (a site's, a supplier's).

    The list is saved as a whole (core.crud.RowList: delete all, insert all, as the source does for a
    site), so rows have no update or soft-delete columns. Each concrete list links to its record and
    allows at most one primary contact per record, as a partial unique constraint."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_('Name'), max_length=100)
    role = models.CharField(_('Role'), max_length=100, blank=True)
    email = models.EmailField(_('Email'), max_length=150, blank=True)
    phone = models.CharField(_('Phone'), max_length=50, blank=True)
    is_primary = models.BooleanField(_('Primary'), default=False)
    created_at = models.DateTimeField(_('Created at'), auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
        verbose_name=_('Created by'),
    )

    class Meta:
        abstract = True
        ordering = ['-is_primary', 'created_at']

    def __str__(self):
        return self.name
