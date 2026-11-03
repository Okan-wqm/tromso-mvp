"""The operation dialogs of Operations › Production units. Each form is one call of the stock service
(farm/stock/services.py): the form checks what it can see (a number, a choice, a date), the service
what needs the ledger (the fish there on that day, the capacity, the unit's status, the species), and
its message lands on the field it concerns (`add_service_error`), never as "please try again".

Every form carries a token: sent twice (a double click), it records the operation once."""
import uuid
from decimal import Decimal

from django import forms
from django.core.exceptions import NON_FIELD_ERRORS
from django.utils.translation import gettext_lazy as _, ngettext

from core.crud import DRAFT

from ..models import Batch, Species, Supplier, Tank
from ..models.stock import ARRIVAL_STATUSES, CullReason, InputStage, MortalityCause, Origin, TransferReason
from ..stock import services
from ..templatetags.stock import number

DATE = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')
DECIMAL = {'inputmode': 'decimal'}
NOTES = forms.Textarea(attrs={'rows': 3})


def share_label(share):
    """A batch in the unit as a choice reads it: B-2026-001 — 3,200 fish · 145.2 g."""
    return _('%(batch)s — %(count)s fish · %(weight)s g') % {
        'batch': share.batch.code, 'count': number(share.count), 'weight': number(share.avg_weight_g, 1)}


class ServiceErrors:
    """Puts a ValidationError of the stock service on the form: on the field it names when the form has
    it (or on the field the form calls it), otherwise above the form."""

    service_fields = {}

    def add_service_error(self, error):
        if not hasattr(error, 'error_dict'):
            self.add_error(None, error.messages)
            return
        for key, messages in error.message_dict.items():
            name = self.service_fields.get(key, key)
            self.add_error(name if name in self.fields and name != NON_FIELD_ERRORS else None, messages)


def acknowledgement():
    return forms.BooleanField(
        label=_('Stock above the max density'), required=False,
        help_text=_('The unit will hold more fish than its max density allows. Tick it only when that is meant, '
                    'e.g. for a few days before a split.'))


class Acknowledged:
    """A form whose service may ask the person to confirm something unusual (fish above a unit's max
    biomass, a feeding above the usual rate): the box `ack_field` is offered once the service asked, or
    when it is ticked already, and the dialog shows it apart from the other fields."""

    ack_field = 'over_capacity_ack'

    @property
    def ack(self):
        return self[self.ack_field]

    @property
    def needs_ack(self):
        return self.ack_field in self.errors or bool(self.ack.value())


class OperationForm(ServiceErrors, forms.Form):
    """An operation on the fish of one unit: the batch (to choose when the unit holds more than one), the
    date (the farm's today by default) and notes."""

    token = forms.UUIDField(widget=forms.HiddenInput)
    batch = forms.ChoiceField(label=_('Batch'))
    date = forms.DateField(label=_('Date'), widget=DATE)
    notes = forms.CharField(label=_('Notes'), max_length=2000, required=False, widget=NOTES)

    service_fields = {'unit': NON_FIELD_ERRORS, 'species': NON_FIELD_ERRORS, 'destinations': NON_FIELD_ERRORS}
    rows = None          # the formset of the units the fish go into, for a transfer or a grading
    rows_label = ''
    # Fields whose change renders the dialog again from what was entered, saving nothing (data-refresh; a weighing
    # shows the batch's estimated weight on the day chosen and how the weight entered compares with it).
    refresh_on = ()

    def __init__(self, *args, unit, present, **kwargs):
        super().__init__(*args, **kwargs)
        self.unit = unit
        self.present = {str(share.batch.pk): share for share in present}
        field = self.fields['batch']
        choices = [(pk, share_label(share)) for pk, share in self.present.items()]
        if len(choices) == 1:
            field.choices = choices
            field.initial = choices[0][0]
            field.widget = forms.HiddenInput()
        else:
            field.choices = [('', '---------'), *choices]
            field.help_text = ngettext(
                'This unit holds %(count)d batch: the operation applies to the one chosen.',
                'This unit holds %(count)d batches: the operation applies to the one chosen.', len(choices)) % {
                'count': len(choices)}
        self.fields['date'].initial = services.local_today(unit)
        self.fields['token'].initial = uuid.uuid4()
        for name in self.refresh_on:
            self.fields[name].widget.attrs['data-refresh'] = DRAFT

    @property
    def only_batch(self):
        """The one batch in the unit, shown instead of a choice."""
        return next(iter(self.present.values())) if len(self.present) == 1 else None

    def clean_batch(self):
        return self.present[self.cleaned_data['batch']].batch


