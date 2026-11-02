"""The water chemistry forms: a sample (Record water sample), a round (many points at one time), voiding a
sample, and a species' water limit (Setup › Reference data › Water limits).

A sample's form is one call of farm/water/services.py: the form checks what it can see (a number inside
its parameter's range, a date and time), the service the rest (a deleted point, the backdating window),
and its message lands on the field it concerns. Every value field is the column of the same name,
with the parameter's label, range and precision (farm/water/parameters.py)."""
import uuid

from django import forms
from django.utils import timezone
from django.utils.translation import gettext, gettext_lazy as _

from core.crud import Fieldset, TabbedForm, tab_fields

from ..models import ProductionDepartment, Site, Species, System, Tank, WaterLimit, WaterMeasurement
from ..models.site import zone_of
from ..models.water import BOUNDS, site_of
from ..templatetags.water import limit_text
from ..water import parameters, services
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


def value_field(parameter, help_text=''):
    """The form field of one parameter: its label, range and precision, never required."""
    return forms.DecimalField(
        label=parameter.label, required=False, min_value=parameter.low, max_value=parameter.high,
        decimal_places=parameter.decimals, localize=True, widget=forms.TextInput(attrs=DECIMAL), help_text=help_text)


def point_value(point):
    """A unit or a system as one choice: tank:<id>, system:<id>."""
    return f'{point._meta.model_name}:{point.pk}'


def point_label(point):
    if isinstance(point, System):
        return gettext('%(code)s · %(name)s (loop)') % {'code': point.code, 'name': point.name}
    return f'{point.code} · {point.name}'


def find_point(value):
    """The live unit or system a choice names; None for anything else."""
    kind, _sep, pk = (value or '').partition(':')
    model = {'tank': Tank, 'system': System}.get(kind)
    try:
        uuid.UUID(pk)
    except ValueError:
        return None
    if model is None:
        return None
    related = ('site',) if model is System else ('production_department__site',)
    return model.objects.select_related(*related).filter(pk=pk).first()


def point_choices():
    """The units, then the systems (a loop sample at the sump), each live."""
    units = Tank.objects.select_related('production_department__site').order_by('code')
    systems = System.objects.select_related('site').order_by('code')
    return [(_('Units'), [(point_value(unit), point_label(unit)) for unit in units]),
            (_('Systems (loop)'), [(point_value(system), point_label(system)) for system in systems])]


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
    """One sample at one point. The point is fixed when the dialog opens from a unit (`point`), else chosen;
    the time defaults to now on the site's clock; each value's help shows the limits for the fish there."""

    token = forms.UUIDField(widget=forms.HiddenInput)
    point = forms.ChoiceField(label=_('Unit or system'))
    measured_at = SiteClockField(label=_('Measured at'),
                                 help_text=_('Date and time on the site’s clock.'))
    source = forms.ChoiceField(label=_('Source'), choices=WaterMeasurement.Source.choices,
                               initial=WaterMeasurement.Source.MANUAL)
    notes = forms.CharField(label=_('Notes'), max_length=500, required=False, widget=NOTES)

    service_fields = {}

    def __init__(self, *args, point=None, limits=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fixed = point
        for parameter in MEASURED:
            rows = (limits or {}).get(parameter.code, [])
            help_text = ' '.join(str(part) for part in (parameter.help, *(limit_text(row) for row in rows)) if part)
            self.fields[parameter.code] = value_field(parameter, help_text)
        field = self.fields['point']
        if point is not None:
            field.choices = [(point_value(point), point_label(point))]
            field.initial = point_value(point)
            field.widget = forms.HiddenInput()
        else:
            field.choices = [('', '---------'), *point_choices()]
        self.fields['token'].initial = uuid.uuid4()
        self.fields['measured_at'].initial = timezone.localtime(
            timezone.now(), zone_of(site_of(point)) if point is not None else zone_of(None)).replace(
            second=0, microsecond=0, tzinfo=None)
        self.order_fields(['point', 'measured_at', 'source', *(parameter.code for parameter in MEASURED), 'notes'])

    def clean_point(self):
        point = find_point(self.cleaned_data['point'])
        if point is None:
            raise forms.ValidationError(_('Choose a unit or a system.'))
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
class RoundScopeForm(forms.Form):
    """Which points a round lists and which columns it shows (a GET form: the round's address)."""

    site = forms.ModelChoiceField(label=_('Site'), queryset=Site.objects.order_by('name'), required=False)
    production_department = forms.ModelChoiceField(label=_('Production department'), required=False,
                                                   queryset=ProductionDepartment.objects.none())
    system = forms.ModelChoiceField(label=_('System'), required=False, queryset=System.objects.none())
    columns = forms.MultipleChoiceField(
        label=_('Parameters'), required=False, widget=forms.CheckboxSelectMultiple,
        choices=[(parameter.code, parameter.label) for parameter in MEASURED])

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
        """(site, department, system, columns) chosen; columns default to the morning round's."""
        if not self.is_valid():
            return None, None, None, ROUND_COLUMNS
        data = self.cleaned_data
        return data['site'], data['production_department'], data['system'], data['columns'] or ROUND_COLUMNS

    @staticmethod
    def points(site, department, system):
        """The live units of the scope whose status is not inactive, then the systems of the scope (their
        loops), in code order."""
        if site is None:
            return []
        units = Tank.objects.filter(production_department__site=site).exclude(status=Tank.Status.INACTIVE)
        systems = System.objects.filter(site=site)
        if department is not None:
            units = units.filter(production_department=department)
            systems = systems.filter(production_department=department)
        if system is not None:
            units = units.filter(system=system)
            systems = systems.filter(pk=system.pk)
        return [*units.select_related('production_department__site').order_by('code'),
                *systems.select_related('site').order_by('code')]


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
        self.fields['measured_at'].initial = timezone.localtime(timezone.now(), zone_of(site)).replace(
            second=0, microsecond=0, tzinfo=None)

    def clean_measured_at(self):
        return timezone.make_aware(self.cleaned_data['measured_at'], zone_of(self.site))


class RoundRowForm(ValuesMixin, forms.Form):
    """One point of a round: the chosen columns and a note. Its prefix names the point (tank-<id>)."""

    notes = forms.CharField(label=_('Notes'), max_length=500, required=False)

    def __init__(self, *args, point, columns, **kwargs):
        super().__init__(*args, prefix=f'{point._meta.model_name}-{point.pk}', **kwargs)
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

