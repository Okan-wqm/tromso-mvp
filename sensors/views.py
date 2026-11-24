"""The Sensors panel's pages beyond its tabs: the overview, and a credential's secret, shown once when it is made or
replaced and never again."""
import csv
from datetime import timedelta
from urllib.parse import urlencode

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import F
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.gzip import gzip_page
from django.utils import formats, timezone
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _, gettext_lazy
from django.views.decorators.http import require_POST

from alarms import read as alarms_read, services as alarm_services, sources as alarm_sources
from core import audit, navigation, ui
from core.crud import DRAFT, done, refusal_text, render_page
from core.dates import read_moment
from core.models import AuditLog
from farm.models import Equipment, System, Tank
from farm.models.site import zone_of
from farm.water import deffeyes
from core.widgets import EXAMPLE, MomentInput

from . import bindings, chart, credentials, quantities, read, trail
from .forms import DeviceMoveForm, on_site_clock, place_choices, place_of
from .models import (AlarmEvent, Binding, Channel, ChannelStatus, Connection, Credential, DeadLetter, DeadReason,
                     Device, IngestStatus)
from .resources import (BindingResource, ChannelResource, ConnectionResource, CredentialResource, DeviceResource,
                        PayloadFormatResource, secret_page)

DATETIME = MomentInput()
# How the activity log says a secret changed: never its value or its hash.
SECRET_LABEL, REPLACED = 'Secret', '(replaced)'


def _context(url_name, **extra):
    place = navigation.page(url_name)
    return {'title': place.entry.label, 'eyebrow': f'{place.workspace.label} · {place.entry.label}', **extra}


def home(request):
    """The Sensors overview: the configuration counted, for the parts the person may read (every signed-in person may
    open it; the panel is offered to those who can use something in it)."""
    tiles = [{'label': resource.title(), 'count': resource.model.objects.count(), 'url': reverse(resource.url_name('list'))}
             for resource in (ConnectionResource, DeviceResource, ChannelResource, PayloadFormatResource)
             if request.user.has_perm(resource.perm('view'))]
    return render_page(request, 'sensors/home.html', _context('sensors:home', setup_tiles=tiles,
                                                               state_tiles=state_tiles(request.user, timezone.now())))


@require_POST
@permission_required(CredentialResource.perm('change'), raise_exception=True)
def credential_rotate(request, pk):
    """Replaces a credential's secret: refused when the credential changed since the page was opened (its version), logged
    without any value, the new secret shown once. The broker takes it when its files are written again
    (`manage.py sensor_broker_sync`)."""
    with transaction.atomic():
        credential = get_object_or_404(Credential.objects.select_for_update(), pk=pk)
        if request.POST.get('version') != str(credential.version):
            messages.error(request, _('Someone else changed this %(name)s while you were editing it. The form now shows '
                                      'their version; make your changes again.') % {'name': CredentialResource.name})
            return done(request, reverse(CredentialResource.url_name('edit'), args=[pk]))
        secret = credentials.give_secret(credential)
        credential.version += 1
        credential.updated_by = request.user
        credential.save(update_fields=['version', 'updated_by', 'updated_at'])
        with audit.source_language():
            audit.record(request.user, AuditLog.Action.UPDATE, credential, {SECRET_LABEL: [REPLACED, REPLACED]},
                         entity_type=CredentialResource.entity_type())
    return secret_page(request, CredentialResource, credential, secret, rotated=True)


# ---- charts and live values (the right to read sensor readings) --------------------------------------------------
READ = 'sensors.view_reading'
RANGES = [('6h', timedelta(hours=6)), ('24h', timedelta(hours=24)), ('7d', timedelta(days=7)), ('30d', timedelta(days=30)),
          ('90d', timedelta(days=90)), ('1y', timedelta(days=365)), ('2y', timedelta(days=730))]
