from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Prefetch
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.crud import RowFormSet, TabbedForm, tab_fields
from farm.forms.water import SiteClockField
from farm.models import EscapeRecord, HealthEvent, SlaughterFacility, Site, StockMovement, Tank
from farm.models.harvest import FacilityStatus
from farm.models.site import zone_of
from core.widgets import DayInput

from . import periods
from .compute import COMPUTE, lice
from .kinds import BY_FACILITY, EVENTS, PERIODIC, info
from .models import (
    HEALTH_EVENT_KINDS, OpenQuestion, NARRATIVE, NARRATIVE_KINDS, SITE_NOTICES, Channel, Report, ResistanceSuspicion, SensitivityTest, TreatmentAnswer,
    UnitAnswer,
)

REPORT_FORM_TABS = [
    ('report', _('Report'), ['kind', 'site', 'facility', 'period_start', 'health_event', 'escape', 'occurred_on',
                             'harvest_condition', 'no_cleaner_feed']),
    ('contact', _('Contact person'), ['contact_name', 'contact_email', 'contact_phone']),
    ('event', _('What happened'), list(NARRATIVE)),
    ('notes', _('Notes'), ['notes']),
]


def escape_label(escape):
    """An escape in a list, as the escape names itself: "Escape of 300 fish from M-01, 2026-10-30" (its line was loaded
    with the list: `ReportForm.__init__`), and what caused it."""
    return f'{escape} · {escape.cause[:50]}'


