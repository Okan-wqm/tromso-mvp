from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from core.models import AuditedModel, CodedMixin

from .site import Site


class ProductionDepartment(CodedMixin, AuditedModel):
    """A production unit within a site: a hatchery hall, a nursery, a grow-out unit. Source table:
    farm.departments.

    These are the farm's production departments. The company's organisational departments
    (management, HR and the like) are a different thing and belong to the HR module.

    Differences from the source: no `administration` type (that is an organisational department);
    no isActive next to status (they were never kept in step); the manager is a user of this system
    instead of an id in another service; name unique per site and code unique per company are
    database constraints among live production departments.
    """

    class Type(models.TextChoices):
        PRODUCTION = 'production', _('Production')
        MAINTENANCE = 'maintenance', _('Maintenance')
        QUALITY_CONTROL = 'quality_control', _('Quality control')
        FEED = 'feed', _('Feed')
        HATCHERY = 'hatchery', _('Hatchery')
        NURSERY = 'nursery', _('Nursery')
        GROW_OUT = 'grow_out', _('Grow-out')
        BROODSTOCK = 'broodstock', _('Broodstock')
        QUARANTINE = 'quarantine', _('Quarantine')
        PROCESSING = 'processing', _('Processing')
        LABORATORY = 'laboratory', _('Laboratory')
        OTHER = 'other', _('Other')

    class Status(models.TextChoices):
        ACTIVE = 'active', _('Active')
        INACTIVE = 'inactive', _('Inactive')

    # A deleted site leaves its production departments without a site ("orphaned"), as in the source.
    site = models.ForeignKey(
        Site, null=True, blank=True, on_delete=models.SET_NULL, related_name='production_departments',
        verbose_name=_('Site'),
    )
    name = models.CharField(_('Name'), max_length=100)
    code = models.CharField(_('Code'), max_length=20)
    type = models.CharField(_('Type'), max_length=20, choices=Type.choices, default=Type.PRODUCTION)
    status = models.CharField(_('Status'), max_length=10, choices=Status.choices, default=Status.ACTIVE)
    description = models.TextField(_('Description'), blank=True)
    capacity = models.DecimalField(
        _('Capacity'), max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)],
    )
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
        verbose_name=_('Manager'),
    )
    notes = models.TextField(_('Notes'), blank=True)

    class Meta:
        db_table = 'production_departments'
        ordering = ['name']
        verbose_name = _('production department')
        verbose_name_plural = _('production departments')
        constraints = [
            models.UniqueConstraint(
                fields=['code'], condition=Q(is_deleted=False), name='uq_production_departments_code_live',
                violation_error_message=_('Another production department already uses this code.'),
            ),
            models.UniqueConstraint(
                fields=['site', 'name'], condition=Q(is_deleted=False), name='uq_production_departments_site_name_live',
                violation_error_message=_('This site already has a production department with this name.'),
            ),
            models.CheckConstraint(
                condition=Q(capacity__isnull=True) | Q(capacity__gte=0), name='chk_production_departments_capacity',
            ),
        ]
        indexes = [models.Index(fields=['type']), models.Index(fields=['status'])]