class MortalityForm(OperationForm):
    count = forms.IntegerField(label=_('Dead fish'), min_value=1)
    cause = forms.ChoiceField(label=_('Cause'), choices=MortalityCause.choices, initial=MortalityCause.UNKNOWN)
    measured_weight_kg = forms.DecimalField(
        label=_('Weight of the dead fish (kg)'), max_digits=14, decimal_places=3, min_value=Decimal('0.001'),
        required=False, localize=True, widget=forms.TextInput(attrs=DECIMAL),
        help_text=_('Optional, when they were weighed. The stock takes them out at the average weight of the '
                    'batch in this unit; the weighed figure is kept beside it.'))

    field_order = ['batch', 'date', 'count', 'cause', 'measured_weight_kg', 'notes']

    def save(self, user, rows=None):
        data = self.cleaned_data
        return services.record_mortality(
            user, unit=self.unit, batch=data['batch'], day=data['date'], count=data['count'], cause=data['cause'],
            measured_weight_kg=data['measured_weight_kg'], notes=data['notes'], token=data['token'])


class CullForm(OperationForm):
    count = forms.IntegerField(label=_('Culled fish'), min_value=1)
    reason = forms.ChoiceField(label=_('Reason'), choices=CullReason.choices, initial=CullReason.GRADING)

    field_order = ['batch', 'date', 'count', 'reason', 'notes']

    def save(self, user, rows=None):
        data = self.cleaned_data
        return services.record_cull(
            user, unit=self.unit, batch=data['batch'], day=data['date'], count=data['count'], reason=data['reason'],
            notes=data['notes'], token=data['token'])


class WeighingForm(OperationForm):
    """A sample weighed: the number of fish and their weight together (bulk weighing), or the average."""

    sample_count = forms.IntegerField(label=_('Fish weighed'), min_value=1, required=False)
    sample_weight_kg = forms.DecimalField(
        label=_('Their weight (kg)'), max_digits=12, decimal_places=4, min_value=Decimal('0.0001'), required=False,
        localize=True, widget=forms.TextInput(attrs=DECIMAL))
    avg_weight_g = forms.DecimalField(
        label=_('Average weight (g)'), max_digits=12, decimal_places=4, min_value=Decimal('0.0001'), required=False,
        localize=True, widget=forms.TextInput(attrs=DECIMAL),
        help_text=_('Or, instead of a sample, the average weight as measured.'))

    field_order = ['batch', 'date', 'sample_count', 'sample_weight_kg', 'avg_weight_g', 'notes']
    refresh_on = ('batch', 'date', 'sample_count', 'sample_weight_kg', 'avg_weight_g')

    def clean(self):
        cleaned = super().clean()
        count, kilos, average = (cleaned.get(name) for name in ('sample_count', 'sample_weight_kg', 'avg_weight_g'))
        if any(name in self.errors for name in ('sample_count', 'sample_weight_kg', 'avg_weight_g')):
            return cleaned
        if average is not None and (count is not None or kilos is not None):
            self.add_error('avg_weight_g', _('Give the average or the sample, not both.'))
        elif average is None and (count is None) != (kilos is None):
            self.add_error('sample_weight_kg' if kilos is None else 'sample_count',
                           _('A sample is the number of fish weighed and their weight together.'))
        elif average is None and count is None:
            self.add_error('sample_count', _('Give the sample, or the average weight.'))
        return cleaned

    def save(self, user, rows=None):
        data = self.cleaned_data
        return services.record_weighing(
            user, unit=self.unit, batch=data['batch'], day=data['date'], avg_weight_g=data['avg_weight_g'],
            sample_count=data['sample_count'], sample_weight_kg=data['sample_weight_kg'], notes=data['notes'],
            token=data['token'])


class SpeciesChoice(forms.ModelChoiceField):
    def label_from_instance(self, species):
        return f'{species.local_name or species.common_name} ({species.code})'


class SupplierChoice(forms.ModelChoiceField):
    """The suppliers of live fish and eggs (the link's limit_choices_to), with the status of those not active."""

    def label_from_instance(self, supplier):
        if supplier.status == Supplier.Status.ACTIVE:
            return str(supplier)
        return f'{supplier} · {supplier.get_status_display()}'


