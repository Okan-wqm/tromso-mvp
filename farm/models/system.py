from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Count, F, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from django.utils.translation import gettext_lazy as _

from core.models import AuditedModel, CodedMixin, TreeMixin, in_tree_order

from .production_department import ProductionDepartment
from .site import Site


class System(CodedMixin, TreeMixin, AuditedModel):
    """A production system of a site: a RAS, a pond, a cage line, a hatchery. Source table: farm.systems.

    Differences from the source: the production department must be on the system's site and a parent system
    on the same site and not below the system itself (the source checked this on create only, and
    update could break it); the units in it (Tank) must be of its production department when it has
    one, so it cannot be moved to another while units of another are in it; no second status flag
    `isActive`; no hand-typed tank count (it would drift from the real units: the list counts them);
    volumes cannot be negative."""

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
        if self.production_department_id and not self._state.adding:
            elsewhere = self.tanks.exclude(production_department_id=self.production_department_id)
            if elsewhere and 'production_department' not in errors:
                errors['production_department'] = ValidationError(
                    _('Units of another production department are in it: %(units)s. Take them out of the system '
                      'first.'), params={'units': ', '.join(str(unit) for unit in elsewhere)})
        if errors:
            raise ValidationError(errors)

    def withdrawal_blockers(self):
        """Why the system is not deleted or restored now: its loop's samples count for the units in it without their own,
        so a withdrawal that holds fish ever in them waits (farm.health.withdrawal.held_reached; the withdrawal gate's
        rule, farm/apps.py)."""
        from ..health.withdrawal import held_reached
        return held_reached(self.tanks(manager='all_objects').values_list('pk', flat=True))

    def delete_blockers(self):
        return self.withdrawal_blockers()

    @classmethod
    def in_tree_order(cls, wanted=None):
        """The live systems, site by site, each followed by the systems nested under it, with the number
        of live units in each (`units`)."""
        Tank = cls._meta.get_field('tanks').related_model
        records = (cls.objects.select_related('site', 'production_department', 'parent')
                   # the units the person may see (core.sealing), never a count through a join
                   .annotate(units=Coalesce(Subquery(Tank.objects.filter(system=OuterRef('pk')).order_by()
                                                     .values('system').annotate(n=Count('pk')).values('n')), 0))
                   .order_by('site__name', 'name'))
        return in_tree_order(records, wanted)
