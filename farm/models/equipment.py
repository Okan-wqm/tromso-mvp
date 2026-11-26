from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils.functional import cached_property
from django.utils.translation import gettext, gettext_lazy as _, ngettext_lazy, pgettext_lazy

from core.models import AuditedModel, CodedMixin, SealedManager, TreeMixin
from core.schema import Schema, SchemaValuesField

from .production_department import ProductionDepartment
from .supplier import Supplier, SupplierLink, SupplyCategory
from .system import System


class EquipmentType(models.Model):
    """A kind of equipment and the technical specifications it has: a centrifugal pump has a flow rate
    and a head, a heater a fuel type. Source table: farm.equipment_types.

    Reference data, written by migrations from the catalogue in farm/equipment_types.py and never
    edited on a screen (the source has no screen for it either). So it is not an AuditedModel: nobody
    creates, changes or deletes a type, so there is no author, version or soft delete to keep; a type
    that is no longer offered is made inactive and its equipment keeps it (PROTECT). The texts are
    English msgids, shown translated. Tanks, ponds and cages are not equipment here: they get their
    own tab, and their types are not in the catalogue."""

    class Category(models.TextChoices):
        PUMP = 'pump', _('Pumping')
        AERATION = 'aeration', _('Aeration')
        FILTRATION = 'filtration', _('Filtration')
        HEATING_COOLING = 'heating_cooling', _('Heating and cooling')
        FEEDING = 'feeding', _('Feeding')
        MONITORING = 'monitoring', _('Sensors')
        WATER_TREATMENT = 'water_treatment', _('Water treatment')
        HARVESTING = 'harvesting', _('Harvesting')
        TRANSPORT = 'transport', _('Transport')
        ELECTRICAL = 'electrical', _('Electrical')
        PLUMBING = 'plumbing', _('Plumbing')
        SAFETY = 'safety', _('Safety')
        OTHER = 'other', _('Other')

    code = models.CharField(_('Code'), max_length=50, unique=True)
    name = models.CharField(_('Name'), max_length=100)
    category = models.CharField(_('Category'), max_length=20, choices=Category.choices)
    description = models.CharField(_('Description'), max_length=255, blank=True)
    specification_schema = models.JSONField(_('Specification fields'), default=dict)
    is_active = models.BooleanField(_('Offered'), default=True)
    sort_order = models.PositiveIntegerField(_('Order'), default=0)

    class Meta:
        db_table = 'equipment_types'
        ordering = ['sort_order', 'name']
        verbose_name = _('equipment type')
        verbose_name_plural = _('equipment types')
        indexes = [models.Index(fields=['category'])]

    def __str__(self):
        return gettext(self.name)

    @cached_property
    def schema(self):
        """The specification fields as a core.schema.Schema."""
        return Schema(self.specification_schema)

    @property
    def takes_calibrations(self):
        """Feeders are calibrated per feed size (FeederCalibration)."""
        return self.category == self.Category.FEEDING

    def clean(self):
        try:
            Schema(self.specification_schema)
        except ImproperlyConfigured as error:
            raise ValidationError({'specification_schema': str(error)})


