"""The harvest tabs' forms: a slaughter facility (Setup › Reference data), a batch's production plan and a
planned harvest or transport (Operations › Harvest). Every rule is the model's or the database's; the forms
narrow the choices and put the message on the field."""
from decimal import ROUND_HALF_UP, Decimal

from django import forms
from django.utils.translation import gettext_lazy as _

from core.crud import TabbedForm, tab_fields
from core.widgets import DependentSelect

from ..models import Batch, HandlingPlanItem, ProductionPlan, SlaughterFacility, Species, Supplier, Tank
from ..models.harvest import PlanKind, offered_facilities
from ..stock import read as stock_read
from ..stock.dates import local_today
from .stock import DATE, DECIMAL, TransportChoice, transport_suppliers


class SupplierOf(forms.ModelChoiceField):
    """Suppliers of one category, with the status of those not active."""

    def label_from_instance(self, supplier):
        if supplier.status == Supplier.Status.ACTIVE:
            return str(supplier)
        return f'{supplier} · {supplier.get_status_display()}'


# ---- slaughter facilities -----------------------------------------------------------------------------
SLAUGHTER_FACILITY_TABS = [
    ('basic', _('Basic info'), ['name', 'approval_number', 'operator', 'status']),
    ('location', _('Location'), ['address', 'municipality', 'latitude', 'longitude']),
    ('intake', _('Species and capacity'), ['species', 'capacity_tonnes_per_day']),
    ('notes', _('Notes'), ['notes']),
]


