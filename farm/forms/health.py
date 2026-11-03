"""The health forms: a medicine (Setup › Reference data › Medicines) and a health event (Operations › Health
events), each a tab's form on core.crud; a treatment, its last day and a sea-lice count, each one call of the
health service (farm/health/services.py) as the stock's dialogs are of theirs (farm/forms/stock.py: the token,
the farm's today, the service's reasons on their fields)."""
import uuid

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.crud import TabbedForm, tab_fields

from ..health import services
from ..health.withdrawal import rule
from ..models import HealthEvent, LiceCount, Medicine, Site, Supplier, Tank, Treatment
from ..models.handling import HandlingKind
from ..models.site import zone_of
from ..stock.dates import local_today, site_earliest, site_today
from .stock import DATE, DECIMAL, NOTES, EventChoice, ServiceErrors, handling_ack_field
from .water import SiteClockField


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
    ('withdrawal', _('Withdrawal'), ['withdrawal_degree_days', 'withdrawal_days']),
    ('notes', _('Notes'), ['notes']),
]


class MedicineForm(TabbedForm):
    """The medicine dialog. The withdrawal is the product's, as its SPC states it."""

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
            'withdrawal_degree_days': _('As the SPC states it (døgngrader): the daily mean water temperatures '
                                        'after the last treatment day add up to this before the fish may be '
                                        'harvested. 0 when it has none.'),
            'withdrawal_days': _('As the SPC states it, in days after the last treatment day. Give it as well '
                                 'when the SPC gives both: the later end wins. 0 when it has none.'),
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


# ---- health events ------------------------------------------------------------------------------------
HEALTH_EVENT_FORM_TABS = [
    ('event', _('Event'), ['site', 'units', 'date', 'kind', 'signs']),
    ('diagnosis', _('Diagnosis'), ['diagnosis', 'confirmation', 'authority_notified_at']),
    ('examination', _('Examination'), ['examined_by', 'vet', 'lab', 'lab_reference', 'findings',
                                       'recommendations']),
    ('closing', _('Closing'), ['closed_on', 'outcome']),
]


class HealthEventForm(TabbedForm):
    """A health event: where and what (the site chosen once, some of its units or the whole site), the
    diagnosis and whether Mattilsynet was told, the examination, and its closing. The units are the site's:
    choosing the site renders the form again with them (refresh_on). Its date follows the farm's date rule
    when it is entered or changed."""

    tabs = HEALTH_EVENT_FORM_TABS
    fixed_after_creation = ('site',)
    refresh_on = ('site',)

    authority_notified_at = SiteClockField(label=_('Mattilsynet notified at'), required=False)

    class Meta:
        model = HealthEvent
        fields = tab_fields(HEALTH_EVENT_FORM_TABS)
        field_classes = {'units': UnitsChoice}
        widgets = {'date': DATE, 'closed_on': DATE, 'findings': NOTES, 'recommendations': NOTES, 'outcome': NOTES}
        help_texts = {
            'units': _('Leave all unticked when it concerns the whole site.'),
            'diagnosis': _('A listed disease is notified to Mattilsynet at once, already on suspicion '
                           '(dyrehelseforskriften § 7).'),
            'authority_notified_at': _('On the site’s clock.'),
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
        if not self.instance._state.adding and self.instance.authority_notified_at and not self.is_bound:
            self.initial['authority_notified_at'] = timezone.localtime(
                self.instance.authority_notified_at, zone_of(self.instance.site)).replace(tzinfo=None)

    def clean_authority_notified_at(self):
        moment = self.cleaned_data['authority_notified_at']
        if moment is None or self.site is None:
            return moment
        moment = timezone.make_aware(moment, zone_of(self.site))
        if moment > timezone.now():
            raise ValidationError(_('The time cannot be in the future.'))
        return moment

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
        notified = cleaned.get('authority_notified_at')
        if notified is not None and day is not None and timezone.localtime(notified, zone_of(site)).date() < day:
            self.add_error('authority_notified_at', _('Mattilsynet is notified on or after the date of the event.'))
        return cleaned


# ---- treatments ---------------------------------------------------------------------------------------
class MedicineChoice(forms.ModelChoiceField):
    def label_from_instance(self, medicine):
        """Salmosan vet. · azamethiphos · bath · 150 degree-days"""
        return ' · '.join([str(medicine), medicine.active_substance,
                           str(medicine.get_administration_display()).lower(), rule(medicine)])


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
        self.fields['medicine'].queryset = Medicine.objects.filter(status=Medicine.Status.ACTIVE)
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
