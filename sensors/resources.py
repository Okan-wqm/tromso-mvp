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
from django.utils import formats, timezone
from django.utils.translation import gettext as gettext_now, gettext_lazy as _, ngettext_lazy

from core import formpanels, listprops
from core.crud import CreateView, Resource, RowList, done, refusal_text, render_page
from farm.models import Equipment, System, Tank
from farm.models.site import zone_of

from . import bindings, credentials
from .forms import (AlarmRuleForm, BindForm, BindingForm, CalibrationFormSet, ChannelForm, ConnectionForm,
                    CredentialForm, DeviceForm, PayloadFormatForm, place_of)
from .models import AlarmRule, Binding, Channel, Connection, Credential, Device, PayloadFormat


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

    next_extras = frozenset({'channels', 'placed_at', 'placement_history'})

    @classmethod
    def next_panels(cls, view, form, device, extra):
        """sensors/device_form.html in the new look: an existing device's Channels (each opens its own form) and its
        Placement (where it is now, Move device for a person who may bind, where it was), on the device site's clock."""
        if device is None:
            return []
        channels = list(extra.get('channels', ()))
        channel_table = formpanels.table(_('Channels'), [
            listprops.column('channel', _('Channel')), listprops.column('quantity', _('Quantity')),
            listprops.column('value', _('Value')), listprops.column('heartbeat', _('Heartbeat (s)'), numeric=True),
            listprops.column('state', _('State'))], [
            listprops.row(channel.pk, {
                'channel': listprops.cell(channel.code, href=reverse('sensors:channel_edit', args=[channel.pk]), strong=True,
                                          sub=[f'{channel.name} · #{channel.channel_no}']),
                'quantity': listprops.cell(channel.get_quantity_display()),
                'value': listprops.cell(channel.value_path or channel.item_name),
                'heartbeat': listprops.cell(formats.localize(channel.heartbeat_s)),
                'state': listprops.cell(channel.get_state_display())}) for channel in channels])
        places = [str(place) for place in extra.get('placed_at') or ()]
        history = list(extra.get('placement_history') or ())
        where = (f"{gettext_now('Placed at')}: {', '.join(places)}." if places
                 else _('Not placed: out of the water, its readings belong to no place.'))
        return [
            formpanels.panel('channels', _('Channels'), [channel_table] if channels else [
                formpanels.help_text(_('No channels yet: add them on the Channels page.'))]),
            formpanels.panel('placement', _('Placement'), [
                formpanels.help_text(where),
                formpanels.link(f"{reverse('sensors:device_move')}?device={device.pk}", _('Move device'), 'target')
                if view.request.user.has_perm('sensors.add_binding') else None,
                formpanels.table(_('Placement'), [
                    listprops.column('where', _('Where')), listprops.column('from', _('From')),
                    listprops.column('until', _('Until'))], [
                    listprops.row(index, {
                        'where': listprops.cell(stay.places[0] if stay.places else '', sub=stay.places[1:]),
                        'from': listprops.cell(formpanels.moment(stay.start, device.site)),
                        'until': listprops.cell(formpanels.moment(stay.end, device.site)) if stay.end
                        else listprops.cell(chip=listprops.chip('neutral', _('now')))})
                    for index, stay in enumerate(history)]) if history else formpanels.help_text(_('Never placed yet.'))]),
        ]


class ChannelCalibrations(RowList):
    """A channel's calibrations, saved as a whole list on its Calibration tab; needs the right to edit channels."""

    key, tab, label = 'calibrations', 'calibration', _('Calibrations')
    # Its panel's words (sensors/channel_form.html).
    title = _('Calibration')
    help_text = _('Value = gain × raw value + offset, from the moment given on the site’s clock, applied by the ingest at the '
                  'device’s time before the unit conversion. Stored values are calibrated; a later calibration never changes '
                  'them. The earliest calibration also covers the time before it. The calibrations are saved separately from '
                  'the channel’s details.')
    empty_text = _('No calibrations: values are stored as the device sends them (after the unit conversion).')
    add_label, save_label = _('Add calibration'), _('Save calibrations')
    pending_text = _('Calibrations can be added once the channel is created.')
    row_kind = 'calibration-row'
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

    @classmethod
    def next_panels(cls, view, form, channel, extra):
        """sensors/channel_form.html in the new look: on its Storing tab how long a value stays fresh, and its
        calibrations."""
        fresh = [formpanels.panel('reduction', None, [formpanels.help_text(
            _('Channel number %(number)s. A value is fresh for %(heartbeats)s heartbeats: %(seconds)s seconds.') % {
                'number': formats.localize(channel.channel_no), 'heartbeats': formats.localize(channel.fresh_heartbeats),
                'seconds': formats.localize(channel.fresh_s)})], tab='reduction')] if channel is not None else []
        return fresh + formpanels.row_list_panels(cls, view, channel, extra)

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

    @classmethod
    def next_panels(cls, view, form, credential, extra):
        """sensors/credential_form.html in the new look: on an existing credential, for a person who may edit it, the
        button that replaces its secret (shown once on the next page)."""
        if credential is None or not (cls.allows('change') and view.request.user.has_perm(cls.perm('change'))):
            return []
        return [formpanels.panel('general', None, [
            formpanels.help_text(_('Replacing the secret makes a new one, shown once. The old one stops working once the '
                                   'broker’s files are written again.')),
            formpanels.post(reverse('sensors:credential_rotate', args=[credential.pk]), _('Replace the secret'),
                            [('version', credential.version)])], tab='general')]

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

    @classmethod
    def queryset(cls):
        return (Binding.objects.visible()
                .select_related('channel__device', 'point__unit', 'point__system', 'point__equipment', 'system',
                                'equipment').order_by('-valid_from'))

    @classmethod
    def filter_list(cls, request, objects):
        """The bindings of one channel (its history), or of one place (`?place=unit:…`: the sensors there now, then
        those there before), when the address names it."""
        channel = request.GET.get('channel', '')
        if _uuid(channel):
            return objects.filter(channel_id=channel), {'channel': channel, 'place': None}
        place = place_of(request.GET.get('place', ''))
        if place is not None:
            found = objects.filter(_at_place(place)).order_by(F('valid_to').desc(nulls_first=True), '-valid_from')
            return found, {'channel': '', 'place': place}
        return objects, {'channel': '', 'place': None}


class AlarmRuleResource(Resource):
    model = AlarmRule
    form_class = AlarmRuleForm
    name, plural = _('alarm rule'), _('alarm rules')
    url_prefix = 'sensors/alarm-rules'
    search_fields = ['channel__code', 'quantity']
    list_template = 'sensors/alarmrule_list.html'
    icon = 'bell'
    page_size = 100

    @classmethod
    def queryset(cls):
        return super().queryset().select_related('channel__device')
