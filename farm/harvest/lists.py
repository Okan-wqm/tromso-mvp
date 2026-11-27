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

from .. import words
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
        L.choice('kind', str(words.PLAN), chosen['kind'], [('', str(words.HARVESTS_AND_TRANSPORTS)), *context['kinds']]),
        L.choice('status', str(words.STATUS), chosen['status'], [('', str(words.ALL_STATUSES)), *context['statuses']]),
        L.choice('site', str(words.SITE), chosen['site'], [('', str(words.ALL_SITES)), *((s.pk, s.name) for s in context['sites'])]),
        L.choice('unit', str(words.UNIT), chosen['unit'],
                 [('', str(words.ALL_UNITS)), *((u.pk, f'{u.code} · {u.name}') for u in context['units'])]),
        L.day('from', str(words.FROM), chosen['from']), L.day('to', str(words.TO), chosen['to']),
    ]


def _before(row):
    """What a plan asks before its handling: the fast, a medicine withdrawal on its day (or that it was not checked),
    the earliest suitable day when it decides, the plan's notes."""
    item, lines, chips, worry = row['item'], [], [], None
    if row['fast']:
        lines.append(str(row['fast'].why()))
    if row['withdrawal']:
        chips.append(L.chip('hold', _('Withdrawal')))
        worry = 'critical'
    for block in row['withdrawal'] or ():
        lines.append(_('%(batch)s: medicine withdrawal, %(end)s') % {'batch': block.batch.code, 'end': harvest_from(block)})
    if row['withdrawal'] is None and row['status'] not in (PlanStatus.DONE, PlanStatus.CANCELLED):
        lines.append(str(words.MEDICINE_WITHDRAWAL_NOT_CHECKED))
        worry = worry or 'warning'
    earliest = row['earliest']
    if earliest is not None and earliest.decides:
        lines.append(str(earliest.text()))
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
            actions.append(L.link(row['record_url'], str(words.RECORD_HARVEST) if item.kind == PlanKind.HARVEST
                                  else str(words.RECORD_TRANSFER), 'package-check' if item.kind == PlanKind.HARVEST
                                  else 'truck', labelled=True))
        if context.get('can_change') and resource.allowed(request, item, 'change'):
            actions.append(L.link(view.url('edit', item.pk), str(words.EDIT_OR_CANCEL), 'pencil'))
        if context.get('can_delete') and resource.allowed(request, item, 'delete'):
            actions.append(L.link(view.url('delete', item.pk), str(words.DELETE), 'trash', danger=True))
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
    notice_link = (context['plan_transport_url'], str(words.PLAN_TRANSPORT)) if context.get('can_add') else None
    return {
        'columns': [L.column('date', str(words.DATE)), L.column('plan', str(words.PLAN)), L.column('unit', str(words.UNIT)),
                    L.column('batch', str(words.BATCH)), L.column('planned', str(words.PLANNED), numeric=True), L.column('to', str(words.TO)),
                    L.column('status', str(words.STATUS)), L.column('actual', str(words.ACTUAL), numeric=True),
                    L.column('before', str(words.BEFORE_HANDLING))],
        'notices': [L.notice('how', 'neutral', str(words.A_PLAN_IS_DONE_WHEN_THE_HARVEST),
            link=notice_link)],
        'rows': rows,
    }


def production_filters(view, context):
    if len(context['sites']) <= 1:
        return []
    return [L.choice('site', str(words.SITE), context['chosen_site'],
                     [('', str(words.ALL_SITES)), *((site.pk, site.name) for site in context['sites'])])]


def _forecast(row):
    forecast = row.get('forecast')
    if not forecast:
        return L.cell(DASH)
    said = row['forecast_said']
    return L.cell(grams(forecast.now_g), sub=said['lines'],
                  chips=[L.chip('ok', str(words.TARGET_REACHED))] if said['reached_already'] else ())