class ChartForm(forms.Form):
    """What a chart shows: a place, a quantity and a time (a preset ending now, or from and to on the site's clock)."""
    target = forms.ChoiceField(label=gettext_lazy('Place'))
    quantity = forms.ChoiceField(label=gettext_lazy('Quantity'), choices=quantities.CHOICES)
    range = forms.ChoiceField(label=gettext_lazy('Time'), required=False,
                              choices=[('', gettext_lazy('From and to')), *[(key, key) for key, _span in RANGES]])
    start = forms.DateTimeField(label=gettext_lazy('From'), required=False, widget=DATETIME)
    end = forms.DateTimeField(label=gettext_lazy('To'), required=False, widget=DATETIME)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['target'].choices = [('', '---------'), *place_choices()]

    def clean(self):
        cleaned = super().clean()
        target = place_of(cleaned.get('target'))
        if target is None:
            self.add_error('target', _('Choose a place from the list.'))
            return cleaned
        cleaned['place'] = target
        now = timezone.now()
        preset = dict(RANGES).get(cleaned.get('range') or '')
        if preset is not None:
            cleaned['from'], cleaned['to'] = now - preset, now
            return cleaned
        if cleaned.get('start') is None or cleaned.get('end') is None:
            self.add_error(None, _('Choose a time: a preset, or from and to.'))
            return cleaned
        zone = read.zone_for(target)
        try:
            # the wall time typed (the form made it aware in the current zone), read on the place's clock
            cleaned['from'] = on_site_clock(timezone.make_naive(cleaned['start'], timezone.get_current_timezone()), zone)
            cleaned['to'] = on_site_clock(timezone.make_naive(cleaned['end'], timezone.get_current_timezone()), zone)
        except ValidationError as error:
            self.add_error(None, error)
            return cleaned
        if cleaned['to'] <= cleaned['from']:
            self.add_error('end', _('The end comes after the start.'))
        return cleaned


def _chart_of(form):
    data = form.cleaned_data
    return read.series(data['place'], data['quantity'], data['from'], data['to'])


def _options(choices):
    """[{label, options: [{value, label}]}] of a ChoiceField's choices, its groups kept (a "" choice is left out)."""
    found = []
    for value, label in choices:
        if isinstance(label, (list, tuple)):
            found.append({'label': str(value), 'options': [{'value': str(v), 'label': str(l)} for v, l in label]})
        elif value:
            found.append({'label': '', 'options': [{'value': str(value), 'label': str(label)}]})
    return found


def _charts_props(request, form):
    """Sensors › Charts in the new look: the same form (place, quantity, a preset or from and to), the chart of the query
    and of the place it is compared with, as data (`chart_payload`), the newest values and the CSV, every word."""
    query = request.GET
    payload = chart_payload(request, form) if form.is_bound else {}
    return {
        'action': reverse('sensors:charts'), 'locale': request.LANGUAGE_CODE,
        'places': _options(form.fields['target'].choices), 'quantities': _options(quantities.CHOICES),
        'ranges': [key for key, _span in RANGES],
        'values': {name: query.get(name, '') for name in ('target', 'quantity', 'range', 'start', 'end', 'compare',
                                                          'compare_quantity')},
        'errors': payload.get('errors', {}), 'chart': payload.get('chart'), 'now': payload.get('now'),
        'compare': payload.get('compare'), 'csv': payload.get('csv', ''),
        'words': {
            'place': str(_('Place')), 'quantity': str(_('Quantity')), 'time': str(_('Time')), 'from': str(_('From')),
            'to': str(_('To')), 'draw': str(_('Draw')), 'choose': '---------',
            'compare': str(_('Compare with')), 'compareQuantity': str(_('Quantity to compare')),
            'noCompare': str(_('Nothing to compare')), 'sameQuantity': str(_('The same quantity')),
            'csv': str(_('Download the drawn values (CSV)')), 'now': str(_('now')), 'stale': str(_('no recent data')),
            'sensor': str(_('Sensor')), 'manual': str(_('Meter or test kit')), 'lab': str(_('Laboratory')),
            'warning': str(_('Warning')), 'critical': str(_('Critical')), 'noValue': str(_('No value')),
            'start': str(_('Choose a place, a quantity and a time, then Draw.')),
            'gaps': str(_('Times without a value are shaded, never filled.')),
            'noBinding': str(_('Nothing is bound here now.')),
            'example': formats.localize_input(EXAMPLE),
        },
    }


