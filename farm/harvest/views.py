"""Operations › Harvest: the harvests recorded (Harvested), with the book against the scale and totals per
batch and site; the strip that joins it to the plans (Harvest plan, Production plans: farm/resources/
harvest_plan.py); and what Production units shows of harvest and handling (the drawer's part, the row badge).

A read page, as Feeding records is: filters in the address, 50 rows a page, voided harvests on request.
Recording a harvest stays the stock's dialog (a unit's drawer, or a plan's "Record harvest"); voiding one is
the stock's void. Who may do what: reading needs view on the harvest records (config/access.py, area
Harvested); the void link needs the stock's void permission."""
from datetime import date
from urllib.parse import urlencode

from django.contrib.auth.decorators import permission_required
from django.core.paginator import Paginator
from django.urls import reverse
from django.utils.translation import gettext as _, ngettext

from core import navigation
from core.crud import render_page

from ..handling import check, fasting
from ..models import (
    Batch, HandlingPlanItem, ProductionDepartment, SlaughterFacility, Site, Species, StockMovement, Tank,
)
from ..models.handling import HandlingKind
from ..models.stock import MovementKind
from ..stock.dates import earliest, local_today
from . import read

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


def _day(value):
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _filtered(params):
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
    for key, lookup in lookups.items():
        if params[key] in {str(pk) for pk in choices[key].values_list('pk', flat=True)}:
            lines = lines.filter(**{lookup: params[key]})
        else:
            params[key] = ''
    for key, lookup in (('from', 'operation__date__gte'), ('to', 'operation__date__lte')):
        day = _day(params[key])
        params[key] = day.isoformat() if day else ''
        if day:
            lines = lines.filter(**{lookup: day})
    return lines, choices


@permission_required(VIEW, raise_exception=True)
def harvests(request):
    """Operations › Harvest › Harvested: one row per harvest, the book against the scale, totals per batch
    and per site of the rows the filters choose."""
    params = {key: request.GET.get(key, '').strip() for key in FILTERS}
    lines, choices = _filtered(params)
    rows = read.harvests(lines)
    live = [row for row in rows if not row.operation.is_deleted]
    page = Paginator(rows, PAGE_SIZE).get_page(request.GET.get('page'))
    can_void = request.user.has_perm(VOID)
    here = request.get_full_path()
    kept = {key: value for key, value in params.items() if value}
    return render_page(request, 'farm/harvests.html', _context(
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
    ))


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


def withdrawals(units):
    """{unit id: [WithdrawalBlock]} of the units with a medicine withdrawal in force today, for the row badge;
    empty when no provider is registered."""
    found = check.in_force_of(units)
    return {unit_id: blocks for unit_id, blocks in (found or {}).items() if blocks}
