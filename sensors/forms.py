"""The sensors configuration forms. Every field is a column of its table; the rules the database holds are its constraints
(the form shows their messages), and the ones it cannot hold are here, said in words: a device's time unit against its
interval, a device's interval against its channels' heartbeats, a channel's deadband against its quantity's precision,
its heartbeat against its device's interval, its range against what its quantity can be, its value path against its
device's payload shape, and its address as a JSON object. A new channel takes the catalogue's defaults (sensors/
quantities.py) for every reduction field left empty, and shows them when its quantity is chosen."""
from datetime import datetime
from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext as _, gettext_lazy, ngettext_lazy

from core.crud import DRAFT, CodedFormMixin, RowFormSet, TabbedForm, tab_fields
from core.dates import on_clock
from farm.models import Equipment, SamplingPoint, Site, System, Tank
from farm.models.site import zone_of
from core.widgets import MomentInput

from . import bindings, quantities
from .models import (AlarmRule, Binding, Calibration, Channel, Connection, Credential, Device, PayloadFormat, Shape,
                     TimeUnit)

DECIMAL = {'inputmode': 'decimal'}
# A whole-second device time cannot tell apart two messages of one second, and the readings' key is (channel, time):
# a device whose time is in whole seconds must send at most every two seconds.
WHOLE_SECONDS_MIN_INTERVAL = 2

CONNECTION_TABS = [
    ('general', gettext_lazy('General'), ['name', 'is_active']),
    ('connection', gettext_lazy('Connection'), ['host', 'port', 'use_tls', 'username', 'secret_file', 'client_id',
                                                'keepalive_s']),
]


class ConnectionForm(TabbedForm):
    tabs = CONNECTION_TABS

    class Meta:
        model = Connection
        fields = tab_fields(CONNECTION_TABS)
        help_texts = {
            'is_active': gettext_lazy('An inactive connection is not listened to: its devices send to no one.'),
            'username': gettext_lazy('The ingest service’s own user name at the broker.'),
            'secret_file': gettext_lazy('The name of the file under /run/secrets that holds the ingest service’s password '
                                        'at the broker (the compose secret mqtt_ingest). The password itself is never '
                                        'typed or stored here.'),
            'client_id': gettext_lazy('The MQTT client id the ingest service connects with; unique among connections.'),
            'keepalive_s': gettext_lazy('From 5 to 600 seconds.'),
        }


FORMAT_TABS = [
    ('general', gettext_lazy('General'), ['name', 'encoding']),
    ('time', gettext_lazy('Time and sequence'), ['time_path', 'time_unit', 'seq_path']),
    ('shape', gettext_lazy('Shape'), ['shape', 'items_path', 'name_key', 'value_key']),
]


class PayloadFormatForm(TabbedForm):
    tabs = FORMAT_TABS

    class Meta:
        model = PayloadFormat
        fields = tab_fields(FORMAT_TABS)
        help_texts = {
            'time_path': gettext_lazy('A JSON pointer to the device’s time, e.g. /ts. Empty: the time the message is '
                                      'received, and the reading says so.'),
            'seq_path': gettext_lazy('A JSON pointer to the device’s sequence number, e.g. /seq; empty for none. It is '
                                     'shown, never used to refuse a message.'),
            'items_path': gettext_lazy('A list of items: where the list is, e.g. /items; empty when the message is the '
                                       'list.'),
            'name_key': gettext_lazy('A list of items: the key of an item that names its channel, e.g. n.'),
            'value_key': gettext_lazy('A list of items: the key of an item’s value, e.g. v.'),
        }


DEVICE_TABS = [
    ('general', gettext_lazy('General'), ['connection', 'code', 'name', 'site', 'equipment', 'manufacturer', 'model',
                                          'note', 'is_active', 'is_simulated']),
    ('payload', gettext_lazy('Payload'), ['payload_format', 'topic', 'expected_interval_s']),
    ('credential', gettext_lazy('Credential'), ['credential']),
]


