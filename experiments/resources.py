"""Research › Experiments, one tab of core.crud: the list (experiments, mine, templates), the experiment's form with its
Details, Design, Places and Team tabs (the design is a grid of factors and a grid of groups, the places a grid of
replicates with a seeded deal, each saved as a whole by its own view),
the read page, and delete through the delete plan (a draft only: the model says so). The creator is the lead of a new
experiment."""
from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.urls import path, reverse
from django.utils import formats
from django.utils.translation import gettext, gettext_lazy as _, ngettext_lazy, pgettext_lazy

from core import listprops as L
from core.crud import DRAFT, Resource, ResourceView, RowList, UpdateView, done, filter_by, render_page
from core.people import person_name
from farm.models import Site, Species, System, Tank
from farm.stock.dates import site_today

from . import design as design_module, read, services
from .forms import (
    CopyForm, ExperimentForm, MemberFormSet, ReleaseForm, ReplaceForm, StartForm, design_forms, design_rows,
    place_rows, places_forms,
)
from .models import AllocationMethod, Experiment, Member, ReplicateUnit, Status

EXPERIMENTS, MINE, TEMPLATES = '', 'mine', 'templates'
VIEWS = (EXPERIMENTS, MINE, TEMPLATES)
ADD_FACTOR = 'add_factor'          # the marker of the button that adds a factor row to the design grid
READ_TABS = {'overview': _('Overview'), 'data': _('Data'), 'team': _('Team')}


def data_links(user, cell):
    """The farm's own lists with this tank and these days chosen (their `unit`, `from` and `to` filters), those the person
    may read: the feeding records, the treatments, the sea-lice counts, the water, and the unit's drawer."""
    days = {'unit': cell.unit.pk, 'from': cell.first.isoformat(), 'to': cell.last.isoformat()}
    return [(label, f'{reverse(name)}?{urlencode(query)}') for label, name, perm, query in (
        (_('Feeding records'), 'farm:feeding_records', 'farm.view_feedingrecord', days),
        (_('Treatments'), 'farm:treatments', 'farm.view_treatment', days),
        (_('Sea-lice counts'), 'farm:lice_counts', 'farm.view_licecount', days),
        (_('Water chemistry'), 'farm:water', 'farm.view_watermeasurement', {**days, 'view': 'history'}),
        (_('Production units'), 'farm:production_units', 'farm.view_stockoperation', {'unit': cell.unit.pk}))
        if user.has_perm(perm)]


def amend_links(experiment, cell):
    """[(label, address)] of what can be done to a tank of a running experiment: release it, or replace it."""
    return [(_('Release'), reverse('experiments:experiment_release', args=[experiment.pk, cell.id])),
            (_('Replace'), reverse('experiments:experiment_replace', args=[experiment.pk, cell.id]))]


class TeamList(RowList):
    """An experiment's team, saved as a whole list on its Team tab: a person and their part, one lead."""

    key, tab, label = 'team', 'team', _('Team')
    formset = MemberFormSet
    saved = ngettext_lazy('%(count)d person saved.', '%(count)d people saved.', 'count')

    @classmethod
    def rows(cls, experiment):
        return super().rows(experiment).select_related('user')

    @classmethod
    def describe(cls, row):
        """e.g. "Kari Nord (Lead)", in English like every log row."""
        return f'{person_name(row.user)} ({row.get_role_display()})'


