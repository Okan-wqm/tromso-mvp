from django import forms

from core.crud import CodedFormMixin, TabbedForm
from core.widgets import DependentSelect

from ..models import ProductionDepartment, Site, System


class SystemForm(CodedFormMixin, TabbedForm):
    tabs = [('details', 'Details', [
        'name', 'code', 'type', 'status', 'site', 'production_department', 'parent', 'description',
        'total_volume_m3', 'max_biomass_kg',
    ])]
    fixed_after_creation = ('site',)

    class Meta:
        model = System
        fields = [
            'name', 'code', 'type', 'status', 'site', 'production_department', 'parent', 'description',
            'total_volume_m3', 'max_biomass_kg',
        ]
        labels = {'total_volume_m3': 'Total volume (m³)', 'max_biomass_kg': 'Max biomass (kg)'}
        help_texts = {
            'site': 'A system stays on the site it was created on.',
            'production_department': 'Only the production departments of the chosen site.',
            'parent': 'Only the systems of the chosen site; leave empty for a top-level system.',
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'e.g. Smolt RAS 1'}),
            'code': forms.TextInput(attrs={'placeholder': 'e.g. SYS-001', 'data-uppercase': ''}),
            'description': forms.Textarea(attrs={'rows': 3}),
            'total_volume_m3': forms.NumberInput(attrs={'min': 0, 'step': 'any', 'placeholder': '0'}),
            'max_biomass_kg': forms.NumberInput(attrs={'min': 0, 'step': 'any', 'placeholder': '0'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['site'].queryset = Site.objects.all()
        self.fields['site'].required = True
        self.fields['site'].empty_label = 'Select a site'

        departments = ProductionDepartment.objects.exclude(site=None)
        self._depend_on_site('production_department', departments, 'No production department')

        # A system cannot be nested under itself or under anything below it.
        parents = System.objects.all()
        if not self.instance._state.adding:
            parents = parents.exclude(pk__in=[self.instance.pk, *(s.pk for s in self.instance.descendants())])
        self._depend_on_site('parent', parents, 'No parent (top-level system)')

    def _depend_on_site(self, name, queryset, empty_label):
        field = self.fields[name]
        field.queryset = queryset
        field.empty_label = empty_label
        DependentSelect.apply(field, 'site', {str(record.pk): str(record.site_id) for record in queryset})
