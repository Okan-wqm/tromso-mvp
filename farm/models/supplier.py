from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from core.fields import ChoiceArrayField
from core.models import CODE, CODE_MESSAGE, AuditedModel, CodedMixin
from core.softdelete import protected

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
    # A slaughterhouse and its processing plant: the operator of a slaughter facility (Reference data).
    SLAUGHTER = 'slaughter', _('Slaughter and processing')
    MAINTENANCE = 'maintenance', _('Maintenance and repair')
    CONSULTANCY = 'consultancy', _('Consultancy')
    OTHER = 'other', _('Other')


class SupplierStatus(models.TextChoices):
    ACTIVE = 'active', _('Active')
    INACTIVE = 'inactive', _('Inactive')
    SUSPENDED = 'suspended', _('Suspended')
    BLOCKED = 'blocked', _('Blocked')


class SupplierLink(models.ForeignKey):
    """A link to a supplier for what it supplies: equipment to a supplier of equipment and spare parts, a feed
    to its manufacturer (a supplier of feed), bought fish to a supplier of live fish, a harvest's transport to a
    supplier of transport, a delivery to the store to a supplier of what it brought. Every side of the rule is
    declared here, once per link, and the supplier reads its links (Supplier.links) instead of naming them:

    - the link takes only a live supplier of the category (`limit_choices_to`, which is part of the
      model's validation and narrows the form's list);
    - the supplier keeps the category while live records link to it this way (`needed`): Supplier.clean
      refuses to untick it, saying `kept`, an ngettext_lazy(..., 'count') whose %(count)d is the number of
      records and %(category)s the category's label;
    - a PROTECT link from a plain row, which core.softdelete does not follow (a harvest's transport on its
      HarvestRecord), blocks deleting the supplier (`blocker`, read by Supplier.delete_blockers); a link from a
      farm record is in the delete plan already.

    A link whose category follows the record names `category_field` instead of one `category`: the lookup
    from the linking record to the category of each thing it was supplied for (a delivery to the store brings
    feed, later medicines: `lines__lot__item__category`). Its list takes any live supplier, the record's own
    write path checks the category, and the supplier keeps every category such live records still need.

    Migrations see a plain ForeignKey: the category is already in `limit_choices_to` and the message
    changes no column."""

    def __init__(self, to=None, on_delete=None, category=None, kept=None, category_field=None, **kwargs):
        self.category, self.kept, self.category_field = category, kept, category_field
        if category is not None:
            kwargs['limit_choices_to'] = {'is_deleted': False, 'supplies__contains': [category]}
        elif category_field is not None:
            kwargs['limit_choices_to'] = {'is_deleted': False}
        super().__init__(to, on_delete, **kwargs)

    def deconstruct(self):
        name, _path, args, kwargs = super().deconstruct()
        return name, 'django.db.models.ForeignKey', args, kwargs

    def records(self, supplier):
        """The live records that link to `supplier` this way (the linking model's default manager)."""
        return self.model._default_manager.filter(**{self.name: supplier})

    def needed(self, supplier, supplies):
        """{category: how many live records link to `supplier` for it}, for the categories not in `supplies`."""
        records = self.records(supplier)
        if self.category_field is None:
            count = 0 if self.category in supplies else records.count()
            return {self.category: count} if count else {}
        missing = [category for category in SupplyCategory.values if category not in supplies]
        rows = (records.filter(**{f'{self.category_field}__in': missing}).order_by().values(self.category_field)
                .annotate(count=models.Count('pk', distinct=True)))
        return {row[self.category_field]: row['count'] for row in rows}

    def blocker(self, supplier):
        """Why deleting `supplier` is blocked by this link, or None: only a PROTECT link from a plain row, which
        the delete plan does not follow; a farm record's link is in the plan (core.softdelete)."""
        if issubclass(self.model, AuditedModel) or self.remote_field.on_delete is not models.PROTECT:
            return None
        count = self.records(supplier).count()
        return protected(self.model, count) if count else None


class Supplier(CodedMixin, AuditedModel):
    """A company the farm buys from: what it supplies (goods, live fish, services), how to reach it and on
    which terms. Source table: farm.suppliers.

    What it supplies is a list of categories (`supplies`), several at once: a feed mill that also
    delivers by boat supplies feed and transport. Other records link to a supplier by what they buy, each
    through a SupplierLink: equipment takes only a supplier of equipment and spare parts
    (Equipment.supplier), a feed only a supplier of feed as its manufacturer (Feed.manufacturer), and a
    supplier keeps a category while live records link to it for that category (`clean`).

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
        """A supplier keeps a category while live records link to it for that category (equipment, which
        can choose another supplier; feeds, made by it; batches of fish, whose origin stays as it was; the
        deliveries and returns of the store): every SupplierLink that points at suppliers is checked, and
        says so in its own words."""
        super().clean()
        if self._state.adding:
            return
        supplies, errors = self.supplies or [], []
        for link in self.links():
            for category, count in link.needed(self, supplies).items():
                errors.append(ValidationError(link.kept, params={
                    'count': count, 'category': SupplyCategory(category).label}))
        if errors:
            raise ValidationError({'supplies': errors})

    @classmethod
    def links(cls):
        """Every SupplierLink that points at suppliers, whatever app its record is in."""
        return [relation.field for relation in cls._meta.related_objects if isinstance(relation.field, SupplierLink)]

    def delete_blockers(self):
        """A PROTECT link from a record that is not a farm record of its own (a harvest's transport, kept on
        the harvest operation's HarvestRecord) blocks the delete too: core.softdelete follows only farm
        records, so each SupplierLink says whether it blocks (SupplierLink.blocker)."""
        return [reason for reason in (link.blocker(self) for link in self.links()) if reason]

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