class ExperimentResource(Resource):
    model = Experiment
    form_class = ExperimentForm
    name, plural = _('experiment'), _('experiments')
    url_prefix = 'research/experiments'
    search_fields = ['code', 'name', 'hypothesis']
    list_template = 'experiments/experiment_list.html'
    form_template = 'experiments/experiment_form.html'
    detail_template = 'experiments/experiment_detail.html'
    icon = 'flask'
    row_lists = (TeamList,)
    page_size = 50

    @classmethod
    def queryset(cls):
        return super().queryset().select_related('site', 'species')

    @classmethod
    def after_save(cls, request, experiment, created):
        """The creator leads a new experiment (logged as a change of its team, as any later one)."""
        if created:
            TeamList.save(request.user, experiment, [{'user': request.user, 'role': Member.Role.LEAD}],
                          cls.entity_type())

    @classmethod
    def filter_list(cls, request, objects):
        view = request.GET.get('view', '')
        view = view if view in VIEWS else EXPERIMENTS
        objects = objects.filter(is_template=view == TEMPLATES)
        if view == MINE:
            objects = objects.filter(members__user=request.user)       # one row a person: no duplicates
        sites = Site.objects.filter(experiments__is_deleted=False).distinct().order_by('name')
        species = Species.objects.filter(experiments__is_deleted=False).distinct().order_by('common_name')
        objects, chosen_site = filter_by(request, objects, 'site', sites, 'site_id')
        objects, chosen_species = filter_by(request, objects, 'species', species, 'species_id')
        objects, chosen_status = filter_by(request, objects, 'status', Status.choices, 'status')
        live = Q(groups__is_deleted=False)
        objects = objects.annotate(
            group_count=Count('groups', filter=live, distinct=True),
            replicate_count=Count('groups__replicates', filter=live & Q(groups__replicates__is_deleted=False),
                                  distinct=True))
        return objects, {'view': view, 'views': [(EXPERIMENTS, _('Experiments')), (MINE, _('Mine')),
                                                  (TEMPLATES, _('Templates'))],
                         'sites': sites, 'chosen_site': chosen_site, 'species_list': species,
                         'chosen_species': chosen_species, 'statuses': Status.choices, 'chosen_status': chosen_status}

    # The new look (core/listprops.py): the classic list's words (experiments/experiment_list.html), its rows as the
    # island's. The rows are the ones the list view read (its queryset and scope): the page shows nothing the classic one
    # does not, and no field of an experiment the classic list leaves out.
    search_placeholder = _('Search by number, name or hypothesis')
    empty_text = _('Plan a trial: its hypothesis, its groups and the tanks they get.')
    STATUS_CHIPS = {Status.RUNNING: 'ok', Status.CLOSED: 'neutral', Status.DRAFT: 'note'}

    @classmethod
    def list_filters(cls, view, context):
        return [
            L.choice('status', _('Status'), context['chosen_status'], [('', _('All statuses')), *context['statuses']]),
            L.choice('site', _('Site'), context['chosen_site'],
                     [('', _('All sites')), *((site.pk, site.name) for site in context['sites'])]),
            L.choice('species', pgettext_lazy('singular', 'Species'), context['chosen_species'],
                     [('', _('All species')), *((species.pk, species.common_name) for species in context['species_list'])]),
        ]

    @classmethod
    def list_rows(cls, view, objects, context):
        rows = []
        for experiment in objects:
            actions = []
            if context.get('can_change'):
                actions.append(L.link(view.url('edit', experiment.pk), gettext('Edit %(name)s') % {'name': experiment.name},
                                      'pencil'))
            if context.get('can_delete') and experiment.status == Status.DRAFT:
                actions.append(L.link(view.url('delete', experiment.pk),
                                      gettext('Delete %(name)s') % {'name': experiment.name}, 'trash', danger=True))
            chips = [L.chip('note', gettext('Template'))] if experiment.is_template else []
            rows.append(L.row(experiment.pk, {
                'experiment': L.cell(experiment.name, href=view.url('detail', experiment.pk), strong=True,
                                     sub=[f'{experiment.code} · {experiment.get_primary_endpoint_display()}'
                                          if experiment.primary_endpoint else experiment.code]),
                'status': L.cell(chip=L.chip(cls.STATUS_CHIPS.get(experiment.status, 'neutral'),
                                             experiment.get_status_display()), chips=chips),
                'site': L.cell(experiment.site.name),
                'species': L.cell(experiment.species.common_name),
                'day0': L.cell(formats.date_format(experiment.starts_on, 'DATE_FORMAT') if experiment.starts_on else '—'),
                'days': L.cell(experiment.duration_days),
                'groups': L.cell(experiment.group_count),
                'replicates': L.cell(experiment.replicate_count),
            }, actions))
        return {
            'tabs': L.tabs(_('Experiments'), [(f'?view={value}' if value else '?', label, None, context['view'] == value)
                                              for value, label in context['views']]),
            'notices': [L.notice('trial', 'neutral', _(
                'A trial of one species on one site: its groups, their replicates and the tanks and days each is booked '
                'to. A draft reserves its tanks; starting it fixes its design, and the figures are read from the farm’s '
                'own records.'))],
            'columns': [L.column('experiment', _('Experiment')), L.column('status', _('Status')), L.column('site', _('Site')),
                        L.column('species', pgettext_lazy('singular', 'Species')), L.column('day0', _('Day 0')),
                        L.column('days', _('Days'), numeric=True), L.column('groups', _('Groups'), numeric=True),
                        L.column('replicates', _('Replicates'), numeric=True)],
            'rows': rows}

    @classmethod
    def detail_extras(cls, request, experiment):
        """The read page: the details, and one of its three parts (`?tab=`): the Overview (where the experiment is in its
        days, what is wrong with a draft or what a started one deviated from, and a replicate a row with its figures read from
        the farm's records), the Data
        (per tank its days and links to the farm's own lists with the tank and the days chosen) and the Team."""
        tab = request.GET.get('tab', '')
        tab = tab if tab in READ_TABS else 'overview'
        today = site_today(experiment.site)
        extras = {
            'tab': tab, 'tabs': [(key, label, f'?tab={key}') for key, label in READ_TABS.items()],
            'team': TeamList.rows(experiment),
            'start_url': reverse('experiments:experiment_start', args=[experiment.pk]),
            'copy_url': reverse('experiments:experiment_copy', args=[experiment.pk]),
            'can_start': request.user.has_perm(cls.perm('change')) and experiment.status == Status.DRAFT
            and not experiment.is_template,
            'phase': read.progress(experiment, today), 'today': today}
        if tab == 'overview':
            extras['rows'] = read.overview(experiment, today)
            if experiment.status == Status.DRAFT and not experiment.is_template:
                extras['findings'] = design_module.assess(experiment)
            elif experiment.status != Status.DRAFT:
                extras['deviations'] = read.deviations(experiment, today)
        elif tab == 'data':
            can_amend = experiment.status == Status.RUNNING and request.user.has_perm(cls.perm('change'))
            extras['tanks'] = [{'data': item, 'links': data_links(request.user, item.cell),
                                'actions': amend_links(experiment, item.cell) if can_amend and item.cell.last >= today
                                else []} for item in read.data(experiment)]
        return extras

    @classmethod
    def form(cls, request, *args, **kwargs):
        """The form knows who is saving: a changed span moves the placements, logged as theirs."""
        return super().form(request, *args, user=request.user, **kwargs)

    @classmethod
    def edit_extras(cls, request, experiment, design=None, places=None):
        """The team's list, the Design tab (the factors' grid and the groups' grid, the stored design or the rows of a
        posted one, and what is wrong with the stored design) and the Places tab (the pool and the seed, a row a
        replicate, and where the tanks stand)."""
        extras = super().edit_extras(request, experiment)
        form, factors, groups = design or design_forms(experiment)
        stored = design_module.load(experiment)
        frozen = experiment.status != Status.DRAFT
        window = services.span(experiment)
        places_form, place_forms = places or places_forms(experiment)
        return {**extras, 'design_form': form, 'factors': factors, 'groups': groups, 'frozen': frozen,
                'findings': None if frozen else design_module.assess(experiment, stored),
                'table': design_module.table(stored), 'add_factor': ADD_FACTOR,
                'design_url': reverse('experiments:experiment_design', args=[experiment.pk]),
                'places_form': places_form, 'places': place_forms, 'span': window,
                'cells': read.cells(experiment) if frozen else [],
                'allocation': allocation_banner(experiment), 'error_df': read.error_df(experiment),
                'places_url': reverse('experiments:experiment_places', args=[experiment.pk]),
                'start_url': reverse('experiments:experiment_start', args=[experiment.pk]),
                'copy_url': reverse('experiments:experiment_copy', args=[experiment.pk])}

    @classmethod
    def urls(cls):
        p = cls.url_prefix
        return [*super().urls(),
                path(f'{p}/<uuid:pk>/design/', ExperimentDesignView.as_view(resource=cls), name='experiment_design'),
                path(f'{p}/<uuid:pk>/places/', ExperimentPlacesView.as_view(resource=cls), name='experiment_places'),
                path(f'{p}/<uuid:pk>/start/', ExperimentStartView.as_view(resource=cls), name='experiment_start'),
                path(f'{p}/<uuid:pk>/copy/', ExperimentCopyView.as_view(resource=cls), name='experiment_copy'),
                path(f'{p}/<uuid:pk>/release/<uuid:placement>/', ExperimentReleaseView.as_view(resource=cls),
                     name='experiment_release'),
                path(f'{p}/<uuid:pk>/replace/<uuid:placement>/', ExperimentReplaceView.as_view(resource=cls),
                     name='experiment_replace')]


