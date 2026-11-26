"""Operations › Harvest: the harvests recorded (Harvested), with the book against the scale and totals per
batch and site; the strip that joins it to the plans (Harvest plan, Production plans: farm/resources/
harvest_plan.py); and what Production units shows of harvest and handling (the drawer's part, the row badge).

A read page, as Feeding records is: filters in the address, 50 rows a page, voided harvests on request.
Recording a harvest stays the stock's dialog (a unit's drawer, or a plan's "Record harvest"); voiding one is
the stock's void. Who may do what: reading needs view on the harvest records (config/access.py, area
Harvested); the void link needs the stock's void permission."""
from urllib.parse import urlencode

from django.contrib.auth.decorators import permission_required
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.translation import gettext as _, ngettext

from core import navigation
from core.crud import render_page
from core.dates import read_day
from core.ui import is_next

from ..handling import check, fasting
from ..models import (
    Batch, HandlingPlanItem, ProductionDepartment, ProductionPlan, SlaughterFacility, Site, Species, StockMovement,
    Tank,
)
from ..models.handling import HandlingKind
from ..models.stock import MovementKind
from ..stock import read as stock_read
from ..stock.dates import earliest, local_today
from . import forecast, read

VIEW = 'farm.view_harvestrecord'
PLAN, TARGETS = 'farm.view_handlingplanitem', 'farm.view_productionplan'
VOID = 'farm.delete_stockoperation'
FILTERS = ('site', 'department', 'unit', 'batch', 'species', 'facility', 'from', 'to', 'voided')
PAGE_SIZE = 50


def tabs(request, current):
    """The strip of the Harvest group's pages the person may read: Harvested, Harvest plan, Production plans."""
    pages = [('harvested', VIEW, 'farm:harvests'), ('plan', PLAN, 'farm:handlingplanitem_list'),
             ('targets', TARGETS, 'farm:productionplan_list')]
    return [{'label': navigation.place(perm).entry.label, 'url': reverse(url_name), 'current': key == current}
            for key, perm, url_name in pages if request.user.has_perm(perm)]


def _context(**extra):
    place = navigation.place(VIEW)
    return {'title': place.entry.label, 'eyebrow': f'{place.section.label} · {place.group.label}', **extra}


def _filtered(params, request):
    """The harvest lines the filters choose, newest first, voided ones only when asked for; and the filters'
    choices. A value that names nothing there is dropped (a stale link shows everything)."""
    lines = StockMovement.objects.filter(kind=MovementKind.HARVEST).order_by('-operation__date',
                                                                             '-operation__created_at')
    if params['voided'] != '1':
        params['voided'] = ''
        lines = lines.filter(operation__is_deleted=False)
    harvested = StockMovement.objects.filter(kind=MovementKind.HARVEST)
    choices = {
        'site': Site.all_objects.filter(production_departments__tanks__movements__in=harvested).distinct()
        .order_by('name'),
        'department': ProductionDepartment.all_objects.filter(tanks__movements__in=harvested).distinct()
        .order_by('name'),
        'unit': Tank.all_objects.filter(movements__in=harvested).distinct().order_by('code'),
        'batch': Batch.all_objects.filter(movements__in=harvested).distinct().order_by('-input_date', '-code'),
        'species': Species.all_objects.filter(batches__movements__in=harvested).distinct().order_by('common_name'),
        'facility': SlaughterFacility.all_objects.filter(harvests__isnull=False).distinct().order_by('name'),
    }
    lookups = {'site': 'unit__production_department__site', 'department': 'unit__production_department',
               'unit': 'unit', 'batch': 'batch', 'species': 'batch__species',
               'facility': 'operation__harvest_record__facility'}
    choices = {key: list(found) for key, found in choices.items()}   # each list read once: offered and checked
    for key, lookup in lookups.items():
        if params[key] in {str(choice.pk) for choice in choices[key]}:
            lines = lines.filter(**{lookup: params[key]})
        else:
            params[key] = ''
    for key, lookup in (('from', 'operation__date__gte'), ('to', 'operation__date__lte')):
        day = read_day(params[key], request)
        params[key] = day or ''          # a date: the input shows it as the language writes it
        if day:
            lines = lines.filter(**{lookup: day})
    return lines, choices


