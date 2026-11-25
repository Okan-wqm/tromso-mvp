"""Operations › Treatments and Operations › Sea-lice counts: read pages with their dialogs, as Feeding records
is (farm/feeding/views.py): each dialog renders in the shared dialog or as a page, posts to itself, shows the
server's reasons on their fields (422) and goes back where it was opened (`next`). The health events are a tab
(farm/resources/health_event.py); their void is here. A unit's drawer on Production units shows its health
(`drawer`) and every row the withdrawal line (`unit_withdrawals`).

Who may do what (config/access.py): reading a page needs view on its records, recording add, voiding delete;
a treatment's last day is changed with change. The buttons a person cannot use are not shown, and the views
refuse them too. The withdrawal line is shown to everyone who sees the units: it is food safety."""
from datetime import timedelta
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _, ngettext

from core import navigation
from core.crud import done, render_page
from core.dates import read_day
from core.ui import is_next
from core.platform import unknown_withdrawal_days

from ..forms.health import LastDayForm, LiceCountForm, TreatmentForm
from ..forms.stock import VoidForm
from ..models import Batch, HealthEvent, LiceCount, Medicine, Site, Tank, Treatment
from ..models.health import MedicineKind
from ..stock import read as stock_read, views as stock_views
from ..stock.dates import earliest, shown_date
from ..stock.services import AlreadyRecorded
from . import notices, pages, read, services, withdrawal

TREATMENTS = {'view': 'farm.view_treatment', 'add': 'farm.add_treatment', 'change': 'farm.change_treatment',
              'delete': 'farm.delete_treatment'}
COUNTS = {'view': 'farm.view_licecount', 'add': 'farm.add_licecount', 'delete': 'farm.delete_licecount'}
EVENTS = {'view': 'farm.view_healthevent', 'add': 'farm.add_healthevent', 'delete': 'farm.delete_healthevent'}
PAGE_SIZE = 50
LICE_WEEKS = 12        # the weeks of site averages the lice page shows
UNDER_WITHDRAWAL, VACCINATIONS = 'withdrawal', 'vaccinations'


def _context(perm, **extra):
    place = navigation.place(perm)
    return {'title': place.entry.label, 'eyebrow': f'{place.section.label} · {place.group.label}', **extra}


def _back(request, default):
    """Where a dialog goes back to: the page it was opened from (`next`, a local address), else `default`."""
    target = request.GET.get('next', '')
    if target.startswith('/') and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        return target
    return default


def _page(request, template, context, props):
    """The classic page, or in the new look (core.ui.is_next) the shared list page with the props of farm/health/pages.py
    (`props`: their builder, given the request and the classic page's context)."""
    if is_next(request):
        return render_page(request, 'crud/list_next.html', {**context, 'group': context['eyebrow'],
                                                            'props': props(request, context)})
    return render_page(request, template, context)


def dialog_url(name, back, unit=None, args=()):
    """A dialog's address that comes back to `back` (and chooses `unit`)."""
    query = {'next': back, **({'unit': str(unit.pk)} if unit is not None else {})}
    return f'{reverse(name, args=args)}?{urlencode(query)}'


def _units_with_fish(site=None, production=False):
    """The live units a treatment or a sea-lice count can be recorded for (of `site` when given), in code order: those
    holding fish now, and those whose fish left on a day that may still be dated (inside the correction window:
    farm.stock.read.left_within, flow fault S-04: a course given before the harvest that emptied the unit must still be
    enterable, or the harvest inside its withdrawal is never found). The service checks the fish on the record's own
    day. With `production`, units of production fish (a cage of cleaner fish alone is not counted for lice: the count is
    of the salmonids)."""
    units = Tank.objects.select_related('production_department__site').order_by('code')
    if site is not None:
        units = units.filter(production_department__site=site)
    units = list(units)
    stock = stock_read.stock_of(units)
    held = {pk for pk, unit_stock in stock.items() if unit_stock.count > 0 or not production}
    held |= set(stock_read.left_within([unit for unit in units if unit.pk not in held], earliest, production))
    return Tank.objects.filter(pk__in=held).select_related('production_department__site').order_by('code')


def _chosen_unit(request):
    chosen = request.GET.get('unit', '')
    return Tank.objects.select_related('production_department__site').filter(pk=chosen).first() \
        if stock_views._is_uuid(chosen) else None


