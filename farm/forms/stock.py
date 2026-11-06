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

from ..handling import check
from ..models import Batch, HandlingPlanItem, HealthEvent, SlaughterFacility, Species, Supplier, Tank
from ..models.handling import HandlingKind
from ..models.harvest import offered_facilities
from ..models.stock import (
    ARRIVAL_STATUSES, PROVENANCE_OF_ORIGIN, CullReason, InputStage, MortalityCause, Origin, TransferReason,
)
from ..models.supplier import SupplyCategory
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


class AcknowledgeInput(forms.CheckboxInput):
    """The box that acknowledges the handling warnings shown (farm/handling/check.py). Its value is the
    warnings' fingerprint, so a save whose warnings changed meanwhile is not taken as acknowledged; it shows
    ticked only when what was posted is what is shown now."""

    fingerprint = ''

    def get_context(self, name, value, attrs):
        if value and value == self.fingerprint:
            attrs = {**(attrs or {}), 'checked': True}
        return super(forms.CheckboxInput, self).get_context(name, self.fingerprint, attrs)

    def value_from_datadict(self, data, files, name):
        return data.get(name, '')


def handling_ack_field(kind):
    """The box to go on past the handling warnings shown; its value is their fingerprint (AcknowledgeInput). Only a
    harvest can be warned of a medicine withdrawal, so only its box says that fish under one must not go to food."""
    stored = _('Going on is stored with what is shown here and logged as critical.')
    if kind == HandlingKind.HARVEST:
        stored = _('Fish under a medicine withdrawal must not go to food. Going on is stored with what is shown '
                   'here and logged as critical.')
    return forms.CharField(label=_('Go on despite these warnings'), required=False, widget=AcknowledgeInput,
                           help_text=stored)


