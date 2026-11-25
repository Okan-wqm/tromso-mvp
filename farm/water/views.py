"""Operations › Water chemistry: the latest water of every unit and loop with its status, the history of
the samples with their values judged, the calculator with the Water Quality Management Chart, and the
dialogs that record a sample, a round or a void. A read page with dialogs, as Production units is
(farm/stock/views.py): each dialog renders in the shared dialog or as a page, posts to itself and goes
back where it was opened (`next`).

A sample is at a sampling point (farm/models/water_point.py). The address names where a page or a dialog is
about: `?point=<id>` one point, `?unit=<id>`, `?system=<id>` or `?equipment=<id>` an owner (every point of it
in the history; its middle point, the one that stands for its water, where one is to be chosen), or `?owner=`
with `unit:<id>`, `system:<id>` or `equipment:<id>` (what the history's filter sends).

Who may do what (config/access.py, area Water chemistry): reading needs view on the samples (the
calculator too: it stores nothing), recording a sample or a round add, voiding one delete. The buttons a
person cannot use are not shown, and the views refuse them too. The page judges every value on read
(farm/water/read.py) and alerts nobody: critical values are shown, not sent."""
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone as dt_timezone
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import NON_FIELD_ERRORS, BadRequest, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import formats, timezone
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.utils.translation import gettext as _, ngettext

from core import navigation, ui
from core.crud import done, render_page
from core.dates import on_clock, on_clock_or_earlier, read_day, read_moment
from core.widgets import EXAMPLE

from ..forms.water import (CalculatorForm, RoundForm, RoundRowForm, RoundScopeForm, SampleVoidForm, WaterSampleForm,
                           find_owner, find_point, point_order)
from ..models import Equipment, SamplingPoint, Site, System, Tank, WaterMeasurement
from ..models.site import zone_of
from ..models.water_point import EQUIPMENT, SYSTEM, UNIT, local_time, owner_type_of, site_of
from ..stock.read import unit_counts
from ..stock.services import AlreadyRecorded
from . import calculation, messages as words, parameters, read, services
from .evaluate import ALERTS, Status
from .parameters import MEASURED, NH3_N

VIEW, RECORD, VOID = 'farm.view_watermeasurement', 'farm.add_watermeasurement', 'farm.delete_watermeasurement'
HISTORY = 'history'
PAGE_SIZE = 50
HISTORY_DAYS = 30      # the history's default span, back from today
HISTORY_MAX_DAYS = 366  # the longest span a history page judges: a longer one starts later, and the page says so
OWNER_MODELS = {UNIT: Tank, SYSTEM: System, EQUIPMENT: Equipment}
OWNER_RELATED = {UNIT: ('production_department__site',), SYSTEM: ('site',), EQUIPMENT: ('production_department__site',)}


def _context(**extra):
    place = navigation.place(VIEW)
    return {'title': place.entry.label, 'eyebrow': f'{place.section.label} · {place.entry.label}', **extra}


def page_url(**query):
    query = {key: value for key, value in query.items() if value}
    return reverse('farm:water') + (f'?{urlencode(query)}' if query else '')


@dataclass
class Place:
    """What an address names: an owner (a unit, a loop, a piece of equipment) and, when it names one, a point."""
    owner: object = None
    point: object = None

    @property
    def target(self):
        """What the page is about: the point when one is named, else the owner."""
        return self.point or self.owner


def target_query(target):
    """The query string key and value that name a point (?point=) or an owner (?unit=, ?system=, ?equipment=)."""
    if isinstance(target, SamplingPoint):
        return 'point', str(target.pk)
    return owner_type_of(target), str(target.pk)


def history_url(target):
    """The history of a point, or of an owner (every point of it)."""
    return page_url(**dict([target_query(target)]))


def _owner(owner_type, value):
    """The live owner of that type the id names; None when it names none."""
    try:
        uuid.UUID(value)
    except ValueError:
        return None
    return OWNER_MODELS[owner_type].objects.select_related(*OWNER_RELATED[owner_type]).filter(pk=value).first()


def _place(request):
    """Where the address says the page or dialog is about (see the module's docstring); Place() when nothing."""
    point = find_point(request.GET.get('point', ''))
    if point is not None:
        return Place(point.owner, point)
    kind, _sep, value = request.GET.get('owner', '').partition(':')
    asked = ([(kind, value)] if kind in OWNER_MODELS else []) + [(name, request.GET.get(name, ''))
                                                                  for name in OWNER_MODELS]
    for owner_type, value in asked:
        owner = _owner(owner_type, value) if value else None
        if owner is not None:
            return Place(owner)
    return Place()


def _next(request, default):
    """Where a dialog goes back to: the page it was opened from (`next`, a local address), else `default`."""
    target = request.GET.get('next', '')
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}) and \
            target.startswith('/'):
        return target
    return default


def _refused(request, template, context):
    response = render_page(request, template, context)
    response.status_code = 422
    return response


# ---- the page ------------------------------------------------------------------------------------------
def _columns(readings_list, derived=True):
    """The parameters that have a value among these readings, in the registry's order, NH₃-N after TAN."""
    present = {code for readings in readings_list for code in readings}
    columns = []
    for parameter in MEASURED:
        if parameter.code in present:
            columns.append(parameter)
            if parameter.code == parameters.TAN and derived and NH3_N.code in present:
                columns.append(NH3_N)
    return columns


def _site_param(request, sites):
    chosen = request.GET.get('site', '')
    return next((site for site in sites if str(site.pk) == chosen), None)


@permission_required(VIEW, raise_exception=True)
def water_page(request):
    sites = list(Site.objects.order_by('name'))
    site = _site_param(request, sites)
    place = _place(request)
    showing_history = place.owner is not None or request.GET.get('view') == HISTORY
    context = _context(
        sites=sites, site=site, place=place, owner=place.owner, point=place.point, showing_history=showing_history,
        latest_url=page_url(site=site.pk if site else ''),
        history_tab_url=page_url(view=HISTORY, site=site.pk if site else ''),
        calculator_url=reverse('farm:water_calculator'),
        can_record=request.user.has_perm(RECORD), can_void=request.user.has_perm(VOID),
        record_url=_dialog_url('farm:water_record', request, place.target),
        round_url=reverse('farm:water_round') + (f'?{urlencode({"site": site.pk})}' if site else ''),
    )
    context.update(_history(request, site, place) if showing_history else _latest(site, ui.is_next(request)))
    return render_page(request, 'farm/water.html', context)