# ---- treatments ---------------------------------------------------------------------------------------
TREATMENT_FILTERS = ('site', 'unit', 'batch', 'method', 'medicine', 'from', 'to', 'show', 'voided')


def _filtered_treatments(params, request):
    treatments = Treatment.all_objects.select_related('medicine', 'vet', 'health_event', 'created_by', 'deleted_by')\
        .prefetch_related('units__production_department__site', 'acknowledgements')
    if params['voided'] != '1':
        params['voided'] = ''
        treatments = treatments.filter(is_deleted=False)
    choices = {
        # Through the treatments the person may see (core.sealing), never a join that reaches a sealed one.
        'site': Site.objects.filter(pk__in=Treatment.objects.values('units__production_department__site'))
        .order_by('name'),
        'unit': Tank.all_objects.filter(pk__in=Treatment.objects.values('units')).order_by('code'),
        'medicine': Medicine.all_objects.filter(pk__in=Treatment.objects.values('medicine')).order_by('name'),
        'batch': Batch.objects.order_by('-input_date', '-code'),
        'method': Treatment.Method.choices,
    }
    for key, lookup in (('site', 'units__production_department__site'), ('unit', 'units'), ('medicine', 'medicine')):
        if params[key] in {str(pk) for pk in choices[key].values_list('pk', flat=True)}:
            treatments = treatments.filter(**{lookup: params[key]}).distinct()
        else:
            params[key] = ''
    if params['method'] in Treatment.Method.values:
        treatments = treatments.filter(method=params['method'])
    else:
        params['method'] = ''
    for key, lookup in (('from', 'end_date__gte'), ('to', 'start_date__lte')):
        day = read_day(params[key], request)
        params[key] = day or ''          # a date: the input shows it as the language writes it
        if day:
            treatments = treatments.filter(**{lookup: day})
    if params['show'] == VACCINATIONS:
        treatments = treatments.filter(medicine__kind=MedicineKind.VACCINE)
    elif params['show'] != UNDER_WITHDRAWAL:
        params['show'] = ''
    batch = choices['batch'].filter(pk=params['batch']).first() if stock_views._is_uuid(params['batch']) else None
    params['batch'] = str(batch.pk) if batch else ''
    if batch is not None or params['show'] == UNDER_WITHDRAWAL:
        candidates = list(treatments)
        rows = withdrawal.of_treatments(candidates)
        keep = [treatment.pk for treatment in candidates
                if (batch is None or any(part.batch.pk == batch.pk for part in rows[treatment.pk]))
                # held today: on today of the site the fish are on (withdrawal.of_treatments)
                and (params['show'] != UNDER_WITHDRAWAL or any(part.held for part in rows[treatment.pk]))]
        treatments = treatments.filter(pk__in=keep)
    return treatments, choices


@permission_required(TREATMENTS['view'], raise_exception=True)
def treatments(request):
    """Operations › Treatments: every treatment, newest first, with the batches it reached and the withdrawal
    it puts on each, filtered in the address."""
    params = {key: request.GET.get(key, '').strip() for key in TREATMENT_FILTERS}
    found, choices = _filtered_treatments(params, request)
    page = Paginator(found, PAGE_SIZE).get_page(request.GET.get('page'))
    rows = list(page.object_list)
    batches = withdrawal.of_treatments(rows)
    here = request.get_full_path()
    can_void, can_change = request.user.has_perm(TREATMENTS['delete']), request.user.has_perm(TREATMENTS['change'])
    kept = {key: value for key, value in params.items() if value}
    return _page(request, 'farm/treatment_list.html', _context(
        TREATMENTS['view'],
        rows=[{'treatment': treatment, 'batches': batches[treatment.pk],
               'void_url': dialog_url('farm:treatment_void', here, args=[treatment.pk]) if can_void else '',
               'last_day_url': dialog_url('farm:treatment_last_day', here, args=[treatment.pk])
               if can_change and not treatment.is_deleted else ''}
              for treatment in rows],
        page=page, pager_query=urlencode(kept), params=params, choices=choices,
        count_line=ngettext('%(count)d treatment', '%(count)d treatments', page.paginator.count) % {
            'count': page.paginator.count},
        filtered=bool({key for key in kept if key != 'voided'}),
        clear_url=reverse('farm:treatments'),
        record_url=dialog_url('farm:treatment_record', here) if request.user.has_perm(TREATMENTS['add']) else '',
        under_withdrawal=UNDER_WITHDRAWAL, vaccinations=VACCINATIONS,
        # The courses whose unknown end has stopped holding fish (withdrawal rule 8), with what gives each an end.
        unresolved=[withdrawal.unresolved_text(batch, held) for batch, held in withdrawal.unresolved()],
        unknown_days=unknown_withdrawal_days(),
    ), pages.treatments_props)


