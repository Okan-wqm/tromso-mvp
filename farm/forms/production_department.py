from django import forms
from django.utils.translation import gettext_lazy as _

from core.crud import CodedFormMixin, TabbedForm

from ..models import ProductionDepartment, Site


class ProductionDepartmentForm(CodedFormMixin, TabbedForm):
    tabs = [('details', _('Details'), ['name', 'code', 'type', 'site', 'capacity', 'notes'])]
    fixed_after_creation = ('site',)

    class Meta:
        model = ProductionDepartment
        fields = ['name', 'code', 'type', 'site', 'capacity', 'notes']
        localized_fields = ['capacity']
        help_texts = {'site': _('A production department stays on the site it was created on.')}
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': _('e.g. Hatchery hall A')}),
            'code': forms.TextInput(attrs={'placeholder': _('e.g. HAT-A'), 'data-uppercase': ''}),
            'capacity': forms.TextInput(attrs={'inputmode': 'decimal'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        site = self.fields['site']
        site.queryset = Site.objects.all()
        site.required = self.instance._state.adding
        # A production department whose site was deleted shows "No site".
        site.empty_label = _('Select a site') if self.instance._state.adding else _('No site')