@permission_required(READ, raise_exception=True)
def charts(request):
    """Sensors › Operations › Charts: one place's quantity over a time, the CSV of what is drawn beside it. The look's
    own `ui` (core/ui.py) is no part of the query."""
    query = request.GET.copy()
    query.pop(ui.PARAM, None)
    form = ChartForm(query or None)
    if ui.is_next(request):
        return render_page(request, 'sensors/charts_next.html', {**_context('sensors:charts'),
                                                                 'props': _charts_props(request, form)})
    found = _chart_of(form) if form.is_bound and form.is_valid() else None
    svg = mark_safe(chart.draw(found, str(form.cleaned_data['place']))) if found is not None else ''
    context = _context('sensors:charts', form=form, chart=found, svg=svg, notes=chart.notes(found) if found else [],
                       csv_query=request.GET.urlencode())
    return render_page(request, 'sensors/charts.html', context)


@permission_required(READ, raise_exception=True)
def chart_csv(request):
    """The buckets the chart draws, as CSV (the same query as the page)."""
    form = ChartForm(request.GET or None)
    if not form.is_valid():
        return HttpResponse(status=400)
    found = _chart_of(form)
    response = HttpResponse(content_type='text/csv; charset=utf-8',
                            headers={'Content-Disposition': 'attachment; filename="sensor-chart.csv"'})
    writer = csv.writer(response)
    writer.writerow(['start', 'end', 'average', 'lowest', 'highest', 'messages', 'channel', 'role', 'source'])
    for bucket in found.buckets:
        writer.writerow([bucket.start.isoformat(), bucket.end.isoformat(), repr(bucket.avg), repr(bucket.vmin),
                         repr(bucket.vmax), bucket.n, bucket.channel_no, bucket.role, bucket.origin])
    return response


WATER_READ = 'farm.view_watermeasurement'


def chart_bands(user, place):
    """The fish's limit bands at a place (sensors.read.bands_of of the water read's limits), for a person who may read
    the water; {} otherwise or for a place with no fish (the chart then has no band: "no limit", never an assumed one)."""
    if not user.has_perm(WATER_READ) or isinstance(place, Equipment):
        return {}
    from farm.water import read as water_read
    return read.bands_of(water_read.limits_now(place.unit if getattr(place, 'unit_id', None) else place))


def chart_now(found, now):
    """The newest value of the channel drawn last in the window, with its time and whether it is fresh (sensors.read
    `latest`, the channel's own freshness): what a chart's "now" dot says; None when nothing is bound there. The channel
    drawn last is the last bucket's (a place's own probe, or the backup or the system's channel where it has none);
    with nothing drawn, the place's first channel (`segments` are in the order they count: own first, the system's
    last), never the last of them (review of batch 1, F3)."""
    if not found.segments:
        return None
    channel = found.buckets[-1].channel_no if found.buckets else found.segments[0].channel_no
    state = read.latest([channel], now)[channel]
    if state.value is None:
        return {'value': None, 'at': None, 'fresh': False, 'channel': state.channel_no}
    return {'value': state.value, 'at': int(state.at.timestamp()), 'fresh': state.fresh, 'channel': state.channel_no}


@permission_required(READ, raise_exception=True)
def chart_data(request):
    """The Charts page's chart as data (the query of the page and of its CSV: a place, a quantity, a preset or from and
    to), for the page behind `?ui=next`: what `charts` draws as SVG (sensors/chart.py `data`), the fish's limit bands for
    a person who may read the water, the newest value of the channel, and the CSV's address. A query the form refuses
    is answered 400 with the form's reasons, never an empty chart.

    Compare: `compare` names a second place ("kind:pk", as `target`) and `compare_quantity` its quantity (the first's when
    not given); its chart is read by the same `series` on EXACTLY the first one's window (one now, the same instants),
    so the two share one time axis, with its own bands and newest value. A second place or quantity that is not one is
    a 400, never a chart left out silently."""
    form = ChartForm(request.GET or None)
    found = chart_payload(request, form)
    if 'errors' in found:
        return JsonResponse(found, status=400)
    return JsonResponse(found)


def _errors(form):
    return {'errors': {name: [str(error) for error in errors] for name, errors in form.errors.items()}}