def forecast_said(forecast):
    """What a row says under its estimate now, once for both looks (the classic template draws the same lines): the day
    the target is reached and at what temperature (a temperature profile's, or the measured one held), then the feed to it and the economic
    FCR of those days; why it is not reached (`warn`); or that the fish are there already (`reached_already`)."""
    from ..templatetags.feeding import fcr, feed_kg
    said = {'lines': [], 'reached_already': False, 'warn': False}
    if forecast.reached and not forecast.planned:
        said['reached_already'] = True
    elif not forecast.reached:
        said['lines'], said['warn'] = ([str(forecast.why)] if forecast.why else []), True
    else:
        if forecast.profiles and forecast.held is None:
            reached = _('target on %(date)s, on the temperature profile %(profile)s') % {
                'date': _day(forecast.day), 'profile': ', '.join(profile.name for profile in forecast.profiles)}
        else:
            reached = _('target on %(date)s, at %(temperature)s °C held') % {
                'date': _day(forecast.day), 'temperature': floatformat(forecast.temperature_c, '1')}
        said['lines'] = [reached, _('%(feed)s of feed to the target · FCR on feed given %(fcr)s · economic FCR '
                                    '%(efcr)s') % {
            'feed': feed_kg(forecast.curve.feed_kg), 'fcr': fcr(forecast.curve.fcr_on_feed_given),
            'efcr': fcr(forecast.curve.economic_fcr)}]
        if forecast.stale:
            said['lines'].append(str(forecast.stale))       # a temperature held that is not fresh is said, never silent
    return said


def _withdrawal(row):
    """The fish's withdrawal today, in the server's words: Not checked, the blocks (each with its end), or None."""
    earliest = [str(row['earliest'].text())] if row['earliest'] is not None and row['earliest'].decides else []
    if row['withdrawal'] is None:
        return L.cell(str(words.NOT_CHECKED), sub=earliest)
    if row['withdrawal']:
        said = [f'{block.batch.code}: {harvest_from(block)}' for block in row['withdrawal']]
        return L.cell(said[0], chips=[L.chip('hold', _('Withdrawal'))], sub=said[1:] + earliest)
    return L.cell(str(words.NONE), sub=earliest)


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
        delete = [L.link(reverse('farm:productionplan_delete', args=[plan.pk]), str(words.DELETE), 'trash', danger=True)] \
            if plan is not None and can_delete else []
        if share is None:
            rows.append(L.row(f'gone-{plan.pk}', {
                'unit': L.cell(DASH), 'batch': L.cell(plan.batch.code, sub=[plan.batch.species.common_name]),
                'fish': L.cell(str(words.NO_LONGER_IN_STOCK)), 'target': target}, delete))
            continue
        batch = share.batch
        if target is None:
            target = L.cell(str(words.SET_TARGET), href=f"{reverse('farm:productionplan_create')}?batch={batch.pk}") \
                if can_add else L.cell(DASH)
        weighed = _('weighed %(date)s') % {'date': _day(share.last_weighed)} if share.last_weighed else str(words.AS_STOCKED)
        actions = [L.link(row['growth_url'], str(words.GROWTH_PLAN), 'chart-line', labelled=True)]
        if row['plan_harvest_url']:
            actions.append(L.link(row['plan_harvest_url'], str(words.PLAN_HARVEST), 'calendar', labelled=True))
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
        'columns': [L.column('unit', str(words.UNIT)), L.column('batch', str(words.BATCH)), L.column('fish', str(words.FISH), numeric=True),
                    L.column('average', str(words.AVG_WEIGHT), numeric=True),
                    L.column('target', str(words.TARGET_WEIGHT), numeric=True),
                    L.column('forecast', str(words.ESTIMATED_NOW_TARGET_REACHED)),
                    L.column('expected', str(words.EXPECTED_HARVEST)), L.column('fed', str(words.LAST_FED)),
                    L.column('withdrawal', str(words.MEDICINE_WITHDRAWAL))],
        'notices': [L.notice('how', 'neutral', str(words.THE_TARGET_WEIGHT_EACH_BATCH_IS_GROWN))],
        'rows': rows,
    }
