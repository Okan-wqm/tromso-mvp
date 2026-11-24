"""The Sensors panel's configuration tabs on top of core.crud: connections, payload formats, devices, channels (with their
calibrations saved as a list) and the broker credentials. Each logs its changes, guards its edits with `version`, and is
deleted softly by the plan its links say (core.softdelete): a connection takes its devices and their channels with it, a
payload format or a credential in use blocks the delete. Readings are never deleted with a channel."""
import uuid

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, F, IntegerField, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as gettext_now, gettext_lazy as _, ngettext_lazy

from core.crud import CreateView, Resource, RowList, done, filter_by, refusal_text, render_page
from farm.models import Equipment, Site, System, Tank
from farm.models.site import zone_of

from . import bindings, credentials, lists
from .forms import (AlarmRuleForm, BindForm, BindingForm, CalibrationFormSet, ChannelForm, ConnectionForm,
                    CredentialForm, DeviceForm, PayloadFormatForm, place_of)
from .models import AlarmRule, Binding, Channel, Connection, Credential, Device, PayloadFormat, Role


def _count(model, link, **condition):
    """A live count of `model` rows pointing at the row (a subquery: an edit locks the row, which a GROUP BY refuses)."""
    found = (model.objects.filter(**{link: OuterRef('pk')}, **condition).order_by().values(link)
             .annotate(n=Count('pk')).values('n'))
    return Coalesce(Subquery(found, output_field=IntegerField()), Value(0))


class ConnectionResource(Resource):
    model = Connection
    form_class = ConnectionForm
    name, plural = _('connection'), _('connections')
    url_prefix = 'sensors/connections'
    search_fields = ['name', 'host', 'client_id']
    list_template = 'sensors/connection_list.html'
    icon = 'plug'
    page_size = 50

    # The new look's list (sensors/lists.py, core/listprops.py): the classic template's words.
    list_rows = staticmethod(lists.connections)
    search_placeholder = _('Search by name, host or client id')
    empty_text = _('A connection is an MQTT broker the ingest service listens to. Its devices say which topics.')

    @classmethod
    def queryset(cls):
        return super().queryset().annotate(device_count=_count(Device, 'connection'))


class PayloadFormatResource(Resource):
    model = PayloadFormat
    form_class = PayloadFormatForm
    name, plural = _('payload format'), _('payload formats')
    url_prefix = 'sensors/payload-formats'
    search_fields = ['name']
    list_template = 'sensors/payloadformat_list.html'
    icon = 'braces'
    page_size = 50

    # The new look's list (sensors/lists.py, core/listprops.py): the classic template's words.
    list_rows = staticmethod(lists.payload_formats)
    search_placeholder = _('Search by name')
    empty_text = _('A payload format says how a kind of device writes its messages: where the time is, and where each '
                   'value is.')

    @classmethod
    def queryset(cls):
        return super().queryset().annotate(device_count=_count(Device, 'payload_format'))


class DeviceResource(Resource):
    model = Device
    form_class = DeviceForm
    name, plural = _('device'), _('devices')
    url_prefix = 'sensors/devices'
    search_fields = ['code', 'name', 'topic', 'manufacturer', 'model']
    list_template = 'sensors/device_list.html'
    form_template = 'sensors/device_form.html'
    icon = 'cpu'
    page_size = 50

    # The new look's list (sensors/lists.py, core/listprops.py): the classic template's words.
    list_rows = staticmethod(lists.devices)
    list_filters = staticmethod(lists.device_filters)
    search_placeholder = _('Search by code, name, topic or model')
    empty_text = _('A device publishes on one topic of a connection: a probe, a PLC, a gateway. Its channels are the '
                   'values it sends.')

    @classmethod
    def queryset(cls):
        return (super().queryset().select_related('connection', 'payload_format', 'site', 'credential', 'equipment')
                .annotate(channel_count=_count(Channel, 'device')))

    @classmethod
    def filter_list(cls, request, objects):
        """The devices placed somewhere now (`?placed=yes`) or out of the water (`?placed=no`)."""
        placed = request.GET.get('placed', '')
        if placed == 'yes':
            return objects.filter(bindings.placed()), {'placed': placed}
        if placed == 'no':
            return objects.exclude(bindings.placed()), {'placed': placed}
        return objects, {'placed': ''}

    @classmethod
    def edit_extras(cls, request, obj):
        return {**super().edit_extras(request, obj), 'channels': obj.channels.order_by('code'),
                'placed_at': bindings.placements([obj])[obj.pk], 'placement_history': bindings.placement_history(obj)}