def chart_payload(request, form):
    """{'chart', 'now', 'compare', 'csv'} of a Charts query (`chart_data`, and the page in the new look), or {'errors'}
    when the form or the compare refuses it."""
    if not form.is_bound or not form.is_valid():
        return _errors(form)
    data = form.cleaned_data
    now = timezone.now()
    found = _chart_of(form)
    drawn = urlencode([(key, value) for key, value in request.GET.items() if key not in ('compare', 'compare_quantity', 'ui')])
    answer = {'chart': chart.data(found, str(data['place']), chart_bands(request.user, data['place'])),
              'now': chart_now(found, now), 'compare': None, 'csv': f'{reverse("sensors:chart_csv")}?{drawn}'}
    if request.GET.get('compare'):
        other = place_of(request.GET['compare'])
        code = request.GET.get('compare_quantity') or data['quantity']
        if other is None or code not in quantities.CODES:
            return {'errors': {'compare': [str(_('Choose a place and a quantity from the lists to compare with.'))]}}
        second = read.series(other, code, data['from'], data['to'])
        answer['compare'] = {'chart': chart.data(second, str(other), chart_bands(request.user, other)),
                             'now': chart_now(second, now)}
    return answer


@permission_required(READ, raise_exception=True)
def target_charts(request):
    """A window's charts (a monitoring card, a Deffeyes window): every quantity bound to a place over a preset time, the
    manual samples as points; the presets reload the window."""
    target = place_of(request.GET.get('target'))
    if target is None:
        raise Http404
    key = request.GET.get('range') if request.GET.get('range') in dict(RANGES) else '24h'
    now = timezone.now()
    start = now - dict(RANGES)[key]
    drawn = []
    for code in read.bound_quantities(target, start, now):
        found = read.series(target, code, start, now)
        drawn.append({'quantity': found.quantity, 'svg': mark_safe(chart.draw(found, str(target))),
                      'notes': chart.notes(found)})
    base = f'{reverse("sensors:target_charts")}?{urlencode({"target": request.GET["target"]})}'
    links = [{'key': each, 'url': f'{base}&range={each}', 'current': each == key} for each, _span in RANGES]
    return render(request, 'sensors/_target_charts.html', {'target': target, 'charts': drawn, 'links': links})


@permission_required(READ, raise_exception=True)
def live(request):
    """Sensors › Operations › Live values: every channel listened to, its last value, how old it is and whether it is
    fresh, and where it is bound now."""
    now = timezone.now()
    channels = list(Channel.objects.exclude(state=ChannelStatus.RETIRED).select_related('device')
                    .order_by('device__code', 'code'))
    states = read.latest([channel.channel_no for channel in channels], now)
    places = {binding.channel_id: binding for binding in Binding.objects.visible().at(now)
              .select_related('point__unit', 'point__system', 'point__equipment', 'system', 'equipment')}
    rows = [{'channel': channel, 'state': states[channel.channel_no], 'binding': places.get(channel.pk)}
            for channel in channels]
    return render_page(request, 'sensors/live.html', _context('sensors:live', rows=rows, now=now))


@permission_required((READ, 'farm.view_watermeasurement'), raise_exception=True)
def trail_points(request):
    """The trail of a unit's or a system's water on the Deffeyes diagram over a preset time (A4), hour by hour, as JSON
    for the card designer's chart: the hours drawn, the hours without every input, the hours whose pH and alkalinity
    cannot go together and the hours whose water the core refuses, each with its reason (never drawn). It joins the sensors and the water
    samples, so it needs the right to read both."""
    target = place_of(request.GET.get('target'))
    if not isinstance(target, (Tank, System)):
        raise Http404
    key = request.GET.get('range') if request.GET.get('range') in dict(RANGES) else '24h'
    end = timezone.now().replace(minute=0, second=0, microsecond=0)
    found = trail.trail(target, end - dict(RANGES)[key], end)
    return JsonResponse({
        'points': [{'at': point.at.isoformat(), 'temperature_c': point.temperature_c, 'ph': point.ph,
                    'alkalinity_mg_l': point.alkalinity_mg_l, 'salinity_ppt': point.salinity_ppt, 'dic': point.dic,
                    'alkalinity_meq': point.alkalinity_meq} for point in found.points],
        'missing': [moment.isoformat() for moment in found.missing],
        'impossible': [moment.isoformat() for moment in found.impossible],
        'unworkable': [{'at': moment.isoformat(), 'why': why} for moment, why in found.unworkable]})


