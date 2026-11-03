"""The water chemistry forms: a sample (Record water sample), a round (many points at one time), voiding a
sample, a species' water limit (Setup › Reference data › Water limits) and the calculator (Operations ›
Water chemistry › Calculator).

A sample's form is one call of farm/water/services.py: the form checks what it can see (a number inside
its parameter's range, a date and time), the service the rest (a deleted point, the backdating window),
and its message lands on the field it concerns. Every value field is the column of the same name,
with the parameter's label, range and precision (farm/water/parameters.py). A sample is at a sampling point
(farm/models/water_point.py), chosen from the points grouped by their owner, and fixed when the dialog is
opened from a unit or a loop that has one point to take it at."""
import uuid
from decimal import Decimal

from django import forms
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext, gettext_lazy as _

from core.crud import Fieldset, TabbedForm, tab_fields

from ..models import (Equipment, ProductionDepartment, SamplingPoint, Site, Species, System, Tank, WaterLimit,
                      WaterMeasurement)
from ..models.site import zone_of
from ..models.water import BOUNDS
from ..models.water_point import EQUIPMENT, SYSTEM, UNIT, PointKind, owner_type_of, site_of
from ..templatetags.water import limit_text
from ..water import chemistry, deffeyes, parameters, services
from ..water.parameters import GROUPS, MEASURED
from .stock import DECIMAL, ServiceErrors, VoidForm

NOTES = forms.Textarea(attrs={'rows': 2})
# The columns a round shows unless others are chosen: the morning round's temperature and oxygen.
ROUND_COLUMNS = ['temperature_c', 'oxygen_mg_l', 'oxygen_saturation_pct']


class SiteClockField(forms.DateTimeField):
    """A date and time on the clock of the point's site: read as typed, without a zone. The form puts it in
    the site's zone (farm.models.site.zone_of); the browser's zone is never used (WQ-10)."""

    widget = forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M')

    def prepare_value(self, value):
        return value

    def to_python(self, value):
        moment = super().to_python(value)      # aware in the current zone, the wall clock kept
        return None if moment is None else timezone.make_naive(moment, timezone.get_current_timezone())


def clock(point):
    """The clock a sample's time is read on: the point's site; before a point is chosen, the zone every site
    shares, else the company's."""
    if point is not None:
        return zone_of(site_of(point))
    zones = {zone_of(site) for site in Site.objects.all()}
    return zones.pop() if len(zones) == 1 else zone_of(None)


def now_on(zone):
    """Now on a clock, to the minute, as the date and time field shows it."""
    return timezone.localtime(timezone.now(), zone).replace(second=0, microsecond=0, tzinfo=None)


def value_field(parameter, help_text=''):
    """The form field of one parameter: its label, range and precision, never required."""
    return number_field(parameter.label, parameter.low, parameter.high, parameter.decimals, help_text=help_text)


def number_field(label, low, high, decimals, help_text='', required=False):
    """A decimal field typed as the language writes it, inside its range and at its precision."""
    return forms.DecimalField(
        label=label, required=required, min_value=Decimal(str(low)), max_value=Decimal(str(high)),
        decimal_places=decimals, localize=True, widget=forms.TextInput(attrs=DECIMAL), help_text=help_text)


def point_label(point):
    """A point as the choices say it: "T-01 › Middle"."""
    return str(point)


def find_point(value):
    """The live sampling point (of a live owner) a choice names, its owner loaded; None for anything else."""
    try:
        uuid.UUID(value or '')
    except ValueError:
        return None
    return SamplingPoint.objects.with_owners().filter(pk=value).first()


def point_order(point):
    """Owners by type (units, loops, equipment) and code, each owner's points in the order of the kinds."""
    rank = {UNIT: 0, SYSTEM: 1, EQUIPMENT: 2}[point.owner_type]
    kinds = list(PointKind.values)
    return rank, point.owner.code, kinds.index(point.kind), point.name


