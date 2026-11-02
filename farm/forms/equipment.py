from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils.translation import gettext, gettext_lazy as _, ngettext_lazy

from core.crud import CodedFormMixin, Fieldset, RowFormSet, TabbedForm
from core.links import LinkList
from core.widgets import DependentSelect

from ..models import Equipment, EquipmentSystem, EquipmentType, FeederCalibration, ProductionDepartment, System

SPECIFICATIONS = 'specifications'   # the inner tab with the type's own fields

EQUIPMENT_FORM_TABS = [
    ('general', _('General'), ['name', 'code', 'category', 'equipment_type', 'status']),
    ('location', _('Location'), ['production_department', 'systems', 'parent']),
    ('details', _('Details'), [
        'manufacturer', 'model', 'serial_number', 'purchase_date', 'warranty_end_date', 'installation_date',
        'description', 'notes',
    ]),
    # Filled per form with the fields of the chosen type (core.schema).
    (SPECIFICATIONS, _('Technical specifications'), []),
]
DATE = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')


class EquipmentForm(CodedFormMixin, TabbedForm):
    """The equipment dialog. The category is a choice of the form only (it narrows the types); the
    type decides the fields of the Technical specifications tab, so changing either renders the form
    again with what was entered (TabbedForm.refresh_on). The production department decides the site:
    the systems and the parent offered are those of its site."""

    tabs = EQUIPMENT_FORM_TABS
    refresh_on = ('category', 'equipment_type')

    category = forms.ChoiceField(label=_('Category'), choices=EquipmentType.Category.choices,
                                 help_text=_('Narrows the list of types.'))
    systems = LinkList(
        through=EquipmentSystem, target='system', details=('role', 'criticality'), primary='is_primary',
        label=_('Systems'),
        help_text=_('The systems it serves, on the site of its production department: at least one, and one of '
                    'them its primary system. Criticality is how much the system depends on it, from 1 '
                    '(little) to 5 (completely).'),
    )

    class Meta:
        model = Equipment
        fields = [
            'name', 'code', 'equipment_type', 'status', 'production_department', 'parent', 'manufacturer', 'model',
            'serial_number', 'purchase_date', 'warranty_end_date', 'installation_date', 'description', 'notes',
        ]
        help_texts = {
            'production_department': _('Its site decides which systems and which parent equipment can be chosen.'),
            'parent': _('When this is a part of other equipment, e.g. the pump of a filter unit.'),
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': _('e.g. Main circulation pump')}),
            'code': forms.TextInput(attrs={'placeholder': _('e.g. PMP-001'), 'data-uppercase': ''}),
            'purchase_date': DATE,
            'warranty_end_date': DATE,
            'installation_date': DATE,
            'description': forms.Textarea(attrs={'rows': 3}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        equipment = self.instance
        editing = not equipment._state.adding
        stored_type = equipment.equipment_type if editing else None

        # The types offered, and the record's own even when it is no longer offered; a category narrows them.
        types = EquipmentType.objects.filter(Q(is_active=True) | Q(pk=equipment.equipment_type_id))
        type_field = self.fields['equipment_type']
        type_field.queryset = types
        type_field.empty_label = _('Select a type')
        DependentSelect.apply(type_field, 'category', {str(kind.pk): kind.category for kind in types})
        used = set(types.values_list('category', flat=True))
        self.fields['category'].choices = [('', _('Select a category'))] + [
            (value, label) for value, label in EquipmentType.Category.choices if value in used]
        if editing:
            self.initial['category'] = stored_type.category

        # The production department decides the site; the systems and parents are offered per site.
        departments = (ProductionDepartment.objects.filter(Q(site__isnull=False) | Q(pk=equipment.production_department_id))
                       .select_related('site').order_by('site__name', 'name'))
        department_field = self.fields['production_department']
        department_field.queryset = departments
        department_field.empty_label = _('Select a production department')
        department_field.label_from_instance = lambda department: (
            f'{department.site.name} · {department.name}' if department.site else department.name)
        on_site = {}
        for department in departments:
            if department.site_id:
                on_site.setdefault(department.site_id, []).append(str(department.pk))

        systems = System.objects.select_related('site').order_by('site__name', 'name')
        self.fields['systems'].offer(
            systems, depends_on='production_department',
            belongs_to={str(system.pk): on_site.get(system.site_id, []) for system in systems},
            empty_text=_('No system to choose: the production department’s site has none, or no production '
                         'department is chosen.'))
        if editing:
            self.initial['systems'] = [
                {'pk': str(link.system_id), 'primary': link.is_primary, 'role': link.role,
                 'criticality': link.criticality}
                for link in equipment.live_links()]
            dropped = [str(link.system) for link in equipment.system_links.all() if link.system.is_deleted]
            if dropped:
                field = self.fields['systems']
                field.help_text = ' '.join([str(field.help_text), gettext(
                    'Its links to deleted systems (%(systems)s) are dropped when it is saved.') % {
                    'systems': ', '.join(dropped)}])

        # Equipment can be a part of equipment on its site, but not of itself or of one of its parts.
        parents = Equipment.objects.select_related('production_department').order_by('name')
        if editing:
            parents = parents.exclude(pk__in=[equipment.pk, *(part.pk for part in equipment.descendants())])
        parent_field = self.fields['parent']
        parent_field.queryset = parents
        parent_field.empty_label = _('None: not a part of other equipment')
        DependentSelect.apply(parent_field, 'production_department',
                              {str(part.pk): on_site.get(part.site_id, []) for part in parents})

        self._add_specification_fields(stored_type)

    def _add_specification_fields(self, stored_type):
        """The fields of the type the form has now. Their names carry the type's code, so values typed
        for one type never fill the fields of another (a power in W is not a power in kW)."""
        self.chosen_type = self.current('equipment_type')
        self.specification_fields = {}
        fieldsets = []
        if self.chosen_type is None:
            self.tab_help[SPECIFICATIONS] = _('Choose a type on the General tab; its specifications appear here.')
        else:
            schema = self.chosen_type.schema
            stored = self.instance.specifications if self.chosen_type == stored_type else None
            initial = schema.initial(stored)
            prefix = f'spec__{self.chosen_type.code}__'
            for name, field in schema.form_fields().items():
                self.fields[prefix + name] = field
                self.initial[prefix + name] = initial[name]
                self.specification_fields[name] = prefix + name
            fieldsets = [Fieldset(label, [prefix + name for name in names], text)
                         for label, text, names in schema.fieldsets()]
            self.tab_help[SPECIFICATIONS] = (
                gettext(self.chosen_type.description) if self.chosen_type.description and fieldsets else
                '' if fieldsets else _('This type has no technical specifications.'))
        self.tabs = [(key, label, fieldsets if key == SPECIFICATIONS else names) for key, label, names in self.tabs]

    def clean(self):
        cleaned = super().clean()
        kind, category = cleaned.get('equipment_type'), cleaned.get('category')
        if kind and category and kind.category != category:
            self.add_error('equipment_type', _('This type is not in the chosen category.'))
        if kind and kind == self.chosen_type:
            self.instance.specifications = kind.schema.to_json(
                {name: cleaned.get(key) for name, key in self.specification_fields.items()})
        return cleaned

    def _post_clean(self):
        # Django's hook after the record is built from the form (as its own password forms use it): the
        # links are checked against the record's site here, by their own model's rule.
        super()._post_clean()
        for link in self.cleaned_data.get('systems') or []:
            link.equipment = self.instance
            try:
                link.clean()
            except ValidationError as error:
                self.add_error('systems', error)

    def _save_m2m(self):
        # The links are saved with the record as a whole list (form.save_m2m(), core.crud), replacing the
        # stored ones, the links to deleted systems among them.
        super()._save_m2m()
        self.instance.system_links.all().delete()
        links = self.cleaned_data['systems']
        for link in links:
            link.equipment = self.instance
        EquipmentSystem.objects.bulk_create(links)


class FeederCalibrationForm(forms.ModelForm):
    class Meta:
        model = FeederCalibration
        fields = ['feed_size_mm', 'label', 'grams_per_dispensing', 'silo_capacity_kg', 'notes']
        localized_fields = ['feed_size_mm', 'grams_per_dispensing', 'silo_capacity_kg']
        widgets = {
            'feed_size_mm': forms.TextInput(attrs={'inputmode': 'decimal', 'placeholder': _('e.g. 3')}),
            'label': forms.TextInput(attrs={'placeholder': _('e.g. Starter')}),
            'grams_per_dispensing': forms.TextInput(attrs={'inputmode': 'decimal', 'placeholder': _('e.g. 25')}),
            'silo_capacity_kg': forms.TextInput(attrs={'inputmode': 'decimal', 'placeholder': _('e.g. 250')}),
            'notes': forms.TextInput(),
        }

    def validate_constraints(self):
        # One feed size per row spans the whole list, which is saved as a full replace; the formset checks
        # it and the database constraint backs it up. Checking each row against the stored rows would
        # reject keeping a feed size while replacing its row.
        pass


class BaseFeederCalibrationFormSet(RowFormSet):
    default_error_messages = {
        'too_many_forms': ngettext_lazy('A feeder has at most %(num)d calibration.',
                                        'A feeder has at most %(num)d calibrations.', 'num'),
    }

    def get_unique_error_message(self, unique_check):
        return gettext('Two rows have the same feed size.')


FeederCalibrationFormSet = forms.inlineformset_factory(
    Equipment, FeederCalibration, form=FeederCalibrationForm, formset=BaseFeederCalibrationFormSet,
    extra=0, can_delete=True, max_num=50, validate_max=True,
)