class Equipment(CodedMixin, TreeMixin, AuditedModel):
    """A piece of equipment of a production department: a pump, a drum filter, a feeder, a generator.
    Source table: farm.equipment.

    Differences from the source: tanks, ponds and cages are not equipment (their own tab) and the
    statuses are the equipment's own; the site comes from the production department, and the
    systems, the parent and the parts are checked against it on every save, not on create only; the
    specifications are checked against the type's schema on every save (types, bounds, choices, not
    only that the required ones are there); code and serial number are unique among live equipment,
    as database constraints; the supplier is a real link, to a supplier of equipment. Not ported: sensor
    links, price, currency, location, maintenance schedule, operating hours, the second status flag
    `isActive`, sub-equipment."""

    class Status(models.TextChoices):
        OPERATIONAL = 'operational', _('Operational')
        MAINTENANCE = 'maintenance', _('Maintenance')
        REPAIR = 'repair', _('Repair')
        STANDBY = 'standby', _('Standby')
        OUT_OF_SERVICE = 'out_of_service', _('Out of service')
        DECOMMISSIONED = 'decommissioned', _('Decommissioned')

    # What deleting a record does to equipment is read from these links (core.softdelete): a deleted
    # production department takes its equipment with it (as the source does), a deleted piece of
    # equipment its parts. A deleted system leaves the link rows (EquipmentSystem) in place.
    production_department = models.ForeignKey(
        ProductionDepartment, on_delete=models.CASCADE, related_name='equipment',
        verbose_name=_('Production department'),
    )
    parent = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.CASCADE, related_name='children',
        verbose_name=_('Parent equipment'),
    )
    equipment_type = models.ForeignKey(
        EquipmentType, on_delete=models.PROTECT, related_name='equipment', verbose_name=_('Type'),
    )
    systems = models.ManyToManyField(
        System, through='EquipmentSystem', related_name='equipment', verbose_name=_('Systems'),
    )
    # Who it was bought from: a live supplier of equipment and spare parts, checked on every save. Such a
    # supplier keeps the category while equipment is bought from it (SupplierLink); deleting it leaves the
    # equipment without a supplier.
    supplier = SupplierLink(
        Supplier, null=True, blank=True, on_delete=models.SET_NULL, related_name='equipment',
        category=SupplyCategory.EQUIPMENT, verbose_name=_('Supplier'),
        error_messages={'invalid': _('Choose a supplier of equipment and spare parts.')},
        kept=ngettext_lazy(
            '%(count)d piece of equipment is bought from it: keep “%(category)s” ticked, or choose another '
            'supplier for it first.',
            '%(count)d pieces of equipment are bought from it: keep “%(category)s” ticked, or choose another '
            'supplier for them first.', 'count'),
    )
    name = models.CharField(_('Name'), max_length=255)
    code = models.CharField(_('Code'), max_length=50)
    status = models.CharField(_('Status'), max_length=20, choices=Status.choices, default=Status.OPERATIONAL)
    manufacturer = models.CharField(_('Manufacturer'), max_length=100, blank=True)
    model = models.CharField(_('Model'), max_length=100, blank=True)
    serial_number = models.CharField(_('Serial number'), max_length=100, blank=True)
    purchase_date = models.DateField(_('Purchase date'), null=True, blank=True)
    warranty_end_date = models.DateField(_('Warranty end date'), null=True, blank=True)
    installation_date = models.DateField(_('Installation date'), null=True, blank=True)
    description = models.CharField(_('Description'), max_length=1000, blank=True)
    notes = models.CharField(_('Notes'), max_length=2000, blank=True)
    specifications = SchemaValuesField(_('Technical specifications'), default=dict, blank=True,
                                       schema_from='equipment_type')

    class Meta:
        db_table = 'equipment'
        ordering = ['name']
        verbose_name = _('equipment')
        verbose_name_plural = _('equipment')
        constraints = [
            models.UniqueConstraint(
                fields=['code'], condition=Q(is_deleted=False), name='uq_equipment_code_live',
                violation_error_message=_('Other equipment already uses this code.'),
            ),
            models.UniqueConstraint(
                fields=['serial_number'], condition=Q(is_deleted=False) & ~Q(serial_number=''),
                name='uq_equipment_serial_number_live',
                violation_error_message=_('Other equipment already has this serial number.'),
            ),
            models.CheckConstraint(
                condition=Q(parent__isnull=True) | ~Q(parent=F('id')),
                name='chk_equipment_not_its_own_parent',
                violation_error_message=_('Equipment cannot be a part of itself.'),
            ),
            models.CheckConstraint(
                condition=Q(warranty_end_date__isnull=True) | Q(purchase_date__isnull=True)
                | Q(warranty_end_date__gte=F('purchase_date')),
                name='chk_equipment_warranty_after_purchase',
                violation_error_message=_('The warranty cannot end before the purchase date.'),
            ),
        ]
        indexes = [models.Index(fields=['status'])]

    @property
    def site_id(self):
        """The site of the production department: equipment has no site of its own."""
        return self.production_department.site_id if self.production_department_id else None

    def live_links(self):
        """The links to systems that are not deleted, the primary one first."""
        return [link for link in self.system_links.all() if not link.system.is_deleted]

    def clean(self):
        super().clean()
        errors = {}
        site_id = self.site_id
        if self.production_department_id and site_id is None:
            errors['production_department'] = _('This production department is not on any site; choose one that is.')
        elif site_id and not self._state.adding:
            elsewhere = [part for part in self.children.select_related('production_department')
                         if part.site_id != site_id]
            if elsewhere:
                errors['production_department'] = ValidationError(
                    _('Its parts are on another site: %(parts)s. Move them first.'),
                    params={'parts': ', '.join(str(part) for part in elsewhere)})
        if self.parent_id:
            if self.parent_id == self.pk:
                errors['parent'] = _('Equipment cannot be a part of itself.')
            elif site_id and self.parent.site_id != site_id:
                errors['parent'] = _('The parent equipment is on another site.')
            elif self.nested_under_itself():
                errors['parent'] = _('The parent equipment is one of its own parts.')
        if self.purchase_date and self.warranty_end_date and self.warranty_end_date < self.purchase_date:
            errors['warranty_end_date'] = _('The warranty cannot end before the purchase date.')
        if (self.equipment_type_id and not self._state.adding and not self.equipment_type.takes_calibrations
                and self.calibrations.exists()):
            errors['equipment_type'] = _('It has feed calibrations, which only a feeder has: remove them on the '
                                         'Feed calibration tab before choosing another kind of type.')
        if errors:
            raise ValidationError(errors)