def point_groups(points):
    """[(group label, [(point id, label)])] of the points, grouped by what owns them: units, loops, equipment."""
    groups = {UNIT: (_('Units'), []), SYSTEM: (_('Systems (loop)'), []), EQUIPMENT: (_('Equipment'), [])}
    for point in sorted(points, key=point_order):
        groups[point.owner_type][1].append((str(point.pk), point_label(point)))
    return [(label, choices) for label, choices in groups.values() if choices]


class ValuesMixin:
    """The value fields of a form, in the record form's groups."""

    def value_groups(self):
        """[(group label, [bound fields])] of the value fields the form has."""
        groups = []
        for key, label in GROUPS:
            fields = [self[parameter.code] for parameter in parameters.in_group(key) if parameter.code in self.fields]
            if fields:
                groups.append((label, fields))
        return groups

    def entered(self):
        return {parameter.code: self.cleaned_data.get(parameter.code) for parameter in MEASURED
                if parameter.code in self.fields and self.cleaned_data.get(parameter.code) is not None}


class WaterSampleForm(ValuesMixin, ServiceErrors, forms.Form):
    """One sample at one point. Opened from a unit, a loop or a piece of equipment (`owner`) it offers that owner's
    active points, with `point` (its middle one by default) chosen, so routine entry is not slower; one point is
    fixed. Opened from nothing it offers every active point, grouped by owner. The time defaults to now on the
    site's clock; each value's help shows the limits for the fish there."""

    token = forms.UUIDField(widget=forms.HiddenInput)
    point = forms.ChoiceField(label=_('Sampling point'))
    measured_at = SiteClockField(label=_('Measured at'),
                                 help_text=_('Date and time on the site’s clock.'))
    source = forms.ChoiceField(label=_('Source'), choices=WaterMeasurement.Source.choices,
                               initial=WaterMeasurement.Source.MANUAL)
    notes = forms.CharField(label=_('Notes'), max_length=500, required=False, widget=NOTES)

    service_fields = {}

    def __init__(self, *args, owner=None, point=None, limits=None, **kwargs):
        super().__init__(*args, **kwargs)
        for parameter in MEASURED:
            rows = (limits or {}).get(parameter.code, [])
            help_text = ' '.join(str(part) for part in (parameter.help, *(limit_text(row) for row in rows)) if part)
            self.fields[parameter.code] = value_field(parameter, help_text)
        points = SamplingPoint.objects.filter(is_active=True).with_owners()
        if owner is not None:
            points = points.filter(**{owner_type_of(owner): owner})
        points = list(points)
        field = self.fields['point']
        field.choices = [('', '---------'), *point_groups(points)] if owner is None else point_groups(points)
        self.fixed = len(points) == 1 and owner is not None
        if point is not None:
            field.initial = str(point.pk)
        if self.fixed:
            field.initial = str(points[0].pk)
            field.widget = forms.HiddenInput()
        self.fields['token'].initial = uuid.uuid4()
        self.fields['measured_at'].initial = now_on(clock(point or (points[0] if self.fixed else None)))
        self.order_fields(['point', 'measured_at', 'source', *(parameter.code for parameter in MEASURED), 'notes'])

    def clean_point(self):
        point = find_point(self.cleaned_data['point'])
        if point is None:
            raise forms.ValidationError(_('Choose a sampling point.'))
        return point

    def clean(self):
        cleaned = super().clean()
        point, moment = cleaned.get('point'), cleaned.get('measured_at')
        if point is not None and moment is not None:
            cleaned['measured_at'] = timezone.make_aware(moment, zone_of(site_of(point)))
        if not self.entered() and not any(parameter.code in self.errors for parameter in MEASURED):
            self.add_error(None, _('Enter at least one value.'))
        return cleaned

    def save(self, user):
        data = self.cleaned_data
        return services.record(user, point=data['point'], measured_at=data['measured_at'], source=data['source'],
                               values=self.entered(), notes=data['notes'], token=data['token'])


