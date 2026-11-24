from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.utils.translation import gettext_lazy as _

from farm.models import Equipment, ProductionDepartment, Site, System, Tank
from farm.feeding.views import overview_tiles as feeding_tiles
from farm.stock.views import overview as stock_overview, overview_tiles
from farm.water.views import RECORD as WATER_RECORD, overview as water_overview
from core.stack import part, stack
from core.ui import is_next
from hr import read as hr_read, scope as hr_scope
from reports import duties
from reports.views import overview_upcoming
from tasks.views import overview_tiles as task_tiles


def _counts(user, *tiles):
    """[{key, label, count, url}] for the records the person may see; tiles are (label, model, url name), the key is the
    model's name."""
    return [
        {'key': model._meta.model_name, 'label': label, 'count': model.objects.count(), 'url': reverse(url_name)}
        for label, model, url_name in tiles
        if user.has_perm(f'{model._meta.app_label}.view_{model._meta.model_name}')
    ]


def home(request):
    """The company's overview. In the new look (core.ui.is_next) the island draws the board of config/company_props.py."""
    if is_next(request):
        from .company_props import overview_props
        return render(request, 'home_next.html', {'props': overview_props(request.user)})
    return render(request, 'home.html', {
        'tiles': _counts(request.user, (_('Sites'), Site, 'farm:site_list')),
        'upcoming': overview_upcoming(request.user),
    })


def _named(tiles):
    """{key: tile} of an area's overview tiles, or None when the person may not read the area (no tiles)."""
    return {tile['key']: tile for tile in tiles} or None


def _upcoming(user):
    """The reports due (reports.views.overview_upcoming), split for the page: the overdue ones (and the overdue duties
    outside this system) need attention, the others are due; `count` is all of them (the ones listed, the ones beyond the
    list and the duties); None for a person who may not read the reports."""
    upcoming = overview_upcoming(user)
    if upcoming is None:
        return None
    return {'not_set_up': [], 'at_once': [], **upcoming,
            'count': len(upcoming['rows']) + upcoming['more'] + len(upcoming['duties']),
            'late': [row for row in upcoming['rows'] if row.overdue],
            'due': [row for row in upcoming['rows'] if not row.overdue],
            'late_duties': [line for line in upcoming['duties'] if line.status == duties.OVERDUE],
            'due_duties': [line for line in upcoming['duties'] if line.status != duties.OVERDUE]}


# The words of the HR board's tiles (templates/hr/_board.html says the same), by Board.tiles key.
TEAM_WORDS = {'upcoming': _('Upcoming'), 'here': _('Here now'), 'not_in': _('Not in yet'), 'absent': _('Absent'),
              'on_leave': _('On leave'), 'done': _('Done'), 'forgotten': _('Clock-out forgotten')}


def team_today(user):
    """The production team today, for the redesigned overview: hr.read.board of the production people the person may
    reach (realm production), as its tiles say it on Production › Team › Today & attendance. Each person planned today is
    in exactly one tile, so the tiles add up to `planned`:
    - upcoming: the shift has not begun;
    - here: clocked in, late ones included (`late` says how many);
    - not_in: the shift has begun, within HR's absent-after time, not clocked in;
    - absent: past that time, not clocked in, not on leave;
    - on_leave: approved leave today;
    - done: clocked out after the shift;
    - forgotten: a clock-in left open longer than HR's setting (never counted as here or done).
    Beside them: `unplanned` (here without a plan) and `on_site`, the muster count of every open clock-in on the farm
    (a number, whoever looks). None for a person who may not read attendance."""
    if not user.has_perm('hr.view_attendancerecord'):
        return None
    board = hr_read.board(user, realm=hr_scope.PRODUCTION)
    return {'tiles': [{'key': tile.key, 'label': TEAM_WORDS[tile.key], 'count': tile.count} for tile in board.tiles
                      if tile.key != 'forgotten' or tile.count or board.unplanned_forgotten],
            'planned': board.planned, 'late': board.late, 'unplanned': board.unplanned, 'on_site': board.on_site,
            'url': reverse('hr:production_today')}


