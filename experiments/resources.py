"""Research › Experiments, one tab of core.crud: the list (experiments, mine, templates), the experiment's form with its
Details, Design and Team tabs (the design is a grid of factors and a grid of groups, saved as a whole by its own view),
the read page, and delete through the delete plan (a draft only: the model says so). The creator is the lead of a new
experiment."""
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.urls import path, reverse
from django.utils.translation import gettext, gettext_lazy as _, ngettext_lazy

from core.crud import DRAFT, Resource, ResourceView, RowList, UpdateView, done, filter_by
from core.people import person_name
from farm.models import Site, Species

from . import design as design_module, services
from .forms import ExperimentForm, MemberFormSet, design_forms, design_rows
from .models import Experiment, Member, Status

EXPERIMENTS, MINE, TEMPLATES = '', 'mine', 'templates'
VIEWS = (EXPERIMENTS, MINE, TEMPLATES)
ADD_FACTOR = 'add_factor'          # the marker of the button that adds a factor row to the design grid


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

    @classmethod
    def detail_extras(cls, request, experiment):
        return {'team': TeamList.rows(experiment)}

    @classmethod
    def edit_extras(cls, request, experiment, design=None):
        """The team's list, and the Design tab: the factors' grid and the groups' grid (the stored design, or the
        rows of a posted one), and what is wrong with the stored design."""
        extras = super().edit_extras(request, experiment)
        form, factors, groups = design or design_forms(experiment)
        stored = design_module.load(experiment)
        frozen = experiment.status != Status.DRAFT
        return {**extras, 'design_form': form, 'factors': factors, 'groups': groups, 'frozen': frozen,
                'findings': None if frozen else design_module.assess(experiment, stored),
                'table': design_module.table(stored), 'add_factor': ADD_FACTOR,
                'design_url': reverse('experiments:experiment_design', args=[experiment.pk])}

    @classmethod
    def urls(cls):
        p = cls.url_prefix
        return [*super().urls(),
                path(f'{p}/<uuid:pk>/design/', ExperimentDesignView.as_view(resource=cls), name='experiment_design')]


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
