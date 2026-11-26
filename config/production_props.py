"""The props of the new look's Production › Overview island (frontend/islands/production.tsx, pages/Production.tsx), in the
design's layout, from the very context config.views.production_home builds for the classic page
(templates/_production_overview.html): the day's figures, what needs attention, the farm, the reports due and the
production team today. Every word is the classic template's msgid, finished here in the request's language; the island
only draws it, and core.pagesays holds the new page to the old one (farm/tests/test_production_overview_next.py).

A water value is its figure in its status's chip, its parameter, what was measured, the unit's own older value and its
origin and age, as on Production units (farm/stock/units_next.py); a stale value that was critical or a warning says so
("Stale, was critical"). The head (its status chips and Record water sample) stays the server's, as on the classic page."""
from django.utils import formats
from django.utils.translation import gettext as _, ngettext

from core.dates import company_zone
from core.formprops import when
from core.templatetags.dates import company_clock
from farm.stock.units_next import VALUE_CHIP, was_said
from farm.templatetags.health import harvest_from
from farm.templatetags.water import reading_figure, source, status_label

# a point's status as its chip (farm/_water_chip.html)
POINT_CHIP = {'critical': 'critical', 'warning': 'warning', 'unevaluated': 'warning', 'ok': 'ok', 'stale': 'stale',
              'not_measured': 'nodata'}


def _tile(key, card, label=None, sub=None, source_=None, status=None):
    """One figure of a metric card (templates/_metric_card.html) as the island's tile."""
    return {'key': key, 'label': str(label if label is not None else card['label']), 'figure': str(card['count']),
            'href': card.get('url'), 'sub': None if sub is None else str(sub), 'source': source_, 'status': status,
            'statusLabel': {'critical': _('Critical'), 'warning': _('Warning')}.get(status)}


def _today(context, clock):
    stock, feeding, water, tasks, upcoming = (context[key] for key in ('stock', 'feeding', 'water', 'tasks', 'upcoming'))
    tiles = []
    if stock:
        said = _('Stock records at %(clock)s') % {'clock': clock}
        fish = stock['fish']
        batches = ngettext('in %(count)s batch', 'in %(count)s batches', fish['batches']) % {'count': fish['batches']} \
            if 'batches' in fish else None
        units = ngettext('of %(total)s unit', 'of %(total)s units', stock['stocked']['of']) % {'total': stock['stocked']['of']}
        tiles += [_tile('stock-stocked', stock['stocked'], sub=units, source_=said),
                  _tile('stock-fish', fish, sub=batches, source_=said),
                  _tile('stock-biomass', stock['biomass'], source_=said)]
    if feeding:
        said = _('Feeding records at %(clock)s') % {'clock': clock}
        tiles += [_tile('feed-today', feeding['today'], sub=feeding['today'].get('sub'), source_=said),
                  _tile('feed-week', feeding['week'], sub=feeding['week'].get('sub'), source_=said)]
    if water:
        said = _('Samples and sensors at %(clock)s') % {'clock': clock}
        points = ngettext('of %(total)s sampling point', 'of %(total)s sampling points', water['points']) % {
            'total': water['points']}
        tiles += [_tile('water-critical', {'count': water['critical'], 'url': water['url']}, _('Critical water points'),
                        points, said, 'critical' if water['critical'] else None),
                  _tile('water-warning', {'count': water['warning'], 'url': water['url']}, _('Water points with a warning'),
                        points, said, 'warning' if water['warning'] else None)]
    if tasks:
        said = _('Tasks at %(clock)s') % {'clock': clock}
        tiles += [_tile('tasks-due_today', tasks['due_today'], source_=said),
                  _tile('tasks-overdue', tasks['overdue'], source_=said,
                        status='warning' if context['late_tasks'] else None)]
    if upcoming:
        late, at_once, unset = context['late_reports'], context['at_once'], context['not_set_up']
        if late:
            sub = ngettext('%(count)s overdue', '%(count)s overdue', late) % {'count': late}
        elif at_once:
            sub = ngettext('%(count)s due at once', '%(count)s due at once', at_once) % {'count': at_once}
        elif unset:
            sub = ngettext('%(count)s site not set up for reports', '%(count)s sites not set up for reports', unset) % {
                'count': unset}
        else:
            sub = _('None overdue')
        tiles.append(_tile('reports-due', {'count': upcoming['count'], 'url': upcoming['url']}, _('Reports due'), sub,
                           _('Reports at %(clock)s') % {'clock': clock},
                           'warning' if late or at_once or unset else None))
    return tiles


