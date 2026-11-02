from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from core.models import AuditedModel, CodedMixin

from .site import Site


class Department(CodedMixin, AuditedModel):
    """An organisational or production unit within a site. Source table: farm.departments.

    Differences from the source: no isActive next to status (they were never kept in step); the
    manager is a user of this system instead of an id in another service; name unique per site
    and code unique per company are database constraints among live departments.
    """

    class Type(models.TextChoices):
        PRODUCTION = 'production', 'Production'
        MAINTENANCE = 'maintenance', 'Maintenance'
        QUALITY_CONTROL = 'quality_control', 'Quality control'
        FEED = 'feed', 'Feed'
        ADMINISTRATION = 'administration', 'Administration'
        HATCHERY = 'hatchery', 'Hatchery'
        NURSERY = 'nursery', 'Nursery'
        GROW_OUT = 'grow_out', 'Grow-out'
        BROODSTOCK = 'broodstock', 'Broodstock'
        QUARANTINE = 'quarantine', 'Quarantine'
        PROCESSING = 'processing', 'Processing'
        LABORATORY = 'laboratory', 'Laboratory'
        OTHER = 'other', 'Other'

    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        INACTIVE = 'inactive', 'Inactive'

    # A deleted site leaves its departments without a site ("orphaned"), as in the source.
    site = models.ForeignKey(Site, null=True, blank=True, on_delete=models.SET_NULL, related_name='departments')
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20)
    type = models.CharField(max_length=20, choices=Type.choices, default=Type.PRODUCTION)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    description = models.TextField(blank=True)
    capacity = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)],
    )
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'departments'
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['code'], condition=Q(is_deleted=False), name='uq_departments_code_live',
                violation_error_message='Another department already uses this code.',
            ),
            models.UniqueConstraint(
                fields=['site', 'name'], condition=Q(is_deleted=False), name='uq_departments_site_name_live',
                violation_error_message='This site already has a department with this name.',
            ),
            models.CheckConstraint(
                condition=Q(capacity__isnull=True) | Q(capacity__gte=0), name='chk_departments_capacity',
            ),
        ]
        indexes = [models.Index(fields=['type']), models.Index(fields=['status'])]