def _dialog_url(name, request, target=None, args=()):
    """A dialog's address: it goes back to this page, and is about `target` (a point or an owner) when given."""
    query = {'next': request.get_full_path()}
    if target is not None:
        query.update([target_query(target)])
    return f'{reverse(name, args=args)}?{urlencode(query)}'


def _latest(site, next_look=False):
    """One row per point: the middle point of every unit (a unit without one is a row of its own, to say so), and
    every other point of an owner that has a sample within the window (loops and equipment show only then). Each row's
    history: in the new look a unit's is Tank › Water (`farm:tank_water`, the one home of a tank's water history), a
    loop's and a piece of equipment's the history page; in the classic look the history page for all."""
    units = Tank.objects.select_related('production_department__site', 'system')
    if site is not None:
        units = units.filter(production_department__site=site)
    units = list(units.order_by('production_department__site__name', 'production_department__name', 'code'))
    since = timezone.now() - read.WINDOW
    recent = (SamplingPoint.objects.filter(is_active=True, samples__is_deleted=False, samples__measured_at__gte=since)
              .with_owners().distinct())
    if site is not None:
        recent = recent.filter(Q(unit__production_department__site=site) | Q(system__site=site)
                               | Q(equipment__production_department__site=site))
    middles = read.middle_points(units)
    points = {point.pk: point for point in [*middles.values(), *recent]}
    by_owner = defaultdict(list)
    for point in points.values():
        by_owner[point.owner.pk].append(point)
    # A unit with no point to read its own water at: its row's water read at its system, in the same read
    # (read.latest `units`; review 2 of the branch R2, review 4 L1).
    anchored = read.anchors(units)
    water = read.latest(list(points.values()), units=read.unanchored(units, anchored))
    entries = []
    for unit in units:
        if unit.pk not in middles:
            entries.append((unit, None))
        entries += [(unit, point) for point in sorted(by_owner.pop(unit.pk, []), key=point_order)]
    entries += [(point.owner, point) for point in sorted((p for found in by_owner.values() for p in found),
                                                         key=point_order)]
    rows = []
    for owner, point in entries:
        point_water = water[point.pk] if point is not None else water.get(owner.pk, read.PointWater(None))
        rows.append({'owner': owner, 'point': point, 'loop': isinstance(owner, System), 'water': point_water,
                     'history_url': reverse('farm:tank_water', args=[owner.pk]) if next_look and isinstance(owner, Tank)
                     else history_url(point or owner)})
    columns = _columns([row['water'].readings for row in rows])
    for row in rows:
        row['cells'] = [row['water'].get(parameter.code) for parameter in columns]
    # A count of POINTS counts what was measured at each point (PointWater.point_status): one physical problem once,
    # though the unit's middle point shows the unit's status computed from its other points too (A9.1).
    counts = {status: sum(1 for row in rows if row['water'].point_status == status) for status in ALERTS}
    return {'rows': rows, 'columns': columns, 'point_count': sum(1 for row in rows if row['point'] is not None),
            'critical_count': counts[Status.CRITICAL], 'warning_count': counts[Status.WARNING],
            'sensors_failed': any(point_water.sensors_failed for point_water in water.values()), 'now': timezone.now()}


def _day(request, name, default):
    return read_day(request.GET.get(name, ''), request) or default


def _history(request, site, place):
    """The history's context: the samples of the span (at most HISTORY_MAX_DAYS, the first day moved and said), paged
    in the database and only the page's judged; with "alerts only" every sample of the span is judged first, as the
    alert is worked out on read."""
    zone = zone_of(site if place.owner is None else site_of(place.owner))
    today = timezone.localdate(timezone=zone)
    start, end = _day(request, 'from', today - timedelta(days=HISTORY_DAYS)), _day(request, 'to', today)
    clipped = (end - start).days > HISTORY_MAX_DAYS
    if clipped:
        start = end - timedelta(days=HISTORY_MAX_DAYS)
    samples = read.samples_of(
        points=[place.point] if place.point is not None else None,
        owner=None if place.point is not None else place.owner,
        site=site if place.owner is None else None,
        since=timezone.make_aware(datetime.combine(start, time.min), zone),
        before=timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min), zone))
    alerts_only = request.GET.get('alerts') == '1'
    if alerts_only:
        # A sample whose judged value cannot be evaluated is one of them (shown as a warning, never OK: the re-check of
        # 2026-11-18, RC-5, found it dropped here).
        rows = [row for row in read.history(list(samples))
                if not row.sample.is_deleted and row.status in (*ALERTS, Status.UNEVALUATED)]
        page = Paginator(rows, PAGE_SIZE).get_page(request.GET.get('page'))
    else:
        page = Paginator(samples, PAGE_SIZE).get_page(request.GET.get('page'))
        page.object_list = read.history(list(page.object_list))
    columns = _columns([row.readings for row in page.object_list])
    earliest = {}
    for row in page.object_list:
        sample = row.sample
        row.cells = [row.readings.get(parameter.code) for parameter in columns]
        row.history_url = history_url(sample.point)
        if request.user.has_perm(VOID) and not sample.is_deleted:
            if sample.point_id not in earliest:
                earliest[sample.point_id] = services.earliest(sample.point)
            if local_time(sample.measured_at, sample.point).date() >= earliest[sample.point_id]:
                row.void_url = _dialog_url('farm:water_void', request, args=[sample.pk])
    kept = request.GET.copy()
    kept.pop('page', None)
    return {'history': page.object_list, 'page': page, 'pager_query': kept.urlencode(), 'columns': columns,
            'start': start, 'end': end, 'clipped': clipped, 'span': HISTORY_MAX_DAYS, 'alerts_only': alerts_only,
            'zone': zone,
            'owner_groups': _owner_groups(site, place.owner),
            'point_choices': _owner_points(place.owner)}