def value(reading, judged):
    """One water value of an attention row (farm/_water_value.html with `latest` and `source`): the parameter, its figure
    in the chip of what the limits said, what was measured, the unit's own older value, its origin and age; a stale one
    that was critical or a warning says so."""
    said = source(reading)
    sub = [reading.measured or '', getattr(reading, 'last_own_said', '') if reading.last_own else '',
           f"{said['origin']} · {said['age']}"]
    if reading.old_alert:
        sub.insert(0, was_said(reading))
    return {'label': str(reading.parameter.short), 'figure': '?' if reading.value is None else str(reading_figure(reading)),
            'kind': VALUE_CHIP.get(judged) or VALUE_CHIP.get(reading.status) or 'neutral',
            'sub': [str(each) for each in sub if each]}


def _chip(status, old=False):
    said = _('%(status)s, no recent data') % {'status': status_label(status)} if old else str(status_label(status))
    return {'kind': POINT_CHIP.get(status, 'neutral'), 'text': said}


def _row(key, kind, chip, title, sub, link, status='warning', values=()):
    return {'key': key, 'kind': kind, 'chip': chip, 'title': str(title), 'sub': str(sub) if sub else None,
            'link': link, 'status': status, 'values': list(values)}


def _attention(context, clock):
    water, tasks, upcoming = context['water'], context['tasks'], context['upcoming']
    if not (water or tasks or upcoming):
        return None
    rows = []
    for row in (water or {}).get('alerts', ()):
        point, owner, status = row['point'], row['owner'], row['water'].point_status
        if row['loop']:
            where = f'{point.name}, {owner.site.name}'
        else:
            # (a unit read at its system or nowhere is its own row, without a point: farm.water.views.overview)
            department = owner.production_department
            where = ', '.join([*([point.name] if point is not None else []), department.name,
                               *([department.site.name] if department.site else [])])
        # A unit with fish whose oxygen has no fresh value says why (PointWater.why_silent, owner decision of 2026-11-23).
        where = ' · '.join([where, *(str(why) for why in row['water'].why_silent)])
        key = f'water-{point.pk}' if point is not None else f'water-unit-{owner.pk}'
        rows.append(_row(key, 'water', _chip(status, row['water'].old_alert), owner.code, where,
                         {'href': row['history_url'], 'label': _('History')},
                         'critical' if status == 'critical' else 'warning',
                         [value(reading, judged) for reading, judged, _old in row['water'].alerts]))
    for row in (water or {}).get('unevaluated', ()):
        rows.append(_row(f'unevaluated-{row["owner"].pk}', 'unevaluated', _chip('unevaluated'), row['owner'].code,
                         ' '.join(str(why) for why in row['water'].why_unevaluated),
                         {'href': water['url'], 'label': _('Water chemistry')}))
    for hold in context.get('holds', ()):
        rows.append(_row(f'hold-{hold["unit"].pk}', 'withdrawal', {'kind': 'hold', 'text': _('Withdrawal')},
                         hold['unit'].code, ' · '.join(f'{block.batch.code}: {harvest_from(block)}' for block in hold['blocks']),
                         {'href': hold['url'], 'label': _('Production units')}, None))
    if context['late_tasks']:
        count = context['late_tasks']
        rows.append(_row('tasks', 'tasks', {'kind': 'warning', 'text': _('Overdue')},
                         ngettext('%(count)s task is overdue', '%(count)s tasks are overdue', count) % {'count': count},
                         None, {'href': tasks['overdue']['url'], 'label': _('Tasks')}))
    if context.get('tasks_unplanned'):
        # the task job behind (tasks.read.unplanned): the task counts miss today's tasks of these recurring tasks
        count = context['tasks_unplanned']
        rows.append(_row('tasks-unplanned', 'tasks', {'kind': 'warning', 'text': _('Not planned')},
                         ngettext('%(count)s recurring task not planned up to today',
                                  '%(count)s recurring tasks not planned up to today', count) % {'count': count},
                         _('Its tasks for today are missing from the counts until the task job runs.'),
                         {'href': tasks['overdue']['url'], 'label': _('Tasks')}))
    reports = {'href': upcoming['url'], 'label': _('Regulatory reports')} if upcoming else None
    for index, row in enumerate((upcoming or {}).get('late', ())):
        rows.append(_row(f'late-{index}', 'report', {'kind': 'warning', 'text': _('Overdue')}, _report(row),
                         _('Due %(date)s') % {'date': formats.date_format(row.deadline, 'DATE_FORMAT')}, reports))
    for index, row in enumerate((upcoming or {}).get('at_once', ())):
        rows.append(_row(f'once-{index}', 'notice', {'kind': 'warning', 'text': _('Due at once')},
                         f'{_kind(row)}, {row.place}', _('A notice is filed at once: it has no later deadline.'),
                         reports))
    for index, item in enumerate((upcoming or {}).get('not_set_up', ())):
        rows.append(_row(f'unset-{index}', 'not-set-up', {'kind': 'warning', 'text': _('Not set up for reports')},
                         str(item.site), _('It holds fish, and what it owes cannot be worked out: no report is listed as due '
                                         'for it.'), reports))
    if context['unmeasured']:
        days = water['window_days']
        rows.append(_row('unmeasured', 'unmeasured', {'kind': 'warning', 'text': _('Not measured')},
                         ', '.join(unit.code for unit in water['unmeasured']),
                         ngettext('Fish, and no water sample in the last %(days)s day.',
                                  'Fish, and no water sample in the last %(days)s days.', days) % {'days': days},
                         {'href': water['url'], 'label': _('Water chemistry')}))
    for index, line in enumerate((upcoming or {}).get('late_duties', ())):
        rows.append(_row(f'duty-{index}', 'duty', {'kind': 'warning', 'text': _('Overdue')},
                         f'{line.duty.title}, {line.site.name}, {line.year}',
                         _('Due %(date)s') % {'date': formats.date_format(line.deadline, 'DATE_FORMAT')},
                         {'href': upcoming['duties_url'], 'label': _('Outside this system')}))
    more = None
    if water and water.get('more'):
        more = {'href': water['url'], 'label': ngettext('%(count)s more sampling point on Water chemistry',
                                                        '%(count)s more sampling points on Water chemistry',
                                                        water['more']) % {'count': water['more']}}
    return {
        'title': _('Needs attention'),
        'safety': _('Nobody is alerted: critical values are shown here, not sent.') if water else None,
        'failed': _('The live sensor values could not be read: the values below come from the water samples only.')
        if water and water.get('sensors_failed') else None,
        'rows': rows, 'more': more,
        'nothing': None if rows else {'chip': _('Nothing needs attention'),
                                      'text': _('Checked at %(clock)s.') % {'clock': clock}},
    }


