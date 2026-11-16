"""The forms of Operations › Feeding › Protocols and Assignments: a protocol's general fields (a tab of core.crud), its
feeding table (a grid of bands by temperature columns, saved whole by farm/feeding/protocols.py) and the assignment
dialogs (several units at once on create, one row on edit)."""
from datetime import timedelta
from decimal import Decimal, InvalidOperation


from django import forms
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db.models import Sum
from django.utils.translation import gettext_lazy as _, ngettext

from core.crud import DRAFT, CodedFormMixin, TabbedForm, tab_fields
from core.widgets import DayInput

from ..feeding import assignments
from ..models import Batch, Feed, FeedingProtocol, ProtocolAssignment, ProtocolBand, Species, StockMovement, Tank
from ..models.feeding_protocol import MAX_SFR, TEMPERATURE, ProtocolStatus
from ..stock.dates import earliest, local_today, too_old

DECIMAL = {'inputmode': 'decimal'}
MAX_COLUMNS = 12      # temperature columns a table can have: what a screen shows side by side
MAX_BANDS = 30

PROTOCOL_TABS = [('general', _('General'), ['name', 'species', 'status', 'expected_fcr', 'notes'])]


class ProtocolForm(CodedFormMixin, TabbedForm):
    """A protocol's general fields. Its feeding table is a tab of its own, saved as a whole (ProtocolTableForm). Once
    it is assigned, its species and expected FCR are fixed and it cannot go back to draft (the model says why)."""

    tabs = PROTOCOL_TABS

    class Meta:
        model = FeedingProtocol
        fields = tab_fields(PROTOCOL_TABS)
        localized_fields = ['expected_fcr']
        widgets = {'expected_fcr': forms.TextInput(attrs=DECIMAL), 'notes': forms.Textarea(attrs={'rows': 3}),
                   'name': forms.TextInput(attrs={'placeholder': _('e.g. Rainbow trout grow-out, RAS')})}
        help_texts = {
            'species': _('The species the table is for: it is assigned only to fish of this species.'),
            'status': _('Draft: being built. Active: can be assigned. Retired: kept for the days it fed, assigned no '
                        'more.'),
            'expected_fcr': _('The kg of feed per kg of growth the table expects; a band may have its own. The '
                              'estimated weight between weighings grows by the feed divided by it.'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['species'].queryset = Species.objects.order_by('common_name')
        self.fields['species'].empty_label = _('Select a species')
        if self.instance.is_assigned():
            for name in ('species', 'expected_fcr'):
                self.fields[name].disabled = True
                self.fields[name].help_text = _('Fixed: the protocol is assigned. Duplicate it to change it.')
            self.fields['status'].choices = [choice for choice in ProtocolStatus.choices
                                             if choice[0] != ProtocolStatus.DRAFT]
        elif self.instance._state.adding:
            self.fields['status'].choices = [(ProtocolStatus.DRAFT, ProtocolStatus.DRAFT.label)]
            self.fields['status'].help_text = _('A new protocol is a draft: fill in its feeding table, then set it '
                                                'active.')


# ---- the feeding table --------------------------------------------------------------------------------------
def column_name(temperature):
    """The SFR field of a temperature column: sfr_120 for 12.0 °C, sfr_m25 for −2.5 °C (a column keeps its values
    when others are added or taken away)."""
    tenths = int(temperature * 10)
    return f'sfr_{"m" if tenths < 0 else ""}{abs(tenths)}'


def parse_temperatures(text):
    """The temperature columns typed as "4 8 12 16" (a decimal comma or point), in order; ValidationError otherwise."""
    values = []
    for word in text.replace(';', ' ').split():
        try:
            value = Decimal(word.replace(',', '.'))
        except InvalidOperation:
            raise ValidationError(_('“%(value)s” is not a temperature.') % {'value': word}) from None
        if not value.is_finite() or value != value.quantize(Decimal('0.1')):
            raise ValidationError(_('A temperature column has at most one decimal: %(value)s.') % {'value': word})
        if not TEMPERATURE.low <= value <= TEMPERATURE.high:
            raise ValidationError(_('A temperature column is between %(low)s and %(high)s °C.') % {
                'low': TEMPERATURE.low, 'high': TEMPERATURE.high})
        values.append(value.quantize(Decimal('0.1')))
    if len(values) < 2:
        # One column gave an SFR at exactly its temperature and none on every other day (no extrapolation, Q1; F-080).
        raise ValidationError(_('Give at least two temperature columns: the SFR is read between them, never outside '
                                'them.'))
    if len(set(values)) != len(values):
        raise ValidationError(_('Each temperature is a column once.'))
    if len(values) > MAX_COLUMNS:
        raise ValidationError(_('A table has at most %(count)d temperature columns.') % {'count': MAX_COLUMNS})
    return sorted(values)


def shown_temperatures(values):
    return ' '.join(f'{value.normalize():f}' if value % 1 == 0 else f'{value:f}' for value in values)


class ProtocolTableForm(forms.Form):
    """The temperature columns of the table and the protocol's version (two people saving it at once: the second is
    told). Changing the columns renders the grid again with the bands entered so far (data-refresh)."""

    version = forms.IntegerField(widget=forms.HiddenInput)
    temperatures = forms.CharField(
        label=_('Temperature columns (°C)'), max_length=200,
        widget=forms.TextInput(attrs={'data-refresh': DRAFT, 'placeholder': _('e.g. 4 8 12 16')}),
        help_text=_('Separated by spaces. A temperature between two columns is read in between them; outside the '
                    'first and the last there is no ration.'))

    def clean_temperatures(self):
        return parse_temperatures(self.cleaned_data['temperatures'])


class BandRowForm(forms.ModelForm):
    """A band of the table: its weights, feed, meals, expected FCR and one SFR per temperature column."""

    class Meta:
        model = ProtocolBand
        fields = ['min_weight_g', 'max_weight_g', 'feed', 'meals_per_day', 'expected_fcr']
        localized_fields = ['min_weight_g', 'max_weight_g', 'expected_fcr']
        widgets = {'min_weight_g': forms.TextInput(attrs=DECIMAL), 'max_weight_g': forms.TextInput(attrs=DECIMAL),
                   'expected_fcr': forms.TextInput(attrs={**DECIMAL, 'placeholder': _('protocol’s')}),
                   'meals_per_day': forms.TextInput(attrs={'inputmode': 'numeric'})}

    def __init__(self, *args, columns=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.columns = list(columns)
        feed = self.fields['feed']
        feed.queryset = Feed.objects.filter(status=Feed.Status.ACTIVE).order_by('name')
        feed.empty_label = _('Select a feed')
        feed.error_messages['invalid_choice'] = _('Choose an active feed.')
        for temperature in self.columns:
            self.fields[column_name(temperature)] = forms.DecimalField(
                label=_('%(temperature)s °C') % {'temperature': shown_temperatures([temperature])},
                max_digits=5, decimal_places=3, min_value=0, max_value=MAX_SFR, localize=True,
                widget=forms.TextInput(attrs=DECIMAL))

    def validate_constraints(self, *args, **kwargs):
        # The rules between the bands (one start each, no overlap, no gap) span the table, which is saved as a whole
        # replace: the formset checks them and the database's constraints back them up.
        pass

    @property
    def cells(self):
        return [self[column_name(temperature)] for temperature in self.columns]

    @property
    def base_fields_shown(self):
        return [self[name] for name in self._meta.fields]


class BaseBandFormSet(forms.BaseFormSet):
    def __init__(self, *args, columns=(), **kwargs):
        super().__init__(*args, form_kwargs={'columns': columns}, **kwargs)
        self.columns = columns

    def kept(self):
        """The cleaned bands to keep, in weight order."""
        rows = [form.cleaned_data for form in self.forms
                if form.cleaned_data and not form.cleaned_data.get('DELETE')]
        return sorted(rows, key=lambda row: row['min_weight_g'])

    def clean(self):
        if any(self.errors):
            return
        rows = self.kept()
        if not rows:
            raise ValidationError(_('A feeding table has at least one band.'))
        for previous, row in zip(rows, rows[1:]):
            if previous['max_weight_g'] is None:
                raise ValidationError(_('Only the last band can be without an upper weight.'))
            if row['min_weight_g'] != previous['max_weight_g']:
                raise ValidationError(_('The bands must meet: one starts at %(start)s g, the band before it ends at '
                                        '%(end)s g.') % {'start': f"{row['min_weight_g'].normalize():f}",
                                                          'end': f"{previous['max_weight_g'].normalize():f}"})


BandFormSet = forms.formset_factory(BandRowForm, formset=BaseBandFormSet, extra=0, can_delete=True,
                                    max_num=MAX_BANDS, validate_max=True)


def table_forms(protocol, data=None, draft=None):
    """(ProtocolTableForm, BandFormSet) of a protocol: bound to `data` (a save), from a `draft` (the columns changed:
    the bands entered so far, nothing validated) or from the stored table."""
    if data is not None:
        form = ProtocolTableForm(data)
        columns = parse_or_none(data.get('temperatures', ''))
        return form, BandFormSet(data, prefix='bands', columns=columns or [])
    if draft is not None:
        columns = parse_or_none(draft.get('temperatures', '')) or []
        form = ProtocolTableForm(initial={'version': draft.get('version'), 'temperatures': draft.get('temperatures')})
        return form, BandFormSet(initial=_drafted_rows(draft, columns), prefix='bands', columns=columns)
    bands = list(protocol.bands.select_related('feed').prefetch_related('rates'))
    columns = sorted({rate.temperature_c for band in bands for rate in band.rates.all()})
    initial = [{'min_weight_g': band.min_weight_g, 'max_weight_g': band.max_weight_g, 'feed': band.feed_id,
                'meals_per_day': band.meals_per_day, 'expected_fcr': band.expected_fcr,
                **{column_name(rate.temperature_c): rate.sfr_pct for rate in band.rates.all()}} for band in bands]
    form = ProtocolTableForm(initial={'version': protocol.version, 'temperatures': shown_temperatures(columns)})
    return form, BandFormSet(initial=initial, prefix='bands', columns=columns)


def parse_or_none(text):
    try:
        return parse_temperatures(text)
    except ValidationError:
        return None


def _drafted_rows(draft, columns):
    """The rows of a posted grid as typed, those marked for removal left out."""
    try:
        total = int(draft.get('bands-TOTAL_FORMS', 0))
    except ValueError:
        total = 0
    names = [*BandRowForm.Meta.fields, *(column_name(temperature) for temperature in columns)]
    rows = []
    for index in range(min(total, MAX_BANDS)):
        if draft.get(f'bands-{index}-DELETE'):
            continue
        rows.append({name: draft[f'bands-{index}-{name}'] for name in names if f'bands-{index}-{name}' in draft})
    return rows


# ---- assignments ------------------------------------------------------------------------------------------
class UnitChoices(forms.ModelMultipleChoiceField):
    def label_from_instance(self, unit):
        place = unit.production_department.name
        if unit.production_department.site:
            place = f'{place} · {unit.production_department.site.name}'
        return f'{unit.code} · {unit.name} · {place}'


class BatchChoice(forms.ModelChoiceField):
    def label_from_instance(self, batch):
        return f'{batch.code} · {batch.species}' + (f' · {batch.name}' if batch.name else '')


class ProtocolChoice(forms.ModelChoiceField):
    def label_from_instance(self, protocol):
        return f'{protocol.name} · {protocol.species}'


def batches_in_stock():
    """The live batches with fish now, the ones a protocol can be assigned to."""
    present = (StockMovement.objects.filter(operation__is_deleted=False).values('batch_id')
               .annotate(fish=Sum('count_delta')).filter(fish__gt=0).values('batch_id'))
    return Batch.objects.filter(pk__in=present).select_related('species').order_by('-input_date', '-code')


def within_window(day, stored=None, unit=None):
    """A first day changed or new is at most the correction window back, as every daily record (farm/stock/dates.py):
    the days before are history."""
    if day != stored and day < earliest(unit):
        raise ValidationError(too_old(_('An assignment can start at most %(days)d days back.')))
    return day


ASSIGNMENT_TABS = [('assignment', _('Assignment'), list(assignments.FIELDS))]
NEW_ASSIGNMENT_TABS = [('assignment', _('Assignment'),
                        ['protocol', 'units', 'batch', 'valid_from', 'valid_until', 'notes'])]
HELP = {
    'valid_from': _('The first day it feeds by, on the farm’s clock.'),
    'valid_until': _('Optional: the last day. Empty: until it is ended.'),
}


class NewAssignmentForm(TabbedForm):
    """Assigns an active protocol: to units (one or more: a row each), to a whole batch (one row, which follows the
    batch through transfers and splits), or to a batch in chosen units (a row per unit). The units and the batch
    chosen say which; the rows are written together, with one group (ProtocolAssignment.group_id)."""

    tabs = NEW_ASSIGNMENT_TABS
    units = UnitChoices(label=_('Units'), queryset=Tank.objects.none(), required=False,
                        widget=forms.CheckboxSelectMultiple,
                        help_text=_('Units only: the protocol feeds whatever is in them. With a batch: that batch in '
                                    'these units only.'))

    class Meta:
        model = ProtocolAssignment
        fields = ['protocol', 'batch', 'valid_from', 'valid_until', 'notes']
        field_classes = {'protocol': ProtocolChoice, 'batch': BatchChoice}
        widgets = {'valid_from': DayInput(),
                   'valid_until': DayInput(),
                   'notes': forms.Textarea(attrs={'rows': 2})}
        help_texts = {**HELP, 'batch': _('A batch alone: the protocol follows it into every unit it is moved to.')}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['protocol'].queryset = (FeedingProtocol.objects.filter(status=ProtocolStatus.ACTIVE)
                                            .select_related('species').order_by('name'))
        self.fields['protocol'].empty_label = _('Select an active protocol')
        self.fields['units'].queryset = (Tank.objects.select_related('production_department__site')
                                         .order_by('code'))
        self.fields['batch'].queryset = batches_in_stock()
        self.fields['batch'].empty_label = _('No batch')
        self.fields['valid_from'].initial = local_today()
        self.rows = []
        self.unvisited = []

    def clean_valid_from(self):
        return within_window(self.cleaned_data['valid_from'])

    def _check_conditional_constraints(self, cleaned):
        """The form's own record is not one of the rows it writes (a row per unit chosen): each row is checked
        against the constraints in clean()."""

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        units, batch = list(cleaned.get('units') or []), cleaned.get('batch')
        if not units and batch is None:
            self.add_error('units', _('Choose units, a batch, or a batch and units.'))
            return cleaned
        self.rows, errors = assignments.rows(cleaned['protocol'], units, batch, cleaned['valid_from'],
                                             cleaned.get('valid_until'), cleaned.get('notes', ''))
        for error in errors:
            # What concerns a field the form shows is said once by the form's own check of the record; what
            # concerns the row as a whole (another protocol on those days) is said per unit.
            if error.field != NON_FIELD_ERRORS:
                continue
            if error.unit is not None:
                self.add_error('units', f'{error.unit.code}: {error.message}')
            else:
                self.add_error('batch', error.message)
        if batch is not None:
            visited = set(StockMovement.objects.filter(batch=batch, operation__is_deleted=False)
                          .values_list('unit_id', flat=True))
            self.unvisited = [unit for unit in units if unit.pk not in visited]
        return cleaned

    def notices(self):
        """What to tell after saving: units the batch has not been in yet (planning a move is allowed)."""
        if not self.unvisited:
            return []
        batch = self.cleaned_data['batch']
        return [ngettext('%(batch)s has not been in %(units)s yet: the row applies once it is.',
                         '%(batch)s has not been in %(units)s yet: the rows apply once it is.', len(self.unvisited))
                % {'batch': batch.code, 'units': ', '.join(unit.code for unit in self.unvisited)}]


class AssignmentForm(TabbedForm):
    """One assignment row. Its unit and batch are chosen once. Before its first day everything else may change;
    from then on only its last day and notes (the days it fed keep their protocol), and its last day is yesterday at
    the earliest (ending it today still feeds today by it)."""

    tabs = ASSIGNMENT_TABS
    fixed_after_creation = ('unit', 'batch')

    class Meta:
        model = ProtocolAssignment
        fields = tab_fields(ASSIGNMENT_TABS)
        field_classes = {'protocol': ProtocolChoice, 'batch': BatchChoice}
        widgets = NewAssignmentForm.Meta.widgets
        help_texts = HELP

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        stored = self.instance
        self.today = stored.today()
        protocols = FeedingProtocol.objects.filter(status=ProtocolStatus.ACTIVE)
        if stored.protocol_id:
            protocols = protocols | FeedingProtocol.objects.filter(pk=stored.protocol_id)
        self.fields['protocol'].queryset = protocols.select_related('species').order_by('name')
        self.fields['batch'].queryset = Batch.all_objects.select_related('species')
        self.fields['unit'].queryset = Tank.all_objects.all()
        self.started = stored.pk is not None and stored.valid_from <= self.today
        if self.started:
            for name in ('protocol', 'valid_from'):
                self.fields[name].disabled = True
                self.fields[name].help_text = _('Fixed: the row has started. End it and add another to change it.')

    def clean_valid_until(self):
        until = self.cleaned_data.get('valid_until')
        stored = self.instance.valid_until
        if self.started and until != stored and until is not None and until < self.today - timedelta(days=1):
            raise ValidationError(_('The days before yesterday keep their protocol: the last day is yesterday at '
                                    'the earliest.'))
        return until

    def clean_valid_from(self):
        return within_window(self.cleaned_data['valid_from'], self.instance.valid_from, self.instance.unit)
