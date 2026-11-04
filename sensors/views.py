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
from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _, gettext_lazy
from django.views.decorators.http import require_POST

from core import audit, navigation
from core.crud import done, render_page
from core.models import AuditLog
from farm.models import Equipment, SamplingPoint, System, Tank

from . import chart, credentials, quantities, read
from .forms import on_site_clock
from .models import Binding, Channel, ChannelStatus, Credential
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
    return render_page(request, 'sensors/home.html', _context('sensors:home', setup_tiles=tiles))


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
