"""The new look's lists (core/listprops.py, island `list-page`) of Operations › Harvest's two tabs, Harvest plan and
Production plans (farm/resources/harvest_plan.py: `list_rows`, `list_filters`), worded as their classic templates word
them (templates/farm/plan_item_list.html, production_plan_list.html: the same msgids) from the rows the one list view
(core.crud.ListView) read for the classic page: each plan's derived status, planned against actual, the fast it asks of its
unit, and a medicine withdrawal on its day said in the server's own words (farm.handling.withdrawal via `harvest_from`),
never left out. The strip of the Harvest group's pages stays the server's (farm/_harvest_tabs.html above the island)."""
from django.template.defaultfilters import floatformat
from django.urls import reverse
from django.utils import formats
from django.utils.translation import gettext as _

from core import listprops as L

from ..models.harvest import PlanKind, PlanStatus
from ..templatetags.feeding import fed_on
from ..templatetags.health import harvest_from
from ..templatetags.stock import fish, grams, kilos

DASH = '—'
STATUS_CHIP = {PlanStatus.PLANNED: 'accent', PlanStatus.OVERDUE: 'warning', PlanStatus.DONE: 'ok',
               PlanStatus.CANCELLED: 'neutral'}


def _day(day):
    return formats.date_format(day, 'DATE_FORMAT') if day else DASH


def _unit(unit):
    department = unit.production_department
    return L.cell(unit.code, strong=True, sub=[department.name + (f' · {department.site.name}' if department.site else '')])


def plan_filters(view, context):
    chosen = context['chosen']
    return [
        L.choice('kind', _('Plan'), chosen['kind'], [('', _('Harvests and transports')), *context['kinds']]),
        L.choice('status', _('Status'), chosen['status'], [('', _('All statuses')), *context['statuses']]),
        L.choice('site', _('Site'), chosen['site'], [('', _('All sites')), *((s.pk, s.name) for s in context['sites'])]),
        L.choice('unit', _('Unit'), chosen['unit'],
                 [('', _('All units')), *((u.pk, f'{u.code} · {u.name}') for u in context['units'])]),
        L.day('from', _('From'), chosen['from']), L.day('to', _('To'), chosen['to']),
    ]


def _before(row):
    """What a plan asks before its handling: the fast, a medicine withdrawal on its day (or that it was not checked),
    the earliest suitable day when it decides, the plan's notes."""
    item, lines, chips, worry = row['item'], [], [], None
    if row['fast']:
        lines.append(str(row['fast'].why))
    if row['withdrawal']:
        chips.append(L.chip('hold', _('Withdrawal')))
        worry = 'critical'
    for block in row['withdrawal'] or ():
        lines.append(_('%(batch)s: medicine withdrawal, %(end)s') % {'batch': block.batch.code, 'end': harvest_from(block)})
    if row['withdrawal'] is None and row['status'] not in (PlanStatus.DONE, PlanStatus.CANCELLED):
        lines.append(_('Medicine withdrawal not checked'))
        worry = worry or 'warning'
    earliest = row['earliest']
    if earliest is not None and earliest.decides:
        lines.append(str(earliest.text))
        if earliest.day is None or item.date < earliest.day:
            worry = worry or 'warning'
    if item.notes:
        lines.append(item.notes)
    return L.cell(lines[0] if lines else None, sub=lines[1:], chips=chips), worry


def plan_items(view, objects, context):
    """Harvest plan: the planned harvests and transports with their status, planned against actual and what each asks
    before its handling; Record harvest / Record transfer opens the stock's form started from the plan."""
    request, resource = view.request, view.resource
    rows = []
    for row in objects:
        item = row['item']
        before, worry = _before(row)
        if row['status'] == PlanStatus.OVERDUE:
            worry = worry or 'warning'
        actions = []
        if row['record_url']:
            actions.append(L.link(row['record_url'], _('Record harvest') if item.kind == PlanKind.HARVEST
                                  else _('Record transfer'), 'package-check' if item.kind == PlanKind.HARVEST
                                  else 'truck', labelled=True))
        if context.get('can_change') and resource.allowed(request, item, 'change'):
            actions.append(L.link(view.url('edit', item.pk), _('Edit or cancel'), 'pencil'))
        if context.get('can_delete') and resource.allowed(request, item, 'delete'):
            actions.append(L.link(view.url('delete', item.pk), _('Delete'), 'trash', danger=True))
        target = item.facility.name if item.facility else (item.destination_unit.code if item.destination_unit else DASH)
        carrier = ' · '.join(part for part in ((item.transport.name if item.transport else ''), item.vessel) if part)
        rows.append(L.row(item.pk, {
            'date': L.cell(_day(item.date)),
            'plan': L.title(view, context, item, item.get_kind_display()),
            'unit': _unit(item.unit),
            'batch': L.cell(item.batch.code, sub=[item.batch.species.common_name]),
            'planned': L.cell(_('%(fish)s fish') % {'fish': fish(item.planned_count)} if item.planned_count else DASH,
                              sub=[kilos(item.planned_kg) if item.planned_kg else '']),
            'to': L.cell(target, sub=[carrier]),
            'status': L.cell(chip=L.chip(STATUS_CHIP.get(row['status'], 'neutral'), row['status'].label),
                             sub=[item.cancelled_reason or '']),
            'actual': L.cell(_('%(fish)s fish') % {'fish': fish(row['actual_count'])}, sub=[kilos(row['actual_kg'])])
            if row.get('actual_count') is not None else L.cell(DASH),
            'before': before,
        }, actions, status=None if row['status'] in (PlanStatus.DONE, PlanStatus.CANCELLED) else worry,
            voided=row['status'] == PlanStatus.CANCELLED))
    notice_link = (context['plan_transport_url'], _('Plan transport')) if context.get('can_add') else None
    return {
        'columns': [L.column('date', _('Date')), L.column('plan', _('Plan')), L.column('unit', _('Unit')),
                    L.column('batch', _('Batch')), L.column('planned', _('Planned'), numeric=True), L.column('to', _('To')),
                    L.column('status', _('Status')), L.column('actual', _('Actual'), numeric=True),
                    L.column('before', _('Before handling'))],
        'notices': [L.notice('how', 'neutral', _(
            'A plan is done when the harvest or transfer recorded from it counts; voiding that operation plans it again. '
            'The fast a plan asks of its unit starts at the start of its day less the handling rule’s hours.'),
            link=notice_link)],
        'rows': rows,
    }