def allocation_banner(experiment):
    """How the tanks were given to the replicates, as the Places tab says it (nothing, while they have not been)."""
    if experiment.allocation_method == AllocationMethod.RANDOMISED:
        return gettext('Randomised, seed %(seed)d.') % {'seed': experiment.allocation_seed}
    if experiment.allocation_method == AllocationMethod.MANUAL:
        return gettext('Placed by hand: %(reason)s') % {'reason': experiment.allocation_note}
    return ''


class ExperimentDesignView(ResourceView):
    """Saves an experiment's design, a part of editing it (its change permission): the factors and the groups, as a
    whole (experiments.services.save_design). Posted with the draft marker it renders the grid again with the columns
    changed (or a factor added) and what was entered, saving nothing."""

    action = 'change'

    def get(self, request, pk):
        return done(request, reverse(self.resource.url_name('edit'), args=[pk]))

    def post(self, request, pk):
        r = self.resource
        experiment = self.get_object(pk)
        page = UpdateView.as_page(r, request)
        if DRAFT in request.POST:
            design = design_forms(experiment, draft=request.POST, add_factor=request.POST[DRAFT] == ADD_FACTOR)
            return page.page(r.form(request, instance=experiment), experiment, open_tab='design',
                             **r.edit_extras(request, experiment, design))
        form, factors, groups = design = design_forms(experiment, data=request.POST)
        if form.is_valid() & factors.is_valid() & groups.is_valid():
            factor_rows, group_rows = design_rows(factors, groups)
            try:
                services.save_design(request.user, experiment, factor_rows, group_rows, form.cleaned_data['version'])
            except ValidationError as error:
                for message in error.messages:
                    form.add_error(None, message)
            else:
                messages.success(request, gettext('Design of “%(experiment)s” saved.') % {'experiment': experiment})
                return done(request, reverse(r.url_name('edit'), args=[pk]), stay=True)
        response = page.page(r.form(request, instance=experiment), experiment, open_tab='design',
                             **r.edit_extras(request, experiment, design))
        response.status_code = 422
        return response