# ---- a round --------------------------------------------------------------------------------------------
# What a round can list besides the middle points of the units and loops: the other kinds of point, and the
# equipment's points (EQUIPMENT: all its active points, a piece of equipment having no middle one to default to).
INCLUDE_CHOICES = [(kind.value, kind.label) for kind in PointKind if kind != PointKind.MIDDLE] + [
    (EQUIPMENT, _('Points of equipment'))]


class RoundScopeForm(forms.Form):
    """Which points a round lists and which columns it shows (a GET form: the round's address). A round has one
    row per unit's middle point and per loop, and lists the other points of the same units and loops, and the
    equipment's, when asked."""

    site = forms.ModelChoiceField(label=_('Site'), queryset=Site.objects.order_by('name'), required=False)
    production_department = forms.ModelChoiceField(label=_('Production department'), required=False,
                                                   queryset=ProductionDepartment.objects.none())
    system = forms.ModelChoiceField(label=_('System'), required=False, queryset=System.objects.none())
    columns = forms.MultipleChoiceField(
        label=_('Parameters'), required=False, widget=forms.CheckboxSelectMultiple,
        choices=[(parameter.code, parameter.label) for parameter in MEASURED])
    include = forms.MultipleChoiceField(label=_('Also list'), required=False, widget=forms.CheckboxSelectMultiple,
                                        choices=INCLUDE_CHOICES)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        site = self.chosen_site()
        departments = ProductionDepartment.objects.filter(site=site) if site else ProductionDepartment.objects.none()
        self.fields['production_department'].queryset = departments.order_by('name')
        self.fields['system'].queryset = (System.objects.filter(site=site) if site else System.objects.none()).order_by(
            'name')

    def chosen_site(self):
        value = self.data.get('site', '')
        try:
            uuid.UUID(value)
        except ValueError:
            return None
        return Site.objects.filter(pk=value).first()

    def scope(self):
        """(site, department, system, columns, include) chosen; columns default to the morning round's."""
        if not self.is_valid():
            return None, None, None, ROUND_COLUMNS, []
        data = self.cleaned_data
        return (data['site'], data['production_department'], data['system'], data['columns'] or ROUND_COLUMNS,
                data['include'])

    @staticmethod
    def points(site, department, system, include=()):
        """The active points of the scope, a round's rows: the middle point of each live unit whose status is not
        inactive and of each system (its loop), and the other kinds of point of those owners and the points of
        the equipment of the scope that `include` names; owners in code order, units first."""
        if site is None:
            return []
        units = Tank.objects.filter(production_department__site=site).exclude(status=Tank.Status.INACTIVE)
        systems = System.objects.filter(site=site)
        equipment = (Equipment.objects.filter(production_department__site=site) if EQUIPMENT in include
                     else Equipment.objects.none())
        if department is not None:
            units = units.filter(production_department=department)
            systems = systems.filter(production_department=department)
            equipment = equipment.filter(production_department=department)
        if system is not None:
            units = units.filter(system=system)
            systems = systems.filter(pk=system.pk)
            equipment = equipment.filter(system_links__system=system)
        kinds = {PointKind.MIDDLE, *(kind for kind in include if kind != EQUIPMENT)}
        points = (SamplingPoint.objects.filter(is_active=True)
                  .filter(Q(unit__in=units) | Q(system__in=systems) | Q(equipment__in=equipment)).with_owners())
        return sorted((point for point in points if point.equipment_id or point.kind in kinds), key=point_order)


