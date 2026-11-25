from django.utils.translation import gettext_lazy as _, pgettext

from core import listprops as L
from core.crud import Resource, filter_by

from ..forms.harvest import SlaughterFacilityForm
from ..models import SlaughterFacility, Species


class SlaughterFacilityResource(Resource):
    """Setup › Harvest and logistics › Slaughter facilities: where harvested fish go."""

    model = SlaughterFacility
    form_class = SlaughterFacilityForm
    name, plural = _('slaughter facility'), _('slaughter facilities')
    url_prefix = 'slaughter-facilities'
    search_fields = ['name', 'approval_number', 'address', 'municipality', 'operator__name']
    list_template = 'farm/slaughter_facility_list.html'
    icon = 'factory'
    page_size = 50

    @classmethod
    def queryset(cls):
        return super().queryset().select_related('operator').prefetch_related('species')

    @classmethod
    def filter_list(cls, request, objects):
        objects, chosen_status = filter_by(request, objects, 'status', SlaughterFacility.Status.choices, 'status')
        species = Species.objects.filter(slaughter_facilities__is_deleted=False).distinct().order_by('common_name')
        objects, chosen_species = filter_by(request, objects, 'species', species, 'species')
        return objects.distinct(), {
            'statuses': SlaughterFacility.Status.choices, 'chosen_status': chosen_status,
            'species_list': species, 'chosen_species': chosen_species,
        }

    # The list in the new look (core/listprops.py), in the classic list's words (farm/slaughter_facility_list.html).
    search_placeholder = _('Search by name, approval number, place or operator')
    empty_text = _('The slaughterhouses harvested fish go to, with Mattilsynet’s approval number: every harvest names its '
                   'facility.')

    @classmethod
    def list_filters(cls, view, context):
        return [
            L.choice('species', pgettext('singular', 'Species'), context['chosen_species'],
                     [('', _('All species')), *((each.pk, each.common_name) for each in context['species_list'])]),
            L.choice('status', _('Status'), context['chosen_status'], [('', _('All statuses')), *context['statuses']]),
        ]

    @classmethod
    def list_rows(cls, view, objects, context):
        from django.template.defaultfilters import floatformat

        def operator(facility):
            if facility.operator is None:
                return L.cell('–')
            company = facility.operator
            return L.cell(company.name, sub=[company.get_status_display() if company.status != 'active' else ''])

        def place(facility):
            if not (facility.municipality or facility.address):
                return L.cell('–')
            return L.cell(facility.municipality, sub=[facility.address])

        return {
            'columns': [L.column('facility', _('Slaughter facility')), L.column('operator', _('Operator')),
                        L.column('place', _('Place')), L.column('species', _('Species it takes')),
                        L.column('capacity', _('Capacity (t a day)'), numeric=True), L.column('status', _('Status'))],
            'rows': [L.row(facility.pk, {
                'facility': L.title(view, context, facility, facility.name, sub=[
                    _('Approval number %(number)s') % {'number': facility.approval_number}]),
                'operator': operator(facility),
                'place': place(facility),
                'species': L.cell(', '.join(each.common_name for each in facility.species.all()) or _('Every species')),
                'capacity': L.cell(floatformat(facility.capacity_tonnes_per_day, '-1g') or '–'),
                'status': L.badge(facility.status, facility.get_status_display()),
            }, L.edit_delete(view, context, facility, facility.name)) for facility in objects],
        }
