"""The form of a sampling point (Setup › Facility structure › Sampling points).

A point is on one owner: a unit, a system's loop or a piece of equipment. The form asks which kind of owner first and
shows the choice of that kind only (`owner_type` is not a field of the model: it says which of `unit`, `system` and
`equipment` the form offers, and is drawn again when it changes, TabbedForm.refresh_on). The kinds offered are the
ones that owner can have (farm.models.water_point.kinds_for), and the depth, the flow and the share of the outflow
appear only for the kinds that have them, so what is on the form is what the kind means. The owner is chosen once.

The rules that span rows are the model's `clean()` (an owner's outlet shares add up to at most 100 %, one active
middle point per owner, a kind its owner can have); the database holds the rules of one row."""
from django import forms
from django.utils.translation import gettext_lazy as _

from core.crud import Fieldset, TabbedForm

from ..models import Equipment, SamplingPoint, System, Tank
from ..models.water_point import (EQUIPMENT, OUTLET_KINDS, OWNER_FIELDS, STREAM_KINDS, SYSTEM, UNIT, PointKind,
                                  kinds_for)
from .stock import DECIMAL

OWNER_TYPES = [(UNIT, _('Unit')), (SYSTEM, _('System (its loop)')), (EQUIPMENT, _('Equipment'))]
OWNER_QUERYSETS = {
    UNIT: lambda: Tank.objects.select_related('production_department__site').order_by('code'),
    SYSTEM: lambda: System.objects.select_related('site').order_by('code'),
    EQUIPMENT: lambda: Equipment.objects.select_related('production_department__site').order_by('code'),
}
OWNER_EMPTY = {UNIT: _('Select a unit'), SYSTEM: _('Select a system'), EQUIPMENT: _('Select a piece of equipment')}

TABS = [
    ('point', _('Point'), [
        'owner_type', 'unit', 'system', 'equipment', 'name', 'kind', 'is_active', 'description',
        Fieldset(_('Depth'), ['depth_m']),
        Fieldset(_('Stream'), ['flow_m3_h', 'flow_share_pct'],
                 _('For the mass balance later: the design or last-known flow of the stream here, and for an outlet '
                   'the share of the owner’s outflow that leaves here (a side outlet 90, a bottom drain 10). '
                   'Nothing here is measured.')),
    ]),
]


class SamplingPointForm(TabbedForm):
    tabs = TABS
    fixed_after_creation = ('owner_type', *OWNER_FIELDS)
    refresh_on = ('owner_type', *OWNER_FIELDS, 'kind')

    owner_type = forms.ChoiceField(label=_('Owner'), choices=OWNER_TYPES, initial=UNIT)

    class Meta:
        model = SamplingPoint
        fields = ['unit', 'system', 'equipment', 'name', 'kind', 'depth_m', 'flow_m3_h', 'flow_share_pct',
                  'is_active', 'description']
        localized_fields = ['depth_m', 'flow_m3_h', 'flow_share_pct']
        help_texts = {
            'name': _('Where the water is taken, e.g. “Side outlet”, “After the filter” or “3 m”. Each owner’s '
                      'points have different names.'),
            'kind': _('What the point sees: the stream entering its owner, the water inside it or the stream '
                      'leaving it. A unit’s water, as the rations and the withdrawal read it, is its middle point.'),
            'is_active': _('A point that has samples is not deleted, so its history stays: make it inactive '
                           'instead. An inactive point takes no new samples.'),
            'depth_m': _('The depth of the water taken, from the surface.'),
            'flow_m3_h': _('Cubic metres per hour.'),
            'flow_share_pct': _('From 0 to 100. The shares of the owner’s outlets add up to at most 100.'),
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': _('e.g. Side outlet')}),
            'description': forms.TextInput(),
            **{name: forms.TextInput(attrs=DECIMAL) for name in ('depth_m', 'flow_m3_h', 'flow_share_pct')},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance._state.adding:
            self.initial['owner_type'] = self.instance.owner_type
        owner_type = self.current('owner_type') or UNIT
        for name in OWNER_FIELDS:
            if name != owner_type:
                del self.fields[name]
        field = self.fields[owner_type]
        field.queryset = OWNER_QUERYSETS[owner_type]()
        field.empty_label = OWNER_EMPTY[owner_type]
        field.required = True
        owner = self.current(owner_type)
        kinds = kinds_for(owner) if owner is not None else list(PointKind)
        self.fields['kind'].choices = [('', _('Select a kind')), *((kind.value, kind.label) for kind in kinds)]
        kind = self.current('kind')
        for name, shown in (('depth_m', kind == PointKind.DEPTH), ('flow_m3_h', kind in STREAM_KINDS),
                            ('flow_share_pct', kind in OUTLET_KINDS)):
            if not shown:
                del self.fields[name]

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if not name:
            raise forms.ValidationError(_('Give the point a name.'))
        return name
