"""Operations › Water chemistry: the latest water of every unit and loop with its status, the history of
the samples with their values judged, the calculator with the Water Quality Management Chart, and the
dialogs that record a sample, a round or a void. A read page with dialogs, as Production units is
(farm/stock/views.py): each dialog renders in the shared dialog or as a page, posts to itself and goes
back where it was opened (`next`).

Who may do what (config/access.py, area Water chemistry): reading needs view on the samples (the
calculator too: it stores nothing), recording a sample or a round add, voiding one delete. The buttons a
person cannot use are not shown, and the views refuse them too. The page judges every value on read
(farm/water/read.py) and alerts nobody: critical values are shown, not sent."""
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.utils.translation import gettext as _, ngettext

from core import navigation
from core.crud import done, render_page

from ..forms.water import (CalculatorForm, RoundForm, RoundRowForm, RoundScopeForm, SampleVoidForm, WaterSampleForm,
                           find_point)
from ..models import Site, System, Tank, WaterMeasurement
from ..models.site import zone_of
from ..models.water import LIVE_POINT, local_time, site_of
from ..stock.services import AlreadyRecorded
from . import calculation, parameters, read, services
from .evaluate import ALERTS, Status
from .parameters import MEASURED, NH3_N

VIEW, RECORD, VOID = 'farm.view_watermeasurement', 'farm.add_watermeasurement', 'farm.delete_watermeasurement'
HISTORY = 'history'
PAGE_SIZE = 50
HISTORY_DAYS = 30      # the history's default span, back from today


def _context(**extra):
    place = navigation.place(VIEW)
    return {'title': place.entry.label, 'eyebrow': f'{place.section.label} · {place.entry.label}', **extra}


def page_url(**query):
    query = {key: value for key, value in query.items() if value}
    return reverse('farm:water') + (f'?{urlencode(query)}' if query else '')


def point_query(point):
    """The query string key and value of a unit's or a system's history."""
    return ('system', str(point.pk)) if isinstance(point, System) else ('unit', str(point.pk))


def history_url(point):
    return page_url(**dict([point_query(point)]))


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
    point = _point(request)
    showing_history = point is not None or request.GET.get('view') == HISTORY
    context = _context(
        sites=sites, site=site, point=point, showing_history=showing_history,
        latest_url=page_url(site=site.pk if site else ''),
        history_tab_url=page_url(view=HISTORY, site=site.pk if site else ''),
        calculator_url=reverse('farm:water_calculator'),
        can_record=request.user.has_perm(RECORD), can_void=request.user.has_perm(VOID),
        record_url=_dialog_url('farm:water_record', request, point),
        round_url=reverse('farm:water_round') + (f'?{urlencode({"site": site.pk})}' if site else ''),
    )
    context.update(_history(request, site, point) if showing_history else _latest(site))
    return render_page(request, 'farm/water.html', context)


def _dialog_url(name, request, point=None, args=()):
    """A dialog's address: it goes back to this page, and is about `point` when one is given."""
    query = {'next': request.get_full_path()}
    if point is not None:
        query.update([point_query(point)])
    return f'{reverse(name, args=args)}?{urlencode(query)}'


def _point(request):
    """The unit or system the address names (?unit= or ?system=), live; None when it names none."""
    if request.GET.get('unit'):
        return find_point(f"tank:{request.GET['unit']}")
    if request.GET.get('system'):
        return find_point(f"system:{request.GET['system']}")
    return None


def _latest(site):
    units = Tank.objects.select_related('production_department__site', 'system')
    systems = System.objects.select_related('site').filter(
        water_samples__is_deleted=False, water_samples__measured_at__gte=timezone.now() - read.WINDOW).distinct()
    if site is not None:
        units = units.filter(production_department__site=site)
        systems = systems.filter(site=site)
    points = [*units.order_by('production_department__site__name', 'production_department__name', 'code'),
              *systems.order_by('site__name', 'code')]
    water = read.latest(points)
    columns = _columns([water[read.key(point)].readings for point in points])
    rows = [{'point': point, 'loop': isinstance(point, System), 'water': water[read.key(point)],
             'history_url': history_url(point),
             'cells': [water[read.key(point)].get(parameter.code) for parameter in columns]}
            for point in points]
    counts = {status: sum(1 for row in rows if row['water'].status == status) for status in ALERTS}
    return {'rows': rows, 'columns': columns, 'critical_count': counts[Status.CRITICAL],
            'warning_count': counts[Status.WARNING], 'now': timezone.now()}