# ---- moving a whole device (a portable probe) ------------------------------------------------------------------
@permission_required(BindingResource.perm('add'), raise_exception=True)
def device_move(request):
    """The Move device dialog: a device to a place or out of the water from a moment (sensors/bindings.py
    `move_device`), with where each channel will land shown before it moves. A link may name the device and the place
    (`?device=…&target=unit:…`, from the device's page, the list or a monitoring card). A change of the device, the place
    or the role renders the dialog again with the landing (a draft, nothing moved)."""
    if request.method == 'POST':
        form = DeviceMoveForm(request.POST)
    else:
        initial = {name: request.GET[name] for name in ('device', 'target', 'role') if request.GET.get(name)}
        form = DeviceMoveForm(initial=initial)
        device, place, _out = form.chosen()
        zone = bindings.clock(device, place) if device is not None else zone_of(None)
        form.initial['valid_from'] = timezone.localtime(timezone=zone).replace(tzinfo=None, second=0, microsecond=0)
    if request.method == 'POST' and DRAFT not in request.POST and form.is_valid():
        data = form.cleaned_data
        try:
            bindings.move_device(request.user, data['device'], data['valid_from'], data['place'], role=data['role'],
                                 note=data['note'])
        except ValidationError as error:
            form.add_error(None, error.messages)
        except IntegrityError as error:
            form.add_error(None, refusal_text(error))
        else:
            if data['place'] is None:
                messages.success(request, _('%(device)s taken out of the water.') % {'device': data['device']})
            else:
                messages.success(request, _('%(device)s moved to %(place)s.') % {'device': data['device'],
                                                                                  'place': data['place']})
            return done(request, reverse(DeviceResource.url_name('list')))
    return render_page(request, 'sensors/device_move.html', {
        **_context('sensors:device_list'), 'form': form, 'plan': _landing(form),
        'list_url': reverse(DeviceResource.url_name('list'))})


def _landing(form):
    """The steps of the move the dialog names (sensors/bindings.py `plan_device`), at its moment (now while it has
    none); empty until a device and a place are chosen."""
    device, place, out = form.chosen()
    if device is None or (place is None and not out):
        return []
    at = form.cleaned_data.get('valid_from') if form.is_bound and hasattr(form, 'cleaned_data') else None
    role = (form.data if form.is_bound else form.initial).get('role') or Binding.Role.PRIMARY
    if role not in Binding.Role.values:
        role = Binding.Role.PRIMARY
    return bindings.plan_device(device, place, at or timezone.now(), role)


# ---- dead letters ----------------------------------------------------------------------------------------------
DEAD_PAGE = 100


@permission_required('sensors.view_deadletter', raise_exception=True)
def dead_letters(request):
    """Sensors › Operations › Dead letters: what the ingest could not store, newest first, the open ones by default; the
    payload shown as text and as hex, escaped (it is whatever a device sent). A person who may change them resolves one."""
    letters = DeadLetter.objects.order_by('-last_at')
    reason = request.GET.get('reason', '')
    if reason in DeadReason.values:
        letters = letters.filter(reason=reason)
    if request.GET.get('show') != 'all':
        letters = letters.filter(resolved_at__isnull=True)
    page = Paginator(letters, DEAD_PAGE).get_page(request.GET.get('page'))
    names = dict(Connection.all_objects.values_list('pk', 'name'))
    rows = [{'letter': letter, 'connection': names.get(letter.connection_id, '—'),
             'text': bytes(letter.payload).decode('utf-8', errors='replace'), 'hex': bytes(letter.payload).hex()}
            for letter in page.object_list]
    kept = request.GET.copy()
    kept.pop('page', None)
    return render_page(request, 'sensors/dead_letters.html', _context(
        'sensors:dead_letters', rows=rows, page=page, reasons=DeadReason.choices, reason=reason,
        show=request.GET.get('show', ''), pager_query=kept.urlencode(),
        can_resolve=request.user.has_perm('sensors.change_deadletter')))


