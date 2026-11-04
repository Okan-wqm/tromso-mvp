"""The Sensors panel's configuration tabs on top of core.crud: connections, payload formats, devices, channels (with their
calibrations saved as a list) and the broker credentials. Each logs its changes, guards its edits with `version`, and is
deleted softly by the plan its links say (core.softdelete): a connection takes its devices and their channels with it, a
payload format or a credential in use blocks the delete. Readings are never deleted with a channel."""
import uuid

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import Count, IntegerField, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as gettext_now, gettext_lazy as _, ngettext_lazy

from core.crud import CreateView, Resource, RowList, done, render_page
from farm.models.site import zone_of

from . import bindings, credentials
from .forms import (BindForm, BindingForm, CalibrationFormSet, ChannelForm, ConnectionForm, CredentialForm, DeviceForm,
                    PayloadFormatForm)
from .models import Binding, Channel, Connection, Credential, Device, PayloadFormat


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
    def edit_extras(cls, request, obj):
        return {**super().edit_extras(request, obj), 'channels': obj.channels.order_by('code')}


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
        # Now, on the clock of the channel's site (the company's while no channel is chosen).
        zone = zone_of(channel.device.site if channel is not None else None)
        initial['valid_from'] = timezone.localtime(timezone=zone).strftime('%Y-%m-%dT%H:%M')
        return self.page(BindForm(initial=initial))

    def post(self, request):
        form = BindForm(request.POST)
        if not form.is_valid():
            return self.page(form)
        data = form.cleaned_data
        try:
            bindings.move(request.user, data['channel'], data['valid_from'], role=data['role'], note=data['note'],
                          **{data['target_kind']: data['target_object']})
        except ValidationError as error:
            for field, messages_ in error.message_dict.items():
                form.add_error(field if field in form.fields else None, messages_)
            return self.page(form)
        except IntegrityError as error:
            # Someone else bound the same place or channel since the form checked it: the database said no.
            cause = getattr(error, '__cause__', None)
            form.add_error(None, str(getattr(getattr(cause, 'diag', None), 'message_primary', '') or error))
            return self.page(form)
        messages.success(request, gettext_now('%(channel)s bound to %(target)s.') % {'channel': data['channel'],
                                                                          'target': data['target_object']})
        return done(request, reverse(self.resource.url_name('list')))


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
        """The bindings of one channel (its history), when the address names it."""
        channel = request.GET.get('channel', '')
        if _uuid(channel):
            return objects.filter(channel_id=channel), {'channel': channel}
        return objects, {'channel': ''}