def _kind(row):
    from reports.kinds import ReportKind
    return ReportKind(row.kind).label


def _report(row):
    """A report row as the classic page says it: its kind, its place and its period."""
    return f'{_kind(row)}, {row.place}' + (f', {row.period.label()}' if row.period else '')


def _farm(context, clock):
    if not context['tiles']:
        return None
    said = _('Setup at %(clock)s') % {'clock': clock}
    small = lambda key, item: {'key': f'{key}-{item["value"]}', 'label': str(item['label']),   # noqa: E731
                               'figure': str(item['count']), 'href': item['url'], 'sub': None, 'source': None,
                               'status': None, 'statusLabel': None}
    return {'title': _('The farm'), 'source': said,
            'tiles': [_tile(f"farm-{tile['key']}", tile) for tile in context['tiles']],
            'groups': [group for group in (
                {'title': _('Systems by status'), 'tiles': [small('system', each) for each in context['systems_by_status']]},
                {'title': _('Units by kind'), 'tiles': [small('kind', each) for each in context['units_by_kind']]},
            ) if group['tiles']]}


def _reports(context):
    upcoming = context['upcoming']
    if not upcoming:
        return None
    items = [{'key': f'due-{index}', 'text': _report(row),
              'sub': _('Due %(date)s') % {'date': formats.date_format(row.deadline, 'DATE_FORMAT')} if row.deadline
              else _('Due at once'), 'link': None} for index, row in enumerate(upcoming['due'])]
    items += [{'key': f'duty-{index}', 'text': f'{line.duty.title}, {line.site.name}, {line.year}',
               'sub': _('Due %(date)s') % {'date': formats.date_format(line.deadline, 'DATE_FORMAT')},
               'link': {'href': upcoming['duties_url'], 'label': _('Outside this system')}}
              for index, line in enumerate(upcoming['due_duties'])]
    unset = len(upcoming['not_set_up'])
    late = context['late_reports']
    return {
        'title': _('Reports due'),
        'badge': ngettext('%(count)s overdue', '%(count)s overdue', late) % {'count': late} if late else None,
        'items': items,
        'empty': _('No report is due.') if not items and not unset else None,
        'notSetUp': ngettext('%(count)s site with fish is not set up for reports: what it owes is not known, so nothing '
                             'is listed as due for it.',
                             '%(count)s sites with fish are not set up for reports: what they owe is not known, so '
                             'nothing is listed as due for them.', unset) % {'count': unset} if unset else None,
        'link': {'href': upcoming['url'],
                 'label': _('and %(count)s more: all reports') % {'count': upcoming['more']} if upcoming['more']
                 else _('All reports')},
    }


