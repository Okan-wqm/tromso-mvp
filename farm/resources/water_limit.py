from django.utils.translation import gettext_lazy as _, pgettext

from core import listprops as L
from core.crud import Resource, filter_by

from ..forms.water import WaterLimitForm
from ..models import Species, WaterLimit
from ..water import read as water_read
from ..water.parameters import LIMIT_CHOICES


class WaterLimitResource(Resource):
    """Setup › Reference data › Water limits: per species and parameter, the bounds a value is judged by; above them,
    what the fish kept today have no limit for (water.read.missing_limits), which their cards say as "No limit"."""

    model = WaterLimit
    form_class = WaterLimitForm
    name, plural = _('water limit'), _('water limits')
    url_prefix = 'water-limits'
    search_fields = ['species__common_name', 'species__local_name', 'species__code', 'reference']
    list_template = 'farm/water_limit_list.html'
    icon = 'gauge'
    page_size = 50

    @classmethod
    def queryset(cls):
        return super().queryset().select_related('species')

    @classmethod
    def filter_list(cls, request, objects):
        species = Species.objects.filter(water_limits__is_deleted=False).distinct().order_by('common_name')
        objects, chosen_species = filter_by(request, objects, 'species', species, 'species_id')
        objects, chosen_parameter = filter_by(request, objects, 'parameter', LIMIT_CHOICES, 'parameter')
        return objects, {
            'species_list': species, 'chosen_species': chosen_species,
            'parameters': LIMIT_CHOICES, 'chosen_parameter': chosen_parameter,
            'missing': water_read.missing_limits(),
        }

    # The list in the new look (core/listprops.py), in the classic list's words (farm/water_limit_list.html): a plate per
    # species, as the classic table's group rows; above it the fish kept today with no limit (a warning, never hidden).
    search_placeholder = _('Search by species or source')
    empty_text = _('The bounds a water value is judged by, per species and parameter: a warning outside one pair, critical '
                   'outside the other.')

    @classmethod
    def list_filters(cls, view, context):
        return [
            L.choice('species', pgettext('singular', 'Species'), context['chosen_species'],
                     [('', _('All species')), *((each.pk, each.common_name) for each in context['species_list'])]),
            L.choice('parameter', _('Parameter'), context['chosen_parameter'],
                     [('', _('All parameters')), *context['parameters']]),
        ]

    @classmethod
    def list_rows(cls, view, objects, context):
        from itertools import groupby

        from ..templatetags.water import bound

        notices = []
        if context['missing']:
            notices.append(L.notice('missing', 'warning', _(
                'These fish are kept today, and no limit judges these values for them: their monitoring cards say “No '
                'limit” whatever the value is. Add the limits your vet or guideline gives.'), title=_('Fish with no limit'),
                items=[f"{entry.species.common_name} ({entry.water_type_label})"
                       + (f" · {_('deleted species')}" if entry.species.is_deleted else '')
                       + ': ' + ', '.join(str(parameter.label) for parameter in entry.parameters)
                       for entry in context['missing']]))
        notices.append(L.notice('limits', 'info', _(
            'The water each species is kept in. A value outside the warning bounds is a warning, outside the critical bounds '
            'critical; a value on a bound is in the inner band. A row for a unit’s water type wins over the row for any '
            'water. Nothing is filled in for you: enter the values your vet or guideline gives, and say where they come '
            'from.')))
        rows, groups = [], []
        for at, (_species, limits) in enumerate(groupby(objects, key=lambda limit: limit.species_id)):
            limits = list(limits)
            species = limits[0].species
            # the classic group row's words: its common name and, muted, " · " its local name
            groups.append(L.group(f'{at}-{species.pk}', ' · '.join(
                name for name in (species.common_name, species.local_name) if name), [limit.pk for limit in limits]))
            rows += [L.row(limit.pk, {
                'parameter': L.title(view, context, limit, limit.get_parameter_display()),
                'water_type': L.cell(limit.get_water_type_display()),
                **{name: L.cell(str(bound(limit, name))) for name in BOUNDS},
                'reference': L.cell(limit.reference or '—'),
            }, L.edit_delete(view, context, limit, str(limit))) for limit in limits]
        return {
            'columns': [L.column('parameter', _('Parameter')), L.column('water_type', _('Water type')),
                        L.column('critical_low', _('Critical below'), numeric=True),
                        L.column('warning_low', _('Warning below'), numeric=True),
                        L.column('warning_high', _('Warning above'), numeric=True),
                        L.column('critical_high', _('Critical above'), numeric=True),
                        L.column('reference', _('Source of the values'))],
            'notices': notices, 'rows': rows, 'groups': groups,
        }


BOUNDS = ('critical_low', 'warning_low', 'warning_high', 'critical_high')
