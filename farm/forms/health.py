"""The health forms: a medicine (Setup › Reference data › Medicines) and a health event (Operations › Health
events), each a tab's form on core.crud; a treatment, its last day and a sea-lice count, each one call of the
health service (farm/health/services.py) as the stock's dialogs are of theirs (farm/forms/stock.py: the token,
the farm's today, the service's reasons on their fields)."""
import uuid

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _, ngettext_lazy

from core.crud import RowFormSet, TabbedForm, tab_fields

from ..health import services
from ..health.withdrawal import rules_text
from ..models import HealthEvent, LiceCount, Medicine, MedicineWithdrawal, Site, Species, Supplier, Tank, Treatment
from ..models.health import SAME_SPECIES_MESSAGE
from ..models.handling import HandlingKind
from ..stock.dates import local_today, site_earliest, site_today
from .stock import DATE, DECIMAL, NOTES, EventChoice, ServiceErrors, handling_ack_field


def supplier_label(supplier):
    """A supplier in a list, with its status when it is not active."""
    if supplier.status == Supplier.Status.ACTIVE:
        return str(supplier)
    return f'{supplier} · {supplier.get_status_display()}'


def unit_label(unit):
    """T-01 · Pen 1 · Bergen"""
    site = unit.production_department.site
    return ' · '.join(part for part in (unit.code, unit.name, site.name if site else '') if part)


class UnitsChoice(forms.ModelMultipleChoiceField):
    widget = forms.CheckboxSelectMultiple

    def label_from_instance(self, unit):
        return unit_label(unit)


class UnitChoice(forms.ModelChoiceField):
    def label_from_instance(self, unit):
        return unit_label(unit)


# ---- medicines ----------------------------------------------------------------------------------------
MEDICINE_FORM_TABS = [
    ('basic', _('Basic info'), ['name', 'marketing_authorisation', 'kind', 'administration', 'active_substance',
                                'lice_report_code', 'strength_value', 'strength_unit', 'manufacturer',
                                'prescription_only', 'status']),
    ('notes', _('Notes'), ['notes']),
]


