"""Operations › Feeding › Temperature profiles and Profile assignments, two tabs of core.crud (owner decisions 15–17 of
2026-11-26). A profile's points are a row list on its own inner tab (core.crud.RowList), editable while the profile is
not assigned; under them, the temperature the profile gives over the fish's weight (farm/feeding/profiles.py, `used`:
the plan's own reading); Duplicate copies a profile into a draft. The assignment tab is farm/resources/
assignment_tab.py's, the protocols' own."""
from django.contrib import messages
from django.urls import path, reverse
from django.utils.translation import gettext, gettext_lazy as _, ngettext_lazy

from core import formpanels, listprops as L
from core.crud import Resource, ResourceView, RowList, done, filter_by

from .. import words
from ..feeding import lists, profiles
from ..forms.temperature_profile import (
    NewProfileAssignmentForm, ProfileAssignmentForm, TemperaturePointFormSet, TemperatureProfileForm,
)
from ..models import Species, TemperatureProfile, TemperatureProfileAssignment
from ..models.temperature_profile import ProtocolStatus
from ..templatetags.feeding import celsius
from ..templatetags.stock import grams
from .assignment_tab import AssignmentTab


class TemperaturePointList(RowList):
    """A profile's points, saved as one list on its Points tab while the profile is not assigned."""

    key, tab, label = 'points', 'points', _('Points')
    formset = TemperaturePointFormSet
    title = _('Points')
    help_text = _('One row per fish weight (g) with the water temperature (°C) expected then. Between two points the '
                  'profile’s rule applies (smooth or a step); before the first point its temperature, after the last '
                  'the last one’s. At most 30 points; saved separately from the profile’s details.')
    empty_text = _('No point yet. Use “Add point” to add a row.')
    add_label, save_label = _('Add point'), _('Save points')
    pending_text = _('The points can be given once the profile is created.')
    saved = ngettext_lazy('%(count)d point saved.', '%(count)d points saved.', 'count')

    @classmethod
    def words(cls, obj):
        found = super().words(obj)
        if obj is not None and obj.is_assigned():
            found['pending'] = words.THE_PROFILE_IS_ASSIGNED_SO_ITS
        return found

    @classmethod
    def applies_to(cls, obj):
        """An assigned profile keeps its points (Q3): they are shown under the list, and changed on a copy."""
        return not obj.is_assigned()

    @classmethod
    def describe(cls, row):
        return f'{row.weight_g.normalize():f} g {row.temperature_c.normalize():f} °C'


def used_props(profile):
    """The temperature the stored profile gives over the fish's weight, as both looks draw it: a row at every point
    (said "entered") and half way between two neighbouring points. None without points."""
    found = profiles.used(profile)
    if not found:
        return None
    return {
        'title': str(words.TEMPERATURE_OVER_THE_WEIGHT),
        'lines': [str(profile.get_temperature_between_display())],
        'columns': [L.column('weight', words.FISH_WEIGHT, numeric=True), L.column('point', words.POINT),
                    L.column('temperature', words.TEMPERATURE, numeric=True)],
        'rows': [L.row(f'used-{index}', {
            'weight': L.cell(grams(used.weight_g), strong=used.point),
            'point': L.cell(gettext('entered') if used.point else gettext('half way')),
            'temperature': L.cell(celsius(used.temperature_c))}) for index, used in enumerate(found)],
    }


