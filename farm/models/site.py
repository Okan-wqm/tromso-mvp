from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext, gettext_lazy as _

from core.models import AuditedModel, CodedMixin

from .contact import ONE_PRIMARY, Contact


class Site(CodedMixin, AuditedModel):
    """A physical facility (locality). Source table: farm.sites."""

    class Type(models.TextChoices):
        LAND_BASED = 'land_based', _('Land-based facility')
        SEA_CAGE = 'sea_cage', _('Sea cage')
        POND = 'pond', _('Pond')
        RACEWAY = 'raceway', _('Raceway')
        RECIRCULATING = 'recirculating', _('Recirculating aquaculture system')
        HATCHERY = 'hatchery', _('Hatchery')

    class Status(models.TextChoices):
        ACTIVE = 'active', _('Active')
        MAINTENANCE = 'maintenance', _('Under maintenance')
        INACTIVE = 'inactive', _('Inactive')
        CLOSED = 'closed', _('Closed')

    TIMEZONES = [
        ('UTC', 'UTC'),
        ('Europe/Oslo', 'Europe/Oslo (CET)'),
        ('Europe/Istanbul', 'Europe/Istanbul (TRT)'),
        ('Europe/London', 'Europe/London (GMT)'),
        ('America/New_York', 'America/New York (EST)'),
        ('Asia/Tokyo', 'Asia/Tokyo (JST)'),
    ]

    # Field names are the labels forms, the admin and the activity log show: sentence case, one msgid each.
    name = models.CharField(_('Site name'), max_length=150)
    code = models.CharField(_('Site code'), max_length=20)
    lokalitetsnummer = models.PositiveIntegerField(
        _('Lokalitetsnummer'), null=True, blank=True,
        validators=[MinValueValidator(10000), MaxValueValidator(99999)],
        help_text=_('Akvakulturregisteret locality number (5 digits).'),
    )
    organisation_number_override = models.CharField(_('Organisation number override'), max_length=20, blank=True)
    type = models.CharField(_('Site type'), max_length=20, choices=Type.choices, default=Type.LAND_BASED)
    status = models.CharField(_('Status'), max_length=20, choices=Status.choices, default=Status.ACTIVE)
    is_active = models.BooleanField(_('Active'), default=True, db_index=True)
    description = models.TextField(_('Description'), blank=True)

    latitude = models.DecimalField(
        _('Latitude'), max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    longitude = models.DecimalField(
        _('Longitude'), max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )
    altitude = models.DecimalField(_('Altitude (m)'), max_digits=8, decimal_places=2, null=True, blank=True)
    street = models.CharField(_('Street address'), max_length=255, blank=True)
    city = models.CharField(_('City'), max_length=100, blank=True)
    state = models.CharField(_('State'), max_length=100, blank=True)
    postal_code = models.CharField(_('Postal code'), max_length=20, blank=True)
    country = models.CharField(_('Country'), max_length=100, blank=True)
    region = models.CharField(_('Region'), max_length=100, blank=True, db_index=True)
    # Empty means "inherit from the company"; the chain is site -> company -> UTC.
    timezone = models.CharField(_('Timezone'), max_length=50, blank=True, choices=TIMEZONES)

    area_m2 = models.DecimalField(_('Total area (m²)'), max_digits=12, decimal_places=2, null=True, blank=True)
    water_capacity_m3 = models.DecimalField(
        _('Water capacity (m³)'), max_digits=12, decimal_places=2, null=True, blank=True)
    max_biomass_kg = models.DecimalField(
        _('Max biomass (kg)'), max_digits=12, decimal_places=2, null=True, blank=True)
    established_date = models.DateField(_('Established'), null=True, blank=True)

    site_manager = models.CharField(_('Site manager'), max_length=255, blank=True)
    contact_email = models.EmailField(_('Contact email'), max_length=150, blank=True)
    contact_phone = models.CharField(_('Contact phone'), max_length=50, blank=True)

    facilities = models.JSONField(_('Facilities'), null=True, blank=True)
    settings = models.JSONField(_('Settings'), null=True, blank=True)
    notes = models.TextField(_('Notes'), blank=True)
    metadata = models.JSONField(_('Metadata'), null=True, blank=True)

    def delete_blockers(self):
        """A site whose units have stock records is closed, not deleted: deleting it would leave its production
        departments without a site and its past figures without their locality."""
        from .stock import StockMovement
        if StockMovement.objects.filter(unit__production_department__site=self, operation__is_deleted=False).exists():
            return [gettext('Its units have stock records: set its status to Closed instead.')]
        return []

    class Meta:
        db_table = 'sites'
        ordering = ['name']
        verbose_name = _('site')
        verbose_name_plural = _('sites')
        constraints = [
            models.UniqueConstraint(
                fields=['code'], condition=Q(is_deleted=False), name='uq_sites_code_live',
                violation_error_message=_('Another site already uses this code.'),
            ),
            models.UniqueConstraint(
                fields=['name'], condition=Q(is_deleted=False), name='uq_sites_name_live',
                violation_error_message=_('Another site already uses this name.'),
            ),
            models.UniqueConstraint(
                fields=['lokalitetsnummer'],
                condition=Q(is_deleted=False, lokalitetsnummer__isnull=False),
                name='uq_sites_lokalitetsnummer_live',
                violation_error_message=_('Another site already uses this lokalitetsnummer.'),
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
                violation_error_message=_('Latitude and longitude must be provided together.'),
            ),
            models.CheckConstraint(
                condition=~Q(type='sea_cage') | Q(latitude__isnull=False, longitude__isnull=False),
                name='chk_sites_sea_cage_location',
                violation_error_message=_('A sea cage site needs latitude and longitude.'),
            ),
        ]
        indexes = [
            models.Index(fields=['type']),
            models.Index(fields=['status']),
        ]


def zone_of(site):
    """The time zone a farm's day and clock are read in: the site's, else the company's (settings.TIME_ZONE).
    Never a browser's (the source's dialogs were a day behind east of UTC)."""
    return ZoneInfo(site.timezone if site is not None and site.timezone else settings.TIME_ZONE)


class SiteContact(Contact):
    """An operational contact of a site. Source table: farm.site_contacts.

    The source saves the contact list as a full replace (delete all, insert all), so rows have no
    update or soft-delete columns (farm.models.contact.Contact).
    """

    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='contacts', verbose_name=_('Site'))

    class Meta(Contact.Meta):
        db_table = 'site_contacts'
        verbose_name = _('site contact')
        verbose_name_plural = _('site contacts')
        constraints = [
            models.UniqueConstraint(
                fields=['site'], condition=Q(is_primary=True), name='uq_site_contacts_one_primary',
                violation_error_message=ONE_PRIMARY,
            ),
        ]
