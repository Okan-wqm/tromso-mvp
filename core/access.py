"""Access areas as data: the parts of the console a role can be given and which of the model's
standard permissions (view/add/change/delete) each offers. The project's areas live in
config/access.py; the role form shows them as a matrix (core.forms.PermissionMatrix).

Read is implied by every other action: a role that may edit sites may also see them. Permissions no
area offers (roles and users among them) cannot be given to a role, so only the platform admin has
them."""
from dataclasses import dataclass
from functools import reduce
from operator import or_

from django.apps import apps
from django.conf import settings
from django.contrib.auth.models import Permission
from django.db.models import Q
from django.utils.module_loading import import_string

# The matrix columns: (action, column label).
ACTIONS = [('view', 'Read'), ('add', 'Create'), ('change', 'Edit'), ('delete', 'Delete')]
READ = 'view'


@dataclass(frozen=True)
class Area:
    group: str            # matrix section, e.g. 'Facility' (as in the rail menu)
    label: str            # 'Sites'
    model: str            # 'farm.Site'
    actions: tuple = ('view', 'add', 'change', 'delete')

    def perm(self, action):
        meta = apps.get_model(self.model)._meta
        return f'{meta.app_label}.{action}_{meta.model_name}'


def areas():
    return import_string(settings.ACCESS_AREAS)


def perm_name(permission):
    """'farm.view_site' for a Permission row, as user.has_perm spells it."""
    return f'{permission.content_type.app_label}.{permission.codename}'


def permissions():
    """The Permission rows the matrix offers."""
    names = [area.perm(action).split('.') for area in areas() for action in area.actions]
    condition = reduce(or_, (Q(content_type__app_label=app, codename=codename) for app, codename in names),
                       Q(pk__in=[]))
    return Permission.objects.filter(condition).select_related('content_type')


def implied(names):
    """The permission names plus Read on every area for which another action is chosen."""
    names = set(names)
    for area in areas():
        if READ in area.actions and any(area.perm(action) in names for action in area.actions):
            names.add(area.perm(READ))
    return names


def summary(permissions):
    """What the permissions allow, area by area: 'Sites: read, create; Activity log: read'."""
    names = {perm_name(permission) for permission in permissions}
    parts = []
    for area in areas():
        allowed = [label.lower() for action, label in ACTIONS
                   if action in area.actions and area.perm(action) in names]
        if allowed:
            parts.append(f'{area.label}: {", ".join(allowed)}')
    return '; '.join(parts)
