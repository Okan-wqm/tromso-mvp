"""A department as a choice: one list of every live department, the production ones (the farm's own rows) and the
office ones (HR's), each option a token `kind:<id>`, and the server turns the token back into the one row it names
(`find`). The same idea as the place of a task (tasks/places.py), with two kinds."""
import uuid

from django.utils.translation import gettext_lazy as _

from farm.models import ProductionDepartment

from .models import OfficeDepartment

KINDS = {
    'production': (ProductionDepartment, 'production_department', _('Production departments')),
    'office': (OfficeDepartment, 'office_department', _('Office departments')),
}


def token(department):
    """'production:<id>' or 'office:<id>'; '' for none."""
    if department is None:
        return ''
    kind = next(kind for kind, (model, _field, _label) in KINDS.items() if isinstance(department, model))
    return f'{kind}:{department.pk}'


def field_of(department):
    """The link of a placement that points at this kind of department."""
    return next(field for model, field, _label in KINDS.values() if isinstance(department, model))


def find(value):
    """The live department a token names; None for an empty, malformed or stale token (deleted, or not there)."""
    kind, _separator, pk = (value or '').partition(':')
    if kind not in KINDS:
        return None
    try:
        pk = uuid.UUID(pk)
    except ValueError:
        return None
    return KINDS[kind][0].objects.filter(pk=pk).first()


def label(department):
    return f'{department.name} ({department.code})'


def choices(include=()):
    """The grouped options of a chooser: [(group label, [(token, label)])]. Inactive departments are not offered for
    a new placement, except those in `include` (the one a person is placed in now)."""
    keep = {token(item) for item in include}
    groups = []
    for kind, (model, _field, group) in KINDS.items():
        rows = [department for department in model.objects.order_by('name')
                if department.status == 'active' or token(department) in keep]
        groups.append((group, [(token(department), label(department)) for department in rows]))
    return groups