@permission_required(TREATMENTS['add'], raise_exception=True)
def record_treatment(request):
    """Record treatment: from the list (the units with fish), or from a unit's drawer (that unit ticked, the
    units of its site offered)."""
    unit = _chosen_unit(request)
    units = _units_with_fish(unit.production_department.site if unit is not None and
                             unit.production_department.site else None)
    back = _back(request, reverse('farm:treatments'))
    context = _context(TREATMENTS['view'], heading=_('Record treatment'), back_url=back, unit=unit)
    if request.method == 'POST':
        form = TreatmentForm(request.POST, units=units, unit=unit)
        if form.is_valid():
            try:
                treatment = form.save(request.user)
            except AlreadyRecorded:
                return done(request, back)
            except ValidationError as error:
                form.add_service_error(error)
            else:
                messages.success(request, _('Treatment recorded: %(what)s in %(units)s from %(start)s to %(end)s.') % {
                    'what': treatment.medicine or treatment.get_method_display(),
                    'units': ', '.join(each.code for each in treatment.units.order_by('code')),
                    'start': shown_date(treatment.start_date), 'end': shown_date(treatment.end_date)})
                return done(request, back)
        return stock_views._refused(request, 'farm/treatment_form.html', {**context, 'form': form})
    return render_page(request, 'farm/treatment_form.html', {**context, 'form': TreatmentForm(units=units, unit=unit)})


@permission_required(TREATMENTS['change'], raise_exception=True)
def change_last_day(request, pk):
    """The last day of a course, changed: it ended earlier, or goes on longer."""
    treatment = get_object_or_404(Treatment.objects.select_related('medicine'), pk=pk)
    back = _back(request, reverse('farm:treatments'))
    context = _context(TREATMENTS['view'], heading=_('Change the last day'), back_url=back, treatment=treatment)
    if request.method == 'POST':
        form = LastDayForm(request.POST, treatment=treatment)
        if form.is_valid():
            try:
                form.save(request.user)
            except ValidationError as error:
                form.add_service_error(error)
            else:
                messages.success(request, _('The last day of the treatment is now %(date)s.') % {
                    'date': shown_date(form.cleaned_data['end_date'])})
                return done(request, back)
        return stock_views._refused(request, 'farm/treatment_last_day.html', {**context, 'form': form})
    return render_page(request, 'farm/treatment_last_day.html', {**context, 'form': LastDayForm(treatment=treatment)})


@permission_required(TREATMENTS['delete'], raise_exception=True)
def void_treatment(request, pk):
    """Voids a treatment, with the reason: its withdrawal is lifted."""
    treatment = get_object_or_404(Treatment.objects.select_related('medicine'), pk=pk)
    back = _back(request, reverse('farm:treatments'))
    context = _context(TREATMENTS['view'], heading=_('Void treatment'), back_url=back, treatment=treatment)
    if request.method == 'POST':
        form = VoidForm(request.POST)
        if form.is_valid():
            try:
                services.void_treatment(request.user, treatment, form.cleaned_data['reason'],
                                        withdrawal_ack=form.cleaned_data['withdrawal_ack'])
            except ValidationError as error:
                form.add_service_error(error)
            else:
                messages.success(request, _('Treatment of %(date)s voided.') % {
                    'date': shown_date(treatment.start_date)})
                return done(request, back)
        return stock_views._refused(request, 'farm/treatment_void.html', {**context, 'form': form})
    return render_page(request, 'farm/treatment_void.html', {**context, 'form': VoidForm()})


# ---- sea-lice counts ----------------------------------------------------------------------------------
COUNT_FILTERS = ('site', 'unit', 'from', 'to', 'voided')