@require_POST
@permission_required('sensors.change_deadletter', raise_exception=True)
def dead_letter_resolve(request, pk):
    """Marks a dead letter resolved (the cause is dealt with), logged; the message itself stays as it came."""
    with transaction.atomic():
        letter = get_object_or_404(DeadLetter.objects.select_for_update(), pk=pk)
        if letter.resolved_at is None:
            letter.resolved_at, letter.resolved_by = timezone.now(), request.user
            letter.save(update_fields=['resolved_at', 'resolved_by'])
            with audit.source_language():
                audit.record(request.user, AuditLog.Action.UPDATE, letter, {'Resolved': [None, 'yes']})
    messages.success(request, _('Dead letter resolved.'))
    return redirect(reverse('sensors:dead_letters'))


# ---- the overview's state ---------------------------------------------------------------------------------------
INGEST_DEAD_AFTER = timedelta(seconds=90)


def state_tiles(user, now):
    """What the overview says of the sensors now, each for the right that may read it: whether the ingest is alive (its
    heartbeat within 90 s), how many devices are online, how many are not placed (out of the water), how many active channels of active devices have no fresh value, and how many
    dead letters came in the last day."""
    tiles = []
    if user.has_perm('sensors.view_connection'):
        statuses = list(IngestStatus.objects.filter(connection_id__in=Connection.objects.filter(is_active=True)
                                                    .values('pk')))
        if not statuses:
            text = _('No heartbeat yet')
        elif all(now - status.heartbeat_at <= INGEST_DEAD_AFTER for status in statuses):
            text = _('Alive')
        else:
            text = _('Down')
        tiles.append({'label': _('Ingest'), 'text': text, 'count': text,
                      'url': reverse('sensors:connection_list')})
        # What the ingest could not keep: QoS 0 messages it dropped on a full queue, messages the database refused (they
        # are dead letters too). Counted since the service started.
        tiles.append({'label': _('QoS 0 messages dropped on a full queue'), 'url': reverse('sensors:connection_list'),
                      'count': sum(status.qos0_dropped for status in statuses)})
        tiles.append({'label': _('Messages the database refused'), 'url': reverse('sensors:connection_list'),
                      'count': sum(status.poison_total for status in statuses)})
    if user.has_perm('sensors.view_device'):
        devices = list(Device.objects.filter(is_active=True))
        online = sum(1 for status in read.device_status(devices, now).values() if status.online)
        tiles.append({'label': _('Devices online'), 'count': f'{online} / {len(devices)}',
                      'url': reverse('sensors:device_list')})
        # Out of the water (storage, calibration): its readings are stored and belong to no place.
        tiles.append({'label': _('Devices not placed'), 'url': f'{reverse("sensors:device_list")}?placed=no',
                      'count': Device.objects.filter(is_active=True).exclude(bindings.placed()).count()})
    if user.has_perm('sensors.view_channel'):
        listened = Channel.objects.filter(state=ChannelStatus.ACTIVE, device__is_active=True, device__is_deleted=False)
        stale = sum(1 for state in read.latest(listened.values_list('channel_no', flat=True), now).values()
                    if not state.fresh)
        tiles.append({'label': _('Channels without a fresh value'), 'count': stale,
                      'url': reverse('sensors:channel_list')})
    if user.has_perm('sensors.view_alarmevent'):
        tiles.append({'label': _('Open alarms'), 'url': reverse('sensors:alarm_events'),
                      'count': AlarmEvent.objects.filter(closed_at__isnull=True).count()})
    if user.has_perm('sensors.view_deadletter'):
        tiles.append({'label': _('Dead letters, last 24 hours'), 'url': reverse('sensors:dead_letters'),
                      'count': DeadLetter.objects.filter(last_at__gte=now - timedelta(days=1)).count()})
    return tiles


# ---- alarm events ----------------------------------------------------------------------------------------------
@permission_required('sensors.view_alarmevent', raise_exception=True)
def alarm_events(request):
    """Sensors › Operations › Alarm events: the times a rule held, the open ones first, with who acknowledged each (the
    alarms app keeps it)."""
    events = AlarmEvent.objects.select_related(
        'rule__channel__device', 'alarm', 'binding__point__unit', 'binding__point__system', 'binding__point__equipment',
        'binding__system', 'binding__equipment').prefetch_related(
        'alarm__acknowledgements__user').order_by(F('closed_at').desc(nulls_first=True), '-opened_at')
    page = Paginator(events, DEAD_PAGE).get_page(request.GET.get('page'))
    return render_page(request, 'sensors/alarm_events.html', _context(
        'sensors:alarm_events', page=page, events=page.object_list, connected=alarms_read.connected(),
        can_acknowledge=request.user.has_perm('sensors.change_alarmevent')))


