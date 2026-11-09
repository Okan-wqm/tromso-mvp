"""Operations › Harvest › Harvest plan and Production plans: the plans as tabs (core.crud), each with its
page of computed rows.

- Harvest plan: the planned harvests and transports, each with its derived status, planned against actual
  (the linked operation's lines), the fast it asks of its unit, a medicine withdrawal on its day, and
  "Record harvest" / "Record transfer", which opens the stock's dialog started from it.
- Production plans: every batch in stock in each unit it is in, with its target weight, its estimated weight
  now and the day it reaches the target (farm/harvest/forecast.py, from the feeding protocols' projection).
  "Plan harvest" starts a planned harvest of the share at the target weight, on that day."""
from urllib.parse import urlencode

from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from core.crud import Resource
from core.dates import read_day

from ..feeding import read as feeding_read
from ..forms.harvest import FROM_ADDRESS, HandlingPlanItemForm, ProductionPlanForm, planned_kg
from ..handling import check, fasting
from ..harvest import forecast, views as harvest_views
from ..models import HandlingPlanItem, ProductionPlan, Site, StockMovement, Tank
from ..models.harvest import PlanKind, PlanStatus
from ..models.stock import MovementKind
from ..stock import read as stock_read
from ..stock.dates import local_today

RECORD = 'farm.add_stockoperation'


class FromAddress:
    """A new plan starts from the values the link that opened it carries (?kind=harvest&unit=…&batch=…)."""

    @classmethod
    def form(cls, request, *args, **kwargs):
        if not args and 'instance' not in kwargs and 'draft' not in kwargs:
            kwargs['initial'] = {key: request.GET[key] for key in cls.from_address if request.GET.get(key)}
        return cls.form_class(*args, **kwargs)


class HandlingPlanItemResource(FromAddress, Resource):
    model = HandlingPlanItem
    form_class = HandlingPlanItemForm
    name, plural = _('planned harvest or transport'), _('planned harvests and transports')
    url_prefix = 'operations/harvest-plan'
    search_fields = ['unit__code', 'unit__name', 'batch__code', 'batch__name', 'facility__name', 'vessel', 'notes']
    list_template = 'farm/plan_item_list.html'
    icon = 'calendar'
    page_size = 50
    from_address = FROM_ADDRESS

    @classmethod
    def queryset(cls):
        return super().queryset().select_related(
            'unit__production_department__site', 'batch__species', 'facility', 'destination_unit', 'transport',
            'operation')

    @classmethod
    def filter_list(cls, request, objects):
        """The items the filters choose, each with what the list shows of it (computed, nothing stored)."""
        sites = Site.objects.filter(production_departments__tanks__plan_items__isnull=False).distinct()
        units = Tank.objects.filter(plan_items__isnull=False).distinct().order_by('code')
        chosen = {key: request.GET.get(key, '') for key in ('kind', 'status', 'site', 'unit', 'from', 'to')}
        if chosen['kind'] in PlanKind.values:
            objects = objects.filter(kind=chosen['kind'])
        else:
            chosen['kind'] = ''
        for key, choices, lookup in (('site', sites, 'unit__production_department__site'), ('unit', units, 'unit')):
            if chosen[key] in {str(pk) for pk in choices.values_list('pk', flat=True)}:
                objects = objects.filter(**{lookup: chosen[key]})
            else:
                chosen[key] = ''
        for key, lookup in (('from', 'date__gte'), ('to', 'date__lte')):
            day = read_day(chosen[key], request)
            chosen[key] = day or ''          # a date: the input shows it as the language writes it
            if day:
                objects = objects.filter(**{lookup: day})
        rows = [plan_row(request, item) for item in objects]
        if chosen['status'] in PlanStatus.values:
            rows = [row for row in rows if row['status'] == chosen['status']]
        else:
            chosen['status'] = ''
        _add_actuals(rows)
        return rows, {
            'kinds': PlanKind.choices, 'statuses': PlanStatus.choices, 'sites': sites.order_by('name'),
            'units': units, 'chosen': chosen, 'tabs': harvest_views.tabs(request, 'plan'),
            'plan_harvest_url': f'{reverse(cls.url_name("create"))}?kind={PlanKind.HARVEST}',
            'plan_transport_url': f'{reverse(cls.url_name("create"))}?kind={PlanKind.TRANSPORT}',
        }


def plan_row(request, item):
    """A plan item as the list shows it: its status, the fast it asks for, the withdrawal on its day (open
    items only) and the link that records it."""
    today = local_today(item.unit)
    status = item.status_on(today)
    row = {'item': item, 'status': status, 'fast': None, 'withdrawal': None, 'earliest': None, 'record_url': ''}
    if not item.is_open:
        return row
    row['fast'] = fasting.fast_of(item)
    row['withdrawal'] = check.in_force(item.unit, item.date, [item.batch])
    if item.kind == PlanKind.HARVEST:       # a transport moves live fish: no suitable date to a slaughter facility
        row['earliest'] = check.earliest(item.unit, item.batch)
    if request.user.has_perm(RECORD) and stock_read.fish_of_batch(item.batch_id).get(item.unit_id):
        operation = 'harvest' if item.kind == PlanKind.HARVEST else 'transfer'
        here = request.get_full_path()
        row['record_url'] = (reverse(f'farm:stock_{operation}', args=[item.unit_id]) + '?'
                             + urlencode({'plan': item.pk, 'next': here}))
    return row