def _filtered_counts(params, request):
    counts = LiceCount.all_objects.select_related('unit__production_department__site', 'created_by', 'deleted_by')
    if params['voided'] != '1':
        params['voided'] = ''
        counts = counts.filter(is_deleted=False)
    choices = {
        # Through the lice counts the person may see (core.sealing).
        'site': Site.objects.filter(pk__in=LiceCount.objects.values('unit__production_department__site'))
        .order_by('name'),
        'unit': Tank.all_objects.filter(pk__in=LiceCount.objects.values('unit')).order_by('code'),
    }
    for key, lookup in (('site', 'unit__production_department__site'), ('unit', 'unit')):
        if params[key] in {str(pk) for pk in choices[key].values_list('pk', flat=True)}:
            counts = counts.filter(**{lookup: params[key]})
        else:
            params[key] = ''
    for key, lookup in (('from', 'date__gte'), ('to', 'date__lte')):
        day = read_day(params[key], request)
        params[key] = day or ''          # a date: the input shows it as the language writes it
        if day:
            counts = counts.filter(**{lookup: day})
    return counts, choices



def _site_weeks(params):
    """The weekly table: each site's average over every cage counted that week (Vedlegg 1 point 6) and its badge. The
    filters choose which sites and weeks are shown (a unit filter: its site; a date range: the weeks it touches), never
    which counts make an average: one cage's average is not the site's (audit F-082)."""
    counts = LiceCount.objects.all()
    if params['unit']:
        unit = Tank.all_objects.select_related('production_department').get(pk=params['unit'])
        site_id = unit.production_department.site_id
        counts = counts.filter(unit__production_department__site=site_id) if site_id else counts.filter(unit=unit)
    elif params['site']:
        counts = counts.filter(unit__production_department__site=params['site'])
    first, last = params['from'] or None, params['to'] or None     # dates already: _filtered_counts read them (read_day)
    if first:
        counts = counts.filter(date__gte=first - timedelta(days=first.weekday()))          # its week's Monday
    if last:
        counts = counts.filter(date__lte=last + timedelta(days=6 - last.weekday()))      # its week's Sunday
    return read.lice_weeks(counts)


@permission_required(COUNTS['view'], raise_exception=True)
def lice_counts(request):
    """Operations › Sea-lice counts: the site's weekly averages against the statutory limit, then every count."""
    params = {key: request.GET.get(key, '').strip() for key in COUNT_FILTERS}
    counts, choices = _filtered_counts(params, request)       # first: it reads the dates (read_day) and the choices
    weeks = _site_weeks(params)[:LICE_WEEKS]
    stocked = read.stocked_by_site(_units_with_fish(production=True))
    for week in weeks:
        week.stocked = stocked.get(week.site.pk if week.site else None, 0)
    page = Paginator(counts, PAGE_SIZE).get_page(request.GET.get('page'))
    here = request.get_full_path()
    can_void = request.user.has_perm(COUNTS['delete'])
    kept = {key: value for key, value in params.items() if value}
    return _page(request, 'farm/lice_list.html', _context(
        COUNTS['view'], weeks=weeks, weeks_shown=LICE_WEEKS,
        rows=[{'count': count, 'void_url': dialog_url('farm:lice_void', here, args=[count.pk]) if can_void else ''}
              for count in page.object_list],
        page=page, pager_query=urlencode(kept), params=params, choices=choices,
        count_line=ngettext('%(count)d count', '%(count)d counts', page.paginator.count) % {
            'count': page.paginator.count},
        filtered=bool({key for key in kept if key != 'voided'}),
        clear_url=reverse('farm:lice_counts'),
        record_url=dialog_url('farm:lice_record', here) if request.user.has_perm(COUNTS['add']) else '',
    ), pages.lice_props)