class BatchInputForm(Acknowledged, ServiceErrors, forms.ModelForm):
    """A new batch: who the fish are and where they come from, how many arrive at what average weight;
    the units they go into are rows below it (InputLineFormSet), whose fish must add up to the fish
    arriving (the source never checked, STK-05)."""

    token = forms.UUIDField(widget=forms.HiddenInput)
    species = SpeciesChoice(label=_('Species'), queryset=Species.objects.filter(status__in=services.STOCKABLE_SPECIES))
    count = forms.IntegerField(label=_('Fish arriving'), min_value=1)
    avg_weight_g = forms.DecimalField(
        label=_('Average weight (g)'), max_digits=12, decimal_places=4, min_value=Decimal('0.0001'), localize=True,
        widget=forms.TextInput(attrs=DECIMAL), help_text=_('As weighed on arrival; to 0.0001 g for eggs and larvae.'))
    over_capacity_ack = acknowledgement()

    service_fields = {'date': 'input_date', 'unit': NON_FIELD_ERRORS, 'batch': NON_FIELD_ERRORS,
                      'count': NON_FIELD_ERRORS}

    class Meta:
        model = Batch
        fields = ['species', 'input_stage', 'origin', 'supplier', 'supplier_batch_ref', 'strain', 'name',
                  'input_date', 'expected_harvest_date', 'notes']
        field_classes = {'supplier': SupplierChoice}
        widgets = {'input_date': DATE, 'expected_harvest_date': DATE, 'notes': NOTES}
        help_texts = {
            'supplier': _('Who sold the fish: a supplier of live fish and eggs (Purchasing › Suppliers); none for '
                          'the own hatchery or wild-caught fish.'),
            'strain': _('E.g. AquaGen, SalmoBreed.'),
            'name': _('Optional; the batch number is given on saving.'),
        }

    field_order = ['species', 'input_stage', 'input_date', 'count', 'avg_weight_g', 'origin', 'supplier',
                   'supplier_batch_ref', 'strain', 'name', 'expected_harvest_date', 'notes', 'over_capacity_ack']

    def __init__(self, *args, unit=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['input_stage'].initial = InputStage.FRY
        self.fields['origin'].initial = Origin.PURCHASED
        self.fields['input_date'].initial = services.local_today(unit)
        self.fields['token'].initial = uuid.uuid4()
        self.fields['supplier'].empty_label = _('None')

    def clean(self):
        cleaned = super().clean()
        purchased = cleaned.get('origin') == Origin.PURCHASED
        if purchased and not cleaned.get('supplier') and 'supplier' not in self.errors:
            self.add_error('supplier', _('Who sold the fish?'))
        elif 'origin' in cleaned and not purchased:
            if cleaned.get('supplier'):
                self.add_error('supplier', _('Only bought fish have a supplier.'))
            if cleaned.get('supplier_batch_ref', '').strip():
                self.add_error('supplier_batch_ref', _('Only bought fish have a supplier.'))
        return cleaned

    def save(self, user, lines):
        data = self.cleaned_data
        return services.record_input(
            user, species=data['species'], input_stage=data['input_stage'], origin=data['origin'],
            day=data['input_date'], lines=[(unit, count, data['avg_weight_g']) for unit, count in lines],
            supplier=data['supplier'], supplier_batch_ref=data['supplier_batch_ref'].strip(),
            strain=data['strain'].strip(), name=data['name'].strip(),
            expected_harvest_date=data['expected_harvest_date'], notes=data['notes'],
            ack=data['over_capacity_ack'], token=data['token'])


class UnitChoice(forms.ModelChoiceField):
    def __init__(self, *args, labels=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.labels = labels or {}

    def label_from_instance(self, unit):
        return self.labels.get(unit.pk, unit.code)


class InputLineForm(forms.Form):
    """A unit the new batch goes into and how many of its fish."""

    unit = UnitChoice(label=_('Unit'), queryset=Tank.objects.none())
    count = forms.IntegerField(label=_('Fish'), min_value=1)

    def __init__(self, *args, units=None, labels=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['unit'].queryset = units if units is not None else Tank.objects.none()
        self.fields['unit'].labels = labels or {}


InputLineFormSet = forms.formset_factory(InputLineForm, extra=0, min_num=1, validate_min=True, max_num=20,
                                         validate_max=True)


def stockable_units():
    """The units fish can go into: those whose status takes fish."""
    return (Tank.objects.filter(status__in=ARRIVAL_STATUSES)
            .select_related('production_department__site').order_by('code'))


class LegForm(InputLineForm):
    """A unit fish move into and how many."""


class OutputForm(InputLineForm):
    """A size class of a grading: the unit it goes into, its fish and their measured average."""

    avg_weight_g = forms.DecimalField(label=_('Average weight (g)'), max_digits=12, decimal_places=4,
                                      min_value=Decimal('0.0001'), localize=True, widget=forms.TextInput(attrs=DECIMAL))
    size_class = forms.CharField(label=_('Size class'), max_length=30, required=False,
                                 widget=forms.TextInput(attrs={'placeholder': _('e.g. Large, > 250 g')}))


LegFormSet = forms.formset_factory(LegForm, extra=0, min_num=1, validate_min=True, max_num=12, validate_max=True)
OutputFormSet = forms.formset_factory(OutputForm, extra=0, min_num=1, validate_min=True, max_num=12,
                                      validate_max=True)


def kept_rows(formset):
    """The cleaned rows that name a unit (a row added and left blank is dropped)."""
    return [row.cleaned_data for row in formset.forms if row.cleaned_data and row.cleaned_data.get('unit')]


class TransferForm(Acknowledged, OperationForm):
    """Fish of one batch moved to one or several units (a split is a transfer into several). They leave at
    the batch's average in this unit and keep their batch."""

    reason = forms.ChoiceField(label=_('Reason'), choices=TransferReason.choices, initial=TransferReason.DENSITY)
    over_capacity_ack = acknowledgement()

    rows = LegFormSet
    rows_label = _('To units')
    field_order = ['batch', 'date', 'reason', 'notes', 'over_capacity_ack']

    def save(self, user, rows):
        data = self.cleaned_data
        return services.record_transfer(
            user, source=self.unit, batch=data['batch'], day=data['date'],
            legs=[(row['unit'], row['count']) for row in rows], reason=data['reason'], notes=data['notes'],
            ack=data['over_capacity_ack'], token=data['token'])


class GradingForm(Acknowledged, OperationForm):
    """The fish of one batch graded by size into other units, each size class with its measured average;
    the fish that stay are weighed too."""

    remainder_avg_weight_g = forms.DecimalField(
        label=_('Average weight of the fish that stay (g)'), max_digits=12, decimal_places=4,
        min_value=Decimal('0.0001'), required=False, localize=True, widget=forms.TextInput(attrs=DECIMAL),
        help_text=_('Required when fish stay in this unit: the grading weighs them too.'))
    over_capacity_ack = acknowledgement()

    service_fields = {**OperationForm.service_fields, 'avg_weight_g': 'remainder_avg_weight_g'}
    rows = OutputFormSet
    rows_label = _('Size classes')
    field_order = ['batch', 'date', 'remainder_avg_weight_g', 'notes', 'over_capacity_ack']

    def save(self, user, rows):
        data = self.cleaned_data
        return services.record_grading(
            user, source=self.unit, batch=data['batch'], day=data['date'],
            outputs=[(row['unit'], row['count'], row['avg_weight_g'], row['size_class'].strip()) for row in rows],
            remainder_avg_weight_g=data['remainder_avg_weight_g'], notes=data['notes'],
            ack=data['over_capacity_ack'], token=data['token'])


class HarvestForm(OperationForm):
    """Fish harvested: their count and their weighed kilos."""

    count = forms.IntegerField(label=_('Fish harvested'), min_value=1)
    measured_weight_kg = forms.DecimalField(
        label=_('Weighed (kg)'), max_digits=14, decimal_places=3, min_value=Decimal('0.001'), localize=True,
        widget=forms.TextInput(attrs=DECIMAL),
        help_text=_('Their weight as weighed at the harvest. The stock takes the fish out at their book weight; '
                    'the difference is shown on the operation.'))
    everything = forms.BooleanField(
        label=_('This empties the unit of this batch'), required=False,
        help_text=_('Fish the book still holds beyond the count are then recorded as an unaccounted loss.'))

    field_order = ['batch', 'date', 'count', 'measured_weight_kg', 'everything', 'notes']

    def save(self, user, rows=None):
        data = self.cleaned_data
        return services.record_harvest(
            user, unit=self.unit, batch=data['batch'], day=data['date'], count=data['count'],
            measured_weight_kg=data['measured_weight_kg'], everything=data['everything'], notes=data['notes'],
            token=data['token'])


class VoidForm(ServiceErrors, forms.Form):
    reason = forms.CharField(label=_('Reason for voiding'), max_length=500, widget=forms.Textarea(attrs={'rows': 3}),
                             help_text=_('E.g. “typed 1000 instead of 100”. The operation stays in the history, '
                                         'struck through, with this reason.'))

    service_fields = {}