class HandlingChecked:
    """A dialog whose save runs the handling check (a harvest, a transfer, a grading): the panel shows what the
    check finds for the date and batch of the form (`handling`), and, with warnings, the box to go on past
    them, which the service reads (`handling_ack`)."""

    handling_kind = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['handling_ack'] = handling_ack_field(self.handling_kind)
        self._handling = None

    @property
    def handling(self):
        """The check for the form's date and batch as entered (else as offered): farm.handling.check.assess."""
        if self._handling is None:
            data = getattr(self, 'cleaned_data', {})
            day = data.get('date') or self.initial.get('date') or self.fields['date'].initial
            batch = data.get('batch')
            if batch is None:
                share = self.present.get(str(self.initial.get('batch', ''))) or self.only_batch
                batch = share.batch if share is not None else None
            self._handling = check.assess(self.handling_kind, self.unit, day, batch)
            self.fields['handling_ack'].widget.fingerprint = self._handling.fingerprint
        return self._handling


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

    def __init__(self, *args, unit, present, events=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.unit = unit
        if 'health_event' in self.fields:
            # The health events the deaths may belong to (`events`), for people who may read them; else none.
            if events is None:
                del self.fields['health_event']
            else:
                self.fields['health_event'].queryset = events
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


class EventChoice(forms.ModelChoiceField):
    """A health event in a list: what and when, and its site."""

    def label_from_instance(self, event):
        return f'{event} · {event.site}'


def event_field():
    return EventChoice(label=_('Health event'), queryset=HealthEvent.objects.none(), required=False,
                       help_text=_('Optional: the health event (Operations › Health events) these fish died or were '
                                   'culled under; it counts them.'))


class MortalityForm(OperationForm):
    count = forms.IntegerField(label=_('Dead fish'), min_value=1)
    cause = forms.ChoiceField(label=_('Cause'), choices=MortalityCause.choices, initial=MortalityCause.UNKNOWN)
    measured_weight_kg = forms.DecimalField(
        label=_('Weight of the dead fish (kg)'), max_digits=14, decimal_places=3, min_value=Decimal('0.001'),
        required=False, localize=True, widget=forms.TextInput(attrs=DECIMAL),
        help_text=_('Optional, when they were weighed. The stock takes them out at the average weight of the '
                    'batch in this unit; the weighed figure is kept beside it.'))
    health_event = event_field()

    field_order = ['batch', 'date', 'count', 'cause', 'measured_weight_kg', 'health_event', 'notes']

    def save(self, user, rows=None):
        data = self.cleaned_data
        return services.record_mortality(
            user, unit=self.unit, batch=data['batch'], day=data['date'], count=data['count'], cause=data['cause'],
            measured_weight_kg=data['measured_weight_kg'], notes=data['notes'],
            health_event=data.get('health_event'), token=data['token'])


class CullForm(OperationForm):
    count = forms.IntegerField(label=_('Culled fish'), min_value=1)
    reason = forms.ChoiceField(label=_('Reason'), choices=CullReason.choices, initial=CullReason.GRADING)
    health_event = event_field()

    field_order = ['batch', 'date', 'count', 'reason', 'health_event', 'notes']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # A cleaner fish's reasons are Mattilsynet's causes, a production fish's the others (services.cull_reasons);
        # with both in the unit, each list under its own heading.
        groups = {}
        for share in self.present.values():
            groups[share.batch.species.is_cleaner_fish] = services.cull_reasons(share.batch)
        field = self.fields['reason']
        if len(groups) == 1:
            reasons, = groups.values()
            field.choices = [(reason.value, reason.label) for reason in reasons]
            if field.initial not in [reason.value for reason in reasons]:
                field.initial = None
        elif groups:
            field.choices = [('', '---------')] + [
                (heading, [(reason.value, reason.label) for reason in groups[cleaner]])
                for cleaner, heading in ((False, _('Production fish')), (True, _('Cleaner fish')))]
            field.initial = None

    def save(self, user, rows=None):
        data = self.cleaned_data
        return services.record_cull(
            user, unit=self.unit, batch=data['batch'], day=data['date'], count=data['count'], reason=data['reason'],
            notes=data['notes'], health_event=data.get('health_event'), token=data['token'])


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
        fields = ['species', 'input_stage', 'origin', 'provenance', 'supplier', 'supplier_batch_ref', 'strain',
                  'year_class', 'name', 'input_date', 'expected_harvest_date', 'notes']
        field_classes = {'supplier': SupplierChoice}
        widgets = {'input_date': DATE, 'expected_harvest_date': DATE, 'notes': NOTES}
        help_texts = {
            'supplier': _('Who sold the fish: a supplier of live fish and eggs (Purchasing › Suppliers); none for '
                          'the own hatchery or wild-caught fish.'),
            'strain': _('E.g. AquaGen, SalmoBreed.'),
            'provenance': _('For bought fish: farmed, or caught in the wild. Required for cleaner fish (their report '
                            'asks it); the own hatchery’s fish are farmed, the farm’s catch wild-caught.'),
            'year_class': _('The year class (årsklasse) the reports give, e.g. 2026. Whether it is the hatch year or '
                            'the year the fish went to sea is not confirmed with the authorities: enter it as the '
                            'farm counts it.'),
            'name': _('Optional; the batch number is given on saving.'),
        }

    field_order = ['species', 'input_stage', 'input_date', 'count', 'avg_weight_g', 'origin', 'provenance',
                   'supplier', 'supplier_batch_ref', 'strain', 'year_class', 'name', 'expected_harvest_date', 'notes',
                   'over_capacity_ack']

    def __init__(self, *args, unit=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['input_stage'].initial = InputStage.FRY
        self.fields['origin'].initial = Origin.PURCHASED
        self.fields['input_date'].initial = services.local_today(unit)
        self.fields['token'].initial = uuid.uuid4()
        self.fields['supplier'].empty_label = _('None')
        self.fields['provenance'].choices = [('', _('Not given')), *self.fields['provenance'].choices[1:]]

    def clean(self):
        cleaned = super().clean()
        origin = cleaned.get('origin')
        said = PROVENANCE_OF_ORIGIN.get(origin)
        if said is not None:
            # The origin says it: the person need not, and may not say otherwise.
            if cleaned.get('provenance') not in ('', said):
                self.add_error('provenance', _('Fish of the own hatchery are farmed, fish caught in the wild '
                                               'wild-caught.'))
            else:
                cleaned['provenance'] = said
        species = cleaned.get('species')
        if (species is not None and species.is_cleaner_fish and origin == Origin.PURCHASED
                and not cleaned.get('provenance') and 'provenance' not in self.errors):
            self.add_error('provenance', _('Farmed or wild-caught? The cleaner-fish report asks it of every cleaner '
                                           'fish.'))
        purchased = origin == Origin.PURCHASED
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
            provenance=data['provenance'], year_class=data['year_class'], ack=data['over_capacity_ack'],
            token=data['token'])


class OpeningBalanceForm(BatchInputForm):
    """An opening balance (services.record_opening_balance): a batch the farm already had when it started using the
    platform, as on the takeover day (its fish, their average weight, the units they are in), with the real stocking date
    (beyond the correction window by design), the year class and the document the counts come from."""

    day = forms.DateField(label=_('Takeover day'), widget=DATE,
                          help_text=_('The day the counts and the average weight are of: inside the correction window, '
                                      'like every record.'))
    document = forms.CharField(label=_('Source document'), max_length=300,
                               help_text=_('Where the counts come from: the old system’s export, a count sheet, a '
                                           'delivery note.'))

    service_fields = {'date': 'day', 'stocked_on': 'input_date', 'unit': NON_FIELD_ERRORS, 'batch': NON_FIELD_ERRORS,
                      'count': NON_FIELD_ERRORS}
    field_order = ['species', 'input_stage', 'input_date', 'year_class', 'day', 'count', 'avg_weight_g', 'document',
                   'origin', 'provenance', 'supplier', 'supplier_batch_ref', 'strain', 'name', 'expected_harvest_date',
                   'notes', 'over_capacity_ack']

    def __init__(self, *args, unit=None, **kwargs):
        super().__init__(*args, unit=unit, **kwargs)
        self.fields['input_date'].label = _('Stocked on (the real date)')
        self.fields['input_date'].help_text = _('The day the fish were stocked, however long ago: their days stocked count '
                                                'from it.')
        self.fields['input_date'].initial = None
        self.fields['day'].initial = services.local_today(unit)
        self.fields['year_class'].required = True
        self.fields['count'].label = _('Fish on the takeover day')
        self.fields['avg_weight_g'].help_text = _('Their average on the takeover day; to 0.0001 g for eggs and larvae.')
        self.order_fields(self.field_order)

    def save(self, user, lines):
        data = self.cleaned_data
        return services.record_opening_balance(
            user, species=data['species'], input_stage=data['input_stage'], origin=data['origin'],
            stocked_on=data['input_date'], day=data['day'], year_class=data['year_class'], document=data['document'],
            lines=[(unit, count, data['avg_weight_g']) for unit, count in lines],
            supplier=data['supplier'], supplier_batch_ref=data['supplier_batch_ref'].strip(),
            strain=data['strain'].strip(), name=data['name'].strip(),
            expected_harvest_date=data['expected_harvest_date'], notes=data['notes'],
            provenance=data['provenance'], ack=data['over_capacity_ack'], token=data['token'])


class BatchDetailsForm(ServiceErrors, forms.ModelForm):
    """The year class and whether the fish are farmed or wild-caught of a batch stocked without them
    (farm/stock/services.py `correct_batch`)."""

    service_fields = {'batch': NON_FIELD_ERRORS}

    class Meta:
        model = Batch
        fields = ['year_class', 'provenance']
        help_texts = {field: BatchInputForm.Meta.help_texts[field] for field in ('year_class', 'provenance')}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['provenance'].choices = [('', _('Not given')), *self.fields['provenance'].choices[1:]]

    def save(self, user):
        return services.correct_batch(user, batch=self.instance, year_class=self.cleaned_data['year_class'],
                                      provenance=self.cleaned_data['provenance'])


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


class PlannedForm:
    """A dialog that can fulfil a plan (Operations › Harvest › Harvest plan): the plan's id travels hidden, and
    the service links the operation to it."""

    plan_kind = None

    def __init__(self, *args, plan=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.plan = plan
        self.fields['plan_item'] = forms.ModelChoiceField(
            queryset=HandlingPlanItem.objects.filter(kind=self.plan_kind, unit=self.unit), required=False,
            widget=forms.HiddenInput)
        if plan is not None:
            # Recorded on the planned day, or today when it is done before it.
            self.initial.update({'plan_item': plan.pk, 'batch': str(plan.batch_id),
                                 'date': min(plan.date, self.fields['date'].initial)})


class TransferForm(PlannedForm, HandlingChecked, Acknowledged, OperationForm):
    """Fish of one batch moved to one or several units (a split is a transfer into several). They leave at
    the batch's average in this unit and keep their batch. A transfer is a transport: the handling check
    runs its rule."""

    reason = forms.ChoiceField(label=_('Reason'), choices=TransferReason.choices, initial=TransferReason.DENSITY)
    over_capacity_ack = acknowledgement()

    handling_kind = HandlingKind.TRANSPORT
    plan_kind = HandlingPlanItem.Kind.TRANSPORT
    service_fields = {**OperationForm.service_fields, 'plan_item': NON_FIELD_ERRORS}
    rows = LegFormSet
    rows_label = _('To units')
    field_order = ['batch', 'date', 'reason', 'notes', 'over_capacity_ack']

    def save(self, user, rows):
        data = self.cleaned_data
        return services.record_transfer(
            user, source=self.unit, batch=data['batch'], day=data['date'],
            legs=[(row['unit'], row['count']) for row in rows], reason=data['reason'], notes=data['notes'],
            ack=data['over_capacity_ack'], handling_ack=data['handling_ack'], plan_item=data['plan_item'],
            token=data['token'])


class GradingForm(HandlingChecked, Acknowledged, OperationForm):
    """The fish of one batch graded by size into other units, each size class with its measured average;
    the fish that stay are weighed too. A grading moves the fish: the handling check takes the longer of
    the grading and the transport rules."""

    remainder_avg_weight_g = forms.DecimalField(
        label=_('Average weight of the fish that stay (g)'), max_digits=12, decimal_places=4,
        min_value=Decimal('0.0001'), required=False, localize=True, widget=forms.TextInput(attrs=DECIMAL),
        help_text=_('Required when fish stay in this unit: the grading weighs them too.'))
    over_capacity_ack = acknowledgement()

    handling_kind = HandlingKind.GRADING
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
            ack=data['over_capacity_ack'], handling_ack=data['handling_ack'], token=data['token'])


class TransportChoice(forms.ModelChoiceField):
    """The suppliers of wellboat and transport, with the status of those not active."""

    def label_from_instance(self, supplier):
        if supplier.status == Supplier.Status.ACTIVE:
            return str(supplier)
        return f'{supplier} · {supplier.get_status_display()}'


def transport_suppliers():
    return Supplier.objects.filter(supplies__contains=[SupplyCategory.TRANSPORT]).order_by('name')


class HarvestForm(PlannedForm, HandlingChecked, OperationForm):
    """Fish harvested: their count and their round (live) kilos as weighed, and where they went: the
    slaughter facility, and who carried them."""

    count = forms.IntegerField(label=_('Fish harvested'), min_value=1)
    measured_weight_kg = forms.DecimalField(
        label=_('Round weight (kg)'), max_digits=14, decimal_places=3, min_value=Decimal('0.001'), localize=True,
        widget=forms.TextInput(attrs=DECIMAL),
        help_text=_('The live weight as weighed at the harvest, before bleeding and gutting. The stock takes the '
                    'fish out at their book weight; the difference is shown with the harvest.'))
    everything = forms.BooleanField(
        label=_('This empties the unit of this batch'), required=False,
        help_text=_('Fish the book still holds beyond the count are then recorded as an unaccounted loss.'))
    facility = forms.ModelChoiceField(
        label=_('Slaughter facility'), queryset=SlaughterFacility.objects.none(),
        help_text=_('Where the fish go: an active facility that takes this species (Harvest and logistics › '
                    'Slaughter facilities).'))
    transport = TransportChoice(label=_('Transport'), queryset=Supplier.objects.none(), required=False,
                                help_text=_('Optional: the wellboat or haulage company that carries them.'))
    vessel = forms.CharField(label=_('Wellboat or vehicle'), max_length=100, required=False,
                             widget=forms.TextInput(attrs={'placeholder': _('e.g. MS Ronja Harvest')}))

    handling_kind = HandlingKind.HARVEST
    plan_kind = HandlingPlanItem.Kind.HARVEST
    service_fields = {**OperationForm.service_fields, 'plan_item': NON_FIELD_ERRORS}
    field_order = ['batch', 'date', 'count', 'measured_weight_kg', 'everything', 'facility', 'transport', 'vessel',
                   'notes']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        species = next(iter(self.present.values())).batch.species if self.present else None
        self.fields['facility'].queryset = offered_facilities(species)
        self.fields['facility'].empty_label = _('Select a slaughter facility')
        self.fields['transport'].queryset = transport_suppliers()
        self.fields['transport'].empty_label = _('None')
        if self.plan is not None:
            self.initial.update({'count': self.plan.planned_count, 'facility': self.plan.facility_id,
                                 'transport': self.plan.transport_id, 'vessel': self.plan.vessel})

    def save(self, user, rows=None):
        data = self.cleaned_data
        return services.record_harvest(
            user, unit=self.unit, batch=data['batch'], day=data['date'], count=data['count'],
            measured_weight_kg=data['measured_weight_kg'], facility=data['facility'], transport=data['transport'],
            vessel=data['vessel'], everything=data['everything'], notes=data['notes'],
            handling_ack=data['handling_ack'], plan_item=data['plan_item'], token=data['token'])


class EscapeForm(OperationForm):
    """Fish that escaped, or are suspected to have: how many (an estimate when only suspected), the cause, when it was
    found, their health status and the fish caught again so far. The fish leave the book at the batch's average;
    Fiskeridirektoratet's notice is started from the escape (Production › Reports)."""

    count = forms.IntegerField(label=_('Fish escaped'), min_value=1)
    suspected = forms.BooleanField(
        label=_('Only suspected'), required=False,
        help_text=_('Tick it when an escape is suspected but not confirmed: the number is then an estimate.'))
    found_time = forms.TimeField(label=_('Time found'), required=False, widget=forms.TimeInput(
        attrs={'type': 'time'}, format='%H:%M'), help_text=_('Optional, on the site’s clock.'))
    cause = forms.CharField(label=_('Cause'), max_length=2000, widget=NOTES,
                            help_text=_('What caused it, or what is thought to have.'))
    health_status = forms.CharField(label=_('Health status of the fish'), max_length=1000, required=False,
                                    help_text=_('Optional: their state of health, e.g. treated or free of disease.'))
    recaptured = forms.IntegerField(label=_('Fish recaptured'), min_value=0, required=False,
                                    help_text=_('Optional: the fish caught again so far.'))

    field_order = ['batch', 'date', 'count', 'suspected', 'found_time', 'cause', 'health_status', 'recaptured', 'notes']

    def save(self, user, rows=None):
        data = self.cleaned_data
        return services.record_escape(
            user, unit=self.unit, batch=data['batch'], day=data['date'], count=data['count'], cause=data['cause'],
            suspected=data['suspected'], found_time=data['found_time'], health_status=data['health_status'],
            recaptured=data['recaptured'], notes=data['notes'], token=data['token'])


class DeliveryForm(HandlingChecked, OperationForm):
    """Live fish delivered out of the company, to whom and where. Moving fish alive is a transport: the handling check
    runs (a medicine withdrawal in force, a fast too short)."""

    count = forms.IntegerField(label=_('Fish delivered'), min_value=1)
    measured_weight_kg = forms.DecimalField(
        label=_('Weight of the fish (kg)'), max_digits=14, decimal_places=3, min_value=Decimal('0.001'),
        required=False, localize=True, widget=forms.TextInput(attrs=DECIMAL),
        help_text=_('Optional, when they were weighed. The stock takes them out at the average weight of the batch in '
                    'this unit; the weighed figure is kept beside it.'))
    destination = forms.CharField(label=_('Delivered to'), max_length=200,
                                  help_text=_('Who received them: the customer or the receiving site.'))
    destination_site_number = forms.IntegerField(
        label=_('Receiving site’s lokalitetsnummer'), min_value=10000, max_value=99999, required=False,
        help_text=_('Optional: the receiving site’s locality number (5 digits).'))

    handling_kind = HandlingKind.TRANSPORT
    field_order = ['batch', 'date', 'count', 'measured_weight_kg', 'destination', 'destination_site_number', 'notes']

    def save(self, user, rows=None):
        data = self.cleaned_data
        return services.record_delivery(
            user, unit=self.unit, batch=data['batch'], day=data['date'], count=data['count'],
            destination=data['destination'], destination_site_number=data['destination_site_number'],
            measured_weight_kg=data['measured_weight_kg'], handling_ack=data['handling_ack'], notes=data['notes'],
            token=data['token'])


class VoidForm(ServiceErrors, forms.Form):
    reason = forms.CharField(label=_('Reason for voiding'), max_length=500, widget=forms.Textarea(attrs={'rows': 3}),
                             help_text=_('E.g. “typed 1000 instead of 100”. The operation stays in the history, '
                                         'struck through, with this reason.'))

    service_fields = {}