CRITICALITY = [(level, str(level)) for level in range(1, 6)]


class EquipmentSystem(models.Model):
    """A system a piece of equipment serves, and how: whether it is the equipment's primary system, its
    role there, and how critical it is to the system (1 to 5). Source table: farm.equipment_systems.

    A plain row, saved with the equipment's form as a whole list. It stays when its system is deleted,
    but only links to live systems count and show, so restoring the system brings the link back."""

    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, related_name='system_links',
                                  verbose_name=_('Equipment'))
    system = models.ForeignKey(System, on_delete=models.CASCADE, related_name='equipment_links',
                               verbose_name=_('System'))
    is_primary = models.BooleanField(pgettext_lazy('link', 'Primary'), default=False)
    role = models.CharField(_('Role'), max_length=50, blank=True)
    criticality = models.PositiveSmallIntegerField(_('Criticality'), choices=CRITICALITY, default=3)

    objects = SealedManager()

    class Meta:
        db_table = 'equipment_systems'
        ordering = ['-is_primary', 'system__name']
        verbose_name = _('system link')
        verbose_name_plural = _('system links')
        constraints = [
            models.UniqueConstraint(fields=['equipment', 'system'], name='uq_equipment_systems_pair',
                                    violation_error_message=_('The equipment is linked to this system already.')),
            models.UniqueConstraint(fields=['equipment'], condition=Q(is_primary=True),
                                    name='uq_equipment_systems_one_primary',
                                    violation_error_message=_('Only one system can be the primary one.')),
            models.CheckConstraint(condition=Q(criticality__gte=1, criticality__lte=5),
                                   name='chk_equipment_systems_criticality',
                                   violation_error_message=_('The criticality is from 1 to 5.')),
        ]

    def __str__(self):
        return f'{self.equipment} → {self.system}'

    def clean(self):
        # The site rule needs both ends; a row being filled in (core.links) gets them before it is saved.
        if self.system_id is None or self.equipment_id is None or self.equipment.site_id is None:
            return
        if self.system.site_id != self.equipment.site_id:
            raise ValidationError(_('%(system)s is on another site than the production department.'),
                                  params={'system': self.system})


class FeederCalibration(models.Model):
    """How much feed a feeder dispenses per shot for one feed size, and its silo capacity. Source
    table: farm.feeder_calibrations. Only a feeder has them; a feeder's calibrations are saved as a
    whole list on its Feed calibration tab (core.crud.RowList)."""

    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, related_name='calibrations',
                                  verbose_name=_('Equipment'))
    feed_size_mm = models.DecimalField(
        _('Feed size (mm)'), max_digits=5, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01')), MaxValueValidator(100)],
    )
    label = models.CharField(_('Label'), max_length=100, blank=True)
    grams_per_dispensing = models.DecimalField(
        _('Feed per shot (g)'), max_digits=8, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.1')), MaxValueValidator(100000)],
    )
    silo_capacity_kg = models.DecimalField(
        _('Silo capacity (kg)'), max_digits=8, decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100000)],
    )
    notes = models.CharField(_('Notes'), max_length=500, blank=True)
    created_at = models.DateTimeField(_('Created at'), auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
        verbose_name=_('Created by'),
    )

    class Meta:
        db_table = 'feeder_calibrations'
        ordering = ['feed_size_mm']
        verbose_name = _('feed calibration')
        verbose_name_plural = _('feed calibrations')
        constraints = [
            models.UniqueConstraint(fields=['equipment', 'feed_size_mm'], name='uq_feeder_calibrations_feed_size',
                                    violation_error_message=_('Two rows have the same feed size.')),
            models.CheckConstraint(condition=Q(feed_size_mm__gte=Decimal('0.01'), feed_size_mm__lte=100),
                                   name='chk_feeder_calibrations_feed_size'),
            models.CheckConstraint(condition=Q(grams_per_dispensing__gte=Decimal('0.1'), grams_per_dispensing__lte=100000),
                                   name='chk_feeder_calibrations_grams'),
            models.CheckConstraint(condition=Q(silo_capacity_kg__gte=0, silo_capacity_kg__lte=100000),
                                   name='chk_feeder_calibrations_silo'),
        ]

    def __str__(self):
        return f'{self.feed_size_mm} mm'

    def clean(self):
        if self.equipment_id and not self.equipment.equipment_type.takes_calibrations:
            raise ValidationError(_('Only a feeder has feed calibrations.'))