def _owner_groups(site, chosen):
    """[(group label, [(value, label, selected)])] of the owners the history can be narrowed to, `type:<id>`."""
    groups = []
    for label, model, owner_type in ((_('Units'), Tank, UNIT), (_('Systems (loop)'), System, SYSTEM),
                                     (_('Equipment'), Equipment, EQUIPMENT)):
        owners = model.objects.order_by('code')
        if site is not None:
            owners = owners.filter(**{('site' if owner_type == SYSTEM else 'production_department__site'): site})
        options = [(f'{owner_type}:{owner.pk}', f'{owner.code} · {owner.name}',
                    chosen is not None and chosen.pk == owner.pk) for owner in owners]
        if options:
            groups.append((label, options))
    return groups


def _owner_points(owner):
    """The points of the owner the history is narrowed to, each can be chosen in turn; none without an owner."""
    if owner is None:
        return []
    return sorted(SamplingPoint.objects.filter(**{owner_type_of(owner): owner}), key=point_order)


# ---- the calculator ------------------------------------------------------------------------------------
def _calculator_data(query):
    """The calculator's values: the address's, and when a unit or a loop was just chosen (`point` is not the
    `loaded` one) its values put in (farm/water/calculation.offers): over what was entered, or over the defaults
    when nothing was. (data, whether values were put in.) Nothing is written anywhere."""
    chosen = query.get('point', '')
    if not chosen or chosen == query.get('loaded', ''):
        return query, False
    data = query.copy() if CalculatorForm.DRAWN in query else CalculatorForm.default_data()
    data['point'] = chosen
    owner = find_owner(chosen)
    if owner is not None:
        offers = calculation.offers(owner)
        # Asked of the address as it came, before the new unit's values go in: the values still those of the unit
        # chosen before.
        kept = {name for name in CalculatorForm.LOADED
                if name not in offers and CalculatorForm.DRAWN in query and CalculatorForm.kept_loaded(query, name)}
        CalculatorForm.fill(data, offers)
        for name, (carried, scale, stored) in CalculatorForm.LOADED.items():
            if name in offers or name in kept:
                # A stored pH is on the NBS scale, whatever was chosen and whatever it was measured on; the value goes
                # with it, so another scale on it is refused, never a second conversion (review R2). So does one the
                # new unit has none of, left in the field from the unit chosen before: still a stored value, not a
                # typed one (the verification of 2026-11-18, V-B: its `ph_loaded` was emptied and it was converted).
                data[scale] = stored
                data[carried] = data[name]
            else:
                data[carried] = ''                 # nothing loaded: what stands in the field was typed, with its scale
        data['water_origin'] = calculation.origin_of(owner)       # the unit's (cross review F3)
    data['loaded'] = chosen
    return data, True


# What a loaded value says of how it was measured, by field (farm/water/messages.py; '' when stored as measured).
STORED = {parameters.PH: words.ph_stored, parameters.PHOSPHATE: words.phosphate_measured_short}


def _source(form, owner):
    """Where the values came from, field by field: what the unit or loop offers, whether the form still has it,
    its time and status; and the measured fields it has no value for."""
    offers = calculation.offers(owner)
    entered = getattr(form, 'cleaned_data', {})
    rows = []
    for name, offer in offers.items():
        field = form.fields[name]
        value = None if offer.value is None else offer.value.quantize(Decimal(1).scaleb(-field.decimal_places))
        sample = getattr(getattr(offer.reading, 'sample', None), 'sample', None)
        rows.append({'label': field.label, 'value': value, 'decimals': field.decimal_places, 'offer': offer,
                     'changed': entered.get(name) != value,
                     # a limit of the fish, not a measured value (the new look puts these under a summary)
                     'limit': offer.reading is None and name != 'altitude_m',
                     # a pH measured on another scale, a phosphate entered as PO₄: what was measured, and that the value
                     # here is the stored one (NBS, as P)
                     'measured': STORED[name](sample) if name in STORED and sample is not None else ''})
    missing = [form.fields[name].label for name in calculation.MEASURED_FIELDS if name not in offers]
    limits = [row for row in rows if row['limit']]
    return {'point': owner, 'rows': rows, 'missing': missing, 'limits': bool(limits),
            'limits_changed': any(row['changed'] for row in limits)}


def _calculator_context(request, data, all_layers=False):
    """The form, the calculation (None while a value is wrong) and where the values came from."""
    form = CalculatorForm(data if data else None)
    result = None
    if not form.is_bound or form.is_valid():
        result = calculation.calculate(**form.inputs(), all_layers=all_layers)
    chosen = data.get('point', '') if data else ''
    owner = find_owner(chosen) if chosen else None
    query = data.urlencode() if data else ''
    return _context(
        form=form, result=result, analysis=result.analysis if result else None,
        chart_scale=deffeyes_scale(result.chart.isolines, result.chart.box) if result else '',
        ph_conversion=form.ph_conversion if result else None,
        chart=result.chart if result else None, source=_source(form, owner) if owner is not None else None,
        point_gone=bool(chosen) and owner is None, query=query,
        latest_url=page_url(), history_tab_url=page_url(view=HISTORY), calculator_url=reverse('farm:water_calculator'),
        results_url=reverse('farm:water_calculator_results'),
        report_url=reverse('farm:water_calculator_report') + (f'?{query}' if query else ''))


@permission_required(VIEW, raise_exception=True)
def calculator(request):
    """The calculator: a water's values, a target, the limits and the dosing in, the Water Quality Management
    Chart (farm/water/deffeyes.py), the four small charts, the values worked out, the dosing recipes and the
    simulator out (farm/water/calculation.py). A GET form: the address holds the values, so a link opens the
    same view; without values it shows its defaults. Choosing a unit or a loop puts its latest values in and
    sends the address with them (a link then keeps them). Nothing is stored. The page's results are its live
    parts (`calculator_results`), which the browser asks for again as the form changes (frontend/poll.ts)."""
    data, filled = _calculator_data(request.GET)
    if filled:
        return redirect(f"{reverse('farm:water_calculator')}?{data.urlencode()}")
    return render_page(request, 'farm/water_calculator.html', _calculator_context(request, data))


