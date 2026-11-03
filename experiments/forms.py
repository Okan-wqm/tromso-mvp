"""The forms of Research › Experiments: an experiment's details (a tab of core.crud; its design and its places are grids
of their own, saved as wholes) and its team (a list of rows saved as a whole, core.crud.RowList)."""
from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils.translation import gettext_lazy as _, ngettext_lazy

from core.codes import next_code
from core.crud import DRAFT, RowFormSet, TabbedForm, tab_fields
from core.people import person_name, who_can
from farm.models import FeedingProtocol, Site, Species
from farm.models.feeding_protocol import ProtocolStatus
from farm.stock.dates import site_today
from farm.stock.services import STOCKABLE_SPECIES

from . import services
from .design import load
from .models import Experiment, FactorKind, GroupRole, Level, Member, Status

DETAILS_TABS = [('details', _('Details'), ['name', 'species', 'site', 'hypothesis', 'primary_endpoint', 'starts_on',
                                           'duration_days', 'notes'])]
# What a started experiment fixes (the database refuses a change too: migration 0002).
FIXED_WHEN_STARTED = ('hypothesis', 'primary_endpoint', 'starts_on', 'duration_days')
# A trial uses a species the farm grows or tries out (STOCKABLE_SPECIES: the batch's own rule).
DATE = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')