class ReportForm(TabbedForm):
    """A report: what it is and for what (fixed once started), the contact person, and for a notice what happened.
    The form shows the fields of the chosen kind: a site or a slaughter facility, a period or the day of the event,
    the narrative of a notice. A day of the period is enough: the report is for its week, month or year."""

    tabs = REPORT_FORM_TABS
    fixed_after_creation = ('kind', 'site', 'facility', 'period_start', 'health_event', 'escape', 'occurred_on')
    refresh_on = ('kind',)

    found_at = SiteClockField(label=_('Found at'), required=False, help_text=_('When it was found, on the site’s clock.'))

    class Meta:
        model = Report
        fields = tab_fields(REPORT_FORM_TABS)
        labels = {'period_start': _('A day in the period')}
        help_texts = {
            'period_start': _('The report is for the week, month or year this day falls in.'),
            'occurred_on': _('The day it happened (for a site taken into use or emptied: the day its first fish came '
                             'in or its last fish left).'),
            'contact_name': _('The person the authority can ask about the report. Needed before it is filed.'),
        }
        widgets = {
            'period_start': DayInput(),
            'occurred_on': DayInput(),
            'what_happened': forms.Textarea(attrs={'rows': 4}),
            'situation': forms.Textarea(attrs={'rows': 3}),
            'measures': forms.Textarea(attrs={'rows': 3}),
            'cause': forms.Textarea(attrs={'rows': 2}),
            'notes': forms.Textarea(attrs={'rows': 3}),
            'contact_phone': forms.TextInput(attrs={'type': 'tel'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['kind'].choices = [('', '---------')] + [
            (kind, label) for kind, label in Report.Kind.choices if kind in COMPUTE]
        if 'site' in self.fields and self.instance._state.adding:
            self.fields['site'].queryset = Site.objects.order_by('name')
        if 'facility' in self.fields and self.instance._state.adding:
            self.fields['facility'].queryset = SlaughterFacility.objects.filter(
                status=FacilityStatus.ACTIVE).order_by('name')
        if 'health_event' in self.fields:
            self.fields['health_event'].queryset = HealthEvent.objects.select_related('site').order_by(
                '-date', '-created_at')
            self.fields['health_event'].label_from_instance = lambda event: f'{event} · {event.site}'
            self.fields['health_event'].empty_label = _('None')
        if 'escape' in self.fields:
            lines = Prefetch('operation__movements', StockMovement.objects.select_related('unit'))
            self.fields['escape'].queryset = EscapeRecord.objects.select_related('operation').prefetch_related(
                lines).order_by('-operation__date', '-operation__created_at')
            self.fields['escape'].label_from_instance = escape_label
        if 'found_at' in self.fields and self.instance.found_at and not self.is_bound:
            self.initial['found_at'] = timezone.localtime(self.instance.found_at, self.zone()).replace(tzinfo=None)
        kind = self.chosen_kind()
        if not kind:
            return
        keep = {'kind', 'contact_name', 'contact_email', 'contact_phone', 'notes'}
        keep.add('facility' if kind in BY_FACILITY else 'site')
        keep.add('period_start' if kind in PERIODIC else 'occurred_on')
        if kind in NARRATIVE_KINDS:
            keep.update(NARRATIVE)
        if kind in HEALTH_EVENT_KINDS:
            keep.add('health_event')
        if kind == Report.Kind.ESCAPE:
            keep.add('escape')
        if kind == Report.Kind.BIOMASS:
            keep.add('harvest_condition')
        if kind == Report.Kind.CLEANER_FISH:
            keep.add('no_cleaner_feed')
        for name in list(self.fields):
            if name not in keep and name != 'version':
                del self.fields[name]
        for name in ('site', 'facility', 'period_start'):
            if name in self.fields and not self.fields[name].disabled:
                self.fields[name].required = True
        if kind == Report.Kind.DISEASE and 'health_event' in self.fields:
            self.fields['health_event'].required = True
        if kind == Report.Kind.ESCAPE and 'escape' in self.fields:
            self.fields['escape'].required = True
        if kind in SITE_NOTICES or kind in EVENTS and 'occurred_on' in self.fields and not self.fields[
                'occurred_on'].disabled:
            self.fields['occurred_on'].required = True

    def zone(self, site=None):
        """The clock `found_at` is typed on: the site's (the one chosen, else the record's, else the company's)."""
        return zone_of(site or (self.instance.site if self.instance.site_id else None))

    def chosen_kind(self):
        """The kind the form is for: the record's, else the one posted, drafted or given as the initial value."""
        if not self.instance._state.adding:
            return self.instance.kind
        value = self.current('kind') if (self.is_bound or self.draft is not None) else self.initial.get('kind')
        return value if value in COMPUTE else ''

    def clean(self):
        cleaned = super().clean()
        kind = cleaned.get('kind') or (self.instance.kind if not self.instance._state.adding else '')
        day = cleaned.get('period_start')
        if kind in PERIODIC and day and 'period_start' in self.fields and not self.fields['period_start'].disabled:
            cleaned['period_start'] = periods.Period.of(info(kind).grain, day).start
            # A planned slaughter is filed before its week; every other report after its period has begun.
            if kind not in BY_FACILITY and cleaned['period_start'] > periods.oslo_today():
                self.add_error('period_start', _('The period has not begun yet.'))
        occurred = cleaned.get('occurred_on')
        if occurred and occurred > periods.oslo_today():
            self.add_error('occurred_on', _('The day cannot be in the future.'))
        found = cleaned.get('found_at')
        if found:
            found = cleaned['found_at'] = timezone.make_aware(found, self.zone(cleaned.get('site')))
            if found > timezone.now():
                self.add_error('found_at', _('The time cannot be in the future.'))
        return cleaned


OPEN_QUESTION_TABS = [('question', _('Question'), ['code', 'question', 'authority', 'affects', 'status', 'asked_by',
                                                    'asked_on', 'answer', 'answered_on'])]


class OpenQuestionForm(TabbedForm):
    """A question for the authority, its answer and who asked when."""

    tabs = OPEN_QUESTION_TABS

    class Meta:
        model = OpenQuestion
        fields = tab_fields(OPEN_QUESTION_TABS)
        widgets = {'question': forms.Textarea(attrs={'rows': 3}), 'answer': forms.Textarea(attrs={'rows': 3}),
                   'asked_on': DayInput(),
                   'answered_on': DayInput()}
        help_texts = {'affects': _('Which rule of which report rests on the answer, e.g. “the sea-lice report, the amount '
                                   'of an active substance”.'),
                      'answer': _('What the authority said, and where (the mail, the page). Needed to mark it answered.')}


class DutyDoneForm(forms.Form):
    """Recording that a duty outside this system was done: the day and the reference the authority gave."""

    done_on = forms.DateField(label=_('Done on'), widget=DayInput())
    reference = forms.CharField(label=_('Receipt or reference'), max_length=200, required=False,
                                help_text=_('The receipt or case number the authority gave, if any.'))


class CloseForm(forms.Form):
    """Closing a report that is owed and will not be filed: why."""

    reason = forms.CharField(label=_('Why it is closed'), max_length=500, widget=forms.Textarea(attrs={'rows': 3}),
                             help_text=_('For example: the slaughter did not take place, or the notice was filed '
                                         'elsewhere. It is kept with your name and the day.'))


class SubmitForm(forms.Form):
    """Recording that a person filed the report: when, how, and the receipt or reference the authority gave."""

    submitted_at = SiteClockField(label=_('Filed at'), help_text=_('Oslo time, as the authority keeps it.'))
    channel = forms.ChoiceField(label=_('Filed through'), choices=Channel.choices)
    reference = forms.CharField(label=_('Receipt or reference'), max_length=200, required=False,
                                help_text=_('Not needed for a notice given by telephone.'))
    authority_id = forms.CharField(label=_('Id returned by the authority’s API'), max_length=100, required=False,
                                   help_text=_('Only for a filing through the reporting API: the id its answer gave. A '
                                               'correction of the report is sent to that id.'))
    version = forms.IntegerField(widget=forms.HiddenInput)
    # The hash of the content the page showed (reports.compute.content_hash): what is recorded is exactly that.
    content_sha256 = forms.CharField(widget=forms.HiddenInput, min_length=64, max_length=64)
    # The open questions the person confirmed by hand (the numbers of reports.OpenQuestion); the service says which are needed.
    acknowledged = forms.MultipleChoiceField(required=False, widget=forms.MultipleHiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['acknowledged'].choices = [(code, code) for code in OpenQuestion.objects.values_list('code', flat=True)]


class ResistanceSuspicionForm(forms.ModelForm):
    class Meta:
        model = ResistanceSuspicion
        fields = ['substance', 'other_substance', 'cause', 'other_cause']


class SensitivityTestForm(forms.ModelForm):
    class Meta:
        model = SensitivityTest
        fields = ['tested_on', 'laboratory', 'substance', 'other_substance', 'result']
        widgets = {'tested_on': DayInput()}

    def clean_tested_on(self):
        day = self.cleaned_data['tested_on']
        if day > periods.oslo_today():
            raise ValidationError(_('The day cannot be in the future.'))
        return day


class TreatmentAnswerForm(forms.ModelForm):
    class Meta:
        model = TreatmentAnswer
        fields = ['treatment', 'done_before_count', 'combination']


class TreatmentAnswerFormSet(RowFormSet):
    """The week's sea-lice treatments of the report's site, to answer what their records do not say."""

    def add_fields(self, form, index):
        super().add_fields(form, index)
        if 'treatment' in form.fields and self.instance.period is not None:
            form.fields['treatment'].queryset = lice.week_treatments(self.instance.site, self.instance.period)

    def clean(self):
        super().clean()
        rows = [row for row in self.kept_rows() if row.get('treatment')]
        if len({row['treatment'] for row in rows}) != len(rows):
            raise ValidationError(_('Each treatment can be listed once.'))
        together = [row['combination'] for row in rows if row.get('combination')]
        for number in sorted(set(together)):
            if together.count(number) < 2:
                raise ValidationError(_('Combination %(number)d is of one treatment: a combination is of at least '
                                        'two.') % {'number': number})


class UnitAnswerForm(forms.ModelForm):
    class Meta:
        model = UnitAnswer
        fields = ['unit', 'reduced_capacity']


class UnitAnswerFormSet(RowFormSet):
    """The units of the report's site, to say which were used for production of reduced capacity."""

    def add_fields(self, form, index):
        super().add_fields(form, index)
        if 'unit' in form.fields:
            form.fields['unit'].queryset = Tank.all_objects.filter(
                production_department__site_id=self.instance.site_id).order_by('code')

    def clean(self):
        super().clean()
        units = [row['unit'] for row in self.kept_rows() if row.get('unit')]
        if len(units) != len(set(units)):
            raise ValidationError(_('Each unit can be listed once.'))


ROW_OPTIONS = {'extra': 0, 'can_delete': True, 'max_num': 50, 'validate_max': True}
ResistanceSuspicionFormSet = forms.inlineformset_factory(
    Report, ResistanceSuspicion, form=ResistanceSuspicionForm, formset=RowFormSet, **ROW_OPTIONS)
SensitivityTestFormSet = forms.inlineformset_factory(
    Report, SensitivityTest, form=SensitivityTestForm, formset=RowFormSet, **ROW_OPTIONS)
TreatmentAnswerFormSet = forms.inlineformset_factory(
    Report, TreatmentAnswer, form=TreatmentAnswerForm, formset=TreatmentAnswerFormSet, **ROW_OPTIONS)
UnitAnswerFormSet = forms.inlineformset_factory(
    Report, UnitAnswer, form=UnitAnswerForm, formset=UnitAnswerFormSet, **ROW_OPTIONS)
