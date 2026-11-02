from django import forms

from core.crud import CodedFormMixin, TabbedForm

from ..models import Department, Site


class DepartmentForm(CodedFormMixin, TabbedForm):
    tabs = [('details', 'Details', ['name', 'code', 'type', 'site', 'capacity', 'notes'])]
    fixed_after_creation = ('site',)

    class Meta:
        model = Department
        fields = ['name', 'code', 'type', 'site', 'capacity', 'notes']
        help_texts = {'site': 'A department stays on the site it was created on.'}
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'e.g. Hatchery hall A'}),
            'code': forms.TextInput(attrs={'placeholder': 'e.g. HAT-A', 'data-uppercase': ''}),
            'capacity': forms.NumberInput(attrs={'min': 0, 'step': 'any'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        site = self.fields['site']
        site.queryset = Site.objects.all()
        site.required = self.instance._state.adding
        # A department whose site was deleted shows "No site".
        site.empty_label = 'Select a site' if self.instance._state.adding else 'No site'