@permission_required(VIEW, raise_exception=True)
def calculator_results(request):
    """The calculator's live parts for the values in the address, each a [data-live-part] that replaces the
    page's own: what the browser asks for while the form is filled in. The same view as the page's, nothing
    stored."""
    data, _filled = _calculator_data(request.GET)
    return render(request, 'farm/calculator/_parts.html', _calculator_context(request, data))


@permission_required(VIEW, raise_exception=True)
def calculator_report(request):
    """The calculator's printed report for the values in the address: the values entered, the values worked
    out, every chart with every layer drawn (as the source's report forces its safety overlays), the recipes
    and the simulator's steps; on a page of its own, to print."""
    data, _filled = _calculator_data(request.GET)
    context = _calculator_context(request, data, all_layers=True)
    context['generated_at'] = timezone.now()
    context['printing'] = True        # on paper nothing is folded away (the new look's <details> stay out)
    return render(request, 'farm/water_calculator_report.html', context)


# ---- a unit's or a system's own chart ----------------------------------------------------------------------------
def _moment(request, owner):
    """The past moment `?at=` names, on the clock of the owner's site (A4: the Deffeyes as it was then); None without
    one. A value that is not a time, or a time the clocks skip or repeat, is refused (400): never read as now."""
    value = request.GET.get('at', '')
    if not value:
        return None
    wall = read_moment(value)                   # core.dates: the one reader, inside 1900-2100 (never an overflow)
    if wall is None:
        raise BadRequest('at')
    zone = zone_of(site_of(owner))
    try:
        first = on_clock(wall, zone)            # core.dates: the one check of a skipped or repeated time
    except ValidationError:
        raise BadRequest('at')
    if first > timezone.now():
        raise BadRequest('at')
    return first


def _owner_chart(request, owner, here):
    chosen = None
    if request.GET.get('point'):
        chosen = next((point for point in calculation.points_for(owner) if str(point.pk) == request.GET['point']), None)
        if chosen is None:
            raise Http404
    at = _moment(request, owner)
    result = calculation.chart_of(owner, chosen, at=at)
    labels = CalculatorForm().fields
    kept = {'at': request.GET['at']} if at is not None else {}
    return render(request, 'farm/_unit_chart.html', {
        'unit': owner, 'result': result, 'uid': f'chart-{result.point.pk}' if result.point else 'chart', 'at': at,
        'chart': getattr(getattr(result, 'calculation', None), 'chart', None),
        'point_links': [{'point': point, 'url': f'{here}?{urlencode({"point": point.pk, **kept})}',
                         'current': result.point is not None and point.pk == result.point.pk}
                        for point in result.points],
        'limit_rows': [(labels[name].label, offer) for name, offer in getattr(result, 'limits', {}).items()],
        # (the fish present are the stock's to tell: a person who may read only water sees the values and the limits)
        'species': sorted({row.species.common_name for offer in getattr(result, 'limits', {}).values()
                           for row in offer.rows}) if request.user.has_perm('farm.view_stockoperation') else [],
    })


# ---- a unit's or a system's water history (Tank › Water, System › Water) ----------------------------------------
HISTORY_RANGES = {'24h': timedelta(hours=24), '7d': timedelta(days=7), '30d': timedelta(days=30)}
HISTORY_LONGEST = timedelta(days=731)          # a custom window: the sensors keep two years (README, Sensors)
SENSOR_READ = 'sensors.view_reading'


def history_window(request, owner, now):
    """(key, start, end) of the window the address names: `range` one of HISTORY_RANGES ending now (24 h by default),
    or `start` and `end` on the site's clock ('custom'); `around` a moment on the site's clock, the 12 hours each side of
    it (an alarm's detail links here so). A time that is not one, an end before the start or a window longer than
    HISTORY_LONGEST is refused (400), never read as another window."""
    from sensors.forms import on_site_clock

    zone = zone_of(site_of(owner))

    def moment(name, repeated=False):
        wall = read_moment(request.GET.get(name, ''))
        if wall is None:
            raise BadRequest(name)
        try:
            # `around` (an alarm's opening, as its link writes it): a time the autumn night shows twice is the earlier of
            # the two; the 12 hours each side hold the opening either way (review C4). A from or a to stays refused.
            found = on_clock_or_earlier(wall, zone) if repeated else on_site_clock(wall, zone)
        except ValidationError:
            raise BadRequest(name)
        # in UTC: arithmetic on a moment that keeps its zone is wall-clock arithmetic, 12 hours back over a change of
        # the clocks would be 11 or 13
        return found.astimezone(dt_timezone.utc)

    if request.GET.get('around'):
        middle = moment('around', repeated=True)
        start, end = middle - timedelta(hours=12), min(middle + timedelta(hours=12), now)
        if end <= start:                        # 12 h or more after now: no window at all, refused (never a 500)
            raise BadRequest('around')
        return 'custom', start, end
    if request.GET.get('start') or request.GET.get('end'):
        start, end = moment('start'), moment('end')
        if end <= start or end - start > HISTORY_LONGEST:
            raise BadRequest('end')
        return 'custom', start, end
    key = request.GET.get('range') if request.GET.get('range') in HISTORY_RANGES else '24h'
    return key, now - HISTORY_RANGES[key], now


