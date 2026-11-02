from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from farm.models import ProductionDepartment, Site, System


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
    """The production overview."""
    return render(request, 'production_home.html', {
        'tiles': _counts(request.user,
                         (_('Production departments'), ProductionDepartment, 'farm:productiondepartment_list'),
                         (_('Systems'), System, 'farm:system_list')),
        'systems_by_status': [
            {'value': value, 'label': label, 'count': System.objects.filter(status=value).count()}
            for value, label in System.Status.choices
        ] if request.user.has_perm('farm.view_system') else [],
    })