class SlaughterFacilityForm(TabbedForm):
    tabs = SLAUGHTER_FACILITY_TABS

    class Meta:
        model = SlaughterFacility
        fields = tab_fields(SLAUGHTER_FACILITY_TABS)
        field_classes = {'operator': SupplierOf}
        localized_fields = ['latitude', 'longitude', 'capacity_tonnes_per_day']
        help_texts = {
            'approval_number': _('Mattilsynet’s approval number of the slaughterhouse (godkjenningsnummer), as the '
                                 'slaughter reports name it.'),
            'operator': _('The company that runs it: a supplier of slaughter and processing (Purchasing › '
                          'Suppliers).'),
            'status': _('Active: harvests can go to it. Inactive: kept for the harvests that went there.'),
            'species': _('The species it takes. None ticked: it takes every species.'),
            'capacity_tonnes_per_day': _('Round weight it can take a day, in tonnes.'),
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': _('e.g. Fjord Slakteri')}),
            'approval_number': forms.TextInput(attrs={'placeholder': _('e.g. M123'), 'data-uppercase': '',
                                                      'maxlength': 6}),
            'latitude': forms.TextInput(attrs={'placeholder': _('e.g. 60.3913'), 'inputmode': 'decimal'}),
            'longitude': forms.TextInput(attrs={'placeholder': _('e.g. 5.3221'), 'inputmode': 'decimal'}),
            'capacity_tonnes_per_day': forms.TextInput(attrs=DECIMAL),
            'species': forms.CheckboxSelectMultiple(attrs={'class': 'choices'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['operator'].empty_label = _('None')
        self.fields['species'].queryset = Species.objects.order_by('common_name')

    def clean_approval_number(self):
        return self.cleaned_data['approval_number'].strip().upper()

    def clean(self):
        cleaned = super().clean()
        latitude, longitude = cleaned.get('latitude'), cleaned.get('longitude')
        if (latitude is None) != (longitude is None) and not {'latitude', 'longitude'} & set(self.errors):
            self.add_error('longitude' if longitude is None else 'latitude',
                           _('Latitude and longitude must be provided together.'))
        return cleaned


# ---- production plans ---------------------------------------------------------------------------------
PRODUCTION_PLAN_TABS = [('plan', _('Production plan'), ['batch', 'target_weight_g', 'notes'])]


class BatchChoice(forms.ModelChoiceField):
    def label_from_instance(self, batch):
        name = f' · {batch.name}' if batch.name else ''
        return f'{batch.code}{name} · {batch.species.common_name}'


class ProductionPlanForm(TabbedForm):
    """A batch's target weight. The batch is chosen once: a batch in stock without a production plan."""

    tabs = PRODUCTION_PLAN_TABS
    fixed_after_creation = ('batch',)

    class Meta:
        model = ProductionPlan
        fields = tab_fields(PRODUCTION_PLAN_TABS)
        field_classes = {'batch': BatchChoice}
        localized_fields = ['target_weight_g']
        help_texts = {
            'target_weight_g': _('The average weight the fish are grown to for harvest, in grams. When they reach '
                                 'it is worked out from the feeding protocols’ projection.'),
        }
        widgets = {'target_weight_g': forms.TextInput(attrs={**DECIMAL, 'placeholder': _('e.g. 5000')}),
                   'notes': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        planned = ProductionPlan.objects.exclude(pk=self.instance.pk).values('batch_id')
        # A target weight is for fish that are harvested: cleaner fish are culled, not harvested.
        batches = (Batch.objects.filter(pk__in=stock_read.batches_in_stock(), species__cleaner_fish_type='')
                   .exclude(pk__in=planned))
        if self.instance.batch_id:
            batches = batches | Batch.all_objects.filter(pk=self.instance.batch_id)
        self.fields['batch'].queryset = batches.order_by('-input_date', '-code')
        self.fields['batch'].empty_label = _('Select a batch')


# ---- planned harvests and transports ------------------------------------------------------------------
PLAN_ITEM_TABS = [
    ('plan', _('Plan'), ['kind', 'date', 'unit', 'batch', 'planned_count', 'planned_kg', 'facility',
                         'destination_unit', 'transport', 'vessel', 'notes', 'cancelled_reason']),
]
FROM_ADDRESS = ('kind', 'unit', 'batch', 'date', 'planned_count', 'planned_kg')


class UnitChoice(forms.ModelChoiceField):
    def label_from_instance(self, unit):
        return f'{unit.code} · {unit.name}'


class HandlingPlanItemForm(TabbedForm):
    """A planned harvest (to a slaughter facility) or transport (to another unit) of one batch's fish in a
    unit. The kind is chosen once and decides the fields; the batches follow the unit, the facilities the
    batch's species. Cancelling is giving a reason, and clearing it plans the item again."""

    tabs = PLAN_ITEM_TABS
    fixed_after_creation = ('kind',)
    refresh_on = ('kind',)

    class Meta:
        model = HandlingPlanItem
        fields = tab_fields(PLAN_ITEM_TABS)
        field_classes = {'unit': UnitChoice, 'destination_unit': UnitChoice, 'batch': BatchChoice,
                         'transport': TransportChoice}
        localized_fields = ['planned_kg']
        help_texts = {
            'planned_count': _('Optional: how many fish.'),
            'planned_kg': _('Optional: their round (live) weight, in kg.'),
            'transport': _('Optional: the wellboat or haulage company.'),
            'cancelled_reason': _('Fill it in to cancel the plan; clear it to plan it again.'),
        }
        widgets = {'date': DATE, 'planned_kg': forms.TextInput(attrs=DECIMAL),
                   'vessel': forms.TextInput(attrs={'placeholder': _('e.g. MS Ronja Harvest')}),
                   'notes': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        item = self.instance
        kind = self.current('kind') or item.kind or PlanKind.HARVEST
        self.fields['kind'].choices = list(PlanKind.choices)
        if kind == PlanKind.HARVEST:
            del self.fields['destination_unit']
        else:
            del self.fields['facility']
        stock = stock_read.stock_of(list(Tank.objects.all()))
        units = Tank.objects.filter(pk__in=list(stock)) | Tank.objects.filter(pk=item.unit_id)
        self.fields['unit'].queryset = units.order_by('code')
        self.fields['unit'].empty_label = _('Select a unit')
        homes = {}
        for unit_id, unit_stock in stock.items():
            for share in unit_stock.counted:          # a cleaner fish is culled, not harvested
                homes.setdefault(str(share.batch.pk), []).append(unit_id)
        if item.batch_id:
            homes.setdefault(str(item.batch_id), []).append(item.unit_id)
        batches = Batch.all_objects.filter(pk__in=homes).select_related('species')
        self.fields['batch'].queryset = batches.order_by('-input_date', '-code')
        self.fields['batch'].empty_label = _('Select a batch')
        DependentSelect.apply(self.fields['batch'], 'unit', homes)
        if kind == PlanKind.HARVEST:
            # The plan is what the planned-slaughter notice reports: the form says what that notice needs, where the
            # field said "optional" and the notice then refused to be filed (flow fault M-12).
            self.fields['planned_kg'].help_text = _(
                'Their round (live) weight, in kg. The plan is saved without it, but the planned-slaughter notice of '
                'its week (Production › Reports) reports these kilos and cannot be filed for a plan that has none.')
            self.fields['facility'].help_text = _(
                'The planned-slaughter notice is filed per facility; it also needs the company that files for the '
                'facility (its operator, Purchasing › Suppliers) to have a 9-digit organisation number.')
        if 'facility' in self.fields:
            facilities = offered_facilities() | SlaughterFacility.objects.filter(pk=item.facility_id)
            self.fields['facility'].queryset = facilities.distinct().order_by('name')
            self.fields['facility'].required = True
            self.fields['facility'].empty_label = _('Select a slaughter facility')
            takes = {}
            for facility in self.fields['facility'].queryset.prefetch_related('species'):
                species = {each.pk for each in facility.species.all()}
                takes[str(facility.pk)] = [str(batch.pk) for batch in batches
                                           if not species or batch.species_id in species]
            DependentSelect.apply(self.fields['facility'], 'batch', takes)
        if 'destination_unit' in self.fields:
            self.fields['destination_unit'].queryset = Tank.objects.order_by('code')
            self.fields['destination_unit'].empty_label = _('Not chosen yet')
        self.fields['transport'].queryset = transport_suppliers()
        self.fields['transport'].empty_label = _('None')
        if not self.is_bound and item._state.adding and item.date is None:
            self.initial.setdefault('date', local_today())

    def clean_cancelled_reason(self):
        return self.cleaned_data['cancelled_reason'].strip()


def planned_kg(count, target_g):
    """The round kilos a count of fish weighs at a target weight, to the gram."""
    return (Decimal(count) * target_g / 1000).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)