class ChannelCalibrations(RowList):
    """A channel's calibrations, saved as a whole list on its Calibration tab; needs the right to edit channels."""

    key, tab, label = 'calibrations', 'calibration', _('Calibrations')
    formset = CalibrationFormSet
    saved = ngettext_lazy('%(count)d calibration saved.', '%(count)d calibrations saved.', 'count')

    @classmethod
    def describe(cls, row):
        """e.g. "2026-11-01 07:00 UTC: × 1.02 + -0.1 (Kari)", in English."""
        text = f'{row.valid_from:%Y-%m-%d %H:%M} UTC: × {row.gain} + {row.offset}'
        return f'{text} ({row.performed_by})' if row.performed_by else text


class ChannelResource(Resource):
    model = Channel
    form_class = ChannelForm
    name, plural = _('channel'), _('channels')
    url_prefix = 'sensors/channels'
    search_fields = ['code', 'name', 'device__code', 'device__name']
    list_template = 'sensors/channel_list.html'
    form_template = 'sensors/channel_form.html'
    icon = 'activity'
    row_lists = (ChannelCalibrations,)
    page_size = 100

    # The new look's list (sensors/lists.py, core/listprops.py): the classic template's words.
    list_rows = staticmethod(lists.channels)
    list_filters = staticmethod(lists.channel_filters)
    search_placeholder = _('Search by code, name or device')
    empty_text = _('A channel is one value a device sends: what it measures, where it is in the message and how it is '
                   'stored.')

    @classmethod
    def queryset(cls):
        return super().queryset().select_related('device__connection', 'device__payload_format', 'device__site')

    @classmethod
    def filter_list(cls, request, objects):
        """The channels of one device, when the address names it (a device's Channels tab links here)."""
        device = request.GET.get('device', '')
        devices = Device.objects.order_by('code')
        if _uuid(device) and devices.filter(pk=device).exists():
            return objects.filter(device_id=device), {'devices': devices, 'device': device}
        return objects, {'devices': devices, 'device': ''}


def _uuid(value):
    """Whether `value` is a UUID as text."""
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def secret_page(request, resource, credential, secret, rotated):
    """The one page a credential's secret is ever shown on: right after it is made or replaced."""
    return render_page(request, 'sensors/credential_secret.html', {
        'credential': credential, 'secret': secret, 'rotated': rotated,
        'list_url': reverse(resource.url_name('list')), 'title': resource.title(), 'group': resource.group()})


class CredentialCreateView(CreateView):
    """A new credential: saved as any tab's record (its secret made in the same transaction, `after_save`), then the
    secret shown once instead of the usual redirect."""

    def post(self, request):
        response = super().post(request)
        made = getattr(request, 'sensors_secret', None)
        if made is None:
            return response
        credential, secret = made
        return secret_page(request, self.resource, credential, secret, rotated=False)


class CredentialResource(Resource):
    model = Credential
    form_class = CredentialForm
    name, plural = _('sensor credential'), _('sensor credentials')
    url_prefix = 'sensors/credentials'
    search_fields = ['username']
    list_template = 'sensors/credential_list.html'
    form_template = 'sensors/credential_form.html'
    icon = 'key-round'
    page_size = 50
    create_view = CredentialCreateView

    # The new look's list (sensors/lists.py, core/listprops.py): the classic template's words.
    list_rows = staticmethod(lists.credentials)
    search_placeholder = _('Search by user name')
    empty_text = _('A credential is the name and secret a device or gateway signs in to the broker with. The secret is '
                   'shown once, when it is made.')

    @classmethod
    def queryset(cls):
        return super().queryset().annotate(device_count=_count(Device, 'credential'))

    @classmethod
    def after_save(cls, request, obj, created):
        """A new credential gets its secret now, in the save's transaction (sensors/views.py shows it once)."""
        if created:
            request.sensors_secret = (obj, credentials.give_secret(obj))



