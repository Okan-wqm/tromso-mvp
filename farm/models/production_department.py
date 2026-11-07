from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from core.models import AuditedModel, CodedMixin

from .site import Site

# The database check that a live production department is on a site; added NOT VALID (migration 0028), so a row a
# deleted site left without one before stays until it is changed.
LIVE_ON_A_SITE = 'chk_production_departments_live_on_a_site'


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

    # A live production department is on a site (the database holds it): a site is deleted only once its units are
    # gone, and its departments go with it (F-212). The source left them without a site ("orphaned"); a row left so
    # before (a deleted site's, null in the column) is put on a site the next time it is saved, and check_stock names it.
    site = models.ForeignKey(
        Site, null=True, on_delete=models.CASCADE, related_name='production_departments',
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
            models.CheckConstraint(
                condition=Q(site__isnull=False) | Q(is_deleted=True), name=LIVE_ON_A_SITE,
            ),
        ]
        indexes = [models.Index(fields=['type']), models.Index(fields=['status'])]

    def clean(self):
        """Moved to another site, a department takes its units along: refused when one of them has stock records
        (their past figures would be reported for the other locality, OUR-06, as a unit's own move is) or when one
        of its units' regulatory numbers is taken on the new site (OUR-07). A department a deleted site left without a
        site (a row from before F-212) is put on a site again whatever its units' records: on no site they are in no
        locality's reports at all, and the change is logged."""
        super().clean()
        if self._state.adding:
            return
        stored = type(self).all_objects.filter(pk=self.pk).values_list('site_id', flat=True).first()
        if stored == self.site_id:
            return
        units = self.tanks.all()
        if stored is not None and any(unit.has_history() for unit in units):
            raise ValidationError({'site': _('Its units have stock records on their site: the department stays on '
                                             'it.')})
        numbers = [unit.regulatory_unit_id for unit in units if unit.regulatory_unit_id]
        if numbers and self.site_id:
            taken = (type(units.first()).objects.filter(production_department__site_id=self.site_id,
                                                        regulatory_unit_id__in=numbers)
                     .exclude(production_department=self).order_by('regulatory_unit_id')
                     .values_list('regulatory_unit_id', flat=True))
            if taken:
                raise ValidationError({'site': _('The site has units numbered %(numbers)s already.') % {
                    'numbers': ', '.join(dict.fromkeys(taken))}})
