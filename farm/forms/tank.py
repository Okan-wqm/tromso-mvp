from decimal import Decimal

from django import forms
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F
from django.template.defaultfilters import floatformat
from django.utils import formats, timezone
from django.utils.translation import gettext, gettext_lazy as _

from core.crud import CodedFormMixin, Fieldset, TabbedForm
from core.widgets import DependentSelect, Output

from ..models import ProductionDepartment, System, Tank
from ..models.tank import (
    KIND_FIELDS, LIMITS, LINER_THICKNESS, LINERS, OFFERED, REQUIRED, SHAPE_MEASURES, VOLUME_FIELDS, Kind, Liner,
    PondType, Shape, described_by,
)

DIMENSIONS = 'dimensions'   # the inner tab with the kind's own fields
CAPACITY = 'capacity'
CALCULATED = ['volume_m3', 'water_volume_m3', 'freeboard', 'max_biomass_kg']
DECIMAL = {'inputmode': 'decimal'}
DATE = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')
NUMBERS = [field.name for field in Tank._meta.concrete_fields if isinstance(field, models.DecimalField)]

# How a kind's fields are grouped on the Dimensions tab; each kind shows only the ones it is described by.
LAYOUT = {
    Kind.TANK: [('', ['shape', 'material']),
                (_('Size'), ['diameter', 'length', 'width', 'stated_volume_m3', 'depth', 'water_depth'])],
    Kind.POND: [('', ['pond_type', 'water_source']),
                (_('Size'), ['surface_area_m2', 'depth', 'max_depth', 'water_depth']),
                (_('Liner'), ['liner_type', 'liner_thickness_mm'])],
    Kind.CAGE: [('', ['cage_type', 'shape']),
                (_('Size'), ['diameter', 'length', 'depth', 'max_submersion_depth']),
                (_('Net and frame'), ['net_material', 'mesh_size_mm', 'frame_type'])],
}
# Labels and help that depend on the kind or the shape: (field, kind or shape) -> (label, help). A field
# not listed keeps its model label.
WORDING = {
    ('depth', Kind.TANK): (_('Depth (m)'), _('From the floor to the rim.')),
    ('depth', Kind.POND): (_('Average depth (m)'), _('The average depth of the water when the pond is full.')),
    ('depth', Kind.CAGE): (_('Net depth (m)'), _('From the water surface to the bottom of the net.')),
    ('water_depth', Kind.TANK): (None, _('The usual water level when it is below the rim; empty when the tank is '
                                         'filled to its depth.')),
    ('water_depth', Kind.POND): (None, _('The usual average water depth when it is below the full depth; empty when '
                                         'the pond is kept full.')),
    ('diameter', Kind.CAGE): (None, _('Across the ring: its circumference divided by π, so a 160 m ring is 50.9 m '
                                      'across.')),
    ('length', Shape.SQUARE): (_('Side (m)'), ''),
    ('length', Shape.OVAL): (_('Long axis (m)'), _('The longest distance across the ellipse.')),
    ('width', Shape.OVAL): (_('Short axis (m)'), _('The shortest distance across, at right angles to the long axis.')),
    ('length', Shape.D_END): (_('Overall length (m)'), _('From end to end; each end is a half circle as wide as the '
                                                         'tank.')),
    ('stated_volume_m3', Shape.OTHER): (_('Volume (m³)'), _('Its volume cannot be calculated from its shape: enter it '
                                                            'as measured or as drawn.')),
    ('surface_area_m2', Kind.POND): (None, _('The water surface when the pond is full.')),
    ('max_depth', Kind.POND): (None, _('At the deepest point, usually by the outlet.')),
    ('max_submersion_depth', Kind.CAGE): (None, _('How deep the top of the cage can be lowered.')),
    ('mesh_size_mm', Kind.CAGE): (None, _('The half mesh, from one knot to the next; a stretched mesh is twice as '
                                          'long.')),
    ('max_density_kg_m3', None): (None, _('The most fish per m³ of water the unit may hold: the welfare limit of the '
                                          'species or the licence’s.')),
}
STATUS_HELP_NEW = _('A new unit starts in one of these; harvesting, cleaning and quarantine come later.')
STATUS_HELP = _('Its current status and the ones it can move to. Harvesting needs fish in the unit.')


def number(value):
    """A bound as the language writes it, e.g. 10,000,000 or 0,1."""
    return formats.number_format(Decimal(value), use_l10n=True, force_grouping=True)


def output(label):
    return forms.CharField(label=label, required=False, disabled=True, widget=Output)