class DeviceForm(CodedFormMixin, TabbedForm):
    """A device: where it publishes, how, and how often. Its connection is chosen once (its channels' numbers and
    readings stay with it). Its site is where it is: while it is placed, the site of its place, which a move
    changes (sensors/bindings.py `move_device`), never this form."""

    tabs = DEVICE_TABS
    fixed_after_creation = ('connection',)

    class Meta:
        model = Device
        fields = tab_fields(DEVICE_TABS)
        help_texts = {
            'topic': gettext_lazy('The topic the device publishes on, as its maker or integrator set it. No “#”; one '
                                  '“+” may stand for a level the device fills in (its serial number).'),
            'expected_interval_s': gettext_lazy('How often the device sends a message. Offline after three times this '
                                                'without one.'),
            'equipment': gettext_lazy('The piece of equipment this device is, if it is one on the Equipment tab.'),
            'credential': gettext_lazy('The broker credential the device publishes with; one gateway may serve many '
                                       'devices.'),
            'is_simulated': gettext_lazy('A simulator or test device: its values are stored marked simulated and used '
                                         'nowhere.'),
        }
        widgets = {'note': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['site'].queryset = Site.objects.order_by('name')
        self.fields['equipment'].queryset = Equipment.objects.order_by('code')
        self.fields['credential'].queryset = Credential.objects.order_by('username')
        self.fields['payload_format'].queryset = PayloadFormat.objects.order_by('name')
        self.fields['connection'].queryset = Connection.objects.order_by('name')
        if self.instance.pk and bindings.holds_site(self.instance):
            self.fields['site'].disabled = True
            self.fields['site'].help_text = _('Where the device is placed now: a move to another site changes it (Move '
                                              'device).')

    def clean(self):
        cleaned = super().clean()
        payload_format, interval = cleaned.get('payload_format'), cleaned.get('expected_interval_s')
        if payload_format and interval and payload_format.time_unit == TimeUnit.EPOCH_S \
                and interval < WHOLE_SECONDS_MIN_INTERVAL:
            self.add_error('expected_interval_s', _(
                'Times in whole seconds cannot tell apart messages sent every second: send every %(seconds)d seconds '
                'or more, or use a format with milliseconds.') % {'seconds': WHOLE_SECONDS_MIN_INTERVAL})
        if interval and not self.instance._state.adding:
            for channel in self.instance.channels.filter(heartbeat_s__lt=interval).order_by('code'):
                self.add_error('expected_interval_s', _(
                    'Channel %(code)s stores at least every %(heartbeat)d seconds, more often than the device would send: '
                    'lengthen its heartbeat first.') % {'code': channel.code, 'heartbeat': channel.heartbeat_s})
                break
        return cleaned


CHANNEL_TABS = [
    ('source', gettext_lazy('Source'), ['device', 'code', 'name', 'value_path', 'item_name', 'note']),
    ('quantity', gettext_lazy('Quantity and unit'), ['quantity', 'unit', 'unit_factor', 'unit_offset']),
    ('address', gettext_lazy('Address'), ['address_protocol', 'address']),
    ('reduction', gettext_lazy('Storing'), ['reduction', 'deadband', 'heartbeat_s', 'fresh_heartbeats', 'range_min',
                                            'range_max', 'state']),
]
# The fields a new channel takes from its quantity when they are left empty.
DEFAULTED = ('unit', 'reduction', 'deadband', 'heartbeat_s', 'range_min', 'range_max')


def number(value):
    """A catalogue number as the pages write it: 2, 0.02, -1000."""
    return format(Decimal(value).normalize(), 'f')


class AddressField(forms.JSONField):
    """A channel's address: a JSON object (an empty one for MQTT)."""

    def to_python(self, value):
        found = super().to_python(value if value not in (None, '') else '{}')
        if not isinstance(found, dict):
            raise ValidationError(_('The address is a JSON object, e.g. {"unit_id": 1, "function": 3, "register": '
                                    '40001}.'))
        return found


class ChannelForm(CodedFormMixin, TabbedForm):
    """A channel. Its device and its quantity are chosen once: the readings stored under its number mean that quantity
    of that device. A new channel's empty reduction fields take the quantity's defaults, and choosing the quantity shows
    them."""

    tabs = CHANNEL_TABS
    fixed_after_creation = ('device', 'quantity')
    refresh_on = ('quantity',)

    class Meta:
        model = Channel
        fields = tab_fields(CHANNEL_TABS)
        field_classes = {'address': AddressField}
        localized_fields = ['unit_factor', 'unit_offset', 'deadband', 'range_min', 'range_max']
        help_texts = {
            'value_path': gettext_lazy('One object per message: a JSON pointer to this channel’s value, e.g. '
                                       '/tags/o2/value.'),
            'item_name': gettext_lazy('A list of items: the name the item of this channel has, e.g. do.'),
            'unit': gettext_lazy('The unit the instrument sends, when it differs from the quantity’s.'),
            'unit_factor': gettext_lazy('Stored value = factor × (calibrated value) + offset, in the quantity’s unit.'),
            'address': gettext_lazy('Where a PLC or field bus holds the value, as JSON. Modbus: unit_id, function, '
                                    'register; S7: db, offset; OPC UA: node_id; MQTT: nothing.'),
            'deadband': gettext_lazy('A value is stored again when it moves this much from the last stored one, in the '
                                     'quantity’s unit. Empty: the quantity’s default.'),
            'heartbeat_s': gettext_lazy('A value is stored at least this often even when it does not move. Fresh for '
                                        'the heartbeats below. Empty: the quantity’s default.'),
            'range_min': gettext_lazy('A value outside the range is stored, marked, and used nowhere. Empty on a new '
                                      'channel: what the quantity can be.'),
            'state': gettext_lazy('In maintenance its values are stored, marked, and used nowhere; retired, they are '
                                  'not listened to.'),
        }
        widgets = {
            'note': forms.Textarea(attrs={'rows': 2}),
            'address': forms.Textarea(attrs={'rows': 3, 'spellcheck': 'false'}),
            **{name: forms.TextInput(attrs=DECIMAL) for name in ('unit_factor', 'unit_offset', 'deadband', 'range_min',
                                                                  'range_max')},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['device'].queryset = Device.objects.select_related('payload_format').order_by('code')
        adding = self.instance._state.adding
        for name in DEFAULTED:
            if adding:
                self.fields[name].required = False
        if adding and self.draft is not None and self.draft.get(DRAFT) == 'quantity' \
                and self.draft.get('quantity') in quantities.BY_CODE:
            for name, value in quantities.defaults(self.draft['quantity']).items():
                self.initial[name] = value
                self.draft = self.draft.copy()
                self.draft.pop(name, None)

    def get_initial_for_field(self, field, field_name):
        if self.instance._state.adding and field_name in DEFAULTED and field_name in self.initial \
                and self.draft is not None and self.draft.get(DRAFT) == 'quantity':
            return self.initial[field_name]
        return super().get_initial_for_field(field, field_name)

    def clean(self):
        cleaned = super().clean()
        code = cleaned.get('quantity') or getattr(self.instance, 'quantity', '')
        quantity = quantities.BY_CODE.get(code)
        device = cleaned.get('device') or (self.instance.device if self.instance.device_id else None)
        if quantity is None:
            return cleaned
        if self.instance._state.adding:
            defaults = quantities.defaults(code)
            ranged = cleaned.get('range_min') is None and cleaned.get('range_max') is None
            for name in DEFAULTED:
                if name in ('range_min', 'range_max'):
                    if ranged:
                        cleaned[name] = defaults[name]
                elif cleaned.get(name) in (None, ''):
                    cleaned[name] = defaults[name]
            for name in DEFAULTED:
                setattr(self.instance, name, cleaned[name])
        self._check_deadband(cleaned, quantity)
        self._check_range(cleaned, quantity)
        if device is not None:
            self._check_device(cleaned, device)
        return cleaned

    def _check_deadband(self, cleaned, quantity):
        deadband = cleaned.get('deadband')
        if cleaned.get('reduction') == quantities.DEADBAND and deadband is not None and 0 < deadband < quantity.step:
            self.add_error('deadband', _('A deadband of %(value)s is finer than the precision of %(quantity)s, %(step)s: '
                                         'a smaller change is noise.') % {
                'value': number(str(deadband)), 'quantity': quantity.label, 'step': number(quantity.step)})

    def _check_range(self, cleaned, quantity):
        low, high = cleaned.get('range_min'), cleaned.get('range_max')
        if low is not None and high is not None and (low < quantity.low or high > quantity.high):
            self.add_error('range_max', _('The range %(low)s to %(high)s is outside what %(quantity)s can be: %(min)s to '
                                          '%(max)s.') % {
                'low': number(str(low)), 'high': number(str(high)), 'quantity': quantity.label,
                'min': number(quantity.low), 'max': number(quantity.high)})

    def _check_device(self, cleaned, device):
        heartbeat = cleaned.get('heartbeat_s')
        if heartbeat and heartbeat < device.expected_interval_s:
            self.add_error('heartbeat_s', _('A heartbeat of %(heartbeat)d seconds is shorter than the %(interval)d '
                                            'seconds the device sends every.') % {
                'heartbeat': heartbeat, 'interval': device.expected_interval_s})
        shape = device.payload_format.shape
        if shape == Shape.OBJECT and not cleaned.get('value_path'):
            self.add_error('value_path', _('Give the value’s path: the device’s payload format is one object.'))
        if shape == Shape.OBJECT and cleaned.get('item_name'):
            self.add_error('item_name', _('No item name: the device’s payload format is one object.'))
        if shape == Shape.ARRAY and not cleaned.get('item_name'):
            self.add_error('item_name', _('Give the item’s name: the device’s payload format is a list of items.'))
        if shape == Shape.ARRAY and cleaned.get('value_path'):
            self.add_error('value_path', _('No value path: the device’s payload format is a list of items.'))


class SiteClockDateTimeField(forms.DateTimeField):
    """A moment typed on the clock of the channel's site (farm.models.site.zone_of), never the browser's. A time a
    change of clocks skips or repeats is refused, so a calibration never starts an hour off."""

    widget = MomentInput()

    def __init__(self, *args, zone=None, **kwargs):
        self.zone = zone
        super().__init__(*args, **kwargs)

    def prepare_value(self, value):
        if isinstance(value, datetime) and timezone.is_aware(value) and self.zone is not None:
            return timezone.make_naive(value, self.zone)
        return value

    def to_python(self, value):
        moment = super().to_python(value)
        if moment is None or self.zone is None:
            return moment
        return on_site_clock(timezone.make_naive(moment, timezone.get_current_timezone()), self.zone)


# The moment a wall-clock time (naive) is on a site's clock, refused when the clocks skip it or show it twice: the one
# check, core.dates.on_clock, under the name the sensors' forms and views use.
on_site_clock = on_clock


class CalibrationForm(forms.ModelForm):
    """A row of a channel's calibrations: from when, gain and offset, by whom."""

    class Meta:
        model = Calibration
        fields = ['valid_from', 'gain', 'offset', 'performed_by', 'note']
        localized_fields = ['gain', 'offset']
        widgets = {'gain': forms.TextInput(attrs=DECIMAL), 'offset': forms.TextInput(attrs=DECIMAL),
                   'note': forms.TextInput()}

    def __init__(self, *args, zone=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['valid_from'] = SiteClockDateTimeField(label=self.fields['valid_from'].label, zone=zone)

    def validate_constraints(self):
        # One row per moment spans the whole list, saved as a full replace: the formset checks it, the database backs it.
        pass


class BaseCalibrationFormSet(RowFormSet):
    default_error_messages = {
        'too_many_forms': ngettext_lazy('A channel has at most %(num)d calibration.',
                                        'A channel has at most %(num)d calibrations.', 'num'),
    }

    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        kwargs['zone'] = zone_of(self.instance.device.site) if self.instance.pk else None
        return kwargs

    def get_unique_error_message(self, unique_check):
        return _('Two calibrations start at the same moment.')


CalibrationFormSet = forms.inlineformset_factory(
    Channel, Calibration, form=CalibrationForm, formset=BaseCalibrationFormSet,
    extra=0, can_delete=True, max_num=200, validate_max=True,
)

CREDENTIAL_TABS = [('general', gettext_lazy('General'), ['username', 'is_enabled'])]


class CredentialForm(TabbedForm):
    """A broker credential: its user name and whether it may sign in. The secret is never a field: it is made on the
    server, shown once, and only its hash is kept (sensors/credentials.py)."""

    tabs = CREDENTIAL_TABS

    class Meta:
        model = Credential
        fields = tab_fields(CREDENTIAL_TABS)
        help_texts = {
            'username': gettext_lazy('The name the device or gateway signs in to the broker with. Letters, digits and '
                                     '. _ @ - only.'),
            'is_enabled': gettext_lazy('A disabled credential cannot sign in once the broker’s files are written again '
                                       '(manage.py sensor_broker_sync).'),
        }



BIND_TABS = [('general', gettext_lazy('Binding'), ['channel', 'target', 'role', 'valid_from', 'note'])]
# The places a dialog or a chart names as "kind:pk": a unit (tank, pond, cage), a sampling point, a system, a piece of
# equipment. A channel is bound to the last three; a unit stands for its middle point (sensors/bindings.py `landing`).
PLACE_KINDS = {'unit': Tank, 'point': SamplingPoint, 'system': System, 'equipment': Equipment}


def place_of(value):
    """The unit, sampling point, system or piece of equipment a "kind:pk" names; None for anything else."""
    kind, _sep, pk = (value or '').partition(':')
    model = PLACE_KINDS.get(kind)
    try:
        return model.objects.filter(pk=pk).first() if model is not None and pk else None
    except (ValueError, ValidationError):
        return None


def place_choices(units=True):
    """The places, grouped: units (when asked), live active sampling points (the owner's code and the point's name),
    systems and pieces of equipment. A value is "kind:pk"."""
    points = SamplingPoint.objects.filter(is_active=True).with_owners()
    return [
        *([(_('Units'), [(f'unit:{unit.pk}', str(unit)) for unit in Tank.objects.order_by('code')])] if units else []),
        (_('Sampling points'), sorted(((f'point:{point.pk}', str(point)) for point in points), key=lambda item: item[1])),
        (_('Systems'), [(f'system:{system.pk}', str(system)) for system in System.objects.order_by('code')]),
        (_('Equipment'), [(f'equipment:{item.pk}', str(item)) for item in Equipment.objects.order_by('code')]),
    ]


class BindForm(TabbedForm):
    """The Move dialog: bind a channel from a moment to a sampling point, a system or a piece of equipment (one choice,
    `target`, that fills the column of its kind). The channel's open binding ends at that moment (sensors/bindings.py).
    The moment is typed on the clock of the place's site (sensors/bindings.py `clock`)."""

    tabs = BIND_TABS
    target = forms.ChoiceField(label=gettext_lazy('Bound to'))
    valid_from = forms.DateTimeField(label=gettext_lazy('From'),
                                     widget=MomentInput())

    class Meta:
        model = Binding
        fields = ['channel', 'role', 'valid_from', 'note']
        help_texts = {
            'note': gettext_lazy('e.g. moved to the new tank after the grading'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['channel'].queryset = Channel.objects.select_related('device__site').order_by('device__code', 'code')
        self.fields['target'].choices = [('', '---------'), *place_choices(units=False)]
        self.fields['target'].help_text = _('A water value goes to a sampling point or a system; a process value '
                                            '(flow, level, power…) to a piece of equipment or a system.')
        self.fields['valid_from'].help_text = _('On the clock of the place’s site. Its binding until now ends then.')

    def clean(self):
        cleaned = super().clean()
        channel, chosen = cleaned.get('channel'), cleaned.get('target', '')
        target = place_of(chosen)
        if chosen and target is None:
            self.add_error('target', _('Choose a place from the list.'))
        if channel is None or target is None:
            return cleaned
        if cleaned.get('valid_from') is not None:
            wall = timezone.make_naive(cleaned['valid_from'], timezone.get_current_timezone())
            try:
                cleaned['valid_from'] = on_site_clock(wall, bindings.clock(channel.device, target))
            except ValidationError as error:
                self.add_error('valid_from', error)
                return cleaned
        # The rules of a move (sensors/bindings.py), said on the form before it is sent; the move checks them again.
        for field, message in bindings.refusals(channel, target, cleaned.get('role'),
                                                cleaned.get('valid_from') or timezone.now()):
            self.add_error(field, message)
        cleaned['target_kind'], cleaned['target_object'] = bindings.kind_of(target), target
        return cleaned

    def _check_conditional_constraints(self, cleaned):
        # The channel's period overlaps its own open binding, which the move ends: sensors/bindings.py checks the
        # moment, the database the rest.
        pass


EDIT_BINDING_TABS = [('general', gettext_lazy('Binding'), ['valid_to', 'note'])]


class BindingForm(TabbedForm):
    """An existing binding: only its end and its note change; where and from when it held is history (a move is a new
    binding)."""

    tabs = EDIT_BINDING_TABS

    class Meta:
        model = Binding
        fields = tab_fields(EDIT_BINDING_TABS)
        help_texts = {'valid_to': gettext_lazy('When the channel stopped being here; empty while it still is.')}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        zone = bindings.clock(self.instance.channel.device, self.instance.target) if self.instance.channel_id else None
        self.fields['valid_to'] = SiteClockDateTimeField(label=self.fields['valid_to'].label, required=False, zone=zone,
                                                         help_text=self.fields['valid_to'].help_text)

    def clean_valid_to(self):
        value = self.cleaned_data.get('valid_to')
        if value is not None and value > timezone.now():
            raise ValidationError(_('A binding cannot end in the future.'))
        return value


OUT = 'out'


class DeviceMoveForm(forms.Form):
    """The Move device dialog: a whole device (a portable probe) to a unit, a sampling point, a system or a piece of
    equipment, or out of the water, from a moment typed on the clock of the place's site (sensors/bindings.py
    `move_device`, `clock`). Choosing the device, the place or the role renders the dialog again with where each channel
    will land (`refresh_on`, saving nothing)."""

    refresh_on = ('device', 'target', 'role')
    device = forms.ModelChoiceField(label=gettext_lazy('Device'), queryset=Device.objects.none())
    target = forms.ChoiceField(label=gettext_lazy('Move to'))
    role = forms.ChoiceField(label=gettext_lazy('Role'), choices=Binding.Role.choices, initial=Binding.Role.PRIMARY)
    valid_from = forms.DateTimeField(label=gettext_lazy('From'), widget=MomentInput())
    note = forms.CharField(label=gettext_lazy('Note'), max_length=300, required=False,
                           help_text=gettext_lazy('e.g. moved to the new tank after the grading'))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['device'].queryset = Device.objects.select_related('site').order_by('code')
        self.fields['target'].choices = [('', '---------'), (OUT, _('Out of the water (not placed)')),
                                         *place_choices()]
        self.fields['target'].help_text = _('A unit takes the water values at its middle point; a system takes them '
                                            'as its own water. A process value goes to a system or a piece of '
                                            'equipment.')
        self.fields['valid_from'].help_text = _('On the clock of the place’s site. Every channel’s binding until now '
                                                'ends then.')
        for name in self.refresh_on:
            self.fields[name].widget.attrs['data-refresh'] = DRAFT

    def chosen(self):
        """(device, place, out) as far as the data names them: for the landing shown before the move."""
        data = self.data if self.is_bound else self.initial
        device_id, value = str(data.get('device') or ''), data.get('target') or ''
        device = None
        try:
            device = Device.objects.select_related('site').filter(pk=device_id).first() if device_id else None
        except (ValueError, ValidationError):
            pass
        return device, (None if value == OUT else place_of(value)), value == OUT

    def clean(self):
        cleaned = super().clean()
        device, chosen = cleaned.get('device'), cleaned.get('target', '')
        place = None if chosen == OUT else place_of(chosen)
        if chosen and chosen != OUT and place is None:
            self.add_error('target', _('Choose a place from the list.'))
            return cleaned
        cleaned['place'] = place
        if device is not None and cleaned.get('valid_from') is not None:
            wall = timezone.make_naive(cleaned['valid_from'], timezone.get_current_timezone())
            try:
                cleaned['valid_from'] = on_site_clock(wall, bindings.clock(device, place))
            except ValidationError as error:
                self.add_error('valid_from', error)
        return cleaned


ALARM_TABS = [('general', gettext_lazy('Alarm rule'), ['channel', 'quantity', 'kind', 'threshold', 'for_s', 'hysteresis',
                                                        'severity', 'is_active'])]


class AlarmRuleForm(TabbedForm):
    """An alarm rule: on one channel or on every channel of a quantity. Its events are alarms (Company › Alarms)."""

    tabs = ALARM_TABS

    class Meta:
        model = AlarmRule
        fields = tab_fields(ALARM_TABS)
        localized_fields = ['threshold', 'hysteresis']
        widgets = {'threshold': forms.TextInput(attrs=DECIMAL), 'hysteresis': forms.TextInput(attrs=DECIMAL)}
        help_texts = {
            'quantity': gettext_lazy('Instead of one channel: every active channel of this quantity.'),
            'threshold': gettext_lazy('In the quantity’s unit; for a rate, the change over the time below.'),
            'for_s': gettext_lazy('Above or below: every value of this time must be past the threshold. No fresh value: '
                                  'this long past the channel’s freshness. A rate: the change over this time.'),
            'hysteresis': gettext_lazy('An open alarm closes only once the value is back past the threshold by this much.'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['channel'].queryset = Channel.objects.select_related('device').order_by('device__code', 'code')