def production_filters(view, context):
    if len(context['sites']) <= 1:
        return []
    return [L.choice('site', _('Site'), context['chosen_site'],
                     [('', _('All sites')), *((site.pk, site.name) for site in context['sites'])])]


def _forecast(row):
    forecast = row.get('forecast')
    if not forecast:
        return L.cell(DASH)
    if forecast.reached and forecast.temperature_c is not None:
        sub, chips = [_('target on %(date)s, at %(temperature)s °C held') % {
            'date': _day(forecast.day), 'temperature': floatformat(forecast.temperature_c, '1')}], ()
    elif forecast.reached:
        sub, chips = [], [L.chip('ok', _('target reached'))]
    else:
        sub, chips = [str(forecast.why)] if forecast.why else [], ()
    return L.cell(grams(forecast.now_g), sub=sub, chips=chips)


def _withdrawal(row):
    """The fish's withdrawal today, in the server's words: Not checked, the blocks (each with its end), or None."""
    earliest = [str(row['earliest'].text)] if row['earliest'] is not None and row['earliest'].decides else []
    if row['withdrawal'] is None:
        return L.cell(_('Not checked'), sub=earliest)
    if row['withdrawal']:
        said = [f'{block.batch.code}: {harvest_from(block)}' for block in row['withdrawal']]
        return L.cell(said[0], chips=[L.chip('hold', _('Withdrawal'))], sub=said[1:] + earliest)
    return L.cell(_('None'), sub=earliest)


def production_plans(view, objects, context):
    """Production plans: every batch in stock in each unit it is in, its book average, its target weight (or Set target),
    the estimate now and the day the target is reached, its expected harvest, its last feeding and its withdrawal; Plan
    harvest starts a planned harvest; the plans of batches no longer in stock follow."""
    can_change, can_add, can_delete = context.get('can_change'), context.get('can_add'), context.get('can_delete')
    rows = []
    for row in objects:
        plan, share = row['plan'], row['share']
        target = None
        if plan is not None:
            target = L.cell(grams(plan.target_weight_g),
                            href=reverse('farm:productionplan_edit', args=[plan.pk]) if can_change else None)
        delete = [L.link(reverse('farm:productionplan_delete', args=[plan.pk]), _('Delete'), 'trash', danger=True)] \
            if plan is not None and can_delete else []
        if share is None:
            rows.append(L.row(f'gone-{plan.pk}', {
                'unit': L.cell(DASH), 'batch': L.cell(plan.batch.code, sub=[plan.batch.species.common_name]),
                'fish': L.cell(_('No longer in stock')), 'target': target}, delete))
            continue
        batch = share.batch
        if target is None:
            target = L.cell(_('Set target'), href=f"{reverse('farm:productionplan_create')}?batch={batch.pk}") \
                if can_add else L.cell(DASH)
        weighed = _('weighed %(date)s') % {'date': _day(share.last_weighed)} if share.last_weighed else _('as stocked')
        actions = [L.link(row['plan_harvest_url'], _('Plan harvest'), 'calendar', labelled=True)] \
            if row['plan_harvest_url'] else []
        rows.append(L.row(f"{row['unit'].pk}-{batch.pk}", {
            'unit': _unit(row['unit']),
            'batch': L.cell(batch.code, sub=[batch.species.common_name]),
            'fish': L.cell(fish(share.count)),
            'average': L.cell(grams(share.avg_weight_g), sub=[weighed]),
            'target': target,
            'forecast': _forecast(row),
            'expected': L.cell(_day(row['expected'])),
            'fed': L.cell(fed_on(row['last_fed'], row['today'])),
            'withdrawal': _withdrawal(row),
        }, actions + delete, status='critical' if row['withdrawal'] else None))
    return {
        'columns': [L.column('unit', _('Unit')), L.column('batch', _('Batch')), L.column('fish', _('Fish'), numeric=True),
                    L.column('average', _('Avg. weight'), numeric=True),
                    L.column('target', _('Target weight'), numeric=True),
                    L.column('forecast', _('Estimated now · target reached')),
                    L.column('expected', _('Expected harvest')), L.column('fed', _('Last fed')),
                    L.column('withdrawal', _('Medicine withdrawal'))],
        'notices': [L.notice('how', 'neutral', _(
            'The target weight each batch is grown to for harvest. The estimated weight now is the feeding protocols’ '
            'estimate; the day it reaches the target walks it forward on the ration of each day, at the unit’s latest '
            'temperature held, with no growth on a fasting day. The expected harvest is the date given when the batch '
            'was stocked.'))],
        'rows': rows,
    }
