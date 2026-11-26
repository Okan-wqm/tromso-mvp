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
# What a new species gets as its size limit (Species.max_weight_ratio) when the box is left empty: the owner's default,
# as migration 0034 gave the species already there, and none for a cleaner fish (the owner, 2026-11-10: lumpfish and
# wrasses are topped up with fish of other sizes; migration 0038 did the same for the cleaner species still at the
# default). The box is not filled in beforehand: a value standing in it could not be told from a typed one (review
# R11), so an empty box on a new species means "the offer of its kind", said after saving, and whatever is typed is
# kept, a 2 for a cleaner fish too.
OFFERED_WEIGHT_RATIO = Decimal(2)


def offered_weight_ratio(cleaner_fish_type):
    """The size limit a new species is given when none is typed: the default, and none for a cleaner fish."""
    return None if cleaner_fish_type else OFFERED_WEIGHT_RATIO


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
                                          'measured: a day counts at its probe’s time-weighted mean when the probe '
                                          'covered at least 20 hours, else at the mean of its water samples, else at '
                                          'this value, but never above the coldest day measured in the 7 days before '
                                          'it; a withdrawal is projected at it when none was measured at all. A mean '
                                          'of 0 °C or below adds nothing. It is the farm’s own assumption: a low value '
                                          'is the conservative choice. Empty: such a day counts as 0 °C. 0 to 40 °C.'),
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
            self.fields['max_weight_ratio'].help_text = _(
                'How many times heavier, on average, one batch of this species may be than another in the same unit, '
                'e.g. 2: fish of 100 g and of 200 g may share a unit. A stocking, transfer or grading beyond it asks '
                'for an acknowledgement first. Left empty on a new species: 2 for a production species, no check for a '
                'cleaner fish (its cages are topped up with fish of other sizes). To have no check on a production '
                'species, empty it after saving.')
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
        # A new species whose box was left empty gets the offer of its kind, which is known only now (the type may come
        # from the catalogue): 2, or no check for a cleaner fish. Whatever was typed is kept; an edit is never touched.
        if self.instance._state.adding and 'max_weight_ratio' in cleaned and cleaned['max_weight_ratio'] is None:
            cleaned['max_weight_ratio'] = offered_weight_ratio(cleaned.get('cleaner_fish_type'))
            self.instance.size_limit_offered = True
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