def _add_actuals(rows):
    """Planned against actual: the fish and kilos of the operation that fulfils each done item (a harvest's
    weighed round kilos; a transfer's fish and the book kilos that moved)."""
    done = [row for row in rows if row['status'] == PlanStatus.DONE]
    if not done:
        return
    lines = list(StockMovement.objects.filter(
        operation__in=[row['item'].operation_id for row in done],
        kind__in=[MovementKind.HARVEST, MovementKind.TRANSFER_OUT]))
    moved = stock_read.moved_grams({line.batch_id for line in lines})
    for row in done:
        mine = [line for line in lines if line.operation_id == row['item'].operation_id]
        row['actual_count'] = -sum(line.count_delta for line in mine)
        if row['item'].kind == PlanKind.HARVEST:
            row['actual_kg'] = sum(line.measured_weight_kg for line in mine)
        else:
            row['actual_kg'] = sum(moved.get(line.id) or 0 for line in mine) / 1000


class ProductionPlanResource(FromAddress, Resource):
    model = ProductionPlan
    form_class = ProductionPlanForm
    name, plural = _('production plan'), _('production plans')
    url_prefix = 'operations/production-plans'
    list_template = 'farm/production_plan_list.html'
    icon = 'target'
    from_address = ('batch',)

    @classmethod
    def queryset(cls):
        return super().queryset().select_related('batch__species')

    @classmethod
    def filter_list(cls, request, objects):
        """One row per batch in stock in each unit it is in, with its plan (or "Set target"), and the plans of
        batches no longer in stock. Searched by unit, batch or species; filtered by site."""
        plans = {plan.batch_id: plan for plan in objects}
        units = list(Tank.objects.select_related('production_department__site').order_by('code'))
        stock = stock_read.stock_of(units)
        feeding = feeding_read.figures(stock)
        sites = sorted({unit.production_department.site for unit in units if unit.pk in stock
                        and unit.production_department.site}, key=lambda site: site.name)
        chosen_site = request.GET.get('site', '')
        if chosen_site not in {str(site.pk) for site in sites}:
            chosen_site = ''
        query = request.GET.get('q', '').strip().lower()
        estimates = forecast.forecasts([(item.unit, share) for item in stock.values() for share in item.counted],
                                       {batch_id: plan.target_weight_g for batch_id, plan in plans.items()})
        rows = []
        for unit_id, unit_stock in stock.items():
            unit = unit_stock.unit
            if chosen_site and str(unit.production_department.site_id) != chosen_site:
                continue
            for share in unit_stock.counted:          # the harvest targets are the production fish's
                batch = share.batch
                words = [unit.code, unit.name, batch.code, batch.name, batch.species.common_name,
                         batch.species.local_name]
                if query and not any(query in word.lower() for word in words if word):
                    continue
                row = share_row(request, unit, share, plans.get(batch.pk), feeding.get(unit_id))
                row['forecast'] = estimates.get((unit_id, batch.pk))
                rows.append(_plan_date(row))
        if not chosen_site and not query:
            in_stock = stock_read.batches_in_stock()
            rows += [{'plan': plan, 'share': None} for batch_id, plan in plans.items() if batch_id not in in_stock]
        return rows, {'sites': sites, 'chosen_site': chosen_site, 'tabs': harvest_views.tabs(request, 'targets')}


def share_row(request, unit, share, plan, feeding):
    """A batch in a unit: its fish and book average, its target, and the links to set it and plan a harvest."""
    today = local_today(unit)
    row = {'unit': unit, 'share': share, 'plan': plan, 'last_fed': feeding.last_fed if feeding else None,
           'today': today, 'withdrawal': check.in_force(unit, today, [share.batch]),
           'earliest': check.earliest(unit, share.batch),
           'expected': share.batch.expected_harvest_date, 'plan_harvest_url': ''}
    if request.user.has_perm('farm.add_handlingplanitem'):
        prefill = {'kind': PlanKind.HARVEST, 'unit': unit.pk, 'batch': share.batch.pk,
                   'planned_count': share.count}
        if plan is not None:
            prefill['planned_kg'] = planned_kg(share.count, plan.target_weight_g)
        if share.batch.expected_harvest_date and share.batch.expected_harvest_date >= today:
            prefill['date'] = share.batch.expected_harvest_date.isoformat()
        row['prefill'] = prefill
        row['plan_harvest_url'] = f'{reverse("farm:handlingplanitem_create")}?{urlencode(prefill)}'
    return row


def _plan_date(row):
    """A planned harvest starts on the day the target is reached, else on the batch's expected harvest."""
    reached = row.get('forecast') is not None and row['forecast'].reached
    if reached and row.get('plan_harvest_url'):
        prefill = {**row['prefill'], 'date': row['forecast'].day.isoformat()}
        row['plan_harvest_url'] = f'{reverse("farm:handlingplanitem_create")}?{urlencode(prefill)}'
    return row
