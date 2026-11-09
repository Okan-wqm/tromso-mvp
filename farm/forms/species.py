from decimal import Decimal

from django import forms
from django.utils.translation import gettext, gettext_lazy as _

from core.crud import CodedFormMixin, Fieldset, TabbedForm, tab_fields

from .. import species_catalog
from ..models import Species
from ..models.species import normalise_scientific_name

SPECIES_FORM_TABS = [
    ('basic', _('Basic info'), ['common_name', 'local_name', 'scientific_name', 'code', 'description']),
    ('classification', _('Classification'), [
        'category', 'family',
        Fieldset(_('Water environment'), list(Species.WATER_FIELDS),
                 _('Every water the species is farmed in. Atlantic salmon and rainbow trout grow up in fresh '
                   'water and are farmed on in sea water: tick both.')),
    ]),
    ('regulatory', _('Regulatory'), [
        'official_code', 'cleaner_fish_type',
        Fieldset(_('Medicine withdrawal'), ['withdrawal_temperature_c']),
    ]),
    ('stocking', _('Stocking'), [
        Fieldset(_('Batches of different sizes'), ['max_weight_ratio'],
                 _('Fish of very different weights of the same species are not kept in one unit: the bigger ones '
                   'outcompete the smaller at feeding.')),
    ]),
    ('status', _('Status and notes'), ['status', 'notes']),
]
# What a new species is offered as its size limit (Species.max_weight_ratio): the owner's default, as migration 0034
# gave the species already there. An offer on the form, never a value the code stores by itself.
OFFERED_WEIGHT_RATIO = Decimal(2)


class SpeciesForm(CodedFormMixin, TabbedForm):
    """The species dialog. For a species the catalogue knows (farm/species_catalog.py), the fields left
    blank are filled in from it when the species is created or its scientific name changes; a typed
    value is never replaced, and an edit that keeps the name fills nothing, so any field can be cleared.
    What was filled is in `instance.catalogue_filled` (the field names), for the message after saving."""

    tabs = SPECIES_FORM_TABS

    class Meta:
        model = Species
        fields = tab_fields(SPECIES_FORM_TABS)
        localized_fields = ['withdrawal_temperature_c', 'max_weight_ratio']
        help_texts = {
            'common_name': _('The English name, e.g. Atlantic salmon.'),
            'local_name': _('The name in the farm’s own language, e.g. Laks.'),
            'scientific_name': _('Genus and species, e.g. Salmo salar; a subspecies may follow. For a species in '
                                 'the catalogue (salmon, trout, char, cod, halibut, turbot, seabass, seabream, '
                                 'lumpfish, wrasses), empty fields are filled in when it is saved.'),
            'code': _('Your own short code: capital letters, digits, hyphens and underscores.'),
            'official_code': _('The artskode of the Norwegian reports, three capital letters, e.g. SAL for '
                               'Atlantic salmon. Reports send this code, never your own code.'),
            'cleaner_fish_type': _('Lumpfish and wrasses are stocked with salmon to eat sea lice.'),
            'withdrawal_temperature_c': _('The degree-days one day counts for when no water temperature was '
                                          'measured: a past day without one, and a withdrawal projected when none '
                                          'was measured at all. It is the farm’s own assumption: a low value is the '
                                          'conservative choice. Empty: such a day counts as 0 °C. 0 to 40 °C.'),
            'max_weight_ratio': _('How many times heavier, on average, one batch of this species may be than another '
                                  'in the same unit, e.g. 2: fish of 100 g and of 200 g may share a unit. A stocking, '
                                  'transfer or grading beyond it asks for an acknowledgement first. Empty: no check.'),
            'status': _('Active: farmed now. Experimental: on trial. Inactive: not farmed at the moment. '
                        'Discontinued: no longer farmed.'),
        }
        widgets = {
            'common_name': forms.TextInput(attrs={'placeholder': _('e.g. Atlantic salmon')}),
            'local_name': forms.TextInput(attrs={'placeholder': _('e.g. Laks')}),
            'scientific_name': forms.TextInput(attrs={'placeholder': _('e.g. Salmo salar')}),
            'code': forms.TextInput(attrs={'placeholder': _('e.g. SAL'), 'data-uppercase': ''}),
            'official_code': forms.TextInput(attrs={'placeholder': _('e.g. SAL'), 'data-uppercase': ''}),
            'family': forms.TextInput(attrs={'placeholder': _('e.g. Salmonidae')}),
            'withdrawal_temperature_c': forms.TextInput(attrs={'inputmode': 'decimal', 'placeholder': _('e.g. 8')}),
            'max_weight_ratio': forms.TextInput(attrs={'inputmode': 'decimal', 'placeholder': _('e.g. 2')}),
            'description': forms.Textarea(attrs={'rows': 3}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance._state.adding:
            self.fields['max_weight_ratio'].initial = OFFERED_WEIGHT_RATIO
        else:
            # The genus is not a field of its own: it is the first word of the scientific name.
            self.tab_help['classification'] = gettext('Genus: %(genus)s (the first word of the scientific name).') % {
                'genus': self.instance.genus}

    def clean_scientific_name(self):
        return normalise_scientific_name(self.cleaned_data['scientific_name'])

    def clean_official_code(self):
        return self.cleaned_data['official_code'].strip().upper()

    def clean(self):
        cleaned = super().clean()
        name = cleaned.get('scientific_name')
        # The stored record still has its stored values here: the form fills it after clean().
        if name and (self.instance._state.adding or name != self.instance.scientific_name):
            self.instance.catalogue_filled = self._fill_from_catalogue(cleaned)
        return cleaned

    def _fill_from_catalogue(self, cleaned):
        """Fills the blank fields from the catalogue's entry for the scientific name and returns their
        names in form order: local name, family, the water environments (only when none is ticked),
        the official code (only a verified one) and the cleaner-fish type."""
        entry = species_catalog.find(cleaned['scientific_name'])
        if entry is None:
            return []
        offered = {name: getattr(entry, name) for name in ('local_name', 'family', 'cleaner_fish_type')}
        offered['official_code'] = entry.official_code if entry.official_code_verified else ''
        if not any(cleaned.get(name) for name in Species.WATER_FIELDS):
            offered.update({name: True for name in Species.WATER_FIELDS if getattr(entry, name)})
        filled = [name for name, value in offered.items()
                  if value and not cleaned.get(name) and name not in self.errors]
        cleaned.update({name: offered[name] for name in filled})
        order = tab_fields(self.tabs)
        return sorted(filled, key=order.index)