class TemperatureProfileResource(Resource):
    model = TemperatureProfile
    form_class = TemperatureProfileForm
    name, plural = _('temperature profile'), _('temperature profiles')
    url_prefix = 'operations/feeding/temperature-profiles'
    search_fields = ['name', 'species__common_name', 'species__local_name', 'notes']
    list_template = 'farm/temperature_profile_list.html'
    form_template = 'farm/temperature_profile_form.html'
    icon = 'activity'
    page_size = 50
    row_lists = (TemperaturePointList,)
    search_placeholder = _('Search by name, species or notes')
    empty_text = _('The water temperature the fish are expected to be kept at as they grow, per species: read by the '
                   'production plans for the days ahead.')

    @classmethod
    def queryset(cls):
        return super().queryset().select_related('species').prefetch_related('points')

    @classmethod
    def filter_list(cls, request, objects):
        species = Species.objects.filter(temperature_profiles__is_deleted=False).distinct().order_by('common_name')
        objects, chosen_species = filter_by(request, objects, 'species', species, 'species_id')
        objects, chosen_status = filter_by(request, objects, 'status', ProtocolStatus.choices, 'status')
        return objects, {'species_list': species, 'chosen_species': chosen_species,
                         'statuses': ProtocolStatus.choices, 'chosen_status': chosen_status,
                         'how': words.A_PROFILE_GIVES}

    @classmethod
    def list_filters(cls, view, context):
        return [
            L.choice('species', str(words.SPECIES_SINGULAR), context['chosen_species'],
                     [('', str(words.ALL_SPECIES)), *((each.pk, each.common_name) for each in context['species_list'])]),
            L.choice('status', str(words.STATUS), context['chosen_status'],
                     [('', str(words.ALL_STATUSES)), *context['statuses']]),
        ]

    @classmethod
    def list_rows(cls, view, objects, context):
        return {
            'columns': [L.column('name', str(words.NAME)), L.column('species', str(words.SPECIES_SINGULAR)),
                        L.column('status', str(words.STATUS)), L.column('points', str(words.POINTS)),
                        L.column('between', str(words.BETWEEN_POINTS))],
            'notices': [L.notice('how', 'info', str(words.A_PROFILE_GIVES))],
            'rows': [L.row(profile.pk, {
                'name': L.title(view, context, profile, profile.name),
                'species': L.cell(profile.species.common_name),
                'status': L.cell(profile.get_status_display()),
                'points': L.cell(points_said(profile)),
                'between': L.cell(profile.get_temperature_between_display()),
            }, L.edit_delete(view, context, profile, str(profile))) for profile in objects],
        }

    @classmethod
    def edit_extras(cls, request, obj, **kwargs):
        found = super().edit_extras(request, obj)
        return {**found, 'used': used_props(obj), 'frozen': obj.is_assigned(),
                'duplicate_url': reverse('farm:temperatureprofile_duplicate', args=[obj.pk])
                if request.user.has_perm(cls.perm('add')) else ''}

    next_extras = frozenset({'used', 'frozen', 'duplicate_url'})

    @classmethod
    def next_panels(cls, view, form, profile, extra):
        """farm/temperature_profile_form.html in the new look: its points (a row list, or the sentence of an assigned
        profile), the temperature it gives over the weight, and Duplicate."""
        panels = formpanels.row_list_panels(cls, view, profile, extra)
        used = extra.get('used') if profile is not None else None
        blocks = []
        if used:
            blocks += [formpanels.table(used['title'], used['columns'], used['rows']),
                       *(formpanels.help_text(line) for line in used['lines'])]
        if extra.get('duplicate_url'):
            blocks += [formpanels.post(extra['duplicate_url'], words.DUPLICATE),
                       formpanels.help_text(words.A_DRAFT_COPY_WITH_THESE_POINTS)]
        if blocks:
            panels.append(formpanels.panel('curve', words.TEMPERATURE_OVER_THE_WEIGHT, blocks))
        return panels

    @classmethod
    def urls(cls):
        return [*super().urls(),
                path(f'{cls.url_prefix}/<uuid:pk>/duplicate/', ProfileDuplicateView.as_view(resource=cls),
                     name='temperatureprofile_duplicate')]


def points_said(profile):
    points = sorted(profile.points.all(), key=lambda point: point.weight_g)
    return ' · '.join(f'{grams(point.weight_g)} {celsius(point.temperature_c)}' for point in points) or '—'


class ProfileDuplicateView(ResourceView):
    """A draft copy of a profile and its points (the add permission), opened for editing."""

    action = 'add'

    def get(self, request, pk):
        return done(request, reverse(self.resource.url_name('edit'), args=[pk]))

    def post(self, request, pk):
        r = self.resource
        copy = profiles.duplicate(request.user, self.get_object(pk), r.snapshot)
        messages.success(request, gettext('Copied as “%(profile)s”, a draft: change it, set it active and assign '
                                          'it.') % {'profile': copy})
        return done(request, reverse(r.url_name('edit'), args=[copy.pk]), stay=True)


class ProfileAssignmentResource(AssignmentTab, Resource):
    """Operations › Feeding › Profile assignments: which temperature profile applies to which fish from which day
    (farm/resources/assignment_tab.py, the protocols' own tab)."""

    model = TemperatureProfileAssignment
    subject_model = TemperatureProfile
    form_class, new_form = ProfileAssignmentForm, NewProfileAssignmentForm
    name, plural = _('profile assignment'), _('profile assignments')
    url_prefix = 'operations/feeding/profile-assignments'
    search_fields = ['profile__name', 'unit__code', 'batch__code', 'notes']
    search_placeholder = _('Search by profile, unit or batch')
    empty_text = _('Which temperature profile applies to which fish, from which day.')
    list_rows = staticmethod(lists.assignments)
    list_filters = staticmethod(lists.assignment_filters)
    kind_words = {'label': words.TEMPERATURE_PROFILE, 'all': words.ALL_PROFILES, 'how': words.A_PROFILE_IS_ASSIGNED,
                  'now': words.APPLIES_NOW, 'search': search_placeholder, 'empty': empty_text,
                  'meanwhile': _('Another profile was assigned to these fish meanwhile: look at the list and try '
                                 'again.')}