def _day(request, name, default):
    return parse_date(request.GET.get(name, '')) or default


def _history(request, site, point):
    zone = zone_of(site if point is None else site_of(point))
    today = timezone.localdate(timezone=zone)
    start, end = _day(request, 'from', today - timedelta(days=HISTORY_DAYS)), _day(request, 'to', today)
    samples = (WaterMeasurement.all_objects.filter(LIVE_POINT)
               .filter(measured_at__gte=timezone.make_aware(datetime.combine(start, time.min), zone),
                       measured_at__lt=timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min), zone))
               .select_related('unit__production_department__site', 'system__site', 'created_by', 'deleted_by'))
    if point is not None:
        samples = samples.filter(**{'system' if isinstance(point, System) else 'unit': point})
    elif site is not None:
        samples = samples.filter(Q(unit__production_department__site=site) | Q(system__site=site))
    rows = read.history(list(samples))
    alerts_only = request.GET.get('alerts') == '1'
    if alerts_only:
        rows = [row for row in rows if not row.sample.is_deleted and row.status in ALERTS]
    page = Paginator(rows, PAGE_SIZE).get_page(request.GET.get('page'))
    columns = _columns([row.readings for row in page.object_list])
    earliest = {}
    for row in page.object_list:
        sample = row.sample
        row.cells = [row.readings.get(parameter.code) for parameter in columns]
        if request.user.has_perm(VOID) and not sample.is_deleted:
            first = earliest.setdefault(read.key(sample.point), services.earliest(sample.point))
            if local_time(sample.measured_at, sample.point).date() >= first:
                row.void_url = _dialog_url('farm:water_void', request, args=[sample.pk])
    kept = request.GET.copy()
    kept.pop('page', None)
    return {'history': page.object_list, 'page': page, 'pager_query': kept.urlencode(), 'columns': columns,
            'start': start, 'end': end, 'alerts_only': alerts_only, 'zone': zone,
            'point_choices': _point_filter(site)}


def _point_filter(site):
    units = Tank.objects.order_by('code')
    systems = System.objects.order_by('code')
    if site is not None:
        units, systems = units.filter(production_department__site=site), systems.filter(site=site)
    return {'units': list(units), 'systems': list(systems)}


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
    point = find_point(chosen)
    if point is not None:
        CalculatorForm.fill(data, calculation.offers(point))
    data['loaded'] = chosen
    return data, True


def _source(form, point):
    """Where the values came from, field by field: what the point offers, whether the form still has it, its
    time and status; and the measured fields it has no value for."""
    offers = calculation.offers(point)
    entered = getattr(form, 'cleaned_data', {})
    rows = []
    for name, offer in offers.items():
        field = form.fields[name]
        value = None if offer.value is None else offer.value.quantize(Decimal(1).scaleb(-field.decimal_places))
        rows.append({'label': field.label, 'value': value, 'decimals': field.decimal_places, 'offer': offer,
                     'changed': entered.get(name) != value})
    missing = [form.fields[name].label for name in calculation.MEASURED_FIELDS if name not in offers]
    return {'point': point, 'rows': rows, 'missing': missing}