TEAM_TONES = {'upcoming': 'hold', 'here': 'ok', 'not_in': 'warning', 'absent': 'critical', 'on_leave': 'note',
              'done': 'neutral', 'forgotten': 'warning'}       # the HR board's bar's (hr.views.PLANNED_PARTS)


def _next_parts(user, stock_part):
    """What the new look's Production › Overview says beyond the classic page (templates/_production_overview.html under
    `next`): the fish's batch count on its card, the units under a medicine withdrawal today in Needs attention (each a
    link to its drawer), and the production team today as the HR board's bar (`team_today`, its tiles adding up to the
    people planned today)."""
    team = team_today(user)
    return {
        'next': True,
        'holds': stock_part['holds'] if stock_part else [],
        'team': team,
        'team_stack': stack(_('Planned today'), [part(tile['key'], tile['label'], tile['count'], TEAM_TONES[tile['key']])
                                                 for tile in team['tiles']],
                            empty=_('Nobody is planned today.')) if team else None,
    }


def production_home(request):
    """The production overview, the panel's landing page at the start of a shift and a dashboard
    (templates/production_home.html): the day's figures as metric cards (the stock now from the ledger, the feed given
    today and over 7 days, the water's critical and warning points, the tasks due today and overdue, the reports due), each
    with its source and the moment it was worked out; what needs attention (the water points with a critical or warning
    value, the critical first; overdue tasks and reports); beside it the farm's structure (departments, systems and their
    status, equipment, units and their kind) and the reports due. Each part only for a person who may read it, read by the
    areas' own functions; the one primary action, Record water sample, only for a person who may record one."""
    user = request.user
    look = is_next(request)
    # The new look reads the stock once for its tiles and its withdrawal holds (farm.stock.views.overview).
    stock_part = stock_overview(user) if look else None
    stock = (stock_part or {}).get('tiles', []) if look else overview_tiles(user)
    feeding, tasks = feeding_tiles(user), task_tiles(user)
    water = water_overview(user)
    upcoming = _upcoming(user)
    tasks_named = _named(tasks)
    return render(request, 'production_home.html', {
        **(_next_parts(user, stock_part) if look else {}),
        'stock_tiles': stock,
        'feeding_tiles': feeding,
        'water_tiles': water['tiles'] if water else [],
        'task_tiles': tasks,
        'stock': _named(stock), 'feeding': _named(feeding), 'tasks': tasks_named, 'water': water,
        'upcoming': upcoming, 'now': timezone.now(),
        'record_url': f"{reverse('farm:water_record')}?{urlencode({'next': request.get_full_path()})}"
        if user.has_perm(WATER_RECORD) else '',
        'late_tasks': tasks_named['overdue']['count'] if tasks_named else 0,
        'late_reports': len(upcoming['late']) + len(upcoming['late_duties']) if upcoming else 0,
        # What else is not "nothing needs attention" (flow faults M-06, M-20), each counted by the read of its own page:
        # the notices to file at once, the sites with fish that are not set up for reports, the stocked units with no
        # water value inside the window of the Water page.
        'at_once': len(upcoming['at_once']) if upcoming else 0,
        'not_set_up': len(upcoming['not_set_up']) if upcoming else 0,
        'unmeasured': len(water.get('unmeasured', ())) if water else 0,
        'tiles': _counts(request.user,
                         (_('Production departments'), ProductionDepartment, 'farm:productiondepartment_list'),
                         (_('Systems'), System, 'farm:system_list'),
                         (_('Equipment'), Equipment, 'farm:equipment_list'),
                         (_('Tanks, ponds & cages'), Tank, 'farm:tank_list')),
        'systems_by_status': [
            {'value': value, 'label': label, 'count': System.objects.filter(status=value).count(),
             'url': reverse('farm:system_list')}
            for value, label in System.Status.choices
        ] if request.user.has_perm('farm.view_system') else [],
        'units_by_kind': [
            {'value': value, 'label': label, 'count': Tank.objects.filter(kind=value).count(),
             'url': f"{reverse('farm:tank_list')}?kind={value}"}
            for value, label in Tank.Kind.choices
        ] if request.user.has_perm('farm.view_tank') else [],
    })