class ExperimentPlacesView(ResourceView):
    """Places an experiment's tanks, a part of editing it (its change permission): either the seeded deal of a pool to
    the replicates (`action=randomise`) or the rows by hand (`action=save`, with the reason), each as a whole
    (experiments.services.randomise, save_places)."""

    action = 'change'
    RANDOMISE = 'randomise'

    def get(self, request, pk):
        return done(request, reverse(self.resource.url_name('edit'), args=[pk]))

    def post(self, request, pk):
        r = self.resource
        experiment = self.get_object(pk)
        page = UpdateView.as_page(r, request)
        form, places = posted = places_forms(experiment, data=request.POST)
        deal = request.POST.get('action') == self.RANDOMISE
        done_ok = False
        if form.is_valid() and (deal or places.is_valid()):
            try:
                if deal:
                    pool = self.pool(experiment, form)
                    seed = form.cleaned_data['seed']
                    if seed is None:
                        raise ValidationError(gettext('Give the seed: a whole number the deal is repeated from.'))
                    services.randomise(request.user, experiment, pool, seed, form.cleaned_data['version'])
                else:
                    services.save_places(request.user, experiment, place_rows(experiment, places),
                                         form.cleaned_data['version'], form.cleaned_data['note'])
            except ValidationError as error:
                for message in error.messages:
                    form.add_error(None, message)
            else:
                done_ok = True
        if done_ok:
            messages.success(request, gettext('Places of “%(experiment)s” saved.') % {'experiment': experiment})
            return done(request, reverse(r.url_name('edit'), args=[pk]), stay=True)
        response = page.page(r.form(request, instance=experiment), experiment, open_tab='places',
                             **r.edit_extras(request, experiment, places=posted))
        response.status_code = 422
        return response

    @staticmethod
    def pool(experiment, form):
        """The tanks and systems of the site the person chose, from the tokens the pool carries."""
        tokens = form.cleaned_data['pool']
        tanks = Tank.objects.filter(pk__in=[token[5:] for token in tokens if token.startswith('tank:')],
                                    production_department__site=experiment.site)
        systems = System.objects.filter(pk__in=[token[7:] for token in tokens if token.startswith('system:')],
                                        site=experiment.site)
        return [*tanks, *systems]


