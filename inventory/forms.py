"""The store's forms: the storage location tab (core.crud) with its reorder levels, and the dialogs of
Operations › Storage, each one call of the write path (inventory/services.py). They are the stock's
dialogs (farm/forms/stock.py): a token so a form sent twice records once, the farm's today, the service's
reasons on the field they concern. Every reference is a choice from a list: a site, a location, a feed, a
supplier, a lot in a location; the only typed texts are a new lot's number as printed on the bag and the
supplier's document number."""
import uuid
from decimal import Decimal

from django import forms
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.utils.translation import gettext_lazy as _, ngettext_lazy

from core.crud import BoundedModelForm, CodedFormMixin, Fieldset, RowFormSet, TabbedForm, tab_fields
from core.widgets import DependentSelect
from farm.forms.stock import DATE, DECIMAL, NOTES, ServiceErrors
from farm.models import Equipment, EquipmentType, Feed, Site, Supplier
from farm.models.supplier import SupplyCategory
from farm.stock.dates import shown_date, site_today

from . import services
from .templatetags.inventory import shown_quantity
from .models import (
    QUANTITY, InventoryLot, IssueReason, ReorderLevel, StorageLocation, WriteOffReason,
)

QUANTITY_FIELD = {**QUANTITY, 'min_value': Decimal('0.001'), 'localize': True, 'widget': forms.TextInput(attrs=DECIMAL)}
# The categories the store keeps today, whose suppliers a delivery offers (feed; medicines with the health module).
STOCKED = [SupplyCategory.FEED]


# ---- Company › Facility › Storage locations ------------------------------------------------------
LOCATION_TABS = [
    ('general', _('General'), ['site', 'name', 'code', 'kind', 'status', 'feeder']),
    ('capacity', _('Capacity and notes'), [
        Fieldset(_('Capacity'), ['capacity', 'capacity_unit'],
                 _('Optional. Above it the overview warns; nothing is refused. Feed is counted in kg.')),
        'notes',
    ]),
]


