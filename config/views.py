from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from farm.models import Equipment, ProductionDepartment, Site, System, Tank
from farm.feeding.views import overview_tiles as feeding_tiles
from farm.stock.views import overview_tiles
from farm.water.views import overview_tiles as water_tiles
from tasks.views import overview_tiles as task_tiles


def _counts(user, *tiles):
    """[(label, count, url)] for the records the person may see; tiles are (label, model, url name)."""
    return [
        {'label': label, 'count': model.objects.count(), 'url': reverse(url_name)}
        for label, model, url_name in tiles
        if user.has_perm(f'{model._meta.app_label}.view_{model._meta.model_name}')
    ]


def home(request):
    """The company's overview."""
    return render(request, 'home.html', {
        'tiles': _counts(request.user, (_('Sites'), Site, 'farm:site_list')),
    })


def production_home(request):
    """The production overview: the stock now (units with fish, fish, biomass, from the ledger), the feed
    given (today, the last 7 days), the units with a critical water value and the tasks due today and overdue,
    then the farm's structure."""
    return render(request, 'production_home.html', {
        'stock_tiles': overview_tiles(request.user),
        'feeding_tiles': feeding_tiles(request.user),
        'water_tiles': water_tiles(request.user),
        'task_tiles': task_tiles(request.user),
        'tiles': _counts(request.user,
                         (_('Production departments'), ProductionDepartment, 'farm:productiondepartment_list'),
                         (_('Systems'), System, 'farm:system_list'),
                         (_('Equipment'), Equipment, 'farm:equipment_list'),
                         (_('Tanks, ponds & cages'), Tank, 'farm:tank_list')),
        'systems_by_status': [
            {'value': value, 'label': label, 'count': System.objects.filter(status=value).count()}
            for value, label in System.Status.choices
        ] if request.user.has_perm('farm.view_system') else [],
        'units_by_kind': [
            {'value': value, 'label': label, 'count': Tank.objects.filter(kind=value).count(),
             'url': f"{reverse('farm:tank_list')}?kind={value}"}
            for value, label in Tank.Kind.choices
        ] if request.user.has_perm('farm.view_tank') else [],
    })
