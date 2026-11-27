"""The assignment dialogs of a table assigned to fish (a feeding protocol, a temperature profile: farm/models/
assignment.py), written once: several units at once on create (a row per unit, one group), one row on edit. A table's
own forms (farm/forms/feeding_protocol.py, temperature_profile.py) name their model, their table's field and their
words; the rules are here."""
from datetime import timedelta

from django import forms
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.utils.translation import gettext_lazy as _, ngettext

from core.crud import TabbedForm
from core.widgets import DayInput

from ..feeding import assignments
from ..models import Batch, StockMovement, Tank
from ..models.assignment import ProtocolStatus
from ..stock.dates import earliest, local_today, too_old


class UnitChoices(forms.ModelMultipleChoiceField):
    def label_from_instance(self, unit):
        place = unit.production_department.name
        if unit.production_department.site:
            place = f'{place} · {unit.production_department.site.name}'
        return f'{unit.code} · {unit.name} · {place}'


class BatchChoice(forms.ModelChoiceField):
    def label_from_instance(self, batch):
        return f'{batch.code} · {batch.species}' + (f' · {batch.name}' if batch.name else '')


class SubjectChoice(forms.ModelChoiceField):
    """A protocol or a profile, with its species."""

    def label_from_instance(self, subject):
        return f'{subject.name} · {subject.species}'


def batches_in_stock():
    """The live batches with fish now (farm.stock.read.present), the ones a table can be assigned to."""
    from ..stock import read
    return (Batch.objects.filter(pk__in=read.present('batch_id').values('batch_id')).select_related('species')
            .order_by('-input_date', '-code'))


def within_window(day, stored=None, unit=None):
    """A first day changed or new is at most the correction window back, as every daily record (farm/stock/dates.py):
    the days before are history."""
    if day != stored and day < earliest(unit):
        raise ValidationError(too_old(_('An assignment can start at most %(days)d days back.')))
    return day


def new_tabs(subject):
    return [('assignment', _('Assignment'), [subject, 'units', 'batch', 'valid_from', 'valid_until', 'notes'])]


def edit_tabs(subject):
    return [('assignment', _('Assignment'), list(assignments.fields_of(subject)))]


HELP = {
    'valid_from': _('The first day it feeds by, on the farm’s clock.'),
    'valid_until': _('Optional: the last day. Empty: until it is ended.'),
}
WIDGETS = {'valid_from': DayInput(), 'valid_until': DayInput(), 'notes': forms.Textarea(attrs={'rows': 2})}


def _subject_model(model):
    return model._meta.get_field(model.SUBJECT).related_model


class NewAssignmentBase(TabbedForm):
    """Assigns an active table: to units (one or more: a row each), to a whole batch (one row, which follows the batch
    through transfers and splits), or to a batch in chosen units (a row per unit). The units and the batch chosen say
    which; the rows are written together, with one group (TargetedAssignment.group_id). A subclass sets Meta.model, its
    table's field first in Meta.fields, `tabs`, `select_label` and `units_help`."""

    select_label = ''
    units_help = ''
    units = UnitChoices(label=_('Units'), queryset=Tank.objects.none(), required=False,
                        widget=forms.CheckboxSelectMultiple)

    class Meta:
        fields = ['batch', 'valid_from', 'valid_until', 'notes']
        field_classes = {'batch': BatchChoice}
        widgets = WIDGETS

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        subject = self._meta.model.SUBJECT
        self.fields[subject].queryset = (_subject_model(self._meta.model).objects
                                         .filter(status=ProtocolStatus.ACTIVE).select_related('species')
                                         .order_by('name'))
        self.fields[subject].empty_label = self.select_label
        self.fields['units'].help_text = self.units_help
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
        self.rows, errors = assignments.rows(cleaned[self._meta.model.SUBJECT], units, batch, cleaned['valid_from'],
                                             cleaned.get('valid_until'), cleaned.get('notes', ''))
        for error in errors:
            # What concerns a field the form shows is said once by the form's own check of the record; what
            # concerns the row as a whole (another table on those days) is said per unit.
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


class AssignmentBase(TabbedForm):
    """One assignment row. Its unit and batch are chosen once. Before its first day everything else may change; from
    then on only its last day and notes (the days it applied to keep their table), and its last day is yesterday at the
    earliest (ending it today still applies today). A subclass sets Meta.model, Meta.fields and `tabs`; the
    message for a last day too early is its model's KEPT."""

    fixed_after_creation = ('unit', 'batch')

    class Meta:
        field_classes = {'batch': BatchChoice}
        widgets = WIDGETS
        help_texts = HELP

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        stored, subject = self.instance, self._meta.model.SUBJECT
        self.today = stored.today()
        model = _subject_model(self._meta.model)
        tables = model.objects.filter(status=ProtocolStatus.ACTIVE)
        if stored.subject_id:
            tables = tables | model.objects.filter(pk=stored.subject_id)
        self.fields[subject].queryset = tables.select_related('species').order_by('name')
        self.fields['batch'].queryset = Batch.all_objects.select_related('species')
        self.fields['unit'].queryset = Tank.all_objects.all()
        self.started = stored.pk is not None and stored.valid_from <= self.today
        if self.started:
            for name in (subject, 'valid_from'):
                self.fields[name].disabled = True
                self.fields[name].help_text = _('Fixed: the row has started. End it and add another to change it.')

    def clean_valid_until(self):
        until = self.cleaned_data.get('valid_until')
        stored = self.instance.valid_until
        if self.started and until != stored and until is not None and until < self.today - timedelta(days=1):
            raise ValidationError(str(self._meta.model.KEPT))
        return until

    def clean_valid_from(self):
        return within_window(self.cleaned_data['valid_from'], self.instance.valid_from, self.instance.unit)
