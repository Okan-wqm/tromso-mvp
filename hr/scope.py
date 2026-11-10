"""Whose records a person may reach in HR: their team. The role matrix gives the verbs; this gives the rows, and it is
the only place that says who is in whose team (core.crud.Resource.scoped asks it, and so does every read that
lists people).

A person's team is themselves (the employee row of their account), plus the people placed, on the day asked, in a
production department they manage (the department's Manager) or in an office department they manage or any
department below it. A holder of Everyone (`hr.all_employee`) has every employee. A manager without a role that
gives the HR pages, or a role without a department, reaches nothing beyond themselves: the role is the verb, the
department the rows.

The realm splits the same people between the two panels: production people are those placed, on the day asked, in a
live production department (Production › Team); everyone else is the office's (Company › HR), so an unplaced person
is never lost. It is read from the placements, never stored, and only narrows the reach above: `realm=None` is the
reach as it is."""
from datetime import timedelta

from django.db.models import Exists, OuterRef, Q

from farm.stock.dates import site_today

from .models import Employee, OfficeDepartment, Posting

ALL = 'hr.all_employee'
ALL_PRODUCTION = 'hr.all_production_employee'
PRODUCTION, OFFICE = 'production', 'office'

# A placement in a live production department: what makes a person a production person on its days.
IN_PRODUCTION = Q(production_department__isnull=False, production_department__is_deleted=False)


def covering(day):
    """The placements in force on `day`."""
    return Q(valid_from__lte=day) & (Q(valid_until__isnull=True) | Q(valid_until__gte=day))


def overlapping(first, last):
    """The placements in force on some day between `first` and `last`."""
    return Q(valid_from__lte=last) & (Q(valid_until__isnull=True) | Q(valid_until__gte=first))


def _placed_in_production(employee, day):
    """Whether `employee` (a reference) has a live placement in a live production department on `day` (a date or a
    reference): the one test of the realm."""
    return Exists(Posting.objects.filter(covering(day), IN_PRODUCTION, employee=employee))


def producing(day):
    """Employees in production on `day`."""
    return Q(_placed_in_production(OuterRef('pk'), day))


def in_realm(realm, day):
    """Employees in `realm` on `day`: production, or the office (everyone not in production); no narrowing for None."""
    if realm is None:
        return Q()
    if realm == PRODUCTION:
        return producing(day)
    if realm == OFFICE:
        return ~producing(day)
    raise ValueError(f'Unknown realm {realm!r}')


def production_people(day):
    return Employee.objects.filter(producing(day))


def office_departments_below(managed):
    """The ids of `managed` (a list of office departments) and of every department below them."""
    found, frontier = {department.pk for department in managed}, [department.pk for department in managed]
    while frontier:
        frontier = [pk for pk in OfficeDepartment.objects.filter(parent__in=frontier).values_list('pk', flat=True)
                    if pk not in found]
        found.update(frontier)
    return found


def managed_departments(user):
    """The departments whose placements `user` manages, as (production departments, office department ids): the live
    production departments they are the Manager of, and the office departments they manage with every one below them. A
    holder of All production manages every live production department: a department without a manager (a new one, or one
    whose manager's account is gone) is never left out of their roster. It gives no office department."""
    from farm.models import ProductionDepartment
    production = ProductionDepartment.objects.all()
    if not user.has_perm(ALL_PRODUCTION):
        production = production.filter(manager=user)
    return production, office_departments_below(list(OfficeDepartment.objects.filter(manager=user)))


def managed(user):
    """The placements `user` manages: those in a department of `managed_departments` (a deleted department gives none).
    Being no Everyone, it gives no leave reason."""
    production, below = managed_departments(user)
    placed = Q(production_department__in=production)
    return placed | Q(office_department__in=below) if below else placed


def placeable(user):
    """A test of a department (production or office): whether `user` may place people in it. A holder of Everyone in any,
    anyone else in one of `managed_departments`, the departments whose people they reach. Read once, asked per department
    (the person form's chooser)."""
    if user.has_perm(ALL):
        return lambda department: True
    production, below = managed_departments(user)
    production = set(production.values_list('pk', flat=True))
    return lambda department: department.pk in (below if isinstance(department, OfficeDepartment) else production)


def can_manage(user, department):
    return placeable(user)(department)


def by_day(user, objects, employee='employee', day='day', realm=None):
    """`objects` (records of a person, dated by the field `day`) narrowed to those whose person the user reached ON THAT DAY:
    a record belongs to the manager of the department the person was placed in on its day, so a person who moved leaves
    their old records with the old manager. A holder of Everyone reaches all; a person always reaches their own. With a
    realm, only the records whose person was in it on the record's day."""
    if realm is not None:
        inside = _placed_in_production(OuterRef(f'{employee}_id'), OuterRef(day))
        objects = objects.filter(inside if realm == PRODUCTION else ~inside)
    if user.has_perm(ALL):
        return objects
    placed = Posting.objects.filter(managed(user), employee=OuterRef(f'{employee}_id'), valid_from__lte=OuterRef(day)).filter(
        Q(valid_until__isnull=True) | Q(valid_until__gte=OuterRef(day)))
    return objects.filter(Q(**{f'{employee}__user': user}) | Exists(placed))


def stretches(user, objects, realm=None, day='clocked_day'):
    """Attendance stretches (annotated with their `day`) that `user` reaches: a stretch belongs to the manager of the
    department the person was placed in on its day (`by_day`), and while it is still open also to whoever reaches the
    person today. An open stretch is today's business: a person who moved since they clocked in is told to ask their
    lead, and their lead of today is who closes a forgotten clock-out (review R9). Once closed it is history of its day."""
    still_open = Q(clock_out__isnull=True, employee__in=team(user, realm=realm).values('pk'))
    return objects.filter(Q(pk__in=by_day(user, objects, 'employee', day, realm).values('pk')) | still_open)


