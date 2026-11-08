from itertools import groupby

from django.contrib import messages
from django.utils.text import capfirst
from django.utils.translation import gettext, gettext_lazy as _, pgettext_lazy

from core.crud import NONE, Resource, filter_by

from ..forms import SpeciesForm
from ..models import Species, StockMovement
from .withdrawal_input import WithdrawalInput

ANY_CLEANER_FISH = 'any'   # the cleaner-fish filter's value for "every cleaner fish, whatever its type"


class SpeciesResource(WithdrawalInput, Resource):
    model = Species
    form_class = SpeciesForm
    name, plural = _('species'), pgettext_lazy('plural', 'species')
    url_prefix = 'species'
    search_fields = ['common_name', 'local_name', 'scientific_name', 'code', 'official_code']
    list_template = 'farm/species_list.html'
    icon = 'fish'
    page_size = 50

    @classmethod
    def reached(cls, request, species):
        """A species' assumed water temperature counts the degree-days of a withdrawal on a day without a measured
        one: the fish of the units its batches were in, from the first stock line."""
        lines = StockMovement.objects.filter(batch__species=species).values_list('unit_id', 'operation__date')
        return {unit for unit, _day in lines}, min((day for _unit, day in lines), default=None)

    @classmethod
    def filter_list(cls, request, objects):
        objects, chosen_category = filter_by(request, objects, 'category', Species.Category.choices, 'category')
        objects, chosen_status = filter_by(request, objects, 'status', Species.Status.choices, 'status')
        waters = [(name, Species._meta.get_field(name).verbose_name) for name in Species.WATER_FIELDS]
        chosen_water = request.GET.get('water', '')
        if chosen_water in Species.WATER_FIELDS:
            objects = objects.filter(**{chosen_water: True})
        else:
            chosen_water = ''
        types = [(value, label) for value, label in Species.CleanerFishType.choices if value]
        chosen_cleaner = request.GET.get('cleaner_fish', '')
        if chosen_cleaner == ANY_CLEANER_FISH:
            objects = objects.exclude(cleaner_fish_type=Species.CleanerFishType.NONE)
        elif chosen_cleaner == NONE:
            objects = objects.filter(cleaner_fish_type=Species.CleanerFishType.NONE)
        else:
            objects, chosen_cleaner = filter_by(request, objects, 'cleaner_fish', types, 'cleaner_fish_type')
        return objects, {
            'categories': Species.Category.choices, 'chosen_category': chosen_category,
            'statuses': Species.Status.choices, 'chosen_status': chosen_status,
            'waters': waters, 'chosen_water': chosen_water,
            'cleaner_types': types, 'chosen_cleaner': chosen_cleaner,
            'any_cleaner': ANY_CLEANER_FISH, 'none_value': NONE,
        }

    @classmethod
    def after_save(cls, request, species, created):
        """Says what the catalogue filled in (SpeciesForm), with the values, in the person's language."""
        filled = getattr(species, 'catalogue_filled', [])
        if not filled:
            return
        label = lambda name: capfirst(Species._meta.get_field(name).verbose_name)
        shown = lambda name: getattr(species, f'get_{name}_display', lambda: getattr(species, name))()
        parts = []
        # The water environments sit together in the form, and are told together.
        for is_water, names in groupby(filled, key=lambda name: name in Species.WATER_FIELDS):
            if is_water:
                parts.append(f'{gettext("Water environment")}: {", ".join(str(label(name)) for name in names)}')
            else:
                parts += [f'{label(name)}: {shown(name)}' for name in names]
        messages.info(request, gettext('Filled in from the species catalogue: %(values)s.') % {
            'values': '; '.join(parts)})