class ExperimentStartView(ResourceView):
    """The Start dialog (the change permission): what is wrong with the design (the errors block, the warnings are
    acknowledged by one box that carries their fingerprint), what starting does, and Start (experiments.services.start)."""

    action = 'change'
    template = 'experiments/experiment_start.html'

    def page(self, form, experiment, status=200):
        r = self.resource
        response = render_page(self.request, self.template, self.context(
            form=form, object=experiment, findings=form.assessment, back_url=reverse(r.url_name('edit'),
                                                                                    args=[experiment.pk])))
        response.status_code = status
        return response

    def get(self, request, pk):
        experiment = self.get_object(pk)
        assessment = design_module.assess(experiment) if experiment.status == Status.DRAFT else None
        return self.page(StartForm(initial={'version': experiment.version}, assessment=assessment), experiment)

    def post(self, request, pk):
        r = self.resource
        experiment = self.get_object(pk)
        assessment = design_module.assess(experiment) if experiment.status == Status.DRAFT else None
        form = StartForm(request.POST, assessment=assessment)
        if form.is_valid():
            try:
                services.start(request.user, experiment, form.cleaned_data['start_ack'], form.cleaned_data['version'])
            except ValidationError as error:
                for field, found in error.message_dict.items():
                    for message in found:
                        form.add_error(None if field == NON_FIELD_ERRORS else field, message)
            else:
                messages.success(request, gettext('“%(experiment)s” started.') % {'experiment': experiment})
                return done(request, reverse(r.url_name('edit'), args=[pk]), stay=True)
        return self.page(form, experiment, status=422)