@permission_required(COUNTS['add'], raise_exception=True)
def record_lice_count(request):
    """Record a sea-lice count, of a unit with fish (the drawer's unit chosen)."""
    unit = _chosen_unit(request)
    units = _units_with_fish(production=True)
    back = _back(request, reverse('farm:lice_counts'))
    context = _context(COUNTS['view'], heading=_('Record sea-lice count'), back_url=back, unit=unit)
    if request.method == 'POST':
        form = LiceCountForm(request.POST, units=units, unit=unit)
        if form.is_valid():
            try:
                count = form.save(request.user)
            except AlreadyRecorded:
                return done(request, back)
            except ValidationError as error:
                form.add_service_error(error)
            else:
                messages.success(request, _('Sea-lice count recorded: %(unit)s on %(date)s.') % {
                    'unit': count.unit.code, 'date': shown_date(count.date)})
                return done(request, back)
        return stock_views._refused(request, 'farm/lice_form.html', {**context, 'form': form})
    return render_page(request, 'farm/lice_form.html', {**context, 'form': LiceCountForm(units=units, unit=unit)})


@permission_required(COUNTS['delete'], raise_exception=True)
def void_lice_count(request, pk):
    count = get_object_or_404(LiceCount.objects.select_related('unit'), pk=pk)
    back = _back(request, reverse('farm:lice_counts'))
    context = _context(COUNTS['view'], heading=_('Void sea-lice count'), back_url=back, count=count)
    if request.method == 'POST':
        form = VoidForm(request.POST)
        if form.is_valid():
            try:
                services.void_lice_count(request.user, count, form.cleaned_data['reason'])
            except ValidationError as error:
                form.add_service_error(error)
            else:
                messages.success(request, _('Sea-lice count of %(date)s in %(unit)s voided.') % {
                    'date': shown_date(count.date), 'unit': count.unit.code})
                return done(request, back)
        return stock_views._refused(request, 'farm/lice_void.html', {**context, 'form': form})
    return render_page(request, 'farm/lice_void.html', {**context, 'form': VoidForm()})


# ---- health events ------------------------------------------------------------------------------------
@permission_required(EVENTS['delete'], raise_exception=True)
def void_event(request, pk):
    """Voids a health event recorded by mistake, with the reason."""
    event = get_object_or_404(HealthEvent.objects.select_related('site'), pk=pk)
    back = _back(request, reverse('farm:healthevent_list'))
    context = _context(EVENTS['view'], heading=_('Void health event'), back_url=back, event=event)
    if request.method == 'POST':
        form = VoidForm(request.POST)
        if form.is_valid():
            try:
                services.void_event(request.user, event, form.cleaned_data['reason'])
            except ValidationError as error:
                form.add_service_error(error)
            else:
                messages.success(request, _('Health event “%(event)s” voided.') % {'event': event})
                return done(request, back)
        return stock_views._refused(request, 'farm/health_event_void.html', {**context, 'form': form})
    return render_page(request, 'farm/health_event_void.html', {**context, 'form': VoidForm()})


# ---- what Production units shows --------------------------------------------------------------------
def drawer(request, unit, back):
    """The Health part of a unit's drawer, for people who may read them: its open health events, its treatments of
    the last RECENT_DAYS days, its latest sea-lice count, and the dialogs with the unit chosen. The withdrawal of
    its fish is the drawer's Harvest and handling section (the registry, farm/handling)."""
    user = request.user
    context = {}
    shown = False
    if user.has_perm(TREATMENTS['view']):
        context['health_treatments'] = read.recent_treatments([unit])[unit.pk]
        context['health_treatments_url'] = f'{reverse("farm:treatments")}?{urlencode({"unit": unit.pk})}'
        shown = True
    if user.has_perm(EVENTS['view']):
        context['health_events'] = read.open_events([unit])[unit.pk]
        context['health_notify'] = {event.pk for event in notices.pending(context['health_events']) or []}
        shown = True
    if user.has_perm(COUNTS['view']):
        context['health_lice'] = read.latest_counts([unit.pk]).get(unit.pk)
        shown = True
    actions = []
    if user.has_perm(TREATMENTS['add']):
        actions.append({'label': _('Record treatment'), 'url': dialog_url('farm:treatment_record', back, unit)})
    if user.has_perm(COUNTS['add']):
        actions.append({'label': _('Record sea-lice count'), 'url': dialog_url('farm:lice_record', back, unit)})
    if user.has_perm(EVENTS['add']):
        actions.append({'label': _('Record health event'),
                        'url': f'{reverse("farm:healthevent_create")}?{urlencode({"unit": unit.pk})}'})
    context.update(health_shown=shown, health_actions=actions)
    return context