class TankForm(CodedFormMixin, TabbedForm):
    """The unit dialog. The kind decides the fields of the Dimensions tab, and so do the shape (a tank's
    or a cage's), the pond type and the cage type: changing one renders the form again with what was
    entered (TabbedForm.refresh_on). Each field gets the bounds of the chosen kind (models.tank.LIMITS).
    The volume, the water volume, the freeboard and the max biomass are shown, never typed: the database
    calculates them when the unit is saved."""

    tabs = [
        ('general', _('General'), ['name', 'code', 'kind', 'status', 'status_changed_at', 'status_reason',
                                   'water_type', 'regulatory_unit_id']),
        ('location', _('Location'), ['production_department', 'system']),
        # Filled per form with the fields of the chosen kind.
        (DIMENSIONS, _('Dimensions'), []),
        (CAPACITY, _('Capacity'), ['max_density_kg_m3', Fieldset(
            _('Calculated'), CALCULATED,
            _('Worked out from the dimensions and the max density each time the unit is saved; shown as last '
              'saved. The max biomass uses the water volume when there is one, else the volume.'))]),
        ('details', _('Details'), ['installation_date', 'description', 'notes']),
    ]
    fixed_after_creation = ('kind',)
    refresh_on = ('kind', 'shape', 'pond_type', 'cage_type')

    status_changed_at = output(_('Status since'))
    volume_m3 = output(_('Volume (m³)'))
    water_volume_m3 = output(_('Water volume (m³)'))
    freeboard = output(_('Freeboard (m)'))
    max_biomass_kg = output(_('Max biomass (kg)'))

    class Meta:
        model = Tank
        fields = [
            'name', 'code', 'kind', 'status', 'status_reason', 'water_type', 'regulatory_unit_id',
            'production_department', 'system', *KIND_FIELDS, 'depth', 'max_density_kg_m3', 'installation_date',
            'description', 'notes',
        ]
        localized_fields = NUMBERS
        help_texts = {
            'kind': _('A tank, a pond or a cage; it cannot be changed later.'),
            'status_reason': _('Why the unit has its current status, e.g. “net change”. When the status changes, a '
                               'reason left as it was is cleared.'),
            'regulatory_unit_id': _('Its number in reports to the authorities (the kar or merd number), when it is '
                                    'not the code.'),
            'production_department': _('Its site decides which systems can be chosen.'),
            'system': _('Only the systems on the production department’s site, and of that production department '
                        'when a system belongs to one.'),
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': _('e.g. Start feeding tank 3')}),
            'code': forms.TextInput(attrs={'placeholder': _('e.g. T-03'), 'data-uppercase': ''}),
            'status_reason': forms.Textarea(attrs={'rows': 2}),
            'installation_date': DATE,
            'description': forms.Textarea(attrs={'rows': 3}),
            'notes': forms.Textarea(attrs={'rows': 3}),
            **{name: forms.TextInput(attrs=DECIMAL) for name in NUMBERS},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        unit = self.instance
        adding = unit._state.adding
        self._general(unit, adding)
        self._location(unit)
        self._dimensions(unit, adding)
        self._capacity(unit, adding)

    # ---- the tabs ----------------------------------------------------------------------------------
    def _general(self, unit, adding):
        self.fields['kind'].choices = [('', _('Select a kind'))] + Kind.choices
        self.fields['water_type'].choices = [('', _('Select a water type'))] + Tank.WaterType.choices
        status = self.fields['status']
        status.choices = [(value, Tank.Status(value).label) for value in unit.next_statuses()]
        status.help_text = STATUS_HELP_NEW if adding else STATUS_HELP
        if adding:
            del self.fields['status_changed_at']
        else:
            self.initial['status_changed_at'] = formats.date_format(
                timezone.localtime(unit.status_changed_at), 'DATETIME_FORMAT') if unit.status_changed_at else ''

    def _location(self, unit):
        departments = (ProductionDepartment.objects.select_related('site')
                       .order_by(F('site__name').asc(nulls_last=True), 'name'))
        department_field = self.fields['production_department']
        department_field.queryset = departments
        department_field.empty_label = _('Select a production department')
        department_field.label_from_instance = lambda department: (
            f'{department.site.name} · {department.name}' if department.site else
            gettext('%(department)s (no site)') % {'department': department.name})
        on_site = {}
        for department in departments:
            if department.site_id:
                on_site.setdefault(department.site_id, []).append(str(department.pk))

        # A system serves the production departments of its site, or only its own when it has one.
        systems = System.objects.select_related('site').order_by('site__name', 'name')
        system_field = self.fields['system']
        system_field.queryset = systems
        system_field.empty_label = _('Not in a system')
        DependentSelect.apply(system_field, 'production_department', {
            str(system.pk): [str(system.production_department_id)] if system.production_department_id
            else on_site.get(system.site_id, []) for system in systems})

    def _dimensions(self, unit, adding):
        """The fields of the kind the form has now, with that kind's choices, bounds and words."""
        kind = self.current('kind')
        for name, offered in OFFERED.items():
            values = offered.get(kind, [])
            field = self.fields[name]
            field.choices = [('', '')] + [(value, label) for value, label in field.choices if value in values]
        pond_type = self.current('pond_type')
        if pond_type in LINERS:
            liners = self.fields['liner_type']
            liners.choices = [('', '')] + [(value, label) for value, label in liners.choices
                                            if value in LINERS[pond_type]]
        shape = self.current('shape')
        names = described_by(kind, shape or '', pond_type or '', self.current('cage_type') or '')
        for name in (*KIND_FIELDS, 'depth'):
            if name not in names:
                del self.fields[name]

        required = {'depth', *REQUIRED.get(kind, ()), *SHAPE_MEASURES.get(shape, ())}
        if pond_type == PondType.LINED:
            required.add('liner_type')
        for name in names:
            field = self.fields[name]
            field.required = name in required
            if isinstance(field, forms.ChoiceField) and not field.required:
                field.choices = [('', _('Not given')), *field.choices[1:]]
            elif isinstance(field, forms.ChoiceField):
                field.choices = [('', _('Select one')), *field.choices[1:]]
            label, text = WORDING.get((name, shape), None) or WORDING.get((name, kind), (None, ''))
            if label:
                field.label = label
            self._bound(field, name, kind, shape, text)

        if kind is None:
            self.tab_help[DIMENSIONS] = _('Choose the kind on the General tab; its dimensions appear here.')
        elif 'shape' in names and not shape:
            self.tab_help[DIMENSIONS] = _('Choose the shape; the measures it is worked out from appear with it.')
        if not adding and unit.has_stock():
            for name in VOLUME_FIELDS:
                if name in self.fields:
                    self.fields[name].disabled = True
            self.tab_help[DIMENSIONS] = _('Fish are in it, so its size cannot change: move or harvest them first.')
        self.tabs = [(key, label, self._layout(kind) if key == DIMENSIONS else items) for key, label, items in self.tabs]

    def _bound(self, field, name, kind, shape, text):
        """Gives a measure the bounds of the kind (a square's side those of its length and its width)."""
        limits = LIMITS.get(name, {}).get(kind)
        if limits and shape == Shape.SQUARE and name == 'length':
            width = LIMITS['width'][kind]
            limits = (max(limits[0], width[0], key=Decimal), min(limits[1], width[1], key=Decimal))
        if limits:
            low, high = limits
            field.validators += [MinValueValidator(Decimal(low)), MaxValueValidator(Decimal(high))]
            text = ' '.join(str(part) for part in (text, gettext('From %(low)s to %(high)s.') % {
                'low': number(low), 'high': number(high)}) if part)
        elif name == 'liner_thickness_mm':
            membrane, concrete = LINER_THICKNESS[Liner.HDPE], LINER_THICKNESS[Liner.CONCRETE]
            text = gettext('A membrane (HDPE, PVC, EPDM) is %(low)s to %(high)s mm thick, concrete %(concrete_low)s to '
                           '%(concrete_high)s mm.') % {
                'low': number(membrane[0]), 'high': number(membrane[1]),
                'concrete_low': number(concrete[0]), 'concrete_high': number(concrete[1])}
        field.help_text = text

    def _layout(self, kind):
        return [Fieldset(label, [name for name in names if name in self.fields])
                for label, names in LAYOUT.get(kind, [])]

    def _capacity(self, unit, adding):
        density = self.fields['max_density_kg_m3']
        self._bound(density, 'max_density_kg_m3', self.current('kind'), None, WORDING[('max_density_kg_m3', None)][1])
        if adding:
            for name in CALCULATED:
                del self.fields[name]
            self.tab_help[CAPACITY] = _('The volume, the water volume and the max biomass are worked out from the '
                                        'dimensions when the unit is saved.')
            return
        shown = {'volume_m3': (unit.volume_m3, '-3g'), 'water_volume_m3': (unit.water_volume_m3, '-3g'),
                 'freeboard': (unit.freeboard, '-2g'), 'max_biomass_kg': (unit.max_biomass_kg, '-2g')}
        for name, (value, places) in shown.items():
            self.initial[name] = floatformat(value, places) if value is not None else ''
