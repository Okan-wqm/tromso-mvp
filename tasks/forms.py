"""The task forms: a task and a recurring task (core.crud TabbedForm), their checklists (core.crud.RowList), and
the small dialogs that complete or cancel a task.

Every link is chosen from a list, never typed (TSK-01, TSK-02): the place is one Location select of every live
place, narrowed by the Site select (core.widgets.DependentSelect; "Without a site" offers the production
departments without one and what is in them); the batch, offered for a task, is one with fish at the chosen
place now, narrowed by the Location select (a chain: site → location → batch); the people are the active
users who can read Tasks (tasks.read.readers). The server checks what the browser only guides."""
from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext, gettext_lazy as _, ngettext_lazy

from core.crud import BoundedModelForm, RowFormSet, TabbedForm, tab_fields
from core.widgets import DayInput, DependentSelect, NONE
from farm.models import Batch, Site, Tank
from farm.models.site import zone_of

from farm.stock import read as stock_read

from . import places, read
from .models import (
    MAX_CHECKLIST, Frequency, Task, TaskChecklistItem, TaskNote, TaskSeries, TaskSeriesChecklistItem,
)

DATE = DayInput()
TIME = forms.TimeInput(attrs={'type': 'time'}, format='%H:%M')


def shared_today():
    """Today on the clock every site shares, else the company's: a form's first date before a place is chosen."""
    zones = {zone_of(site) for site in Site.objects.all()}
    zone = zones.pop() if len(zones) == 1 else zone_of(None)
    return timezone.localdate(timezone=zone)


class PersonChoice(forms.ModelMultipleChoiceField):
    """The people a task is for, by their full name; one kept from before who can no longer be chosen says so."""

    def __init__(self, *args, **kwargs):
        self.eligible = set()
        super().__init__(*args, **kwargs)

    def label_from_instance(self, user):
        name = read.person(user)
        if user.pk in self.eligible:
            return name
        return gettext('%(person)s (can no longer be chosen)') % {'person': name}