class MedicineForm(TabbedForm):
    """The medicine dialog. Its withdrawal is a list of rows of its own, per species, on the Withdrawal tab
    (MedicineWithdrawalFormSet, saved separately once the medicine exists)."""

    tabs = MEDICINE_FORM_TABS

    class Meta:
        model = Medicine
        fields = tab_fields(MEDICINE_FORM_TABS)
        localized_fields = ['strength_value']
        help_texts = {
            'name': _('The product name, as on the pack, e.g. Salmosan vet.'),
            'marketing_authorisation': _('The MT number, when the medicine has one.'),
            'administration': _('How it is given; a treatment with it uses the same method.'),
            'active_substance': _('As the SPC names it, e.g. azamethiphos.'),
            'lice_report_code': _('A sea-lice medicine only: its substance as Mattilsynet’s weekly lice report '
                                  'names it.'),
            'manufacturer': _('A supplier of medicines and vaccines (Purchasing › Suppliers).'),
            'status': _('Active: a new treatment can use it. Inactive: kept for the treatments that used it.'),
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': _('e.g. Salmosan vet.')}),
            'strength_value': forms.TextInput(attrs=DECIMAL),
            'notes': NOTES,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['kind'].choices = [('', _('Select a kind'))] + list(Medicine.Kind.choices)
        self.fields['administration'].choices = [('', _('Select how it is given'))] + list(
            Medicine.Administration.choices)
        self.fields['lice_report_code'].choices = [('', _('Not a sea-lice medicine'))] + list(
            Medicine.LiceSubstance.choices)
        self.fields['strength_unit'].choices = [('', '—')] + list(Medicine.StrengthUnit.choices)
        manufacturer = self.fields['manufacturer']
        manufacturer.empty_label = _('None')
        manufacturer.label_from_instance = supplier_label


class MedicineWithdrawalForm(forms.ModelForm):
    """One row of a medicine's withdrawal: the species (empty: every species without a row of its own), the
    degree-days and the days as the SPC states them, the farm's safety margin on top and a note."""

    class Meta:
        model = MedicineWithdrawal
        fields = ['species', 'degree_days', 'days', 'safety_margin_pct', 'note']
        localized_fields = ['degree_days', 'safety_margin_pct']
        widgets = {
            'degree_days': forms.TextInput(attrs={**DECIMAL, 'placeholder': _('e.g. 150')}),
            'days': forms.NumberInput(attrs={'min': 0, 'placeholder': _('e.g. 7')}),
            'safety_margin_pct': forms.TextInput(attrs={**DECIMAL, 'placeholder': _('e.g. 20')}),
            'note': forms.TextInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['species'].queryset = Species.objects.order_by('common_name')
        self.fields['species'].empty_label = _('All species')
        self.fields['safety_margin_pct'].required = False      # empty is none: 0 %
        self.fields['safety_margin_pct'].initial = None         # (the column's default of 0 is not shown on a new row)
        if self.instance._state.adding:
            self.initial.pop('safety_margin_pct', None)         # a new row's margin is empty: left alone, it is blank

    def clean_safety_margin_pct(self):
        margin = self.cleaned_data['safety_margin_pct']
        return 0 if margin is None else margin

    def validate_constraints(self):
        # One row per species spans the whole list, which is saved as a full replace; the formset checks it and the
        # database constraint backs it up. Checking each row against the stored rows would reject keeping a species
        # while replacing its row.
        pass


class BaseMedicineWithdrawalFormSet(RowFormSet):
    default_error_messages = {
        'too_many_forms': ngettext_lazy('A medicine has at most %(num)d row.', 'A medicine has at most %(num)d rows.',
                                        'num'),
    }

    def get_unique_error_message(self, unique_check):
        return str(SAME_SPECIES_MESSAGE)

    def clean(self):
        if not any(self.errors):
            species = [form.cleaned_data.get('species') for form in self.forms
                       if form.cleaned_data and not form.cleaned_data.get('DELETE')]
            if len(species) != len(set(species)):          # the one for every species is None: one only, too
                raise ValidationError(SAME_SPECIES_MESSAGE)
        super().clean()


MedicineWithdrawalFormSet = forms.inlineformset_factory(
    Medicine, MedicineWithdrawal, form=MedicineWithdrawalForm, formset=BaseMedicineWithdrawalFormSet,
    extra=0, can_delete=True, max_num=50, validate_max=True,
)


# ---- health events ------------------------------------------------------------------------------------
HEALTH_EVENT_FORM_TABS = [
    ('event', _('Event'), ['site', 'units', 'date', 'kind', 'signs']),
    ('diagnosis', _('Diagnosis'), ['diagnosis', 'confirmation']),
    ('examination', _('Examination'), ['examined_by', 'vet', 'lab', 'lab_reference', 'findings',
                                       'recommendations']),
    ('closing', _('Closing'), ['closed_on', 'outcome']),
]


class HealthEventForm(TabbedForm):
    """A health event: where and what (the site chosen once, some of its units or the whole site), the
    diagnosis, the examination, and its closing. That Mattilsynet was told is the filing of a notice (Production ›
    Reports), not a field here. The units are the site's:
    choosing the site renders the form again with them (refresh_on). Its date follows the farm's date rule
    when it is entered or changed."""

    tabs = HEALTH_EVENT_FORM_TABS
    fixed_after_creation = ('site',)
    refresh_on = ('site',)

    class Meta:
        model = HealthEvent
        fields = tab_fields(HEALTH_EVENT_FORM_TABS)
        field_classes = {'units': UnitsChoice}
        widgets = {'date': DATE, 'closed_on': DATE, 'findings': NOTES, 'recommendations': NOTES, 'outcome': NOTES}
        help_texts = {
            'units': _('Leave all unticked when it concerns the whole site.'),
            'diagnosis': _('A listed disease is notified to Mattilsynet at once, already on suspicion '
                           '(dyrehelseforskriften § 7): the event’s page offers to start the notice.'),
            'examined_by': _('The vet or fish-health biologist, or who observed it.'),
            'vet': _('A supplier of veterinary and fish health services (Purchasing › Suppliers).'),
            'lab': _('A supplier of laboratory analyses.'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['site'].queryset = Site.objects.order_by('name')
        self.fields['kind'].choices = [('', _('Select a kind'))] + list(HealthEvent.Kind.choices)
        self.fields['diagnosis'].choices = [('', _('No diagnosis'))] + [
            (code, label) for code, label in HealthEvent._meta.get_field('diagnosis').choices]
        self.fields['confirmation'].choices = [('', '—')] + list(HealthEvent.Confirmation.choices)
        for name in ('vet', 'lab'):
            self.fields[name].empty_label = _('None')
            self.fields[name].label_from_instance = supplier_label
        self.site = self.instance.site if self.instance.site_id else self.current('site')
        units = self.fields['units']
        units.queryset = (Tank.objects.filter(production_department__site=self.site)
                          .select_related('production_department__site').order_by('code')
                          if self.site is not None else Tank.objects.none())
        if self.site is None:
            units.help_text = _('Choose the site first.')

    def clean(self):
        cleaned = super().clean()
        day, site = cleaned.get('date'), self.site
        changed = self.instance._state.adding or day != self.instance.date
        if day is not None and site is not None and changed:
            if day > site_today(site):
                self.add_error('date', _('The date cannot be in the future.'))
            elif day < site_earliest(site):
                self.add_error('date', _('Operations can be dated at most %(days)d days back.') % {
                    'days': settings.STOCK_BACKDATE_DAYS})
        return cleaned


# ---- treatments ---------------------------------------------------------------------------------------
class MedicineChoice(forms.ModelChoiceField):
    def label_from_instance(self, medicine):
        """Salmosan vet. · azamethiphos · bath · 150 degree-days"""
        return ' · '.join([str(medicine), medicine.active_substance,
                           str(medicine.get_administration_display()).lower(), rules_text(medicine)])


class TreatmentForm(ServiceErrors, forms.ModelForm):
    """A treatment: the units (those with fish now, of one site), how and with what, its first and last day,
    the dose and the amount used, the prescription and the vet, the health event it answers, notes."""

    token = forms.UUIDField(widget=forms.HiddenInput)
    units = UnitsChoice(label=_('Units'), queryset=Tank.objects.none())
    medicine = MedicineChoice(label=_('Medicine'), queryset=Medicine.objects.none(), required=False)
    health_event = EventChoice(label=_('Health event'), queryset=HealthEvent.objects.none(), required=False)

    service_fields = {'date': 'start_date'}

    class Meta:
        model = Treatment
        fields = ['units', 'method', 'medicine', 'reason', 'start_date', 'end_date', 'dose_value', 'dose_unit',
                  'amount_value', 'amount_unit', 'bath_minutes', 'prescribed_by', 'prescription_ref', 'vet',
                  'health_event', 'notes']
        widgets = {'start_date': DATE, 'end_date': DATE, 'notes': NOTES, 'dose_value': forms.TextInput(attrs=DECIMAL),
                   'amount_value': forms.TextInput(attrs=DECIMAL)}
        localized_fields = ['dose_value', 'amount_value']
        help_texts = {
            'method': _('A bath, medicated feed, injection or dip is given with a medicine, the way the medicine '
                        'is given; the others without one.'),
            'start_date': _('The first day of the course.'),
            'end_date': _('The last day of the course, planned up to 28 days ahead. The withdrawal counts from it.'),
            'amount_value': _('The amount of the medicine used, as the lice report asks for it.'),
            'bath_minutes': _('A bath, a dip or a freshwater bath only.'),
            'prescription_ref': _('The prescription’s number, for a prescription-only medicine.'),
        }

    def __init__(self, *args, units, unit=None, **kwargs):
        super().__init__(*args, instance=Treatment(), **kwargs)
        self.fields['token'].initial = uuid.uuid4()
        self.fields['units'].queryset = units
        self.fields['handling_ack'] = handling_ack_field(HandlingKind.TREATMENT)
        self._handling = None
        today = local_today(unit)
        # A new record's own empty dates would win over the farm's today (as the feeding form says).
        self.initial.update({'start_date': today, 'end_date': today})
        if unit is not None:
            self.initial['units'] = [unit.pk]
        self.fields['medicine'].queryset = Medicine.objects.filter(status=Medicine.Status.ACTIVE).prefetch_related(
            'withdrawals__species')
        site_ids = {each.production_department.site_id for each in units}
        self.fields['health_event'].queryset = (HealthEvent.objects.filter(site_id__in=site_ids, closed_on__isnull=True)
                                                .select_related('site'))
        self.fields['method'].choices = [('', _('Select a method'))] + list(Treatment.Method.choices)
        self.fields['reason'].choices = [('', _('Select a reason'))] + list(Treatment.Reason.choices)
        self.fields['dose_unit'].choices = [('', '—')] + list(Treatment.DoseUnit.choices)
        self.fields['amount_unit'].choices = [('', '—')] + list(Treatment.AmountUnit.choices)
        self.fields['vet'].empty_label = _('None')
        self.fields['vet'].label_from_instance = supplier_label

    @property
    def handling(self):
        """The fast before the treatment, for the units, first day and method as entered (else as offered):
        farm.health.services.handling, shown by the handling panel with its box."""
        if self._handling is None:
            data = getattr(self, 'cleaned_data', {})
            units = data.get('units')
            if units is None:
                chosen = {str(pk) for pk in (self['units'].value() or [])}
                units = [unit for unit in self.fields['units'].queryset if str(unit.pk) in chosen]
            day = data.get('start_date') or self.current('start_date')
            method = data.get('method') or self['method'].value()
            self._handling = services.handling(list(units), day, method)
            self.fields['handling_ack'].widget.fingerprint = self._handling.fingerprint
        return self._handling

    def current(self, name):
        """A field's value as the form has it now (posted or offered), cleaned; None when it is not valid."""
        try:
            return self.fields[name].clean(self[name].value())
        except ValidationError:
            return None

    def save(self, user):
        data = self.cleaned_data
        return services.record_treatment(
            user, units=list(data['units']), method=data['method'], reason=data['reason'],
            start_date=data['start_date'], end_date=data['end_date'], medicine=data['medicine'],
            dose_value=data['dose_value'], dose_unit=data['dose_unit'], amount_value=data['amount_value'],
            amount_unit=data['amount_unit'], bath_minutes=data['bath_minutes'], prescribed_by=data['prescribed_by'],
            prescription_ref=data['prescription_ref'], vet=data['vet'], health_event=data['health_event'],
            notes=data['notes'], handling_ack=data['handling_ack'], token=data['token'])


class LastDayForm(ServiceErrors, forms.Form):
    end_date = forms.DateField(label=_('Last day'), widget=DATE,
                               help_text=_('The withdrawal counts from the new last day; the change is logged.'))

    def __init__(self, *args, treatment, **kwargs):
        super().__init__(*args, **kwargs)
        self.treatment = treatment
        self.fields['end_date'].initial = treatment.end_date

    def save(self, user):
        return services.change_last_day(user, self.treatment, self.cleaned_data['end_date'])


# ---- sea-lice counts ----------------------------------------------------------------------------------
class LiceCountForm(ServiceErrors, forms.ModelForm):
    """A sea-lice count: the unit (with fish), the day, the fish examined and the lice of each stage found on
    them, in total; the averages per fish are worked out."""

    token = forms.UUIDField(widget=forms.HiddenInput)
    unit = UnitChoice(label=_('Unit'), queryset=Tank.objects.none())

    class Meta:
        model = LiceCount
        fields = ['unit', 'date', 'fish_counted', 'adult_females', 'mobile', 'attached', 'notes']
        widgets = {'date': DATE, 'notes': NOTES}
        help_texts = {
            'fish_counted': _('At least 10 fish a cage, 20 in the spring weeks (lakselusforskriften, Vedlegg 1).'),
            'adult_females': _('All adult female lice found on the fish examined, with or without egg strings.'),
            'mobile': _('Pre-adult lice and adult males, in total.'),
            'attached': _('Copepodids and chalimus, in total.'),
        }

    def __init__(self, *args, units, unit=None, **kwargs):
        super().__init__(*args, instance=LiceCount(), **kwargs)
        self.fields['token'].initial = uuid.uuid4()
        self.fields['unit'].queryset = units
        if unit is not None:
            self.initial['unit'] = unit.pk
        self.initial['date'] = local_today(unit)

    def save(self, user):
        data = self.cleaned_data
        return services.record_lice_count(
            user, unit=data['unit'], day=data['date'], fish_counted=data['fish_counted'],
            adult_females=data['adult_females'], mobile=data['mobile'], attached=data['attached'],
            notes=data['notes'], token=data['token'])
