"""Farm module models, ported tab by tab from aquaculture_platform's farm-service.

Differences from the source schema (apply to every model here):
- Single tenant: no tenantId column and no row-level security.
- Satellite monitoring (monitoringRadiusM, monitoringArea, monitoringLocationRevision) is not ported.
- jsonb location/address are flat columns; the source also duplicated city and country.
- Uniqueness rules the source only enforced in service code are database constraints here.
"""
import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from core.models import AuditedModel, CodedMixin


class Site(CodedMixin, AuditedModel):
    """A physical facility (locality). Source table: farm.sites."""

    class Type(models.TextChoices):
        LAND_BASED = 'land_based', 'Land-based facility'
        SEA_CAGE = 'sea_cage', 'Sea cage'
        POND = 'pond', 'Pond'
        RACEWAY = 'raceway', 'Raceway'
        RECIRCULATING = 'recirculating', 'Recirculating aquaculture system'
        HATCHERY = 'hatchery', 'Hatchery'

    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        MAINTENANCE = 'maintenance', 'Under maintenance'
        INACTIVE = 'inactive', 'Inactive'
        CLOSED = 'closed', 'Closed'

    TIMEZONES = [
        ('UTC', 'UTC'),
        ('Europe/Oslo', 'Europe/Oslo (CET)'),
        ('Europe/Istanbul', 'Europe/Istanbul (TRT)'),
        ('Europe/London', 'Europe/London (GMT)'),
        ('America/New_York', 'America/New York (EST)'),
        ('Asia/Tokyo', 'Asia/Tokyo (JST)'),
    ]

    name = models.CharField(max_length=150)
    code = models.CharField(max_length=20)
    lokalitetsnummer = models.PositiveIntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(10000), MaxValueValidator(99999)],
        help_text='Akvakulturregisteret locality number (5 digits).',
    )
    organisation_number_override = models.CharField(max_length=20, blank=True)
    type = models.CharField(max_length=20, choices=Type.choices, default=Type.LAND_BASED)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    is_active = models.BooleanField(default=True, db_index=True)
    description = models.TextField(blank=True)

    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )
    altitude = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    street = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=100, blank=True)
    region = models.CharField(max_length=100, blank=True, db_index=True)
    # Empty means "inherit from the company"; the chain is site -> company -> UTC.
    timezone = models.CharField(max_length=50, blank=True, choices=TIMEZONES)

    area_m2 = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    water_capacity_m3 = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    max_biomass_kg = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    established_date = models.DateField(null=True, blank=True)

    site_manager = models.CharField(max_length=255, blank=True)
    contact_email = models.EmailField(max_length=150, blank=True)
    contact_phone = models.CharField(max_length=50, blank=True)

    facilities = models.JSONField(null=True, blank=True)
    settings = models.JSONField(null=True, blank=True)
    notes = models.TextField(blank=True)
    metadata = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = 'sites'
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['code'], condition=Q(is_deleted=False), name='uq_sites_code_live',
                violation_error_message='Another site already uses this code.',
            ),
            models.UniqueConstraint(
                fields=['name'], condition=Q(is_deleted=False), name='uq_sites_name_live',
                violation_error_message='Another site already uses this name.',
            ),
            models.UniqueConstraint(
                fields=['lokalitetsnummer'],
                condition=Q(is_deleted=False, lokalitetsnummer__isnull=False),
                name='uq_sites_lokalitetsnummer_live',
                violation_error_message='Another site already uses this lokalitetsnummer.',
            ),
            models.CheckConstraint(
                condition=Q(lokalitetsnummer__isnull=True) | Q(lokalitetsnummer__gte=10000, lokalitetsnummer__lte=99999),
                name='chk_sites_lokalitetsnummer_range',
            ),
            models.CheckConstraint(
                condition=Q(latitude__isnull=True) | Q(latitude__gte=-90, latitude__lte=90),
                name='chk_sites_latitude_range',
            ),
            models.CheckConstraint(
                condition=Q(longitude__isnull=True) | Q(longitude__gte=-180, longitude__lte=180),
                name='chk_sites_longitude_range',
            ),
            models.CheckConstraint(
                condition=Q(latitude__isnull=True, longitude__isnull=True)
                | Q(latitude__isnull=False, longitude__isnull=False),
                name='chk_sites_coordinates_paired',
                violation_error_message='Latitude and longitude must be provided together.',
            ),
            models.CheckConstraint(
                condition=~Q(type='sea_cage') | Q(latitude__isnull=False, longitude__isnull=False),
                name='chk_sites_sea_cage_location',
                violation_error_message='A sea cage site needs latitude and longitude.',
            ),
        ]
        indexes = [
            models.Index(fields=['type']),
            models.Index(fields=['status']),
        ]


class SiteContact(models.Model):
    """An operational contact of a site. Source table: farm.site_contacts.

    The source saves the contact list as a full replace (delete all, insert all), so rows have no
    update or soft-delete columns.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='contacts')
    name = models.CharField(max_length=100)
    role = models.CharField(max_length=100, blank=True)
    email = models.EmailField(max_length=150, blank=True)
    phone = models.CharField(max_length=50, blank=True)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )

    class Meta:
        db_table = 'site_contacts'
        ordering = ['-is_primary', 'created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['site'], condition=Q(is_primary=True), name='uq_site_contacts_one_primary',
                violation_error_message='Only one contact can be the primary contact.',
            ),
        ]

    def __str__(self):
        return self.name


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
