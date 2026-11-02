from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q

from core.models import AuditedModel, CodedMixin

from .department import Department
from .site import Site


class System(CodedMixin, AuditedModel):
    """A production system of a site: a RAS, a pond, a cage line, a hatchery. Source table: farm.systems.

    Differences from the source: the department must be on the system's site and a parent system
    on the same site and not below the system itself (the source checked this on create only, and
    update could break it); no second status flag `isActive`; no hand-typed tank count (it would
    drift from the real tanks; it is derived once tanks exist); volumes cannot be negative."""

    class Type(models.TextChoices):
        RAS = 'ras', 'RAS (recirculating)'
        FLOW_THROUGH = 'flow_through', 'Flow-through'
        POND = 'pond', 'Pond'
        CAGE = 'cage', 'Cage'
        RACEWAY = 'raceway', 'Raceway'
        HATCHERY = 'hatchery', 'Hatchery'
        NURSERY = 'nursery', 'Nursery'
        BIOFLOC = 'biofloc', 'Biofloc'
        AQUAPONICS = 'aquaponics', 'Aquaponics'
        OTHER = 'other', 'Other'

    class Status(models.TextChoices):
        OPERATIONAL = 'operational', 'Operational'
        MAINTENANCE = 'maintenance', 'Maintenance'
        OFFLINE = 'offline', 'Offline'
        CONSTRUCTION = 'construction', 'Construction'

    # What deleting a record does to the records that point at it is read from these links
    # (core.softdelete): a deleted site takes its systems with it, a deleted system the systems
    # nested under it, and a deleted department leaves its systems in place without a department.
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='systems')
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL, related_name='systems',
    )
    parent = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.CASCADE, related_name='children',
        verbose_name='parent system',
    )
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20)
    type = models.CharField(max_length=20, choices=Type.choices, default=Type.OTHER)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPERATIONAL)
    description = models.CharField(max_length=1000, blank=True)
    total_volume_m3 = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)],
    )
    max_biomass_kg = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)],
    )

    class Meta:
        db_table = 'systems'
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['site', 'code'], condition=Q(is_deleted=False), name='uq_systems_site_code_live',
                violation_error_message='This site already has a system with this code.',
            ),
            models.CheckConstraint(
                condition=Q(total_volume_m3__isnull=True) | Q(total_volume_m3__gte=0),
                name='chk_systems_total_volume', violation_error_message='The volume cannot be negative.',
            ),
            models.CheckConstraint(
                condition=Q(max_biomass_kg__isnull=True) | Q(max_biomass_kg__gte=0),
                name='chk_systems_max_biomass', violation_error_message='The biomass cannot be negative.',
            ),
            models.CheckConstraint(
                condition=Q(parent__isnull=True) | ~Q(parent=F('id')),
                name='chk_systems_not_its_own_parent',
                violation_error_message='A system cannot be its own parent.',
            ),
        ]
        indexes = [models.Index(fields=['type']), models.Index(fields=['status'])]

    def clean(self):
        super().clean()
        errors = {}
        if self.department_id and self.site_id and self.department.site_id != self.site_id:
            errors['department'] = 'The department belongs to another site.'
        if self.parent_id:
            if self.parent_id == self.pk:
                errors['parent'] = 'A system cannot be its own parent.'
            elif self.site_id and self.parent.site_id != self.site_id:
                errors['parent'] = 'The parent system belongs to another site.'
            elif self.pk in {system.pk for system in self.parent.self_and_ancestors()}:
                errors['parent'] = 'The parent system is nested under this system.'
        if errors:
            raise ValidationError(errors)

    def self_and_ancestors(self):
        """This system, its parent, that one's parent, and so on up to the top."""
        seen, node = set(), self
        while node is not None and node.pk not in seen:
            seen.add(node.pk)
            yield node
            node = node.parent

    def descendants(self):
        """Every system nested below this one, at any depth."""
        found, frontier = [], [self]
        while frontier:
            frontier = list(System.objects.filter(parent__in=frontier))
            found.extend(frontier)
        return found

    @classmethod
    def in_tree_order(cls, wanted=None):
        """The live systems, site by site, each followed by the systems nested under it, with `depth`
        set on each. `wanted` (a queryset) keeps only its systems, in the same order and depth."""
        children = {}
        for system in cls.objects.select_related('site', 'department', 'parent').order_by('name'):
            children.setdefault(system.parent_id, []).append(system)
        keep = None if wanted is None else {system.pk for system in wanted}
        ordered = []

        def walk(system, depth):
            system.depth = depth
            if keep is None or system.pk in keep:
                ordered.append(system)
            for child in children.get(system.pk, []):
                walk(child, depth + 1)

        for system in sorted(children.get(None, []), key=lambda s: (s.site.name, s.name)):
            walk(system, 0)
        return ordered