@permission_required(VIEW, raise_exception=True)
def harvests(request):
    """Operations › Harvest › Harvested: one row per harvest, the book against the scale, totals per batch
    and per site of the rows the filters choose."""
    params = {key: request.GET.get(key, '').strip() for key in FILTERS}
    lines, choices = _filtered(params, request)
    # The totals count every live harvest chosen (one fold); the page is cut in the database and only its rows are built.
    live, moved = read.summary(lines)
    page = Paginator(read.with_related(lines), PAGE_SIZE).get_page(request.GET.get('page'))
    page.object_list = read.harvests(page.object_list, moved)
    can_void = request.user.has_perm(VOID)
    here = request.get_full_path()
    kept = {key: value for key, value in params.items() if value}
    context = _context(
        rows=[{'harvest': row,
               'void_url': f'{reverse("farm:stock_void", args=[row.operation.pk])}?{urlencode({"next": here})}'
               if can_void and not row.operation.is_deleted and row.operation.date >= earliest(row.unit) else ''}
              for row in page.object_list],
        page=page, pager_query=urlencode(kept), params=params, choices=choices,
        count_line=ngettext('%(count)d harvest', '%(count)d harvests', len(live)) % {'count': len(live)},
        grand=next(iter(read.totals(live, key=lambda row: 'all', label=lambda row: '')), None),
        by_batch=read.totals(live, key=lambda row: row.batch.pk, label=lambda row: row.batch.code),
        by_site=read.totals(live, key=lambda row: row.site.pk if row.site else None,
                            label=lambda row: row.site.name if row.site else _('No site')),
        filtered=bool({key for key in kept if key != 'voided'}),
        clear_url=reverse('farm:harvests'), tabs=tabs(request, 'harvested'),
    )
    if is_next(request):
        # the new look: the shared list page (farm/harvest/pages.py) under the strip of the Harvest group's pages
        from .pages import harvests_props
        return render_page(request, 'crud/list_next.html', {**context, 'group': context['eyebrow'],
                                                            'props': harvests_props(request, context),
                                                            'list_above': 'farm/_harvest_tabs.html'})
    return render_page(request, 'farm/harvests.html', context)


# ---- what Production units shows ---------------------------------------------------------------------
def drawer(request, unit, stock):
    """The Harvest part of a stocked unit's drawer: the handling check of a harvest today (last fed, the rule,
    a medicine withdrawal) and the unit's open plans with the fast each asks for."""
    if stock is None:
        return {}
    today = local_today(unit)
    context = {'handling': check.assess(HandlingKind.HARVEST, unit, today)}
    if request.user.has_perm(PLAN):
        items = (HandlingPlanItem.objects.filter(unit=unit).select_related('batch__species', 'facility',
                                                                            'destination_unit', 'operation')
                 .order_by('date'))
        context['unit_plans'] = [{'item': item, 'status': item.status_on(today), 'fast': fasting.fast_of(item)}
                                 for item in items if item.is_open]
        context['plan_list_url'] = f'{reverse("farm:handlingplanitem_list")}?{urlencode({"unit": unit.pk})}'
    return context



# ---- a batch's growth plan ------------------------------------------------------------------------------
@permission_required(TARGETS, raise_exception=True)
def production_plan(request, unit_pk, batch_pk):
    """Operations › Harvest › Production plans › Growth plan: a batch in a unit, its plan ahead from today's estimate or
    (`?from=` a day) from a measured point, the measured weights beside it, and every day as a file (`?format=csv`).
    Read with the production plans' right. The page's words and the file are farm/harvest/plan_page.py's."""
    from . import plan_page
    unit = get_object_or_404(Tank.objects.select_related('production_department__site'), pk=unit_pk)
    stock = stock_read.stock_of([unit]).get(unit.pk)
    share = next((each for each in (stock.counted if stock is not None else ()) if each.batch.pk == batch_pk), None)
    if share is None:
        raise Http404
    target = ProductionPlan.objects.filter(batch=share.batch).first()
    target_g = target.target_weight_g if target is not None else None
    found = forecast.plan(unit, share, target_g, read_day(request.GET.get('from', '')))
    if found is None:
        raise Http404
    if request.GET.get('format') == 'csv':
        return plan_page.csv_response(unit, share.batch, found)
    place = navigation.place(TARGETS)
    url = reverse('farm:production_plan', args=[unit.pk, share.batch.pk])
    kept = {'from': found.chosen.day.isoformat()} if found.chosen is not None else {}
    context = {
        'title': _('Growth plan · %(unit)s · %(batch)s') % {'unit': unit.code, 'batch': share.batch.code},
        'eyebrow': f'{place.section.label} · {place.group.label} · {place.entry.label}',
        'unit': unit, 'batch': share.batch, 'target_g': target_g, 'plan': found, 'url': url,
        'csv_url': f"{url}?{urlencode({**kept, 'format': 'csv'})}", 'back_url': reverse('farm:productionplan_list'),
        'tabs': tabs(request, 'targets'),
    }
    context['props'] = plan_page.props(request, context)
    if is_next(request):
        return render_page(request, 'crud/list_next.html', {**context, 'group': context['eyebrow'],
                                                            'list_above': 'farm/_harvest_tabs.html'})
    return render_page(request, 'farm/production_plan.html', context)