def _history_of(user, place, start, end, now, title):
    """One place's water over the window, as data (sensors.read.water_history, sensors.chart.data): every parameter's
    chart with its limit band, each sample with its status as the history page judges it (`status`, and `status_text`
    in words), the NH₃-N worked out per sample with its status. The sensors' values only for a person who may read them
    (otherwise the samples alone, and the chart says why)."""
    from sensors import chart as sensor_chart, read as sensor_read

    found = sensor_read.water_history(place, start, end, now=now)
    sensors = user.has_perm(SENSOR_READ)
    charts = []
    for each in found.charts:
        drawn = sensor_chart.data(each, title, found.bands)
        judged = {int(at.timestamp()): status for at, status in found.judged.get(each.quantity.code, {}).items()}
        for sample in drawn['samples']:
            sample['status'] = judged.get(sample['at'], '')
            sample['status_text'] = str(Status(sample['status']).label) if sample['status'] else ''
        if not sensors:
            drawn['buckets'] = {name: [] for name in drawn['buckets']}
            drawn['gaps'], drawn['markers'], drawn['simulated'], drawn['simulated_text'] = [], [], False, ''
            drawn['notes'] = [str(_('Sensor values are not shown: they need the right to read sensor readings.'))]
            drawn['empty'] = not drawn['samples']
        charts.append(drawn)
    worked = {code: {'label': str(parameters.get(code).short), 'decimals': parameters.get(code).decimals,
                     'band': found.bands.get(code, {}),
                     'values': [{'at': int(item.at.timestamp()), 'value': item.value, 'status': item.status,
                                 'status_text': str(Status(item.status).label) if item.status else '',
                                 'note': item.note} for item in items]}
              for code, items in found.worked.items()}
    return {'charts': charts, 'worked': worked}


RANGE_FRAMES = 120     # about this many Deffeyes frames over a window (the step snapped up the replay's ladder)


def range_deffeyes(user, owner, start, end):
    """Deffeyes for the range (Tank › Water, owner-approved): the replay's frames of the window
    (`sensors.read.deffeyes_frames`, about RANGE_FRAMES of them, so one page) drawn as one chart: the diagram of the
    newest frame that has one (its regions, the fish's limits and the pH isolines of that water; the server's figure, its
    pH labels placed by the server) and the path of the water's point through the window, broken where a frame has no
    diagram (never bridged; a run of one frame is a dot). The star is that newest water's, named with its time; when the
    window's last frame has no diagram the chart says so in words ("No diagram after <time>: <why>"), so a water of
    yesterday is never read as now (review of batch 1, F2). None for a person who may not read the sensors (the frames
    join them with the samples). Without any frame with a diagram, the newest frame's reason: the inputs it lacks, or why
    its pH and alkalinity cannot go together."""
    from sensors import read as sensor_read

    from .deffeyes import Box, as_props, pixel, render
    if not user.has_perm(SENSOR_READ):
        return None
    step = sensor_read.replay_step((end - start) / RANGE_FRAMES)
    # At a step of an hour or more the replay reads the hourly tier: a frame sees the last value of the newest hour that
    # has ended by it, so a frame at :42 would see a probe's value 42 minutes old, never fresh. The frames start on the
    # top of the hour then, whatever the minute the page was opened at (review recheck N1).
    frames_from = start.replace(minute=0, second=0, microsecond=0) if step >= timedelta(hours=1) else start
    found = sensor_read.deffeyes_frames(owner, frames_from, end, step, size=sensor_read.PAGE)
    drawn = [frame for frame in found.frames if frame.figure is not None]
    zone = zone_of(site_of(owner))
    words = {'title': _('Deffeyes chart of the time'), 'water': _('The water'), 'path': _('The water through the time'),
             'first': _('First drawn'), 'dic': _('DIC (mmol/L)'), 'alkalinity': _('Alkalinity (meq/L)'),
             'isolines': _('pH isolines')}

    def lacks(frame):
        missing = ', '.join(str(parameters.get(code).label) for code in frame.missing)
        return frame.impossible or (_('no fresh value of %(missing)s') % {'missing': missing} if missing
                                    else _('a value the chart needs is missing'))

    def shown(at):
        return formats.date_format(timezone.localtime(at, zone), 'DATETIME_FORMAT')

    last = found.frames[-1]
    if not drawn:
        missing = ', '.join(str(parameters.get(code).label) for code in last.missing)
        reason = last.impossible or (_('No frame of this time has every value the chart needs: %(missing)s.') % {
            'missing': missing} if missing else _('No frame of this time has every value the chart needs.'))
        return {'chart': None, 'reason': str(reason), 'words': {key: str(value) for key, value in words.items()}}
    newest = drawn[-1]
    box = Box(*found.figures[newest.figure]['box'])
    runs, run = [], []
    for frame in found.frames:
        if frame.point is None:
            if run:
                runs.append(run)
            run = []
            continue
        x, y = pixel(box, frame.point.dic, frame.point.alkalinity_meq)
        run.append((f'{x:.2f}', f'{y:.2f}', int(frame.at.timestamp())))
    if run:
        runs.append(run)
    first = drawn[0]
    fx, fy = pixel(box, first.point.dic, first.point.alkalinity_meq)
    words['water'] = _('The water at %(time)s') % {'time': shown(newest.at)}
    # the window's end without a diagram: said, never a star read as now
    stale = '' if last.figure is not None else _('No diagram after %(time)s: %(why)s') % {
        'time': shown(newest.at), 'why': lacks(last)}
    caption = _('%(drawn)s of %(total)s moments every %(step)s drawn, from %(first)s to %(last)s; the regions, the limits '
                'and the pH isolines are those of the newest water drawn. A moment without every value is left out, '
                'never joined.') % {
        'drawn': len(drawn), 'total': len(found.frames), 'step': _step_text(found.step),
        'first': shown(first.at), 'last': shown(newest.at)}
    # a page's figure is shared by the frames of the same equilibria, its point left out: the newest frame's own is drawn
    figure = {**found.figures[newest.figure], 'point': [newest.point.dic, newest.point.alkalinity_meq]}
    chart = as_props(render(figure))
    return {'chart': chart, 'path': [' '.join(f'{x},{y}' for x, y, _at in each) for each in runs if len(each) > 1],
            'dots': [{'x': each[0][0], 'y': each[0][1], 'at': each[0][2]} for each in runs if len(each) == 1],
            'first': {'x': f'{fx:.2f}', 'y': f'{fy:.2f}', 'at': int(first.at.timestamp())},
            'at': int(newest.at.timestamp()), 'now': str(stale or words['water']), 'now_status': 'warning' if stale else '',
            'stale': str(stale), 'caption': str(caption), 'reason': '',
            # what the chart's labels say, in words: shown in their place where the chart is too narrow for them
            'scale': deffeyes_scale(chart['isolines'], box),
            'said': [[str(words['water']), str(_('pH %(ph)s, DIC %(dic)s mmol/L, alkalinity %(alkalinity)s meq/L, CO₂ '
                                                  '%(co2)s mg/L') % {
                'ph': formats.number_format(newest.point.ph, 2), 'dic': formats.number_format(newest.point.dic, 3),
                'alkalinity': formats.number_format(newest.point.alkalinity_meq, 3),
                'co2': formats.number_format(newest.point.co2_mg_l, 1)})]]
                    + ([[str(_('No diagram')), str(stale)]] if stale else []),
            'words': {key: str(value) for key, value in words.items()}}


