"""The forms of Operations › Feeding › Protocols and Assignments: a protocol's general fields (a tab of core.crud), its
feeding table (a grid of bands by temperature columns, saved whole by farm/feeding/protocols.py) and the assignment
dialogs (several units at once on create, one row on edit)."""
from decimal import Decimal, InvalidOperation


from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from core.crud import DRAFT, CodedFormMixin, TabbedForm, tab_fields


from ..models import Feed, FeedingProtocol, ProtocolAssignment, ProtocolBand, Species
from ..models.feeding_protocol import (
    BETWEEN_FIELDS, FIXED_ONCE_ASSIGNED, MAX_SFR, TEMPERATURE, BetweenBands, ProtocolStatus,
)
from .assignment import HELP, AssignmentBase, NewAssignmentBase, SubjectChoice, edit_tabs, new_tabs

DECIMAL = {'inputmode': 'decimal'}
MAX_COLUMNS = 12      # temperature columns a table can have: what a screen shows side by side
MAX_BANDS = 30

PROTOCOL_TABS = [('general', _('General'), ['name', 'species', 'status', 'expected_fcr', 'uneaten_pct',
                                             'mortality_pct_month', *BETWEEN_FIELDS, 'notes'])]


class ProtocolForm(CodedFormMixin, TabbedForm):
    """A protocol's general fields. Its feeding table is a tab of its own, saved as a whole (ProtocolTableForm). Once
    it is assigned, its species, expected FCR, uneaten share and expected mortality are fixed and it cannot go back to draft (the model says why)."""

    tabs = PROTOCOL_TABS

    class Meta:
        model = FeedingProtocol
        fields = tab_fields(PROTOCOL_TABS)
        localized_fields = ['expected_fcr', 'uneaten_pct', 'mortality_pct_month']
        widgets = {'expected_fcr': forms.TextInput(attrs=DECIMAL),
                   'uneaten_pct': forms.TextInput(attrs={**DECIMAL, 'placeholder': _('none')}),
                   'mortality_pct_month': forms.TextInput(attrs={**DECIMAL, 'placeholder': _('none')}),
                   'notes': forms.Textarea(attrs={'rows': 3}),
                   'name': forms.TextInput(attrs={'placeholder': _('e.g. Rainbow trout grow-out, RAS')})}
        help_texts = {
            'species': _('The species the table is for: it is assigned only to fish of this species.'),
            'status': _('Draft: being built. Active: can be assigned. Retired: kept for the days it fed, assigned no '
                        'more.'),
            'expected_fcr': _('The kg of feed eaten per kg of growth the table expects (the biological FCR); a band '
                              'may have its own. Between two bands it is read in between them, with no jump at a '
                              'band’s edge. The estimated weight between weighings and the production plan grow '
                              'by the feed eaten divided by it.'),
            'uneaten_pct': _('The share of the feed given that the fish do not eat, 0 to 50 %%; a band may have its '
                             'own. Empty: all of it is eaten. The feed given less this share is what grows the '
                             'fish; the FCR on the feed given is worked out from the two and '
                             'shown, never entered.'),
            'mortality_pct_month': _('The share of the fish expected to die in a month (30 days), 0 to 30 %%; a band '
                                     'may have its own. Empty: none. Read by the production plan only: it lowers '
                                     'the fish, the biomass and the feed ahead, never the average weight.'),
            'fcr_between': _('For fish between two weight bands. Smooth: each band’s value sits at the middle of the '
                             'band and is read in between, with no jump at a band’s edge. Step: the fish’s own '
                             'band’s value, changing at the edge. The Feeding table tab shows the values this '
                             'gives. The same choice for the uneaten feed and for the SFR.'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['species'].queryset = Species.objects.order_by('common_name')
        for name in BETWEEN_FIELDS:
            # one of the two rules, never empty: a form that does not send it keeps the protocol's (a new one: smooth)
            self.fields[name].required = False
            self.fields[name].choices = BetweenBands.choices
        self.fields['species'].empty_label = _('Select a species')
        if self.instance.is_assigned():
            for name in FIXED_ONCE_ASSIGNED:
                self.fields[name].disabled = True
                self.fields[name].help_text = _('Fixed: the protocol is assigned. Duplicate it to change it.')
            self.fields['status'].choices = [choice for choice in ProtocolStatus.choices
                                             if choice[0] != ProtocolStatus.DRAFT]
        elif self.instance._state.adding:
            self.fields['status'].choices = [(ProtocolStatus.DRAFT, ProtocolStatus.DRAFT.label)]
            self.fields['status'].help_text = _('A new protocol is a draft: fill in its feeding table, then set it '
                                                'active.')


    def clean(self):
        cleaned = super().clean()
        for name in BETWEEN_FIELDS:
            if not cleaned.get(name):
                cleaned[name] = getattr(self.instance, name)
        return cleaned


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
    """A band of the table: its weights, feed, meals, expected FCR, uneaten share, expected mortality and one SFR per
    temperature column."""

    class Meta:
        model = ProtocolBand
        fields = ['min_weight_g', 'max_weight_g', 'feed', 'meals_per_day', 'expected_fcr', 'uneaten_pct',
                  'mortality_pct_month']
        localized_fields = ['min_weight_g', 'max_weight_g', 'expected_fcr', 'uneaten_pct', 'mortality_pct_month']
        widgets = {'min_weight_g': forms.TextInput(attrs=DECIMAL), 'max_weight_g': forms.TextInput(attrs=DECIMAL),
                   'expected_fcr': forms.TextInput(attrs={**DECIMAL, 'placeholder': _('protocol’s')}),
                   'uneaten_pct': forms.TextInput(attrs={**DECIMAL, 'placeholder': _('protocol’s')}),
                   'mortality_pct_month': forms.TextInput(attrs={**DECIMAL, 'placeholder': _('protocol’s')}),
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
                'uneaten_pct': band.uneaten_pct, 'mortality_pct_month': band.mortality_pct_month,
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
class NewAssignmentForm(NewAssignmentBase):
    """Assigns an active protocol (farm/forms/assignment.py: the dialog shared with the temperature profiles)."""

    tabs = new_tabs('protocol')
    select_label = _('Select an active protocol')
    units_help = _('Units only: the protocol feeds whatever is in them. With a batch: that batch in these units only.')

    class Meta(NewAssignmentBase.Meta):
        model = ProtocolAssignment
        fields = ['protocol', *NewAssignmentBase.Meta.fields]
        field_classes = {**NewAssignmentBase.Meta.field_classes, 'protocol': SubjectChoice}
        help_texts = {**HELP, 'batch': _('A batch alone: the protocol follows it into every unit it is moved to.')}


class AssignmentForm(AssignmentBase):
    """One protocol assignment row (farm/forms/assignment.py)."""

    tabs = edit_tabs('protocol')

    class Meta(AssignmentBase.Meta):
        model = ProtocolAssignment
        fields = tab_fields(edit_tabs('protocol'))
        field_classes = {**AssignmentBase.Meta.field_classes, 'protocol': SubjectChoice}


ASSIGNMENT_TABS = AssignmentForm.tabs
