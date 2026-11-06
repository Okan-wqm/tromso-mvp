"""Who is notified of an alarm at a level (the recipient rules, alarms.models.RecipientRule): every live, active rule of that
level whose site and production department are the alarm's or every one, and whose least severity the alarm reaches; its
role's active members or its person, if active; with `on_shift_only`, only those on shift now (hr.read.on_shift). A person
reached by several rules is notified once, by the first."""
from django.contrib.auth import get_user_model
from django.db.models import Q

from hr import read as hr_read

from .models import RANK, RecipientRule


def _reaching(alarm):
    """The live, active rules whose site, department and least severity reach the alarm, at any level."""
    reached = [severity for severity, rank in RANK.items() if rank <= RANK[alarm.severity]]
    return (RecipientRule.objects.filter(is_active=True, min_severity__in=reached)
            .filter(Q(site__isnull=True) | Q(site=alarm.site_id))
            .filter(Q(production_department__isnull=True) | Q(production_department=alarm.production_department_id)))


def rules(alarm, level):
    """The rules of `level` that reach the alarm."""
    return _reaching(alarm).filter(level=level).select_related('role', 'user').order_by('created_at', 'id')


def next_level(alarm, level):
    """The first level above `level` with a rule that reaches the alarm, or None."""
    return _reaching(alarm).filter(level__gt=level).order_by('level').values_list('level', flat=True).first()


def recipients(alarm, level, now):
    """[(user, rule)] notified of the alarm at `level`, each person once, by username."""
    found = {}
    on_shift = None
    for rule in rules(alarm, level):
        people = ([rule.user] if rule.user_id else
                  list(get_user_model().objects.filter(groups=rule.role_id).order_by('username')))
        if rule.on_shift_only:
            on_shift = hr_read.on_shift(now) if on_shift is None else on_shift
            people = [person for person in people if person.pk in on_shift]
        for person in people:
            if person.is_active and person.pk not in found:
                found[person.pk] = (person, rule)
    return sorted(found.values(), key=lambda pair: pair[0].get_username())