@require_POST
@permission_required('sensors.change_alarmevent', raise_exception=True)
def alarm_event_acknowledge(request, pk):
    """A person says they saw an alarm event: the alarms' acknowledgement of its alarm (alarms.services.acknowledge, logged;
    app 'console'), once per person; the event stays open until its rule no longer holds."""
    with transaction.atomic():
        event = get_object_or_404(AlarmEvent.objects.select_for_update(), pk=pk)
        alarm = getattr(event, 'alarm', None) or alarm_sources.mirror(event)
        if not alarm.acknowledgements.filter(user=request.user).exists():
            alarm_services.acknowledge(alarm, request.user, app='console')
    messages.success(request, _('Alarm event acknowledged.'))
    return redirect(reverse('sensors:alarm_events'))


@gzip_page                 # owner amendment B4: the page compressed (geometry, no secret)
@permission_required((READ, 'farm.view_watermeasurement'), raise_exception=True)
def deffeyes_frames(request):
    """A page of the Deffeyes replay of a unit's or a system's water (A6, A7, A8) as JSON for the player: `figures`, the
    whole diagram of each different water of the page once (deffeyes.figure: the server's SVG draws the same with
    deffeyes.render), and the frames as columns, frame i at `first` + i × `step_s`: its figure's index (None without a
    diagram), the point, what was missing or why the water cannot be, and each input's value, origin, age and channel.
    `start`/`end` on the site's clock (else `range` ending now, 7 days by default), `step` in seconds (snapped up to the
    ladder), `cursor` the first frame of the page (0 by default; `next` gives the following page's, None after the last).
    It joins the sensors and the water samples, so it needs the right to read both."""
    target = place_of(request.GET.get('target'))
    if not isinstance(target, (Tank, System)):
        raise Http404
    zone = read.zone_for(target)
    try:
        if request.GET.get('start') and request.GET.get('end'):
            walls = [read_moment(request.GET[name]) for name in ('start', 'end')]   # core.dates: inside 1900-2100
            if None in walls:
                raise ValueError('Not a moment this page reads.')
            start, end = (on_site_clock(wall, zone) for wall in walls)
        else:
            end = timezone.now().replace(minute=0, second=0, microsecond=0)
            start = end - dict(RANGES).get(request.GET.get('range', ''), timedelta(days=7))
        step = timedelta(seconds=int(request.GET.get('step') or 3600))
        found = read.deffeyes_frames(target, start, end, step, cursor=int(request.GET.get('cursor') or 0))
    except (ValueError, OverflowError, ValidationError):     # OverflowError: a step longer than a timedelta holds
        return JsonResponse({'error': _('Give a start before the end on the site’s clock, a step in seconds and a '
                                        'cursor inside the range.')}, status=400)
    frames = found.frames
    return JsonResponse({
        'plot': {'left': deffeyes.LEFT, 'top': deffeyes.TOP, 'size': deffeyes.PLOT},
        'step_s': found.step.total_seconds(), 'tier': found.tier, 'total': found.total, 'cursor': found.cursor,
        'next': found.next, 'first': frames[0].at.isoformat(), 'figures': found.figures,
        'frames': {
            'figure': [frame.figure for frame in frames],
            'missing': [list(frame.missing) for frame in frames],
            'impossible': [frame.impossible for frame in frames],
            **{name: [None if frame.point is None else getattr(frame.point, name) for frame in frames]
               for name in ('dic', 'alkalinity_meq', 'ph', 'co2_mg_l')},
            'inputs': {code: {
                'value': [frame.inputs[code].value if code in frame.inputs else None for frame in frames],
                'origin': [frame.inputs[code].origin if code in frame.inputs else None for frame in frames],
                'age_s': [frame.inputs[code].age_s if code in frame.inputs else None for frame in frames],
                'channel': [frame.inputs[code].channel_no if code in frame.inputs else None for frame in frames]}
                for code in read.REPLAY_INPUTS if any(code in frame.inputs for frame in frames)}}})