class RoundForm(ServiceErrors, forms.Form):
    """The round's shared time and source."""

    token = forms.UUIDField(widget=forms.HiddenInput)
    measured_at = SiteClockField(label=_('Measured at'), help_text=_('Date and time on the site’s clock.'))
    source = forms.ChoiceField(label=_('Source'), choices=WaterMeasurement.Source.choices,
                               initial=WaterMeasurement.Source.MANUAL)

    service_fields = {}

    def __init__(self, *args, site=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.site = site
        self.fields['token'].initial = uuid.uuid4()
        self.fields['measured_at'].initial = now_on(zone_of(site))

    def clean_measured_at(self):
        return timezone.make_aware(self.cleaned_data['measured_at'], zone_of(self.site))


class RoundRowForm(ValuesMixin, forms.Form):
    """One point of a round: the chosen columns and a note. Its prefix names the point (point-<id>)."""

    notes = forms.CharField(label=_('Notes'), max_length=500, required=False)

    def __init__(self, *args, point, columns, **kwargs):
        super().__init__(*args, prefix=f'point-{point.pk}', **kwargs)
        self.point = point
        for parameter in MEASURED:
            if parameter.code in columns:
                self.fields[parameter.code] = value_field(parameter)
        self.order_fields([*columns, 'notes'])

    def add_service_error(self, code, message):
        self.add_error(code if code in self.fields else None, message)


# ---- voiding --------------------------------------------------------------------------------------------
class SampleVoidForm(VoidForm):
    """The stock's void form, said of a sample."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['reason'].help_text = _('E.g. “typed into the wrong unit”. The sample stays in the history, '
                                            'struck through, with this reason.')


# ---- limits ---------------------------------------------------------------------------------------------
WATER_LIMIT_TABS = [
    ('limit', _('Limit'), ['species', 'parameter', 'water_type',
                           Fieldset(_('Bounds'), list(BOUNDS),
                                    _('Inside the warning bounds a value is ok; outside them, a warning; outside the '
                                      'critical bounds, critical. A value on a bound is in the inner band. Leave '
                                      'a bound empty where there is none.')),
                           'reference']),
]


class WaterLimitForm(TabbedForm):
    """A species' limits for one parameter. The bounds are in the parameter's unit, shown once it is chosen
    (the form is drawn again when the parameter changes, TabbedForm.refresh_on)."""

    tabs = WATER_LIMIT_TABS
    refresh_on = ('parameter',)

    class Meta:
        model = WaterLimit
        fields = tab_fields(WATER_LIMIT_TABS)
        localized_fields = BOUNDS
        help_texts = {
            'water_type': _('The water of the units it applies to. A row for a unit’s water type wins over the row '
                            'for any water.'),
            'reference': _('Where the values come from, e.g. “the vet, November 2026” or a guideline.'),
        }
        widgets = {
            **{bound: forms.TextInput(attrs=DECIMAL) for bound in BOUNDS},
            'reference': forms.TextInput(attrs={'placeholder': _('e.g. the vet, November 2026')}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['species'].queryset = Species.objects.order_by('common_name')
        self.fields['species'].empty_label = _('Select a species')
        self.fields['parameter'].choices = [('', _('Select a parameter'))] + list(parameters.LIMIT_CHOICES)
        code = self.current('parameter')
        if code in parameters.BY_CODE:
            measure = parameters.get(code)
            self.tab_help['limit'] = gettext('%(parameter)s: bounds from %(low)s to %(high)s, at most %(decimals)d '
                                                 'decimals.') % {
                'parameter': measure.label, 'low': measure.low, 'high': measure.high, 'decimals': measure.decimals}



# ---- the calculator -----------------------------------------------------------------------------------------
def _measured(code, required=False, low=None, help_text=None):
    """A measured parameter's field in the calculator: its label, range and precision (the pH's range starts
    at the chart's, 4)."""
    parameter = parameters.get(code)
    return number_field(parameter.label, parameter.low if low is None else low, parameter.high, parameter.decimals,
                        help_text=parameter.help if help_text is None else help_text, required=required)


class CalculatorForm(forms.Form):
    """The water the Water Quality Management Chart is drawn for, a target, the limits and the chart's layers.
    A GET form: the values live in the address and nothing is stored. Without values it shows DEFAULTS: the
    source's example water, and limits that are defaults, not the limits of any fish (farm/water/deffeyes.py;
    the bug document, WQ-30 on). A measured value has its parameter's label, range and precision."""

    temperature_c = _measured('temperature_c', required=True)
    ph = _measured('ph', required=True, low=4)
    salinity_ppt = _measured('salinity_ppt', required=True)
    alkalinity_mg_l = _measured('alkalinity_mg_l', required=True)
    tan_mg_l = _measured('tan_mg_l', help_text=_('NH₃ and NH₄⁺ together, as nitrogen. The NH₃ limit is drawn from '
                                                 'it.'))
    total_sulfide_ug_l = number_field(
        _('Total sulfide (µg/L as S)'), 0, 10000, 1,
        _('Sulfide as a laboratory or a methylene-blue kit reports it, as S. The H₂S is worked out from it, the '
          'pH, the temperature and the salinity.'))
    oxygen_mg_l = _measured('oxygen_mg_l', help_text=_('For the oxygen saturation.'))
    calcium_mg_l = number_field(_('Calcium (mg/L Ca²⁺)'), 0, 2000, 1,
                                _('For the calcite and aragonite saturation lines, in water of 5 to 44 ‰.'))
    altitude_m = number_field(_('Altitude (m)'), 0, 5000, 0,
                              _('For the oxygen saturation: the pressure of the standard atmosphere there. Empty is '
                                'sea level.'))
    target_ph = number_field(_('Target pH (NBS scale)'), 4, 12, 2)
    target_alkalinity_mg_l = number_field(_('Target alkalinity (mg/L as CaCO₃)'), 0, 1000, 0)
    alkalinity_low_mg_l = number_field(_('Alkalinity band, low (mg/L as CaCO₃)'), 0, 1000, 0,
                                       _('The safe zone lies in this band.'))
    alkalinity_high_mg_l = number_field(_('Alkalinity band, high (mg/L as CaCO₃)'), 0, 1000, 0)
    nh3_n_limit_mg_l = number_field(
        _('NH₃-N limit (mg/L as N)'), Decimal('0.0001'), 100, 4,
        _('Default 0.0103: 0.0125 mg/L NH₃ (Piper et al. 1982) as nitrogen.'))
    co2_limit_mg_l = number_field(_('CO₂ limit (mg/L)'), Decimal('0.1'), 200, 1,
                                  _('Default 15 mg/L, a common guideline for salmonids.'))
    h2s_limit_ug_l = number_field(_('H₂S limit (µg/L H₂S)'), Decimal('0.1'), 10000, 1,
                                  _('Default 2 µg/L, the US EPA criterion for un-ionised H₂S (1986).'))
    layers = forms.MultipleChoiceField(label=_('Show on the chart'), choices=deffeyes.LAYERS, required=False,
                                       widget=forms.CheckboxSelectMultiple)

    GROUPS = [
        (_('Water'), ['temperature_c', 'ph', 'salinity_ppt', 'alkalinity_mg_l', 'tan_mg_l', 'total_sulfide_ug_l',
                      'oxygen_mg_l', 'calcium_mg_l', 'altitude_m']),
        (_('Target and alkalinity band'), ['target_ph', 'target_alkalinity_mg_l', 'alkalinity_low_mg_l',
                                           'alkalinity_high_mg_l']),
        (_('Limits'), ['nh3_n_limit_mg_l', 'co2_limit_mg_l', 'h2s_limit_ug_l']),
    ]
    DEFAULTS = {
        'temperature_c': Decimal('12'), 'ph': Decimal('7.00'), 'salinity_ppt': Decimal('1'),
        'alkalinity_mg_l': Decimal('80'), 'tan_mg_l': Decimal('0.5'), 'total_sulfide_ug_l': Decimal('2'),
        'oxygen_mg_l': None, 'calcium_mg_l': None, 'altitude_m': None,
        'target_ph': Decimal('7.5'), 'target_alkalinity_mg_l': Decimal('100'),
        'alkalinity_low_mg_l': Decimal('50'), 'alkalinity_high_mg_l': Decimal('100'),
        'nh3_n_limit_mg_l': Decimal('0.0103'), 'co2_limit_mg_l': Decimal('15'), 'h2s_limit_ug_l': Decimal('2'),
        'layers': [key for key, _label in deffeyes.LAYERS],
    }
    # A submitted form carries this, so a chart with every layer unticked stays so.
    DRAWN = 'drawn'

    def __init__(self, data=None, **kwargs):
        super().__init__(data, initial=self.DEFAULTS, **kwargs)

    def groups(self):
        return [(label, [self[name] for name in names]) for label, names in self.GROUPS]

    def clean_layers(self):
        if self.DRAWN not in self.data:
            return self.DEFAULTS['layers']
        return self.cleaned_data['layers']

    def clean(self):
        data = super().clean()
        for pair in (('target_ph', 'target_alkalinity_mg_l'), ('alkalinity_low_mg_l', 'alkalinity_high_mg_l')):
            given = [name for name in pair if data.get(name) is not None]
            if len(given) == 1 and not any(name in self.errors for name in pair):
                self.add_error(next(name for name in pair if name not in given), _('Give both or neither.'))
        low, high = data.get('alkalinity_low_mg_l'), data.get('alkalinity_high_mg_l')
        if low is not None and high is not None and low >= high:
            self.add_error('alkalinity_high_mg_l', _('The band goes up: its high end is above its low end.'))
        self._possible(data)
        return data

    def _possible(self, data):
        """A pH the alkalinity allows: hydroxide and borate are alkalinity too, so at a high pH the alkalinity
        has a floor, below which the DIC would be negative. Checked for the water and the target once their
        values are in."""
        if data.get('temperature_c') is None or data.get('salinity_ppt') is None:
            return
        eq = chemistry.equilibria(float(data['temperature_c']), float(data['salinity_ppt']))
        for ph_name, alkalinity_name in (('ph', 'alkalinity_mg_l'), ('target_ph', 'target_alkalinity_mg_l')):
            if data.get(ph_name) is None or data.get(alkalinity_name) is None:
                continue
            floor = eq.isoline(float(data[ph_name]))[1] * chemistry.MG_CACO3_PER_MEQ
            if float(data[alkalinity_name]) <= floor:
                self.add_error(alkalinity_name, _('At this pH the alkalinity is above %(floor)s mg/L as CaCO₃: '
                                                  'the hydroxide and borate alone are that much.')
                               % {'floor': deffeyes.shown(floor, 1)})

    def values(self):
        """The values the chart is drawn for: those of a submitted form, DEFAULTS before."""
        return self.cleaned_data if self.is_bound else self.DEFAULTS

    def inputs(self):
        """(water, limits, target, pressure in atm, layers) for farm/water/deffeyes.py."""
        values = {name: float(value) if isinstance(value, Decimal) else value for name, value in self.values().items()}
        water = deffeyes.Water(
            temperature_c=values['temperature_c'], salinity_ppt=values['salinity_ppt'], ph=values['ph'],
            alkalinity_mg_l=values['alkalinity_mg_l'], tan_mg_l=values['tan_mg_l'],
            total_sulfide_ug_l=values['total_sulfide_ug_l'], calcium_mg_l=values['calcium_mg_l'],
            oxygen_mg_l=values['oxygen_mg_l'])
        limits = deffeyes.Limits(
            nh3_n_mg_l=values['nh3_n_limit_mg_l'], co2_mg_l=values['co2_limit_mg_l'],
            h2s_ug_l=values['h2s_limit_ug_l'], alkalinity_low_mg_l=values['alkalinity_low_mg_l'],
            alkalinity_high_mg_l=values['alkalinity_high_mg_l'])
        target = None
        if values['target_ph'] is not None:
            target = deffeyes.Target(values['target_ph'], values['target_alkalinity_mg_l'])
        altitude = values['altitude_m']
        pressure = chemistry.pressure_atm(altitude) if altitude is not None else 1.0
        return water, limits, target, pressure, frozenset(values['layers'])