def _team(context):
    team = context.get('team')
    if not team:
        return None
    line = f"{_('On site now')}: {team['on_site']}"
    if team['late']:
        line += ' · ' + ngettext('%(late)s late', '%(late)s late', team['late']) % {'late': team['late']}
    if team['unplanned']:
        line += f" · {_('Here, not planned')}: {team['unplanned']}"
    return {'title': _('Production team today'), 'stack': context['team_stack']['props'], 'line': line,
            'link': {'href': team['url'], 'label': _('Today & attendance')}}


def production_props(context):
    """Everything the island draws, from production_home's context (the classic page's, with the new look's parts)."""
    clock = formats.time_format(company_clock(context['now']), 'TIME_FORMAT')
    if not any(context[key] for key in ('stock', 'feeding', 'water', 'tasks', 'upcoming', 'tiles')):
        return {'empty': {'title': _('Your role opens none of the production figures yet.'),
                          'text': _('The pages your role opens are in the menu.')},
                'today': None, 'attention': None, 'farm': None, 'reports': None, 'team': None}
    tiles = _today(context, clock)
    return {
        'empty': None,
        'today': {'title': _('Today on the farm'), 'tiles': tiles,
                  'meta': _('Worked out %(when)s · %(zone)s') % {'when': when(context['now']), 'zone': company_zone().key}}
        if tiles else None,
        'attention': _attention(context, clock),
        'farm': _farm(context, clock),
        'reports': _reports(context),
        'team': _team(context),
    }