class PlaceForm(TabbedForm):
    """The Site and Location fields and the people of a task or a recurring task (see the module)."""

    site = forms.ChoiceField(label=_('Site'), help_text=_('Narrows the places offered under Location. “Without a '
                                                          'site” offers the production departments that have none '
                                                          'and what is in them.'))
    location = forms.ChoiceField(label=_('Location'), help_text=_('Where the job is done: a whole site, a production '
                                                                  'department, a system, a unit or equipment.'))
    assignees = PersonChoice(label=_('Assignees'), queryset=get_user_model().objects.none(),
                             widget=forms.CheckboxSelectMultiple,
                             help_text=_('Who does it: active users who can read Tasks. Each of them sees it, and any '
                                         'of them can start and complete it.'))

    def __init__(self, *args, place=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.places = places.live()
        grouped, belongs = places.choices(self.places)
        sites = [(str(site.pk), site.name) for site in self.places['site']]
        without = [(NONE, _('Without a site'))] if None in belongs.values() else []
        self.fields['site'].choices = [('', _('Select a site')), *sites, *without]
        self.fields['location'].choices = [('', _('Select a place')), *grouped]
        DependentSelect.apply(self.fields['location'], 'site', belongs)

        stored = None if self.instance._state.adding else self.instance.place
        chosen = stored if stored is not None else place
        if chosen is not None:
            self.initial['site'] = places.site_key(chosen)
            if places.token(chosen) in belongs:
                self.initial['location'] = places.token(chosen)
            else:
                self.fields['location'].help_text = gettext('Its place, %(place)s, is deleted: choose another.') % {
                    'place': places.label(chosen)}
        elif len(sites) == 1 and not without:
            self.initial['site'] = sites[0][0]

        # The people offered, and the only ones accepted: who can be given tasks now, and on an existing one
        # whoever it is for already (kept, marked, until someone takes them off).
        eligible = read.readers()
        kept = [] if self.instance._state.adding else list(self.instance.assignees.values_list('pk', flat=True))
        people = self.fields['assignees']
        people.queryset = (get_user_model().objects.filter(Q(pk__in=eligible.values('pk')) | Q(pk__in=kept))
                           .order_by('first_name', 'last_name', 'username'))
        people.eligible = set(eligible.values_list('pk', flat=True))

    def clean_location(self):
        place = places.find(self.cleaned_data['location'], self.places)
        if place is None:
            raise forms.ValidationError(_('Choose a place from the list.'))
        return place

    def clean(self):
        cleaned = super().clean()
        place = cleaned.get('location')
        if place is not None and 'site' in cleaned:
            if places.site_key(place) != cleaned['site']:
                self.add_error('location', _('This place is not on the chosen site.'))
            else:
                self.instance.set_place(place)
        return cleaned


# ---- a task ------------------------------------------------------------------------------------------------
TASK_TABS = [
    ('general', _('General'), ['title', 'description', 'category', 'priority']),
    ('where', _('Where'), ['site', 'location', 'batch']),
    ('when', _('When and who'), ['due_date', 'due_time', 'assignees']),
]


class BatchChoice(forms.ModelChoiceField):
    def label_from_instance(self, batch):
        return f'{batch.code} · {batch.species.common_name}'


def stocked_batches():
    """{batch id: the tokens of the places it has fish at now}: its units, their production departments,
    systems and sites (from the stock ledger's live lines)."""
    rows = stock_read.present('batch_id', 'unit_id')
    units = Tank.objects.select_related('production_department__site', 'system').in_bulk(
        {row['unit_id'] for row in rows})
    found = {}
    for row in rows:
        unit = units.get(row['unit_id'])
        if unit is None:
            continue
        department = unit.production_department
        at = [unit, department, unit.system, department.site]
        found.setdefault(row['batch_id'], set()).update(places.token(place) for place in at if place is not None)
    return found


class TaskForm(PlaceForm):
    """A task: what, where (and which fish), when and for whom. Its checklist is a list of its own (TaskChecklist)
    once the task exists."""

    tabs = TASK_TABS
    batch = BatchChoice(label=_('Batch'), queryset=Batch.objects.none(), required=False,
                        help_text=_('Optional: the fish the job is about, a batch with fish at the chosen place now.'))

    class Meta:
        model = Task
        fields = ['title', 'description', 'category', 'priority', 'batch', 'due_date', 'due_time', 'assignees']
        help_texts = {
            'due_date': _('On the clock of the place’s site; a task not done by then is overdue.'),
            'due_time': _('Optional: from this time on the due day the task is overdue.'),
        }
        widgets = {
            'title': forms.TextInput(attrs={'placeholder': _('e.g. Clean the drum filter')}),
            'description': forms.Textarea(attrs={'rows': 3}),
            'due_date': DATE,
            'due_time': TIME,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.stocked = stocked_batches()
        stored = self.instance.batch if not self.instance._state.adding and self.instance.batch_id else None
        belongs = {str(pk): sorted(tokens) for pk, tokens in self.stocked.items()}
        if stored is not None and str(stored.pk) not in belongs:
            belongs[str(stored.pk)] = [places.token(self.instance.place)]   # kept while its place stays
        field = self.fields['batch']
        field.queryset = (Batch.all_objects.filter(pk__in=belongs).select_related('species')
                          .order_by('-input_date', '-code'))
        field.empty_label = _('None')
        DependentSelect.apply(field, 'location', belongs)
        if self.instance._state.adding:
            self.fields['due_date'].initial = shared_today()

    def clean(self):
        cleaned = super().clean()
        batch, place = cleaned.get('batch'), cleaned.get('location')
        if batch is None or place is None or 'location' in self.errors:
            return cleaned
        # A batch is checked when it is chosen or its place changes; a task keeps its batch after the fish left.
        chosen = self.instance._state.adding or {'batch', 'location'} & set(self.changed_data)
        if chosen and places.token(place) not in self.stocked.get(batch.pk, ()):
            self.add_error('batch', _('%(batch)s has no fish at %(place)s now.') % {
                'batch': batch.code, 'place': places.label(place)})
        return cleaned


class CompleteForm(forms.Form):
    note = forms.CharField(label=_('Completion note'), max_length=1000, required=False,
                           widget=forms.Textarea(attrs={'rows': 3}),
                           help_text=_('Optional: what was done or found, e.g. “2 dead fish removed”.'))


class CancelForm(forms.Form):
    reason = forms.CharField(label=_('Reason for cancelling'), max_length=500, widget=forms.Textarea(attrs={'rows': 3}),
                             help_text=_('E.g. “the unit was emptied”. The task stays among the completed ones with '
                                         'this reason, and can be reopened.'))


class NoteForm(forms.Form):
    body = forms.CharField(label=_('Note'), max_length=TaskNote.MAX_LENGTH, widget=forms.Textarea(attrs={'rows': 2}))


# ---- checklists ------------------------------------------------------------------------------------------
class ChecklistLineForm(BoundedModelForm):
    class Meta:
        fields = ['text']
        widgets = {'text': forms.TextInput(attrs={'placeholder': _('e.g. Check the oxygen in every tank')})}


class ChecklistFormSet(RowFormSet):
    default_error_messages = {
        'too_many_forms': ngettext_lazy('A checklist has at most %(num)d line.', 'A checklist has at most %(num)d lines.',
                                        'num'),
    }


STARTED = _('The checklist has been started: its lines can no longer be changed. Add a note instead.')


class TaskChecklistFormSet(ChecklistFormSet):
    """A task's lines, replaced as a whole until the first one is ticked; after that a tick is the only change
    (the source gave every line a new id on an edit and lost who ticked it, TSK-11)."""

    def clean(self):
        super().clean()
        if self.instance.checklist.filter(done_at__isnull=False).exists():
            raise forms.ValidationError(STARTED)


def checklist_formset(parent, model, formset):
    form = forms.modelform_factory(model, form=ChecklistLineForm, fields=['text'])
    return forms.inlineformset_factory(parent, model, form=form, formset=formset, extra=0, can_delete=True,
                                       max_num=MAX_CHECKLIST, validate_max=True)


TaskChecklistLines = checklist_formset(Task, TaskChecklistItem, TaskChecklistFormSet)
SeriesChecklistLines = checklist_formset(TaskSeries, TaskSeriesChecklistItem, ChecklistFormSet)


# ---- a recurring task ----------------------------------------------------------------------------------------
SERIES_TABS = [
    ('general', _('General'), ['title', 'description', 'category', 'priority']),
    ('where', _('Where'), ['site', 'location']),
    ('rule', _('Repeats'), ['frequency', 'interval', 'weekdays', 'day_of_month', 'due_time', 'starts_on', 'ends_on',
                            'is_active']),
    ('who', _('Who'), ['assignees']),
]
EVERY = {
    Frequency.DAILY: _('1 for every day, 2 for every other day, up to 52.'),
    Frequency.WEEKLY: _('1 for every week, 2 for every other week, up to 52; the weeks are counted from the first '
                        'day’s week.'),
    Frequency.MONTHLY: _('1 for every month, 3 for every quarter, up to 52; the months are counted from the first '
                         'day’s month.'),
}


class TaskSeriesForm(PlaceForm):
    """A recurring task: the task it plans, where, the rule, and for whom. Changing how often it repeats renders
    the form again with the fields of that rule (TabbedForm.refresh_on)."""

    tabs = SERIES_TABS
    refresh_on = ('frequency',)

    class Meta:
        model = TaskSeries
        fields = tab_fields([(key, label, [name for name in names if name not in ('site', 'location')])
                             for key, label, names in SERIES_TABS])
        help_texts = {
            'weekdays': _('The days of the week it is due.'),
            'day_of_month': _('1 to 31; in a shorter month the 29th, 30th and 31st fall on its last day.'),
            'due_time': _('Optional: from this time on the due day a task is overdue.'),
            'starts_on': _('Its tasks are made from this day on, up to two weeks ahead.'),
            'ends_on': _('Optional: no tasks after this day.'),
            'is_active': _('Untick to pause it: its tasks from today on that nobody has started are removed, and '
                           'none are made until it is ticked again.'),
        }
        widgets = {
            'title': forms.TextInput(attrs={'placeholder': _('e.g. Morning oxygen round')}),
            'description': forms.Textarea(attrs={'rows': 3}),
            'due_time': TIME,
            'starts_on': DATE,
            'ends_on': DATE,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        frequency = self.current('frequency') or Frequency.WEEKLY
        if frequency != Frequency.WEEKLY:
            del self.fields['weekdays']
        else:
            self.fields['weekdays'].required = True
        if frequency != Frequency.MONTHLY:
            del self.fields['day_of_month']
        else:
            self.fields['day_of_month'].required = True
        self.fields['interval'].help_text = EVERY[frequency]
        if self.instance._state.adding:
            self.fields['starts_on'].initial = shared_today()

    def clean(self):
        cleaned = super().clean()
        # The fields another rule has are not on the form: they are empty for this one.
        if 'weekdays' not in self.fields:
            self.instance.weekdays = []
        if 'day_of_month' not in self.fields:
            self.instance.day_of_month = None
        return cleaned