class StorageLocationForm(CodedFormMixin, TabbedForm):
    """A storage location: its site, chosen once; a silo may name the feeder it fills, a feeder of its site."""

    tabs = LOCATION_TABS
    fixed_after_creation = ('site',)

    class Meta:
        model = StorageLocation
        fields = tab_fields(LOCATION_TABS)
        localized_fields = ['capacity']
        help_texts = {
            'site': _('A location stays on the site it was created on.'),
            'code': _('Your own short code: capital letters, digits, hyphens and underscores.'),
            'status': _('An inactive location takes no new stock; what it holds still shows and can leave.'),
            'feeder': _('A silo only: the feeder it fills, on the same site.'),
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': _('e.g. Feed store 1')}),
            'code': forms.TextInput(attrs={'placeholder': _('e.g. FS-01'), 'data-uppercase': ''}),
            'capacity': forms.TextInput(attrs=DECIMAL),
            'notes': NOTES,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        site = self.fields['site']
        site.queryset = Site.objects.all()
        site.required = True
        site.empty_label = _('Select a site')
        self.fields['kind'].choices = [('', _('Select a kind'))] + list(StorageLocation.Kind.choices)
        self.fields['capacity_unit'].choices = [('', '---------')] + list(StorageLocation._meta.get_field(
            'capacity_unit').choices)
        feeders = (Equipment.objects.filter(equipment_type__category=EquipmentType.Category.FEEDING,
                                            production_department__site__isnull=False)
                   .select_related('production_department').order_by('name'))
        feeder = self.fields['feeder']
        feeder.queryset = feeders
        feeder.empty_label = _('None')
        DependentSelect.apply(feeder, 'site', {str(item.pk): str(item.production_department.site_id)
                                               for item in feeders})


class ReorderLevelForm(BoundedModelForm):
    """A row of a location's reorder levels: a feed and the quantity below which it is low there. The row
    stores the feed's item of the store (RowList.values)."""

    feed = forms.ModelChoiceField(label=_('Feed'), queryset=Feed.objects.all())

    class Meta:
        model = ReorderLevel
        fields = ['feed', 'level']
        localized_fields = ['level']
        widgets = {'level': forms.TextInput(attrs={**DECIMAL, 'placeholder': _('e.g. 2000')})}
        labels = {'level': _('Reorder level (kg)')}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['feed'].empty_label = _('Select a feed')
        if self.instance.pk:
            self.initial['feed'] = self.instance.item.feed_id

    def validate_constraints(self):
        # One row per item spans the whole list, saved as a full replace: the formset checks it.
        pass


class BaseReorderLevelFormSet(RowFormSet):
    default_error_messages = {
        'too_many_forms': ngettext_lazy('A location has at most %(num)d reorder level.',
                                        'A location has at most %(num)d reorder levels.', 'num'),
    }

    def clean(self):
        super().clean()
        feeds = [row['feed'] for row in self.kept_rows() if row.get('feed')]
        if len(feeds) != len(set(feeds)):
            raise ValidationError(_('One reorder level per feed.'))


ReorderLevelFormSet = forms.inlineformset_factory(
    StorageLocation, ReorderLevel, form=ReorderLevelForm, formset=BaseReorderLevelFormSet,
    extra=0, can_delete=True, max_num=100, validate_max=True,
)


# ---- the dialogs of Operations › Storage ---------------------------------------------------------
class Dialog(ServiceErrors, forms.Form):
    """What every dialog has: the token, the date (the farm's today on the site's clock) and notes."""

    token = forms.UUIDField(widget=forms.HiddenInput)
    date = forms.DateField(label=_('Date'), widget=DATE)
    notes = forms.CharField(label=_('Notes'), max_length=2000, required=False, widget=NOTES)

    service_fields = {}

    def __init__(self, *args, site=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['date'].initial = site_today(site)
        self.fields['token'].initial = uuid.uuid4()


class SupplierChoice(forms.ModelChoiceField):
    """Live suppliers of what the store keeps, with the status of those not active."""

    def label_from_instance(self, supplier):
        if supplier.status == Supplier.Status.ACTIVE:
            return str(supplier)
        return f'{supplier} · {supplier.get_status_display()}'


def suppliers():
    return Supplier.objects.filter(supplies__overlap=STOCKED).order_by('name')


class LocationChoice(forms.ModelChoiceField):
    def label_from_instance(self, location):
        return f'{location.code} · {location.name} ({location.site.name})'


def active_locations():
    return StorageLocation.objects.filter(status=StorageLocation.Status.ACTIVE).select_related('site').order_by(
        'site__name', 'code')


class ReceiptForm(Dialog):
    """A delivery: the supplier (a live supplier of feed, Purchasing › Suppliers), the day, the supplier's
    document number; its lines below (ReceiptLineFormSet)."""

    supplier = SupplierChoice(label=_('Supplier'), queryset=Supplier.objects.none())
    reference = forms.CharField(label=_('Supplier’s document number'), max_length=100, required=False,
                                help_text=_('Optional: the number of the delivery note or invoice.'))

    field_order = ['supplier', 'date', 'reference', 'notes']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['supplier'].queryset = suppliers()
        self.fields['supplier'].empty_label = _('Select a supplier')

    def save(self, user, lines):
        data = self.cleaned_data
        return services.receive(
            user, supplier=data['supplier'], day=data['date'], reference=data['reference'], notes=data['notes'],
            lines=[(row['feed'], row['lot_number'], row['expiry_date'], row['location'], row['quantity'],
                    row['unit_cost'], row['currency']) for row in lines],
            token=data['token'])


class ReceiptLineForm(forms.Form):
    """A line of a delivery: the feed, its lot (the number and expiry printed on the bag; both optional for
    feed), the location it goes into, the kilos, and what a kilo cost."""

    feed = forms.ModelChoiceField(label=_('Feed'), queryset=Feed.objects.none())
    lot_number = forms.CharField(label=_('Lot number'), max_length=100, required=False)
    expiry_date = forms.DateField(label=_('Expiry date'), required=False, widget=DATE)
    location = LocationChoice(label=_('Location'), queryset=StorageLocation.objects.none())
    quantity = forms.DecimalField(label=_('Quantity (kg)'), **QUANTITY_FIELD)
    unit_cost = forms.DecimalField(label=_('Cost per kg'), max_digits=14, decimal_places=4, min_value=0,
                                   required=False, localize=True, widget=forms.TextInput(attrs=DECIMAL))
    currency = forms.CharField(label=_('Currency'), max_length=3, required=False,
                               widget=forms.TextInput(attrs={'placeholder': 'NOK', 'data-uppercase': '',
                                                             'maxlength': 3}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['feed'].queryset = Feed.objects.filter(status=Feed.Status.ACTIVE).order_by('name')
        self.fields['location'].queryset = active_locations()

    def clean(self):
        cleaned = super().clean()
        currency = (cleaned.get('currency') or '').strip().upper()
        cleaned['currency'] = currency
        if 'unit_cost' in cleaned and (cleaned['unit_cost'] is None) != (not currency):
            self.add_error('currency' if cleaned['unit_cost'] is not None else 'unit_cost',
                           _('A unit cost needs its currency, and a currency a unit cost.'))
        return cleaned


ReceiptLineFormSet = forms.formset_factory(ReceiptLineForm, extra=0, min_num=1, validate_min=True, max_num=30,
                                           validate_max=True)


def kept_rows(formset):
    """The cleaned rows that name what they are about (a row added and left blank is dropped)."""
    return [row.cleaned_data for row in formset.forms if row.cleaned_data and any(
        row.cleaned_data.get(name) for name in ('feed', 'lot'))]


class BucketChoice(forms.ChoiceField):
    """A lot in a location with stock, as one choice: "FS-01 · Feed 3 mm (F3) · lot 4711, expires
    1 Mar 2027 — 1,200 kg". Its value is "<location id>:<lot id>"; it cleans to (location, lot)."""

    def __init__(self, *args, buckets=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.set_buckets(buckets)

    def set_buckets(self, buckets):
        self.buckets = {f'{row.location.pk}:{row.lot.pk}': row for row in buckets}
        self.choices = [('', _('Select a lot in a location'))] + [
            (key, bucket_label(row)) for key, row in self.buckets.items()]

    def clean(self, value):
        value = super().clean(value)
        row = self.buckets[value]
        return row.location, row.lot


def bucket_label(row):
    """FS-01 · Feed 3 mm (F3) · lot 4711, expires 1 Mar 2027 — 1,200 kg"""
    params = {'location': row.location.code, 'item': row.item, 'lot': services.lot_label(row.lot),
              'quantity': shown_quantity(row.quantity, row.item.unit), 'unit': row.item.get_unit_display()}
    if row.lot.number and row.lot.expiry_date:
        return _('%(location)s · %(item)s · lot %(lot)s, expires %(date)s — %(quantity)s %(unit)s') % {
            **params, 'date': shown_date(row.lot.expiry_date)}
    return _('%(location)s · %(item)s · lot %(lot)s — %(quantity)s %(unit)s') % params


class DepartureForm(Dialog):
    """A lot leaving a location: which (a lot in a location with stock), when, how much."""

    source = BucketChoice(label=_('Lot in location'))
    quantity = forms.DecimalField(label=_('Quantity'), **QUANTITY_FIELD)

    service_fields = {'location': 'source', 'lot': 'source', 'lines': NON_FIELD_ERRORS}
    field_order = ['source', 'date', 'quantity']

    def __init__(self, *args, buckets=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['source'].set_buckets(buckets)

    def common(self, user):
        data = self.cleaned_data
        location, lot = data['source']
        return {'location': location, 'lot': lot, 'day': data['date'], 'quantity': data['quantity'],
                'notes': data['notes'], 'token': data['token']}


class IssueForm(DepartureForm):
    reason = forms.ChoiceField(label=_('Reason'), choices=IssueReason.choices)
    field_order = ['source', 'date', 'quantity', 'reason', 'notes']

    def save(self, user):
        return services.issue(user, reason=self.cleaned_data['reason'], **self.common(user))


class WriteOffForm(DepartureForm):
    reason = forms.ChoiceField(label=_('Reason'), choices=WriteOffReason.choices)
    field_order = ['source', 'date', 'quantity', 'reason', 'notes']

    def save(self, user):
        return services.write_off(user, reason=self.cleaned_data['reason'], **self.common(user))


class ReturnForm(DepartureForm):
    supplier = SupplierChoice(label=_('Supplier'), queryset=Supplier.objects.none(),
                              help_text=_('Who it goes back to.'))
    reference = forms.CharField(label=_('Supplier’s document number'), max_length=100, required=False,
                                help_text=_('Optional: the number of the return note.'))
    field_order = ['source', 'date', 'quantity', 'supplier', 'reference', 'notes']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['supplier'].queryset = suppliers()
        self.fields['supplier'].empty_label = _('Select a supplier')

    def save(self, user):
        data = self.cleaned_data
        return services.return_to_supplier(user, supplier=data['supplier'], reference=data['reference'],
                                           **self.common(user))


class TransferForm(DepartureForm):
    destination = LocationChoice(label=_('To location'), queryset=StorageLocation.objects.none(),
                                 help_text=_('Any active location, on this site or another.'))
    field_order = ['source', 'destination', 'date', 'quantity', 'notes']
    service_fields = {**DepartureForm.service_fields, 'location': 'source'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['destination'].queryset = active_locations()
        self.fields['destination'].empty_label = _('Select a location')

    def save(self, user):
        common = self.common(user)
        return services.transfer(user, source=common.pop('location'), destination=self.cleaned_data['destination'],
                                 **common)


class CountForm(Dialog):
    """A count of one location at the end of a day: the location and the day decide the lots listed (the
    book then, computed on read); changing either renders the form again (core.crud's draft)."""

    location = LocationChoice(label=_('Location'), queryset=StorageLocation.objects.none())

    service_fields = {'lines': NON_FIELD_ERRORS, 'lot': NON_FIELD_ERRORS, 'quantity': NON_FIELD_ERRORS}
    field_order = ['location', 'date', 'notes']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['location'].queryset = StorageLocation.objects.select_related('site').order_by('site__name', 'code')
        self.fields['location'].empty_label = _('Select a location')
        for name in ('location', 'date'):
            self.fields[name].widget.attrs['data-refresh'] = '_draft'


class CountLineForm(forms.Form):
    """A lot the book has in the location: the quantity found (0 when none is left)."""

    lot = forms.ModelChoiceField(queryset=InventoryLot.objects.all(), widget=forms.HiddenInput)
    quantity = forms.DecimalField(label=_('Counted'), max_digits=14, decimal_places=3, min_value=0, localize=True,
                                  widget=forms.TextInput(attrs=DECIMAL))


CountLineFormSet = forms.formset_factory(CountLineForm, extra=0, max_num=500)


class FoundLotForm(forms.Form):
    """A lot found in the location that the book did not have there: its feed, number and expiry (a known
    lot is reused), and the quantity found."""

    feed = forms.ModelChoiceField(label=_('Feed'), queryset=Feed.objects.none())
    lot_number = forms.CharField(label=_('Lot number'), max_length=100, required=False)
    expiry_date = forms.DateField(label=_('Expiry date'), required=False, widget=DATE)
    quantity = forms.DecimalField(label=_('Counted'), **QUANTITY_FIELD)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['feed'].queryset = Feed.objects.order_by('name')


FoundLotFormSet = forms.formset_factory(FoundLotForm, extra=0, max_num=30, validate_max=True)
