"""The Sensors panel's pages beyond its tabs: the overview, and a credential's secret, shown once when it is made or
replaced and never again."""
import csv
import uuid
from datetime import timedelta
from urllib.parse import urlencode

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _, gettext_lazy
from django.views.decorators.http import require_POST

from core import audit, navigation
from core.crud import done, render_page
from core.models import AuditLog
from farm.models import Equipment, SamplingPoint, System, Tank

from . import chart, credentials, quantities, read, trail
from .forms import on_site_clock
from .models import (Binding, Channel, ChannelStatus, Connection, Credential, DeadLetter, DeadReason, Device,
                     IngestStatus)
from .resources import (ChannelResource, ConnectionResource, CredentialResource, DeviceResource, PayloadFormatResource,
                        secret_page)

DATETIME = forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M')
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
TARGET_MODELS = {'unit': Tank, 'system': System, 'point': SamplingPoint, 'equipment': Equipment}


def parse_target(value):
    """The unit, system, sampling point or piece of equipment a "kind:pk" names; None for anything else."""
    kind, _sep, pk = (value or '').partition(':')
    model = TARGET_MODELS.get(kind)
    if model is None:
        return None
    try:
        return model.objects.filter(pk=uuid.UUID(pk)).first()
    except ValueError:
        return None


def target_choices():
    """The places a chart can be drawn for: units, systems, sampling points, equipment ("kind:pk")."""
    points = SamplingPoint.objects.filter(is_active=True).with_owners()
    return [
        (_('Units'), [(f'unit:{unit.pk}', str(unit)) for unit in Tank.objects.order_by('code')]),
        (_('Systems'), [(f'system:{system.pk}', str(system)) for system in System.objects.order_by('code')]),
        (_('Sampling points'), sorted(((f'point:{point.pk}', str(point)) for point in points), key=lambda item: item[1])),
        (_('Equipment'), [(f'equipment:{item.pk}', str(item)) for item in Equipment.objects.order_by('code')]),
    ]


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
        self.fields['target'].choices = [('', '---------'), *target_choices()]

    def clean(self):
        cleaned = super().clean()
        target = parse_target(cleaned.get('target'))
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
        current = timezone.get_current_timezone()
        try:
            cleaned['from'] = on_site_clock(timezone.make_naive(cleaned['start'], current), zone)
            cleaned['to'] = on_site_clock(timezone.make_naive(cleaned['end'], current), zone)
        except ValidationError as error:
            self.add_error(None, error)
            return cleaned
        if cleaned['to'] <= cleaned['from']:
            self.add_error('end', _('The end comes after the start.'))
        return cleaned


def _chart_of(form):
    data = form.cleaned_data
    return read.series(data['place'], data['quantity'], data['from'], data['to'])


@permission_required(READ, raise_exception=True)
def charts(request):
    """Sensors › Operations › Charts: one place's quantity over a time, the CSV of what is drawn beside it."""
    form = ChartForm(request.GET or None)
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


@permission_required(READ, raise_exception=True)
def target_charts(request):
    """A window's charts (a monitoring card, a Deffeyes window): every quantity bound to a place over a preset time, the
    manual samples as points; the presets reload the window."""
    target = parse_target(request.GET.get('target'))
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
    for the card designer's chart: the hours drawn and the hours without every input. It joins the sensors and the water
    samples, so it needs the right to read both."""
    target = parse_target(request.GET.get('target'))
    if not isinstance(target, (Tank, System)):
        raise Http404
    key = request.GET.get('range') if request.GET.get('range') in dict(RANGES) else '24h'
    end = timezone.now().replace(minute=0, second=0, microsecond=0)
    found = trail.trail(target, end - dict(RANGES)[key], end)
    return JsonResponse({
        'points': [{'at': point.at.isoformat(), 'temperature_c': point.temperature_c, 'ph': point.ph,
                    'alkalinity_mg_l': point.alkalinity_mg_l, 'salinity_ppt': point.salinity_ppt, 'dic': point.dic,
                    'alkalinity_meq': point.alkalinity_meq} for point in found.points],
        'missing': [moment.isoformat() for moment in found.missing]})


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
    heartbeat within 90 s), how many devices are online, how many active channels of active devices have no fresh value, and how many
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
    if user.has_perm('sensors.view_device'):
        devices = list(Device.objects.filter(is_active=True))
        online = sum(1 for status in read.device_status(devices, now).values() if status.online)
        tiles.append({'label': _('Devices online'), 'count': f'{online} / {len(devices)}',
                      'url': reverse('sensors:device_list')})
    if user.has_perm('sensors.view_channel'):
        listened = Channel.objects.filter(state=ChannelStatus.ACTIVE, device__is_active=True, device__is_deleted=False)
        stale = sum(1 for state in read.latest(listened.values_list('channel_no', flat=True), now).values()
                    if not state.fresh)
        tiles.append({'label': _('Channels without a fresh value'), 'count': stale,
                      'url': reverse('sensors:channel_list')})
    if user.has_perm('sensors.view_deadletter'):
        tiles.append({'label': _('Dead letters, last 24 hours'), 'url': reverse('sensors:dead_letters'),
                      'count': DeadLetter.objects.filter(last_at__gte=now - timedelta(days=1)).count()})
    return tiles
