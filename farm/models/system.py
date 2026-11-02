from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _

from core.models import AuditedModel, CodedMixin, TreeMixin, in_tree_order

from .production_department import ProductionDepartment
from .site import Site


class System(CodedMixin, TreeMixin, AuditedModel):
    """A production system of a site: a RAS, a pond, a cage line, a hatchery. Source table: farm.systems.

    Differences from the source: the production department must be on the system's site and a parent system
    on the same site and not below the system itself (the source checked this on create only, and
    update could break it); no second status flag `isActive`; no hand-typed tank count (it would
    drift from the real tanks; it is derived once tanks exist); volumes cannot be negative."""

    class Type(models.TextChoices):
        RAS = 'ras', _('RAS (recirculating)')
        FLOW_THROUGH = 'flow_through', _('Flow-through')
        POND = 'pond', _('Pond')
        CAGE = 'cage', _('Cage')
        RACEWAY = 'raceway', _('Raceway')
        HATCHERY = 'hatchery', _('Hatchery')
        NURSERY = 'nursery', _('Nursery')
        BIOFLOC = 'biofloc', _('Biofloc')
        AQUAPONICS = 'aquaponics', _('Aquaponics')
        OTHER = 'other', _('Other')

    class Status(models.TextChoices):
        OPERATIONAL = 'operational', _('Operational')
        MAINTENANCE = 'maintenance', _('Maintenance')
        OFFLINE = 'offline', _('Offline')
        CONSTRUCTION = 'construction', _('Construction')

    # What deleting a record does to the records that point at it is read from these links
    # (core.softdelete): a deleted site takes its systems with it, a deleted system the systems
    # nested under it, and a deleted production department leaves its systems in place without one.
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='systems', verbose_name=_('Site'))
    production_department = models.ForeignKey(
        ProductionDepartment, null=True, blank=True, on_delete=models.SET_NULL, related_name='systems',
        verbose_name=_('Production department'),
    )
    parent = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.CASCADE, related_name='children',
        verbose_name=_('Parent system'),
    )
    name = models.CharField(_('Name'), max_length=100)
    code = models.CharField(_('Code'), max_length=20)
    type = models.CharField(_('Type'), max_length=20, choices=Type.choices, default=Type.OTHER)
    status = models.CharField(_('Status'), max_length=20, choices=Status.choices, default=Status.OPERATIONAL)
    description = models.CharField(_('Description'), max_length=1000, blank=True)
    total_volume_m3 = models.DecimalField(
        _('Total volume (m³)'), max_digits=12, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(0)],
    )
    max_biomass_kg = models.DecimalField(
        _('Max biomass (kg)'), max_digits=12, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(0)],
    )

    class Meta:
        db_table = 'systems'
        ordering = ['name']
        verbose_name = _('system')
        verbose_name_plural = _('systems')
        constraints = [
            models.UniqueConstraint(
                fields=['site', 'code'], condition=Q(is_deleted=False), name='uq_systems_site_code_live',
                violation_error_message=_('This site already has a system with this code.'),
            ),
            models.CheckConstraint(
                condition=Q(total_volume_m3__isnull=True) | Q(total_volume_m3__gte=0),
                name='chk_systems_total_volume', violation_error_message=_('The volume cannot be negative.'),
            ),
            models.CheckConstraint(
                condition=Q(max_biomass_kg__isnull=True) | Q(max_biomass_kg__gte=0),
                name='chk_systems_max_biomass', violation_error_message=_('The biomass cannot be negative.'),
            ),
            models.CheckConstraint(
                condition=Q(parent__isnull=True) | ~Q(parent=F('id')),
                name='chk_systems_not_its_own_parent',
                violation_error_message=_('A system cannot be its own parent.'),
            ),
        ]
        indexes = [models.Index(fields=['type']), models.Index(fields=['status'])]

    def clean(self):
        super().clean()
        errors = {}
        if self.production_department_id and self.site_id and self.production_department.site_id != self.site_id:
            errors['production_department'] = _('The production department belongs to another site.')
        if self.parent_id:
            if self.parent_id == self.pk:
                errors['parent'] = _('A system cannot be its own parent.')
            elif self.site_id and self.parent.site_id != self.site_id:
                errors['parent'] = _('The parent system belongs to another site.')
            elif self.nested_under_itself():
                errors['parent'] = _('The parent system is nested under this system.')
        if errors:
            raise ValidationError(errors)

    @classmethod
    def in_tree_order(cls, wanted=None):
        """The live systems, site by site, each followed by the systems nested under it."""
        records = cls.objects.select_related('site', 'production_department', 'parent').order_by('site__name', 'name')
        return in_tree_order(records, wanted)
