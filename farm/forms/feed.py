from django import forms
from django.utils.translation import gettext_lazy as _, ngettext_lazy

from core.crud import CodedFormMixin, Fieldset, RowFormSet, TabbedForm, tab_fields

from ..models import Feed, FeedSuitability, Supplier
from ..models.feed import ENERGIES, PERCENTAGES, SAME_STAGE_MESSAGE

DECIMAL = {'inputmode': 'decimal'}
NUMBERS = ['pellet_size_mm', *PERCENTAGES, *ENERGIES, 'price_per_kg']

FEED_FORM_TABS = [
    ('basic', _('Basic info'), ['name', 'code', 'manufacturer', 'feed_type', 'feed_form', 'pellet_size_mm', 'buoyancy',
                                'status']),
    ('analysis', _('Analysis'), [
        Fieldset(_('Composition as fed'), list(PERCENTAGES),
                 _('Percent of the feed as delivered, as the feed declaration states it. Protein, fat, carbohydrate, '
                   'fibre, ash and moisture together are at most 100; phosphorus is part of the ash.')),
        Fieldset(_('Energy'), list(ENERGIES)),
    ]),
    ('price', _('Price and notes'), ['price_per_kg', 'currency', 'notes']),
]


class FeedForm(CodedFormMixin, TabbedForm):
    """The feed dialog. The species and weights it suits are a list of their own on the Suitable for tab
    (a RowList, like a feeder's calibrations)."""

    tabs = FEED_FORM_TABS

    class Meta:
        model = Feed
        fields = tab_fields(FEED_FORM_TABS)
        localized_fields = NUMBERS
        help_texts = {
            'name': _('The product name, as on the bag, e.g. Nutra Olympic 3 mm.'),
            'code': _('Your own short code: capital letters, digits, hyphens and underscores.'),
            'manufacturer': _('The feed mill that makes it: a supplier of feed (Purchasing › Suppliers).'),
            'feed_type': _('What it is made for. A medicated feed is given on a vet’s prescription.'),
            'feed_form': _('Dry (pellets) or wet (moist feed, paste): the cleaner-fish report gives the month’s kilos '
                           'of each.'),
            'pellet_size_mm': _('The pellet diameter, as a feeder’s calibrations write it.'),
            'buoyancy': _('Floating feed stays at the surface; sinking and slow-sinking feed is for cages and deep '
                          'tanks.'),
            'status': _('Active: fed now or ready to be fed. Inactive: not used at the moment. Discontinued: no '
                        'longer made or bought.'),
            'nfe_pct': _('The nitrogen-free extract: what is left when the other parts are taken away.'),
            'gross_energy_mj_kg': _('All the energy in the feed, in MJ per kg as fed.'),
            'digestible_energy_mj_kg': _('The part of the gross energy the fish can digest.'),
            'price_per_kg': _('What the farm pays per kg, with its currency.'),
            'currency': _('Three letters, e.g. NOK.'),
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': _('e.g. Nutra Olympic 3 mm')}),
            'code': forms.TextInput(attrs={'placeholder': _('e.g. NUTRA-3'), 'data-uppercase': ''}),
            'currency': forms.TextInput(attrs={'placeholder': 'NOK', 'data-uppercase': '', 'maxlength': 3}),
            'notes': forms.Textarea(attrs={'rows': 3}),
            **{name: forms.TextInput(attrs=DECIMAL) for name in NUMBERS},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['buoyancy'].choices = [('', _('Not stated'))] + list(Feed.Buoyancy.choices)
        self.fields['feed_type'].choices = [('', _('Select a feed type'))] + list(Feed.Type.choices)
        # The suppliers of feed (the link's limit_choices_to), with the status of those not active.
        manufacturer = self.fields['manufacturer']
        manufacturer.empty_label = _('None')
        manufacturer.label_from_instance = lambda supplier: (
            str(supplier) if supplier.status == Supplier.Status.ACTIVE
            else f'{supplier} · {supplier.get_status_display()}')

    def clean_currency(self):
        return self.cleaned_data['currency'].strip().upper()


class FeedSuitabilityForm(forms.ModelForm):
    class Meta:
        model = FeedSuitability
        fields = ['species', 'growth_stage', 'min_weight_g', 'max_weight_g', 'notes']
        localized_fields = ['min_weight_g', 'max_weight_g']
        widgets = {
            'min_weight_g': forms.TextInput(attrs={'inputmode': 'decimal', 'placeholder': _('e.g. 50')}),
            'max_weight_g': forms.TextInput(attrs={'inputmode': 'decimal', 'placeholder': _('e.g. 150')}),
            'notes': forms.TextInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['species'].empty_label = _('Select a species')
        self.fields['growth_stage'].choices = [('', _('Select a life stage'))] + list(FeedSuitability.GrowthStage.choices)

    def validate_constraints(self):
        # One row per species and stage spans the whole list, which is saved as a full replace; the formset
        # checks it and the database constraint backs it up. Checking each row against the stored rows would
        # reject keeping a species and stage while replacing its row.
        pass


class BaseFeedSuitabilityFormSet(RowFormSet):
    default_error_messages = {
        'too_many_forms': ngettext_lazy('A feed has at most %(num)d row.', 'A feed has at most %(num)d rows.', 'num'),
    }

    def get_unique_error_message(self, unique_check):
        return str(SAME_STAGE_MESSAGE)


FeedSuitabilityFormSet = forms.inlineformset_factory(
    Feed, FeedSuitability, form=FeedSuitabilityForm, formset=BaseFeedSuitabilityFormSet,
    extra=0, can_delete=True, max_num=50, validate_max=True,
)
