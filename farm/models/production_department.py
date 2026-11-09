from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from core.models import AuditedModel, CodedMixin

from .site import Site

# The database check that a live production department is on a site; added NOT VALID (migration 0029), so a row a
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
        site (a row from before F-212) goes back on a site by the owner's rule (cross review F4): without stock records
        in its units to any live site, with them only to the site they were recorded on (`former_site`, restored
        first), and not at all when that site is not known."""
        super().clean()
        if self._state.adding:
            return
        stored = type(self).all_objects.filter(pk=self.pk).values_list('site_id', flat=True).first()
        if stored == self.site_id:
            return
        units = self.tanks.all()
        if any(unit.has_history() for unit in units):
            if stored is not None:
                raise ValidationError({'site': _('Its units have stock records on their site: the department stays on '
                                                 'it.')})
            former = self.former_site()
            if former is None:
                raise ValidationError({'site': _('Its units have stock records, and the site they were recorded on is '
                                                 'not known: it cannot be put on another one.')})
            if former.pk != self.site_id:
                raise ValidationError({'site': _('Its units have stock records on %(site)s: restore that site and '
                                                 'choose it.') % {'site': former}})
        numbers = [unit.regulatory_unit_id for unit in units if unit.regulatory_unit_id]
        if numbers and self.site_id:
            taken = (type(units.first()).objects.filter(production_department__site_id=self.site_id,
                                                        regulatory_unit_id__in=numbers)
                     .exclude(production_department=self).order_by('regulatory_unit_id')
                     .values_list('regulatory_unit_id', flat=True))
            if taken:
                raise ValidationError({'site': _('The site has units numbered %(numbers)s already.') % {
                    'numbers': ', '.join(dict.fromkeys(taken))}})

    def former_site(self):
        """The site this department was on before a deleted site left it without one (the source cleared the link and
        logged it, {"Site": ["Name (CODE)", None]}): the one site, deleted or not, that log names; None when the log
        names none, or more than one site answers to it."""
        from core import audit
        from core.models import AuditLog
        entries = (AuditLog.objects.filter(entity_type=audit.entity_type_of(type(self)), entity_id=str(self.pk),
                                           action=AuditLog.Action.UPDATE, changes__has_key='Site')
                   .order_by('-created_at').values_list('changes', flat=True))
        label = next((change['Site'][0] for change in entries if change['Site'][1] is None), None)
        if label is None:
            return None
        found = [site for site in Site.all_objects.filter(code__in=[label.rpartition('(')[2].rstrip(')')])
                 if str(site) == label]
        return found[0] if len(found) == 1 else None
