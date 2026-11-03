"""The place of a task as a choice: one list of every live place, grouped by kind (a whole site, production
departments, systems, units, equipment), each option a token `kind:<id>` that belongs to its site. The
form's Site field narrows it (core.widgets.DependentSelect; a place without a site belongs to NONE,
"Without a site"), and the server turns the token back into the one link it names (`find`). The source's
place was free text typed into a box (TSK-01)."""
import uuid

from django.db.models import F
from django.utils.translation import gettext, gettext_lazy as _

from core.widgets import NONE
from farm.models import Equipment, ProductionDepartment, Site, System, Tank

# kind in a token → (the model, the task's link, how a group of them is called)
KINDS = {
    'site': (Site, 'site', _('Whole site')),
    'department': (ProductionDepartment, 'production_department', _('Production departments')),
    'system': (System, 'system', _('Systems')),
    'unit': (Tank, 'unit', _('Units')),
    'equipment': (Equipment, 'equipment', _('Equipment')),
}


def token(place):
    """'unit:<id>' for a unit, and so on; '' for none."""
    if place is None:
        return ''
    kind = next(kind for kind, (model, _field, _label) in KINDS.items() if isinstance(place, model))
    return f'{kind}:{place.pk}'


def field_of(place):
    """The link of a task that points at this kind of place ('unit')."""
    return next(field for model, field, _label in KINDS.values() if isinstance(place, model))


def site_of(place):
    """The site a place is on: the site itself, a system's site, else the site of the production department of
    the department, unit or equipment (None when it has none)."""
    if place is None or isinstance(place, Site):
        return place
    if isinstance(place, System):
        return place.site
    department = place if isinstance(place, ProductionDepartment) else place.production_department
    return department.site


def site_key(place):
    """The value of the Site field a place belongs to: its site's id, or NONE."""
    site = site_of(place)
    return str(site.pk) if site is not None else NONE


def label(place):
    """How a place reads in a list: a site by its name, a department by its name, a system or a unit by its code
    and name, equipment by its name and code."""
    if isinstance(place, (System, Tank)):
        return f'{place.code} · {place.name}'
    if isinstance(place, Site):
        return place.name
    return str(place) if isinstance(place, Equipment) else place.name


def context(place):
    """The line under a place: where it is (its production department and site), or "Whole site"."""
    if isinstance(place, Site):
        return gettext('Whole site')
    if isinstance(place, System):
        return place.site.name
    department = place if isinstance(place, ProductionDepartment) else place.production_department
    parts = [] if department is place else [department.name]
    parts.append(department.site.name if department.site_id else gettext('No site'))
    return ' · '.join(parts)


def kind_label(place):
    """What kind of place it is, in the singular."""
    return {Site: _('Site'), ProductionDepartment: _('Production department'), System: _('System'),
            Tank: _('Unit'), Equipment: _('Equipment')}[type(place)]


def live():
    """Every live place, grouped by kind, each kind in the order a person looks for it."""
    return {
        'site': list(Site.objects.order_by('name')),
        'department': list(ProductionDepartment.objects.select_related('site').order_by(
            F('site__name').asc(nulls_last=True), 'name')),
        'system': list(System.objects.select_related('site').order_by('site__name', 'code')),
        'unit': list(Tank.objects.select_related('production_department__site').order_by(
            F('production_department__site__name').asc(nulls_last=True), 'code')),
        'equipment': list(Equipment.objects.select_related('production_department__site').order_by(
            F('production_department__site__name').asc(nulls_last=True), 'name')),
    }


def choices(places):
    """The grouped choices of a Location select, and {token: the Site value it belongs to} for DependentSelect
    (None for a place without a site, which the Site field offers as NONE)."""
    grouped, belongs = [], {}
    for kind, records in places.items():
        options = []
        for place in records:
            value = token(place)
            site = site_of(place)
            belongs[value] = str(site.pk) if site is not None else None
            options.append((value, label(place) if kind == 'site' else f'{label(place)} — {context(place)}'))
        if options:
            grouped.append((KINDS[kind][2], options))
    return grouped, belongs


def find(value, places=None):
    """The live place a token names; None for anything else (a stale, deleted or malformed choice). With
    `places` (from `live`), only those."""
    kind, _sep, pk = (value or '').partition(':')
    if kind not in KINDS:
        return None
    try:
        pk = uuid.UUID(pk)
    except ValueError:
        return None
    if places is not None:
        return next((place for place in places[kind] if place.pk == pk), None)
    model = KINDS[kind][0]
    return model.objects.filter(pk=pk).first()
