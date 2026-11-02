from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _, ngettext

from core.fields import ChoiceArrayField
from core.models import CODE, CODE_MESSAGE, AuditedModel, CodedMixin

from .contact import ONE_PRIMARY, Contact
from .site import Site

# A company registration or VAT number as stored: no spaces, capital letters (normalise_organisation_number).
ORGANISATION_NUMBER = r'^[A-Z0-9-]+$'
ORGANISATION_NUMBER_MESSAGE = _('Use letters, digits and hyphens only, e.g. 923456789 or NO923456789MVA.')
SUPPLIES_MESSAGE = _('Tick at least one thing it supplies.')
RATINGS = [(stars, str(stars)) for stars in range(1, 6)]


def normalise_organisation_number(text):
    """'923 456 789' as '923456789', 'no 923456789 mva' as 'NO923456789MVA'."""
    return ''.join((text or '').split()).upper()


class SupplyCategory(models.TextChoices):
    """What a fish farm buys from a supplier: goods first, then services."""
    LIVE_FISH = 'live_fish', _('Live fish and eggs')
    FEED = 'feed', _('Feed')
    EQUIPMENT = 'equipment', _('Equipment and spare parts')
    CONSUMABLES = 'consumables', _('Consumables')
    CHEMICALS = 'chemicals', _('Chemicals')
    MEDICINES = 'medicines', _('Medicines and vaccines')
    VETERINARY = 'veterinary', _('Veterinary and fish health')
    LABORATORY = 'laboratory', _('Laboratory analyses')
    DIVING = 'diving', _('Diving and ROV')
    TRANSPORT = 'transport', _('Wellboat and transport')
    MAINTENANCE = 'maintenance', _('Maintenance and repair')
    CONSULTANCY = 'consultancy', _('Consultancy')
    OTHER = 'other', _('Other')


class SupplierStatus(models.TextChoices):
    ACTIVE = 'active', _('Active')
    INACTIVE = 'inactive', _('Inactive')
    SUSPENDED = 'suspended', _('Suspended')
    BLOCKED = 'blocked', _('Blocked')