def _calculator_context(request, data, all_layers=False):
    """The form, the calculation (None while a value is wrong) and where the values came from."""
    form = CalculatorForm(data if data else None)
    result = None
    if not form.is_bound or form.is_valid():
        result = calculation.calculate(**form.inputs(), all_layers=all_layers)
    chosen = data.get('point', '') if data else ''
    point = find_point(chosen) if chosen else None
    query = data.urlencode() if data else ''
    return _context(
        form=form, result=result, analysis=result.analysis if result else None,
        chart=result.chart if result else None, source=_source(form, point) if point is not None else None,
        point_gone=bool(chosen) and point is None, query=query,
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
    return render(request, 'farm/water_calculator_report.html', context)


# ---- the dialogs ---------------------------------------------------------------------------------------
@permission_required(RECORD, raise_exception=True)
def record_sample(request):
    """Record water sample: at the unit or loop named in the address (from the unit drawer or a history),
    else at the unit or system chosen."""
    point = _point(request)
    back = _next(request, history_url(point) if point is not None else page_url())
    limits = read.limits_now(point) if point is not None else {}
    context = _context(heading=_('Record water sample'), point=point, back_url=back)
    if request.method == 'POST':
        form = WaterSampleForm(request.POST, point=point, limits=limits)
        if form.is_valid():
            try:
                sample = form.save(request.user)
            except AlreadyRecorded:
                return done(request, back)
            except ValidationError as error:
                form.add_service_error(error)
            else:
                messages.success(request, _('Water sample recorded at %(point)s.') % {'point': sample.point.code})
                return done(request, back)
        return _refused(request, 'farm/water_record.html', {**context, 'form': form})
    form = WaterSampleForm(point=point, limits=limits)
    return render_page(request, 'farm/water_record.html', {**context, 'form': form})


@permission_required(RECORD, raise_exception=True)
def record_round(request):
    """A round: the units (and loops) of a site, a production department or a system, one row each, at one
    time and from one source. Empty rows are skipped; the rest are recorded together or not at all."""
    scope = RoundScopeForm(request.GET)
    site, department, system, columns = scope.scope()
    points = scope.points(site, department, system)
    if len(points) > services.ROUND_ROWS:
        points = []
        scope.add_error(None, _('More than %(rows)d units and systems: choose a production department or a system.')
                        % {'rows': services.ROUND_ROWS})
    data = request.POST if request.method == 'POST' else None
    header = RoundForm(data, site=site)
    rows = [RoundRowForm(data, point=point, columns=columns) for point in points]
    context = _context(heading=_('Water round'), scope=scope, header=header, rows=rows,
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
                    rows=[(row.point, row.entered(), row.cleaned_data['notes']) for row in entered])
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
    """The service's reasons on the round: a cell's on its row and parameter, the time on the header."""
    for key, messages_ in error.message_dict.items():
        index, _sep, code = key.partition('-')
        if code and index.isdigit():
            entered[int(index)].add_service_error(code, messages_)
        else:
            header.add_error(key if key in header.fields and key != NON_FIELD_ERRORS else None, messages_)


@permission_required(VOID, raise_exception=True)
def void_sample(request, pk):
    """Voids a sample, with the reason."""
    sample = get_object_or_404(WaterMeasurement.objects.select_related(
        'unit__production_department__site', 'system__site'), pk=pk)
    back = _next(request, history_url(sample.point))
    context = _context(heading=_('Void water sample'), sample=sample, back_url=back,
                       values=[(parameters.get(code), value) for code, value in sample.values().items()])
    if request.method == 'POST':
        form = SampleVoidForm(request.POST)
        if form.is_valid():
            try:
                services.void(request.user, sample, form.cleaned_data['reason'])
            except ValidationError as error:
                form.add_service_error(error)
            else:
                messages.success(request, _('Water sample of %(point)s voided.') % {'point': sample.point.code})
                return done(request, back)
        return _refused(request, 'farm/water_void.html', {**context, 'form': form})
    return render_page(request, 'farm/water_void.html', {**context, 'form': SampleVoidForm()})


# ---- Production units and the overview ------------------------------------------------------------------
def unit_water(user, units):
    """The latest water of each unit on Production units, by unit id (its Temp. and O₂ columns and its
    status dot); nothing for a person who may not read the water."""
    if not user.has_perm(VIEW):
        return {}
    water = read.latest(units)
    return {unit.pk: water[read.key(unit)] for unit in units}


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
    """The Water section of a unit's drawer on Production units: the latest value of every parameter with its
    age, status and limits, the values worked out from it, Record water sample and the unit's history."""
    if not request.user.has_perm(VIEW):
        return {}
    point_water = read.latest([unit])[read.key(unit)]
    return {
        'water_point': point_water, 'water_readings': _drawer_order(point_water),
        'water_history_url': history_url(unit),
        'water_record_url': _dialog_url('farm:water_record', request, unit) if request.user.has_perm(RECORD) else '',
    }


def overview_tiles(user):
    """The production overview's water figure: the units with a critical water value now."""
    if not user.has_perm(VIEW):
        return []
    units = list(Tank.objects.select_related('production_department__site'))
    return [{'label': _('Units with a critical water value'), 'count': critical_count(unit_water(user, units)),
             'url': page_url()}]