def deffeyes_scale(isolines, box):
    """What a Deffeyes chart's labels say, in words (the pH lines' range, the axes' ends): shown in their place where the
    chart is too narrow for them (under 480 px; Tank › Water's chart of the time and the calculator's, one rule in
    static/css/components.css). `isolines` are the chart's (`render`, or `as_props` of it), `box` its axes' ends."""
    labelled = [line['label']['text'] for line in isolines if line['label']]
    return str(_('Lines of equal pH: %(low)s to %(high)s; DIC across, up to %(dic)s mmol/L; alkalinity up, '
                 'up to %(alkalinity)s meq/L') % {
        'low': labelled[0] if labelled else '', 'high': labelled[-1] if labelled else '',
        'dic': formats.number_format(box.dic), 'alkalinity': formats.number_format(box.alkalinity)})


def _step_text(step):
    """A replay step in words: 15 min, 3 h, 1 day, 7 days."""
    minutes = int(step.total_seconds() // 60)
    if minutes < 60:
        return _('%(count)d min') % {'count': minutes}
    if minutes < 24 * 60:
        return _('%(count)d h') % {'count': minutes // 60}
    days = minutes // (24 * 60)
    return ngettext('%(count)d day', '%(count)d days', days) % {'count': days}


def history_data(request, owner, now=None):
    """A unit's water history (Tank › Water) or a system's (System › Water: each of its points side by side), as data:
    the window, the charts, the values worked out, the events and the address of the Deffeyes replay of the window."""
    now = now or timezone.now()
    key, start, end = history_window(request, owner, now)
    user = request.user
    if isinstance(owner, System):
        places = [{'point': str(point), 'kind': point.kind, **_history_of(user, point, start, end, now, str(point))}
                  for point in calculation.points_for(owner)]
    else:
        places = [{'point': str(owner), 'kind': 'unit', **_history_of(user, owner, start, end, now, str(owner))}]
    query = urlencode({'target': f'{owner_type_of(owner)}:{owner.pk}',
                       'start': timezone.localtime(start, zone_of(site_of(owner))).strftime('%Y-%m-%dT%H:%M'),
                       'end': timezone.localtime(end, zone_of(site_of(owner))).strftime('%Y-%m-%dT%H:%M')})
    return {
        'range': key, 'start': int(start.timestamp()), 'end': int(end.timestamp()),
        'zone': zone_of(site_of(owner)).key, 'places': places, 'events': read.history_events(user, owner, start, end),
        'range_chart': range_deffeyes(user, owner, start, end),
        'deffeyes': f'{reverse("sensors:deffeyes_frames")}?{query}' if user.has_perm(SENSOR_READ) else '',
        'record': _dialog_url('farm:water_record', request, owner) if user.has_perm(RECORD) else '',
        'samples': history_url(owner)}


def _owner_history(request, owner):
    """`history_data` as JSON (`?view=history` of unit_chart and system_chart)."""
    return JsonResponse(history_data(request, owner))


# ---- Tank › Water: the one home of a tank's water history (behind ?ui=next) ---------------------------------------
def _history_words():
    """Every word Tank › Water and System › Water draw (the island words nothing of its own)."""
    return {
        'sensor': _('Sensor'), 'manual': _('Meter or test kit'), 'lab': _('Laboratory'), 'worked': _('Worked out'),
        'warning': _('Warning'), 'critical': _('Critical'), 'noValue': _('No value'), 'time': _('Time'),
        'custom': _('From and to'), 'from': _('From'), 'to': _('To'), 'draw': _('Draw'),
        'empty': _('No water value in this time: nothing was measured or sampled here.'),
        'noChart': _('No sensor values in this time.'),
        'events': _('Events'), 'noEvents': _('No feeding, treatment, harvest or alarm in this time.'),
        'notWorked': _('Not worked out'), 'record': _('Record water sample'), 'samples': _('Samples'),
        'deffeyes': _('Deffeyes chart'), 'calculated': _('worked out from each sample, not measured'),
        'zoneNote': _('Times on the site’s clock (%(zone)s).'),
        'bandsToday': _('The limit bands are the limits of the fish today, over the whole time.'),
    }


def window_props(request, data, here, zone):
    """The window and the words of a water history page's island (`water`: Tank › Water, System › Water) over its
    `history_data`: the preset ranges as links to `here`, the custom window as the date box shows it (core.widgets.
    MomentInput: dd.mm.yyyy HH:MM in every language) on the site's clock `zone`, every word with the zone named, and the
    request's language for the figures."""
    words = _history_words()
    return {
        'ranges': [{'key': key, 'label': key, 'href': f'{here}?{urlencode({"range": key})}',
                    'current': data['range'] == key} for key in HISTORY_RANGES],
        'custom': {'action': here, 'current': data['range'] == 'custom',
                   'start': formats.localize_input(datetime.fromtimestamp(data['start'], tz=zone).replace(tzinfo=None)),
                   'end': formats.localize_input(datetime.fromtimestamp(data['end'], tz=zone).replace(tzinfo=None)),
                   'example': formats.localize_input(EXAMPLE)},
        'words': {**words, 'zoneNote': words['zoneNote'] % {'zone': zone.key}},
        'locale': request.LANGUAGE_CODE,
    }


@permission_required(VIEW, raise_exception=True)
def tank_water(request, pk):
    """Tank › Water (owner-approved home of a tank's water history), in the new look only: every parameter on one time
    axis, the sensors' lines and the samples on the same chart, the fish's limits as bands, the NH₃-N worked out per
    sample, gaps shown, the events of the window (`history_data`). Without the new look the address is the unit's
    history on Water chemistry, today's page for it."""
    unit = get_object_or_404(Tank.objects.select_related('production_department__site'), pk=pk)
    if not ui.is_next(request):
        return redirect(history_url(unit))
    data = history_data(request, unit)
    data.update(window_props(request, data, reverse('farm:tank_water', args=[unit.pk]), zone_of(site_of(unit))))
    data['unit'] = {'code': unit.code, 'name': unit.name, 'place': str(unit.production_department)}
    place = navigation.place('farm.view_stockoperation')
    return render_page(request, 'farm/tank_water.html', {
        'title': f'{unit.code} · {_("Water")}', 'eyebrow': f'{place.section.label} · {place.entry.label}', 'props': data,
        'units_url': reverse('farm:production_units') + f'?{urlencode({"unit": unit.pk})}'})


@permission_required(VIEW, raise_exception=True)
def unit_chart(request, pk):
    """The Deffeyes chart of one unit's water, as the body of the monitoring cards' window (the fragment is polled):
    the chart, the readings it is drawn from with their origin, age, status and point, the limits and species of the
    fish, and the unit's points as links to the same fragment for another one. `?point=` is one of the unit's own active
    points (404 for any other); without it, the middle point. `?at=` draws the water as it was at a past moment (on the
    site's clock). A water that cannot be drawn is refused with what it lacks (farm/water/calculation.chart_of). Gated
    by the right to read water samples alone: it shows nothing else of the unit's records. `?view=history`: the unit's
    water history as JSON instead (`_owner_history`: Tank › Water), each part of it for the person who may read it."""
    unit = get_object_or_404(Tank.objects.select_related('production_department__site'), pk=pk)
    if request.GET.get('view') == HISTORY:
        return _owner_history(request, unit)
    return _owner_chart(request, unit, reverse('farm:water_unit_chart', args=[unit.pk]))


@permission_required(VIEW, raise_exception=True)
def system_chart(request, pk):
    """A system's own Deffeyes chart (A4): its loop's water and the system's sensors, as a unit's (`unit_chart`)."""
    system = get_object_or_404(System.objects.select_related('site'), pk=pk)
    if request.GET.get('view') == HISTORY:
        return _owner_history(request, system)
    return _owner_chart(request, system, reverse('farm:water_system_chart', args=[system.pk]))


# ---- the dialogs ---------------------------------------------------------------------------------------
@permission_required(RECORD, raise_exception=True)
def record_sample(request):
    """Record water sample: at the point named in the address, or at the middle point of the unit, loop or piece
    of equipment named (from the unit drawer or a history), the others of the owner one choice away; else at the
    point chosen."""
    place = _place(request)
    point = place.point
    if point is None and place.owner is not None:
        point = read.middle_points([place.owner]).get(place.owner.pk)
    back = _next(request, history_url(place.target) if place.owner is not None else page_url())
    limits = read.limits_now(point) if point is not None else {}
    context = _context(heading=_('Record water sample'), owner=place.owner, point=point, back_url=back)
    if request.method == 'POST':
        form = WaterSampleForm(request.POST, owner=place.owner, point=point, limits=limits)
        if form.is_valid():
            try:
                sample = form.save(request.user)
            except AlreadyRecorded:
                return done(request, back)
            except ValidationError as error:
                form.add_service_error(error)
            else:
                messages.success(request, _('Water sample recorded at %(point)s.') % {'point': sample.point})
                return done(request, back)
        return _refused(request, 'farm/water_record.html', {**context, 'form': form})
    form = WaterSampleForm(owner=place.owner, point=point, limits=limits)
    return render_page(request, 'farm/water_record.html', {**context, 'form': form})


@permission_required(RECORD, raise_exception=True)
def record_round(request):
    """A round: the middle points of the units and loops of a site, a production department or a system, one row
    each, and the other points of them or of the equipment when asked, at one time and from one source. Empty rows
    are skipped; the rest are recorded together or not at all."""
    scope = RoundScopeForm(request.GET)
    site, department, system, columns, include = scope.scope()
    points = scope.points(site, department, system, include)
    if len(points) > services.ROUND_ROWS:
        points = []
        scope.add_error(None, _('More than %(rows)d points: choose a production department or a system.')
                        % {'rows': services.ROUND_ROWS})
    data = request.POST if request.method == 'POST' else None
    header = RoundForm(data, site=site)
    # One read of every row's water and assumed salinity for what an oxygen column says it would be worked out with
    # (forms.water.OxygenInputs; what it is worked out with is found by the server when the round is written).
    oxygen = bool(points) and bool({parameters.OXYGEN_MG_L, parameters.OXYGEN_PCT} & set(columns))
    water = read.latest(points) if oxygen else {}
    assumed = read.assumed_salinities(points) if oxygen else {}
    rows = [RoundRowForm(data, point=point, columns=columns, water=water.get(point.pk), assumed=assumed.get(point.pk))
            for point in points]
    context = _context(heading=_('Water round'), scope=scope, header=header, rows=rows,
                       ph_column=parameters.PH in columns, phosphate_column=parameters.PHOSPHATE in columns,
                       columns=[parameters.get(code) for code in columns], site=site,
                       back_url=page_url(site=site.pk if site else ''))
    if data is not None and points:
        valid = header.is_valid() & all([row.is_valid() for row in rows])
        if valid:
            entered = [row for row in rows if row.entered()]
            try:
                samples = services.record_round(
                    request.user, measured_at=header.cleaned_data['measured_at'],
                    source=header.cleaned_data['source'], token=header.cleaned_data['token'],
                    withdrawal_ack=header.cleaned_data['withdrawal_ack'],
                    rows=[(row.point, row.entered(), row.cleaned_data['notes']) for row in entered],
                    require_basis=True, ph_scale=header.cleaned_data.get('ph_scale') or services.NBS,
                    phosphate_unit=header.cleaned_data.get('phosphate_unit') or services.AS_P)
            except AlreadyRecorded:
                return done(request, context['back_url'])
            except ValidationError as error:
                _round_errors(error, header, entered)
            else:
                messages.success(request, ngettext('%(count)d water sample recorded.',
                                                   '%(count)d water samples recorded.', len(samples))
                                 % {'count': len(samples)})
                return done(request, context['back_url'])
        return _refused(request, 'farm/water_round.html', context)
    return render_page(request, 'farm/water_round.html', context)


def _round_errors(error, header, entered):
    """The service's reasons on the round: a cell's on its row and parameter, the time on the header. The withdrawal
    guard's question goes on the header, with its box."""
    header.withdrawal_change = getattr(error, 'change', None) or header.withdrawal_change
    for key, messages_ in error.message_dict.items():
        index, _sep, code = key.partition('-')
        if code and index.isdigit():
            entered[int(index)].add_service_error(code, messages_)
        else:
            header.add_error(key if key in header.fields and key != NON_FIELD_ERRORS else None, messages_)


@permission_required(VOID, raise_exception=True)
def void_sample(request, pk):
    """Voids a sample, with the reason."""
    sample = get_object_or_404(WaterMeasurement.objects.select_related(*read.POINT_RELATED), pk=pk)
    back = _next(request, history_url(sample.point))
    context = _context(heading=_('Void water sample'), sample=sample, back_url=back,
                       values=[(parameters.get(code), value) for code, value in sample.values().items()])
    if request.method == 'POST':
        form = SampleVoidForm(request.POST)
        if form.is_valid():
            try:
                services.void(request.user, sample, form.cleaned_data['reason'],
                              withdrawal_ack=form.cleaned_data['withdrawal_ack'])
            except ValidationError as error:
                form.add_service_error(error)
            else:
                messages.success(request, _('Water sample of %(point)s voided.') % {'point': sample.point})
                return done(request, back)
        return _refused(request, 'farm/water_void.html', {**context, 'form': form})
    return render_page(request, 'farm/water_void.html', {**context, 'form': SampleVoidForm()})


# ---- Production units and the overview ------------------------------------------------------------------
def unit_water(user, units):
    """The latest water of each unit on Production units, by unit id (its Temp. and O₂ columns and its
    status dot): its middle point's (farm/water/read.py); nothing for a person who may not read the water."""
    if not user.has_perm(VIEW):
        return {}
    return read.unit_water(units)


def critical_count(water):
    return sum(1 for point_water in water.values() if point_water.status == Status.CRITICAL)


def _drawer_order(point_water):
    """A unit's readings in the registry's order, the ammonia worked out from TAN after it."""
    codes = []
    for parameter in MEASURED:
        codes.append(parameter.code)
        if parameter.code == parameters.TAN:
            codes += [NH3_N.code, parameters.NH4_N.code]
    return [point_water.get(code) for code in codes if point_water.get(code)]


def drawer(request, unit):
    """The Water section of a unit's drawer on Production units: the latest value of every parameter of its middle
    point with its age, status and limits, the values worked out from it, Record water sample and the unit's
    history."""
    if not request.user.has_perm(VIEW):
        return {}
    point_water = read.unit_water([unit])[unit.pk]
    return {
        'water_point': point_water, 'water_readings': _drawer_order(point_water),
        # the unit's Tank › Water (owner 2026-11-24); in the classic look that address redirects to the old history
        'water_history_url': reverse('farm:tank_water', args=[unit.pk]),
        'water_record_url': _dialog_url('farm:water_record', request, unit) if request.user.has_perm(RECORD) else '',
        'water_points_url': f'{reverse("farm:samplingpoint_list")}?{urlencode({"unit": unit.pk})}'
        if request.user.has_perm('farm.view_samplingpoint') else '',
    }


OVERVIEW_ALERTS = 6     # the alerting points the overview lists; the rest are a link to this page


def overview(user):
    """The production overview's water, read once as this page reads it (`_latest`: every point it lists, an outlet too), so
    the two cannot disagree: its counts of points, critical and warning points, the rows of the points with a critical or
    warning value measured at them (`point_status`, what the counts count), the critical first and each group in the page's
    order, at most OVERVIEW_ALERTS of them; the rows with a value that cannot be evaluated; and the tile of the points with
    a critical value. None for a person who may not read the water."""
    if not user.has_perm(VIEW):
        return None
    latest = _latest(None)
    # (a unit read at its system or nowhere is its own row, without a point: it is counted, so it is listed)
    alerting = [row for row in latest['rows'] if (row['point'] is not None or isinstance(row['owner'], Tank))
                and row['water'].point_status in ALERTS]
    alerting.sort(key=lambda row: row['water'].point_status != Status.CRITICAL)
    # The units that hold fish and have no water value at all inside the page's window (no row of theirs has a reading:
    # "Not measured" on this page): nothing is known about their water, which is not "nothing needs attention" (flow
    # fault M-20). Read from the page's own rows, so the overview and Water chemistry cannot disagree.
    rows_of = defaultdict(list)
    for row in latest['rows']:
        if isinstance(row['owner'], Tank):
            rows_of[row['owner']].append(row)
    stocked = {unit_id for unit_id, fish in unit_counts([unit.pk for unit in rows_of]).items() if fish > 0}
    unmeasured = [unit for unit, rows in rows_of.items()
                  if unit.pk in stocked and not any(row['water'].readings for row in rows)]
    return {'points': latest['point_count'], 'critical': latest['critical_count'], 'warning': latest['warning_count'],
            'unmeasured': unmeasured, 'window_days': read.WINDOW.days,
            # The rows whose judged value the chemistry core refuses to work out (PointWater.unevaluated: said on this
            # page beside the row's status): not "nothing needs attention" (the verification of 2026-11-18, V-A).
            'unevaluated': [row for row in latest['rows'] if row['point'] is not None and row['water'].unevaluated],
            'alerts': alerting[:OVERVIEW_ALERTS], 'more': max(len(alerting) - OVERVIEW_ALERTS, 0),
            'sensors_failed': latest['sensors_failed'], 'url': page_url(),
            'tiles': [{'label': _('Sampling points with a critical water value'), 'count': latest['critical_count'],
                       'url': page_url()}]}