class Supplier(CodedMixin, AuditedModel):
    """A company the farm buys from: what it supplies (goods, live fish, services), how to reach it and on
    which terms. Source table: farm.suppliers.

    What it supplies is a list of categories (`supplies`), several at once: a feed mill that also
    delivers by boat supplies feed and transport. Other records link to a supplier by what they buy:
    equipment takes only a supplier of equipment and spare parts (Equipment.supplier), so such a
    supplier keeps that category while equipment is bought from it.

    Differences from the source: one list of categories instead of a main type next to a second, free
    list (`type`, `supplyTypes`); one status (no `isActive`); the address in flat columns (the source
    kept city and country twice); contact persons as rows (the source accepted them and dropped them);
    name (whatever its case), code and organisation number unique among live suppliers, and every rule
    checked by the database. Not ported: the free list of product names (the products are records of
    their own tabs, linked to the supplier), the preferred site, fax, description and certifications
    (accepted and never stored)."""

    # Defined outside the class so that its Meta can name their values in the constraints.
    Category, Status = SupplyCategory, SupplierStatus

    name = models.CharField(_('Name'), max_length=200)
    code = models.CharField(_('Code'), max_length=20, validators=[RegexValidator(CODE, CODE_MESSAGE)])
    organisation_number = models.CharField(
        _('Organisation number'), max_length=50, blank=True,
        validators=[RegexValidator(ORGANISATION_NUMBER, ORGANISATION_NUMBER_MESSAGE)],
    )
    supplies = ChoiceArrayField(models.TextField(choices=SupplyCategory.choices), verbose_name=_('Supplies'),
                                default=list)
    status = models.CharField(_('Status'), max_length=20, choices=Status.choices, default=Status.ACTIVE)
    rating = models.PositiveSmallIntegerField(_('Rating'), null=True, blank=True, choices=RATINGS)
    email = models.EmailField(_('Email'), max_length=150, blank=True)
    phone = models.CharField(_('Phone'), max_length=50, blank=True)
    website = models.URLField(_('Website'), max_length=200, blank=True)
    street = models.CharField(_('Street address'), max_length=255, blank=True)
    postal_code = models.CharField(_('Postal code'), max_length=20, blank=True)
    city = models.CharField(_('City'), max_length=100, blank=True)
    country = models.CharField(_('Country'), max_length=100, blank=True)
    # The sites it delivers to or works at. A deleted site keeps its link rows: the link comes back
    # with the site (core.softdelete).
    sites = models.ManyToManyField(Site, blank=True, related_name='suppliers', db_table='supplier_sites',
                                   verbose_name=_('Sites served'))
    payment_terms = models.CharField(_('Payment terms'), max_length=100, blank=True)
    notes = models.CharField(_('Notes'), max_length=2000, blank=True)

    class Meta:
        db_table = 'suppliers'
        ordering = ['name']
        verbose_name = _('supplier')
        verbose_name_plural = _('suppliers')
        constraints = [
            models.UniqueConstraint(
                fields=['code'], condition=Q(is_deleted=False), name='uq_suppliers_code_live',
                violation_error_message=_('Another supplier already uses this code.'),
            ),
            models.UniqueConstraint(
                Lower('name'), condition=Q(is_deleted=False), name='uq_suppliers_name_live',
                violation_error_message=_('Another supplier already has this name.'),
            ),
            models.UniqueConstraint(
                fields=['organisation_number'], condition=Q(is_deleted=False) & ~Q(organisation_number=''),
                name='uq_suppliers_organisation_number_live',
                violation_error_message=_('Another supplier already has this organisation number.'),
            ),
            models.CheckConstraint(
                condition=Q(code__regex=CODE), name='chk_suppliers_code', violation_error_message=CODE_MESSAGE,
            ),
            models.CheckConstraint(
                condition=Q(organisation_number='') | Q(organisation_number__regex=ORGANISATION_NUMBER),
                name='chk_suppliers_organisation_number', violation_error_message=ORGANISATION_NUMBER_MESSAGE,
            ),
            models.CheckConstraint(
                condition=Q(supplies__contained_by=SupplyCategory.values), name='chk_suppliers_supplies',
            ),
            models.CheckConstraint(
                condition=Q(supplies__len__gt=0), name='chk_suppliers_supplies_not_empty',
                violation_error_message=SUPPLIES_MESSAGE,
            ),
            models.CheckConstraint(condition=Q(status__in=SupplierStatus.values), name='chk_suppliers_status'),
            models.CheckConstraint(
                condition=Q(rating__isnull=True) | Q(rating__gte=1, rating__lte=5), name='chk_suppliers_rating',
            ),
        ]
        indexes = [models.Index(fields=['status'])]

    def supplies_labels(self):
        """The labels of what it supplies, in the order of the categories."""
        return [SupplyCategory(value).label for value in self.supplies]

    def primary_contact(self):
        """The primary contact person, or None (the list shows it; contacts are prefetched there)."""
        return next((contact for contact in self.contacts.all() if contact.is_primary), None)

    def clean(self):
        super().clean()
        if not self._state.adding and SupplyCategory.EQUIPMENT not in (self.supplies or []):
            bought = self.equipment.count()
            if bought:
                raise ValidationError({'supplies': ValidationError(ngettext(
                    '%(count)d piece of equipment is bought from it: keep “%(category)s” ticked, or choose '
                    'another supplier for it first.',
                    '%(count)d pieces of equipment are bought from it: keep “%(category)s” ticked, or choose '
                    'another supplier for them first.', bought),
                    params={'count': bought, 'category': SupplyCategory.EQUIPMENT.label})})

    def save(self, *args, **kwargs):
        self.organisation_number = normalise_organisation_number(self.organisation_number)
        super().save(*args, **kwargs)


class SupplierContact(Contact):
    """A person to contact at a supplier: sales, orders, technical support, the vet on call.

    The source accepted a contact list and a primary contact and stored only one name
    (`contactPerson`); here they are rows, saved as a whole list on the supplier's Contact tab."""

    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='contacts',
                                 verbose_name=_('Supplier'))

    class Meta(Contact.Meta):
        db_table = 'supplier_contacts'
        verbose_name = _('supplier contact')
        verbose_name_plural = _('supplier contacts')
        constraints = [
            models.UniqueConstraint(
                fields=['supplier'], condition=Q(is_primary=True), name='uq_supplier_contacts_one_primary',
                violation_error_message=ONE_PRIMARY,
            ),
        ]
