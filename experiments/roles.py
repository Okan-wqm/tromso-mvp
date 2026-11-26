"""The research collaborator as data: a starting point for Company › Administration › Roles, made by `manage.py
experiments_roles` (never on migrate, as the production roles: hr.roles). An outside researcher is an ordinary account
the platform admin makes (there are no guest accounts: owner decision of 23.11.2026); the admin gives it this role, and
an experiment's lead adds the person to the experiment's team or shares a part of it with them (experiments.sealing).

- Research collaborator: Experiments: read, nothing else. The person sees the Research menu and the experiments they are
  in the team of, hold a share of, or that are open; no farm page, no list of the farm's records, no other area. The
  experiment's own pages show the figures of its tanks without the farm's rights (owner decision F-168).

The role is named in the language given (the catalogs' translation of its name); a role that exists is left as it is."""
from django.contrib.auth.models import Group, Permission
from django.db import transaction
from django.utils import translation
from django.utils.translation import gettext, gettext_noop

COLLABORATOR = gettext_noop('Research collaborator')
RIGHTS = ('experiments.view_experiment',)


def permission(name):
    app, codename = name.split('.')
    return Permission.objects.get(content_type__app_label=app, codename=codename)


def create(language='en'):
    """Makes the Research collaborator role, named in `language`, when no role has that name. Returns (name, created)."""
    with translation.override(language):
        name = gettext(COLLABORATOR)
    with transaction.atomic():
        group, created = Group.objects.get_or_create(name=name)
        if created:
            group.permissions.set([permission(right) for right in RIGHTS])
    return name, created
