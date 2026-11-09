from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.utils.translation import gettext_lazy as _

from farm.models import Equipment, ProductionDepartment, Site, System, Tank
from farm.feeding.views import overview_tiles as feeding_tiles
from farm.stock.views import overview_tiles
from farm.water.views import RECORD as WATER_RECORD, overview as water_overview
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
    """The company's overview."""
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
    return {**upcoming, 'count': len(upcoming['rows']) + upcoming['more'] + len(upcoming['duties']),
            'late': [row for row in upcoming['rows'] if row.overdue],
            'due': [row for row in upcoming['rows'] if not row.overdue],
            'late_duties': [line for line in upcoming['duties'] if line.status == duties.OVERDUE],
            'due_duties': [line for line in upcoming['duties'] if line.status != duties.OVERDUE]}


def production_home(request):
    """The production overview, the panel's landing page at the start of a shift and a dashboard
    (templates/production_home.html): the day's figures as metric cards (the stock now from the ledger, the feed given
    today and over 7 days, the water's critical and warning points, the tasks due today and overdue, the reports due), each
    with its source and the moment it was worked out; what needs attention (the water points with a critical or warning
    value, the critical first; overdue tasks and reports); beside it the farm's structure (departments, systems and their
    status, equipment, units and their kind) and the reports due. Each part only for a person who may read it, read by the
    areas' own functions; the one primary action, Record water sample, only for a person who may record one."""
    user = request.user
    stock, feeding, tasks = overview_tiles(user), feeding_tiles(user), task_tiles(user)
    water = water_overview(user)
    upcoming = _upcoming(user)
    tasks_named = _named(tasks)
    return render(request, 'production_home.html', {
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