class ExperimentForm(TabbedForm):
    """An experiment's details. Its species and site are chosen once (a unit holds one species, and one clock gives
    the day key); once it has started its hypothesis, endpoint, day 0 and duration are fixed too: the design is
    pre-registered, and a changed trial is a copy. The number is given on saving (core.codes.next_code, inside the
    creating transaction) and never changes."""

    tabs = DETAILS_TABS
    fixed_after_creation = ('species', 'site')

    class Meta:
        model = Experiment
        fields = tab_fields(DETAILS_TABS)
        widgets = {
            'hypothesis': forms.Textarea(attrs={'rows': 4}),
            'starts_on': DATE,
            'duration_days': forms.NumberInput(attrs={'min': 1, 'inputmode': 'numeric'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }
        help_texts = {
            'species': _('One species per experiment: a unit holds one.'),
            'site': _('One site per experiment: its clock gives the days.'),
            'hypothesis': _('What the trial tests, before it starts. Needed to start it.'),
            'primary_endpoint': _('The one variable the trial is judged on. Needed to start it.'),
            'starts_on': _('Day 0, the baseline weighing, on the site’s clock. The last day, the final weighing, is '
                           'this many days later.'),
            'duration_days': _('Days from the baseline weighing to the final weighing.'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        stored = self.instance
        species = Species.objects.filter(status__in=STOCKABLE_SPECIES)
        if stored.species_id:
            species = Species.objects.filter(Q(status__in=STOCKABLE_SPECIES) | Q(pk=stored.species_id))
        self.fields['species'].queryset = species.order_by('common_name')
        self.fields['site'].queryset = Site.objects.order_by('name')
        if not stored._state.adding and stored.status != Status.DRAFT:
            for name in FIXED_WHEN_STARTED:
                self.fields[name].disabled = True
                self.fields[name].help_text = _('Fixed: the experiment has started. Copy it to change the design.')

    def save(self, commit=True):
        if self.instance._state.adding and not self.instance.code:
            self.instance.code = next_code(Experiment, f'E-{site_today(self.instance.site).year}-')
        return super().save(commit)


class PersonChoice(forms.ModelChoiceField):
    def label_from_instance(self, user):
        return person_name(user)


class MemberForm(forms.ModelForm):
    """One person of the team and their part. A person who can read Experiments is offered (someone who cannot could
    never see the experiment they were put in), and one kept from before stays in the list."""

    user = PersonChoice(label=_('Person'), queryset=get_user_model().objects.none())

    class Meta:
        model = Member
        fields = ['user', 'role']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        kept = Q(pk=self.instance.user_id) if self.instance.user_id else Q(pk__in=[])
        self.fields['user'].queryset = get_user_model().objects.filter(
            Q(pk__in=who_can('experiments', 'view_experiment').values('pk')) | kept
        ).order_by('first_name', 'last_name', 'username')

    def validate_constraints(self):
        # The list is saved as a whole, replacing the stored rows: a row is not checked against the rows it replaces.
        # The formset checks the person once and the lead (BaseMemberFormSet), the database holds both.
        pass


class BaseMemberFormSet(RowFormSet):
    default_error_messages = {
        'too_many_forms': ngettext_lazy('A team has at most %(num)d person.', 'A team has at most %(num)d people.',
                                        'num'),
    }

    def get_unique_error_message(self, unique_check):
        return _('This person is in the list twice.')

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        leads = [row for row in self.kept_rows() if row['role'] == Member.Role.LEAD]
        if not leads:
            raise ValidationError(_('The team needs a lead.'))
        if len(leads) > 1:
            raise ValidationError(_('An experiment has one lead.'))


MemberFormSet = forms.inlineformset_factory(
    Experiment, Member, form=MemberForm, formset=BaseMemberFormSet, extra=0, can_delete=True, max_num=50,
    validate_max=True,
)


# ---- the design: a grid of factors and a grid of groups, saved as a whole (experiments/services.py) ------------------
MAX_FACTORS, MAX_GROUPS = 12, 60
CELL_KINDS = ('diet', 'label', 'value')


class DesignForm(forms.Form):
    """The experiment's version the design grids were built on (two people saving at once: the second is told), and the
    errors that belong to the design as a whole."""

    version = forms.IntegerField(widget=forms.HiddenInput)


class FactorRowForm(forms.Form):
    """A factor: a name, its kind and, for a quantity, the unit of its levels. A change of name or kind renders the grid
    again, so the groups get the column (data-refresh)."""

    id = forms.UUIDField(widget=forms.HiddenInput, required=False)
    name = forms.CharField(label=_('Factor'), max_length=60, widget=forms.TextInput(attrs={'data-refresh': DRAFT}))
    kind = forms.ChoiceField(label=_('Kind'), choices=FactorKind.choices,
                             widget=forms.Select(attrs={'data-refresh': DRAFT}))
    unit = forms.CharField(label=_('Unit of its levels'), max_length=20, required=False,
                           widget=forms.TextInput(attrs={'placeholder': _('e.g. °C')}))


class BaseFactorFormSet(forms.BaseFormSet):
    def kept(self):
        """The cleaned factors to keep, in the order of the grid."""
        return [form.cleaned_data for form in self.forms if form.cleaned_data and not form.cleaned_data.get('DELETE')]

    def clean(self):
        if any(self.errors):
            return
        if sum(row['kind'] == FactorKind.DIET for row in self.kept()) > 1:
            raise ValidationError(_('An experiment has one diet factor.'))


FactorFormSet = forms.formset_factory(FactorRowForm, formset=BaseFactorFormSet, extra=0, can_delete=True,
                                      max_num=MAX_FACTORS, validate_max=True)


class ProtocolChoice(forms.ModelChoiceField):
    def label_from_instance(self, protocol):
        return protocol.name


class GroupRowForm(forms.Form):
    """A group: its name and role, a level of each factor (the diet a protocol, another factor a label and perhaps a
    number) and how many replicates it has. `columns` are the factors, in the order of the grid."""

    id = forms.UUIDField(widget=forms.HiddenInput, required=False)
    name = forms.CharField(label=_('Group'), max_length=60)
    role = forms.ChoiceField(label=_('Role'), choices=GroupRole.choices)
    replicates = forms.IntegerField(label=_('Replicates'), min_value=1, max_value=99,
                                    widget=forms.NumberInput(attrs={'min': 1, 'max': 99, 'inputmode': 'numeric'}))

    def __init__(self, *args, columns=(), protocols=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.columns = list(columns)
        for column in self.columns:
            number, label = column['index'], column['name']
            if column['kind'] == FactorKind.DIET:
                self.fields[f'diet_{number}'] = ProtocolChoice(
                    label=label, queryset=protocols, required=False, empty_label=_('Not chosen'))
            else:
                self.fields[f'label_{number}'] = forms.CharField(label=label, max_length=60, required=False)
                self.fields[f'value_{number}'] = forms.DecimalField(
                    label=_('%(factor)s: number') % {'factor': label}, max_digits=12, decimal_places=4,
                    required=False, localize=True, widget=forms.TextInput(attrs={'inputmode': 'decimal'}))

    def cells(self):
        """[(column, [the bound fields of its cell])] in the order of the grid."""
        return [(column, [self[f'diet_{column["index"]}']] if column['kind'] == FactorKind.DIET
                 else [self[f'label_{column["index"]}'], self[f'value_{column["index"]}']])
                for column in self.columns]


class BaseGroupFormSet(forms.BaseFormSet):
    def __init__(self, *args, columns=(), protocols=None, **kwargs):
        super().__init__(*args, form_kwargs={'columns': columns, 'protocols': protocols}, **kwargs)
        self.columns = list(columns)

    def kept(self):
        return [form.cleaned_data for form in self.forms if form.cleaned_data and not form.cleaned_data.get('DELETE')]


GroupFormSet = forms.formset_factory(GroupRowForm, formset=BaseGroupFormSet, extra=0, can_delete=True,
                                     max_num=MAX_GROUPS, validate_max=True)


def _posted_total(data, prefix, limit):
    try:
        return min(int(data.get(f'{prefix}-TOTAL_FORMS', 0)), limit)
    except ValueError:
        return 0


def posted_columns(data):
    """The factors a posted grid has, as the groups' columns: those with a name that are not marked for removal, each
    with the index of its row, which names its cells (`diet_<index>`, `label_<index>`, `value_<index>`)."""
    columns = []
    for index in range(_posted_total(data, 'factors', MAX_FACTORS)):
        name = data.get(f'factors-{index}-name', '').strip()
        if name and not data.get(f'factors-{index}-DELETE'):
            kind = data.get(f'factors-{index}-kind', '')
            columns.append({'index': index, 'name': name,
                            'kind': kind if kind in FactorKind.values else FactorKind.OTHER,
                            'unit': data.get(f'factors-{index}-unit', '').strip()})
    return columns


def _drafted(data, prefix, names, limit):
    """The rows of a posted grid as typed, those marked for removal left out."""
    rows = []
    for index in range(_posted_total(data, prefix, limit)):
        if data.get(f'{prefix}-{index}-DELETE'):
            continue
        rows.append({name: data[f'{prefix}-{index}-{name}'] for name in names if f'{prefix}-{index}-{name}' in data})
    return rows


def design_protocols(experiment):
    """The protocols a diet cell offers: the active ones of the experiment's species, and those its levels already
    name (one retired since stays in its cell, and the design says so)."""
    used = Level.objects.filter(factor__experiment=experiment, protocol__isnull=False).values('protocol')
    return FeedingProtocol.objects.filter(
        Q(status=ProtocolStatus.ACTIVE, species=experiment.species) | Q(pk__in=used)).order_by('name')


def design_forms(experiment, data=None, draft=None, add_factor=False):
    """(DesignForm, FactorFormSet, GroupFormSet) of an experiment: bound to `data` (a save), from a `draft` (a column
    changed or a factor added: the rows entered so far, nothing validated, `add_factor` adding an empty factor row)
    or from the stored design (a new experiment starts with its diet factor and no group)."""
    protocols = design_protocols(experiment)
    if data is not None:
        columns = posted_columns(data)
        return (DesignForm(data), FactorFormSet(data, prefix='factors'),
                GroupFormSet(data, prefix='groups', columns=columns, protocols=protocols))
    if draft is None:
        return stored_design_forms(experiment, protocols)
    # The rows as typed, the rows marked for removal left out; a removed factor renumbers the cells of those after it.
    columns = posted_columns(draft)
    factor_rows = _drafted(draft, 'factors', ('id', 'name', 'kind', 'unit'), MAX_FACTORS)
    if add_factor:
        factor_rows.append({'kind': FactorKind.OTHER})
    kept = [index for index in range(_posted_total(draft, 'factors', MAX_FACTORS))
            if not draft.get(f'factors-{index}-DELETE')]
    renumber = {old: new for new, old in enumerate(kept)}
    names = ['id', 'name', 'role', 'replicates']
    for column in columns:
        names += ([f'diet_{column["index"]}'] if column['kind'] == FactorKind.DIET
                  else [f'label_{column["index"]}', f'value_{column["index"]}'])
    group_rows = []
    for row in _drafted(draft, 'groups', names, MAX_GROUPS):
        moved = {}
        for key, value in row.items():
            kind, _separator, number = key.rpartition('_')
            moved[f'{kind}_{renumber[int(number)]}' if kind in CELL_KINDS else key] = value
        group_rows.append(moved)
    renumbered = [{**column, 'index': renumber[column['index']]} for column in columns]
    return (DesignForm(initial={'version': draft.get('version')}), FactorFormSet(initial=factor_rows, prefix='factors'),
            GroupFormSet(initial=group_rows, prefix='groups', columns=renumbered, protocols=protocols))


def stored_design_forms(experiment, protocols):
    """The grids of the stored design (design.load): its factors and groups, each group's level in each column."""
    design = load(experiment)
    factors = [{'id': factor.pk, 'name': factor.name, 'kind': factor.kind, 'unit': factor.unit}
               for factor in design.factors] or [{'name': str(_('Diet')), 'kind': FactorKind.DIET}]
    columns = [{'index': index, 'name': row['name'], 'kind': row['kind'], 'unit': row.get('unit', '')}
               for index, row in enumerate(factors)]
    groups = []
    for group in design.groups:
        row = {'id': group.pk, 'name': group.name, 'role': group.role,
               'replicates': len(design.replicates.get(group.pk, [])) or 1}
        for index, factor in enumerate(design.factors):
            level = design.level_of(group, factor)
            if level is None:
                continue
            if factor.kind == FactorKind.DIET:
                row[f'diet_{index}'] = level.protocol_id
            else:
                row[f'label_{index}'], row[f'value_{index}'] = level.label, level.value
        groups.append(row)
    return (DesignForm(initial={'version': experiment.version}), FactorFormSet(initial=factors, prefix='factors'),
            GroupFormSet(initial=groups, prefix='groups', columns=columns, protocols=protocols))


def design_rows(factors, groups):
    """The rows a valid grid gives the service (experiments.services): the factors in the order of the grid, and
    each group with one cell per factor in the same order. A cell is named by the number of its factor's row."""
    kept = [form for form in factors.forms if form.cleaned_data and not form.cleaned_data.get('DELETE')]
    rows = [services.FactorRow(name=form.cleaned_data['name'], kind=form.cleaned_data['kind'],
                               unit=form.cleaned_data['unit'], id=form.cleaned_data['id']) for form in kept]
    numbers = [int(form.prefix.rpartition('-')[2]) for form in kept]
    result = []
    for group in groups.kept():
        cells = []
        for number, row in zip(numbers, rows):
            if row.kind == FactorKind.DIET:
                cells.append(services.Cell(protocol=group.get(f'diet_{number}')))
            else:
                cells.append(services.Cell(label=(group.get(f'label_{number}') or '').strip(),
                                           value=group.get(f'value_{number}')))
        result.append(services.GroupRow(name=group['name'], role=group['role'], replicates=group['replicates'],
                                        cells=cells, id=group['id']))
    return rows, result
