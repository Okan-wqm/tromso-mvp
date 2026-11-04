"""Whose records a person may reach in HR: their team. The role matrix gives the verbs; this gives the rows, and it is
the only place that says who is in whose team (core.crud.Resource.scoped asks it, and so does every read that
lists people).

A person's team is themselves (the employee row of their account), plus the people placed, on the day asked, in a
production department they manage (the department's Manager) or in an office department they manage or any
department below it. A holder of Everyone (`hr.all_employee`) has every employee. A manager without a role that
gives the HR pages, or a role without a department, reaches nothing beyond themselves: the role is the verb, the
department the rows."""
from datetime import timedelta

from django.db.models import Q

from farm.stock.dates import site_today

from .models import Employee, OfficeDepartment, Posting

ALL = 'hr.all_employee'


def covering(day):
    """The placements in force on `day`."""
    return Q(valid_from__lte=day) & (Q(valid_until__isnull=True) | Q(valid_until__gte=day))


def office_departments_below(managed):
    """The ids of `managed` (a list of office departments) and of every department below them."""
    found, frontier = {department.pk for department in managed}, [department.pk for department in managed]
    while frontier:
        frontier = [pk for pk in OfficeDepartment.objects.filter(parent__in=frontier).values_list('pk', flat=True)
                    if pk not in found]
        found.update(frontier)
    return found


def team(user, day=None):
    """The employees `user` may reach on `day` (the company's today by default): live rows only. Path joins
    bypass the soft-delete manager, so a deleted department or placement is left out explicitly."""
    if user.has_perm(ALL):
        return Employee.objects.all()
    day = day or site_today(None)
    managed_production = Q(production_department__manager=user, production_department__is_deleted=False)
    managed_office = OfficeDepartment.objects.filter(manager=user)
    placed = Q()
    placed |= managed_production
    below = office_departments_below(list(managed_office))
    if below:
        placed |= Q(office_department__in=below)
    members = Posting.objects.filter(placed & covering(day)).values('employee')
    return Employee.objects.filter(Q(user=user) | Q(pk__in=members))


def can_reach(user, employee, day=None):
    return team(user, day).filter(pk=employee.pk).exists()


def visible_days(user, first, last):
    """{employee id: the days between `first` and `last` the user may reach them on}, for the reads that run over
    several days (the week's roster, the overview): a person is the viewer's on the days a placement in a department
    they manage covers (so a person who moved is the old manager's up to the move and the new one's from it), and
    always on all days for the viewer themselves. A holder of Everyone reaches every employee on every day: None."""
    if user.has_perm(ALL):
        return None
    days = {}
    each = [first + timedelta(days=n) for n in range((last - first).days + 1)]
    for employee_id in Employee.objects.filter(user=user).values_list('pk', flat=True):
        days[employee_id] = set(each)
    managed_production = Q(production_department__manager=user, production_department__is_deleted=False)
    below = office_departments_below(list(OfficeDepartment.objects.filter(manager=user)))
    placed = managed_production | (Q(office_department__in=below) if below else Q())
    overlapping = Q(valid_from__lte=last) & (Q(valid_until__isnull=True) | Q(valid_until__gte=first))
    for posting in Posting.objects.filter(placed & overlapping).values('employee', 'valid_from', 'valid_until'):
        start = max(posting['valid_from'], first)
        end = min(posting['valid_until'] or last, last)
        days.setdefault(posting['employee'], set()).update(
            start + timedelta(days=n) for n in range((end - start).days + 1))
    return days