class BindView(CreateView):
    """The Move dialog: binds a channel from a moment (sensors/bindings.py `move`, which ends its open binding then). A
    link may name the channel and the place (`?channel=…&target=point:…`, from a monitoring card or a Deffeyes window)."""

    def get(self, request):
        initial = {name: request.GET[name] for name in ('channel', 'target', 'role') if request.GET.get(name)}
        chosen = initial.get('channel', '')
        channel = Channel.objects.select_related('device__site').filter(pk=chosen).first() if _uuid(chosen) else None
        # Now, on the clock of the place's site, else the channel's device's (the company's while no channel is chosen).
        zone = bindings.clock(channel.device, place_of(initial.get('target', ''))) if channel is not None \
            else zone_of(None)
        initial['valid_from'] = timezone.localtime(timezone=zone).replace(tzinfo=None, second=0, microsecond=0)
        return self.page(BindForm(initial=initial))

    def post(self, request):
        form = BindForm(request.POST)
        if form.sent_before() is not None:                 # the same dialog sent again (core.models.EntryKey)
            return done(request, reverse(self.resource.url_name('list')))
        if not form.is_valid():
            return self.page(form)
        data = form.cleaned_data
        try:
            with transaction.atomic():
                form.note_sent(bindings.move(request.user, data['channel'], data['valid_from'], role=data['role'],
                                             note=data['note'], **{data['target_kind']: data['target_object']}))
        except ValidationError as error:
            for field, messages_ in error.message_dict.items():
                form.add_error(field if field in form.fields else None, messages_)
            return self.page(form)
        except IntegrityError as error:
            if form.sent_before() is not None:             # sent twice at once: the other sending bound it
                return done(request, reverse(self.resource.url_name('list')))
            form.add_error(None, refusal_text(error))
            return self.page(form)
        messages.success(request, gettext_now('%(channel)s bound to %(target)s.') % {'channel': data['channel'],
                                                                          'target': data['target_object']})
        return done(request, reverse(self.resource.url_name('list')))


def _at_place(place):
    """The bindings at a place: a unit's or a piece of equipment's sampling points (and the piece itself), a system and
    its loop's points, a sampling point."""
    if isinstance(place, Tank):
        return Q(point__unit=place)
    if isinstance(place, System):
        return Q(system=place) | Q(point__system=place)
    if isinstance(place, Equipment):
        return Q(equipment=place) | Q(point__equipment=place)
    return Q(point=place)


class BindingResource(Resource):
    model = Binding
    form_class = BindingForm
    name, plural = _('channel binding'), _('channel bindings')
    url_prefix = 'sensors/bindings'
    search_fields = ['channel__code', 'channel__device__code', 'point__name', 'system__code', 'equipment__code']
    list_template = 'sensors/binding_list.html'
    icon = 'link'
    create_view = BindView
    page_size = 100

    # The new look's list (sensors/lists.py, core/listprops.py): the classic template's words.
    list_rows = staticmethod(lists.bindings)
    search_placeholder = _('Search by channel, device or place')
    empty_text = _("A binding says where a channel's values belong from a moment on: a sampling point or a system for a "
                   'water value, a piece of equipment or a system for a process value.')

    @classmethod
    def queryset(cls):
        return (Binding.objects.visible()
                .select_related('channel__device', 'point__unit', 'point__system', 'point__equipment', 'system',
                                'equipment').order_by('-valid_from'))

    list_filters = staticmethod(lists.binding_filters)

    @classmethod
    def filter_list(cls, request, objects):
        """The bindings of one channel (its history), or of one place (`?place=unit:…`: the sensors there now, then
        those there before), when the address names it; then by the channel's device's site (`site`), the role (`role`)
        and those that hold now (`bound=now`), the new look's selects (the classic page has no control for them: its
        address narrows it the same way)."""
        channel = request.GET.get('channel', '')
        place = None
        if _uuid(channel):
            objects = objects.filter(channel_id=channel)
        else:
            channel = ''
            place = place_of(request.GET.get('place', ''))
            if place is not None:
                objects = objects.filter(_at_place(place)).order_by(F('valid_to').desc(nulls_first=True), '-valid_from')
        sites = Site.objects.filter(sensor_devices__isnull=False).distinct().order_by('name')
        objects, chosen_site = filter_by(request, objects, 'site', sites, 'channel__device__site_id')
        objects, chosen_role = filter_by(request, objects, 'role', Role.choices, 'role')
        bound = 'now' if request.GET.get('bound') == 'now' else ''
        if bound:
            objects = objects.at(timezone.now())
        return objects, {'channel': channel, 'place': place, 'sites': sites, 'chosen_site': chosen_site,
                         'roles': Role.choices, 'chosen_role': chosen_role, 'chosen_bound': bound}


class AlarmRuleResource(Resource):
    model = AlarmRule
    form_class = AlarmRuleForm
    name, plural = _('alarm rule'), _('alarm rules')
    url_prefix = 'sensors/alarm-rules'
    search_fields = ['channel__code', 'quantity']
    list_template = 'sensors/alarmrule_list.html'
    icon = 'bell'
    page_size = 100

    # The new look's list (sensors/lists.py, core/listprops.py): the classic template's words.
    list_rows = staticmethod(lists.alarm_rules)
    search_placeholder = _('Search by channel or quantity')
    empty_text = _('A rule says when a channel needs a look: no fresh value, its device offline, a value above or below '
                   'a threshold, or a change too fast.')

    @classmethod
    def queryset(cls):
        return super().queryset().select_related('channel__device')