class ExperimentCopyView(ResourceView):
    """The copy dialog (the add permission: Create creates and copies): a new draft experiment, or a template, with the design
    of this one, never its tanks, allocation or team; the copier leads it (experiments.services.copy)."""

    action = 'add'
    template = 'experiments/experiment_copy.html'

    def page(self, form, source, status=200):
        response = render_page(self.request, self.template, self.context(
            form=form, object=source, back_url=reverse(self.resource.url_name('list'))))
        response.status_code = status
        return response

    def get(self, request, pk):
        source = self.get_object(pk)
        kind = CopyForm.TEMPLATE if request.GET.get('as') == CopyForm.TEMPLATE else CopyForm.EXPERIMENT
        return self.page(CopyForm(initial={'name': gettext('%(name)s (copy)') % {'name': source.name}, 'kind': kind}),
                         source)

    def post(self, request, pk):
        r = self.resource
        source = self.get_object(pk)
        form = CopyForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            try:
                with transaction.atomic():
                    new = services.copy(request.user, source, data['name'], data['starts_on'],
                                        data['kind'] == CopyForm.TEMPLATE, data['token'])
                    if not new.members.exists():            # a form sent twice finds the copy it made, with its lead
                        TeamList.save(request.user, new, [{'user': request.user, 'role': Member.Role.LEAD}],
                                      r.entity_type())
            except ValidationError as error:
                for message in error.messages:
                    form.add_error(None, message)
            else:
                messages.success(request, gettext('Copied as “%(copy)s”: a draft, to change and start.') % {
                    'copy': new})
                return done(request, reverse(r.url_name('edit'), args=[new.pk]), stay=True)
        return self.page(form, source, status=422)



class ExperimentAmendView(ResourceView):
    """A tank of a running experiment leaves or is replaced (the change permission): a dialog with the tank, its replicate and
    its days, the fields of its form and the reason, which is asked (experiments.services.release_unit, replace_unit)."""

    action = 'change'
    template = 'experiments/experiment_amend.html'
    heading = ''
    done_text = ''

    def get_placement(self, experiment, placement):
        return get_object_or_404(ReplicateUnit.objects.select_related('replicate__group', 'unit'), pk=placement,
                                 replicate__group__experiment=experiment)

    def page(self, form, experiment, placement, status=200):
        response = render_page(self.request, self.template, self.context(
            form=form, object=experiment, placement=placement, heading_text=self.heading,
            back_url=reverse(self.resource.url_name('detail'), args=[experiment.pk]) + '?tab=data'))
        response.status_code = status
        return response

    def get(self, request, pk, placement):
        experiment = self.get_object(pk)
        row = self.get_placement(experiment, placement)
        today = site_today(experiment.site)
        return self.page(self.form(experiment, row, initial={'version': experiment.version, **self.initial(today)}),
                         experiment, row)

    def post(self, request, pk, placement):
        r = self.resource
        experiment = self.get_object(pk)
        row = self.get_placement(experiment, placement)
        form = self.form(experiment, row, data=request.POST)
        if form.is_valid():
            try:
                self.apply(request.user, row, form.cleaned_data)
            except ValidationError as error:
                for message in error.messages:
                    form.add_error(None, message)
            else:
                messages.success(request, str(self.done_text) % {'tank': row.unit.code, 'experiment': experiment})
                return done(request, reverse(r.url_name('detail'), args=[pk]) + '?tab=data')
        return self.page(form, experiment, row, status=422)


class ExperimentReleaseView(ExperimentAmendView):
    heading = _('Release a tank')
    done_text = _('%(tank)s left “%(experiment)s”.')

    def initial(self, today):
        return {'last_day': today}

    def form(self, experiment, placement, data=None, initial=None):
        return ReleaseForm(data, initial=initial)

    def apply(self, user, row, data):
        services.release_unit(user, row, data['last_day'], data['reason'], data['version'])


class ExperimentReplaceView(ExperimentAmendView):
    heading = _('Replace a tank')
    done_text = _('%(tank)s was replaced in “%(experiment)s”.')

    def initial(self, today):
        return {'from_day': today}

    def form(self, experiment, placement, data=None, initial=None):
        return ReplaceForm(data, initial=initial, experiment=experiment, leaving=placement.unit)

    def apply(self, user, row, data):
        services.replace_unit(user, row, data['new_unit'], data['from_day'], data['reason'], data['version'])