def team(user, day=None, realm=None):
    """The employees `user` may reach on `day` (the company's today by default), only those in `realm` that day if one is
    given: live rows only. Path joins bypass the soft-delete manager, so a deleted department or placement is left out
    explicitly."""
    day = day or site_today(None)
    if user.has_perm(ALL):
        people = Employee.objects.all()
    else:
        members = Posting.objects.filter(managed(user) & covering(day)).values('employee')
        people = Employee.objects.filter(Q(user=user) | Q(pk__in=members))
    return people.filter(in_realm(realm, day)) if realm is not None else people


def can_reach(user, employee, day=None):
    return team(user, day).filter(pk=employee.pk).exists()


def _days(first, last):
    return [first + timedelta(days=n) for n in range((last - first).days + 1)]


def _placed_days(postings, first, last):
    """{employee id: the days between `first` and `last` that `postings` (placements) cover}."""
    days = {}
    for posting in postings.filter(overlapping(first, last)).values('employee', 'valid_from', 'valid_until'):
        days.setdefault(posting['employee'], set()).update(
            _days(max(posting['valid_from'], first), min(posting['valid_until'] or last, last)))
    return days


def visible_days(user, first, last, realm=None):
    """{employee id: the days between `first` and `last` the user may reach them on}, for the reads that run over
    several days (the week's roster, the overview): a person is the viewer's on the days a placement in a department
    they manage covers (so a person who moved is the old manager's up to the move and the new one's from it), and
    always on all days for the viewer themselves. A holder of Everyone reaches every employee on every day: None.
    With a realm, only the days each person was in it, and a person left with no day is left out (for Everyone too)."""
    if user.has_perm(ALL):
        days = None
    else:
        days = {employee_id: set(_days(first, last))
                for employee_id in Employee.objects.filter(user=user).values_list('pk', flat=True)}
        for employee_id, placed in _placed_days(Posting.objects.filter(managed(user)), first, last).items():
            days.setdefault(employee_id, set()).update(placed)
    if realm is None:
        return days
    production = _placed_days(Posting.objects.filter(IN_PRODUCTION), first, last)
    if days is None:
        everyone = Employee.objects.values_list('pk', flat=True) if realm == OFFICE else list(production)
        days = {employee_id: set(_days(first, last)) for employee_id in everyone}
    narrowed = {employee_id: (reached & production.get(employee_id, set()) if realm == PRODUCTION
                              else reached - production.get(employee_id, set()))
                for employee_id, reached in days.items()}
    return {employee_id: reached for employee_id, reached in narrowed.items() if reached}


def production_days(user, first, last):
    """{day: production department} of the viewer's own live placements in production between `first` and `last`: the
    days the viewer has a crew on (empty for a viewer with no production placement then)."""
    own = list(Employee.objects.filter(user=user).values_list('pk', flat=True))
    department_on = {}
    for posting in Posting.objects.filter(IN_PRODUCTION, overlapping(first, last), employee__in=own).values(
            'production_department', 'valid_from', 'valid_until'):
        for day in _days(max(posting['valid_from'], first), min(posting['valid_until'] or last, last)):
            department_on[day] = posting['production_department']
    return department_on


def colleagues(user, first, last):
    """{employee id: days} of the viewer's crew between `first` and `last`: on each day of the viewer's own live placement in
    a production department, the other live people placed in the same department that day, less the days the viewer
    already reaches them on (their own team, `visible_days`). Empty for a viewer with no production placement. Only the
    crew's shift plan is read with it (hr.read.crew_week), never anything else of theirs."""
    department_on = production_days(user, first, last)
    if not department_on:
        return {}
    own = list(Employee.objects.filter(user=user).values_list('pk', flat=True))
    reached = visible_days(user, first, last, PRODUCTION) or {}
    crew = {}
    for posting in Posting.objects.filter(overlapping(first, last), employee__is_deleted=False,
                                          production_department__in=set(department_on.values())).exclude(
            employee__in=own).values('employee', 'production_department', 'valid_from', 'valid_until'):
        for day in _days(max(posting['valid_from'], first), min(posting['valid_until'] or last, last)):
            if department_on.get(day) == posting['production_department'] and day not in reached.get(posting['employee'], ()):
                crew.setdefault(posting['employee'], set()).add(day)
    return crew


# ---- menu courtesies: which menu lines a person is shown, never what they may open -------------------------------------
def leads(user):
    """Whether the person leads production people: a holder of Everyone or All production, or the manager of a live
    production department (Production › Team overview is shown to them)."""
    from farm.models import ProductionDepartment
    return (user.has_perm(ALL) or user.has_perm(ALL_PRODUCTION)
            or ProductionDepartment.objects.filter(manager=user).exists())


def production_only(user, day=None):
    """Whether the person's HR is all in Production: placed in production on `day`, without Everyone, managing no office
    department. Their Company › HR lines would repeat Production › Team, so the menu leaves them out."""
    if user.has_perm(ALL) or OfficeDepartment.objects.filter(manager=user).exists():
        return False
    return Employee.objects.filter(producing(day or site_today(None)), user=user).exists()


def not_production_only(user, day=None):
    return not production_only(user, day)


def realm_of(mount):
    """The realm of the panel a page is served in (core.crud.Mount): Production › Team's mount is the production realm, and
    Company › HR (no mount) is the office's."""
    return mount.key if mount is not None else OFFICE


def realm_for(request):
    """The realm of the page a request is for (its mount, core.crud.mount_of)."""
    from core.crud import mount_of
    return realm_of(mount_of(request))
