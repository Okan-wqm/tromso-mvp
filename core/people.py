"""People as the pages name and offer them: one rule for the tasks' assignees, the team of an experiment and the
messages' members."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db.models import Q


def person_name(user):
    """A person as the pages name them: their full name, else their username."""
    return user.get_full_name() or user.get_username()


def who_can(app_label, codename):
    """The people something can be for: active users who hold a permission (the platform admin among them), by
    name. Someone who cannot read a page could never see what was given to them."""
    users = get_user_model().objects
    perm = Permission.objects.filter(content_type__app_label=app_label, codename=codename)
    holders = (Q(is_superuser=True) | Q(pk__in=users.filter(groups__permissions__in=perm).values('pk'))
               | Q(pk__in=users.filter(user_permissions__in=perm).values('pk')))
    return users.filter(holders, is_active=True).order_by('first_name', 'last_name', 'username')
