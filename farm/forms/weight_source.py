"""Setup › Reference data › Weight sources: how an average weight was measured (farm.WeightSource)."""
from django import forms
from django.utils.translation import gettext_lazy as _

from core.crud import TabbedForm, tab_fields

from ..models import WeightSource

WEIGHT_SOURCE_TABS = [('source', _('Weight source'), ['name', 'code', 'notes'])]


class WeightSourceForm(TabbedForm):
    """A weight source. Its code is chosen once: the seeded `manual` is what a weighing without a source means."""

    tabs = WEIGHT_SOURCE_TABS
    fixed_after_creation = ('code',)

    class Meta:
        model = WeightSource
        fields = tab_fields(WEIGHT_SOURCE_TABS)
        widgets = {'notes': forms.Textarea(attrs={'rows': 3}),
                   'name': forms.TextInput(attrs={'placeholder': _('e.g. Biomass camera')})}
        help_texts = {
            'name': _('What measured the weight, as the pages name it: a sample weighed by hand, a biomass camera.'),
            'code': _('A short name in lower-case letters, digits and hyphens, chosen once.'),
            'notes': _('What it is, and how far its weights can be trusted.'),
        }
