"""The HR demonstration company: a site on Oslo time, two production departments, an office department, people placed
in them, shifts, a week of plans, leave and a presence. One implementation, two commands of different kinds (README,
Management commands), each behind its own guard:

- `seed_hr_demo` (dev, core/management/devtool.py): on a developer's database, with the demonstration's sign-ins of a
  known password (the leads manage their departments, the staff member files their own leave);
- `seed_stack_proof` (stack, core/management/stackproof.py): on the go-live stack's own database only, with no
  sign-in at all: every record is written by the account the stack names (its first admin).

Not a command: a module of the app beside sensors/demo.py, so the layering audit counts its own writes (the reference
rows made with get_or_create and the departments' managers: core/tests_data_access.py, WRITES_ALLOWED). It writes only
when one of those two commands calls it, each behind its guard. The people and what follows are written through
hr.services, the one writer of those records: every rule runs and every record is logged."""
from datetime import date, time, timedelta

from django.db import transaction
from django.utils import timezone

from farm.models import ProductionDepartment, Site
from farm.stock.dates import site_today

from . import services
from .models import Employee, Holiday, LeaveType, OfficeDepartment, Shift

# (number, the demonstration's account it belongs to, first name, last name, department, title). With the account
# there, the person is the account's (their name is the account's); without it, a person with the name given here.
ROSTER = (
    ('D-01', 'demo_lead_hatchery', 'Hanne', 'Hatchery', 'DEMO-HAT', 'Hatchery lead'),
    ('D-02', 'demo_lead_nursery', 'Nils', 'Nursery', 'DEMO-NUR', 'Nursery lead'),
    ('D-03', 'demo_staff', 'Siri', 'Staff', 'DEMO-HAT', 'Technician'),
    ('D-04', None, 'Bjorn', 'Brekke', 'DEMO-HAT', 'Feeder'),
    ('D-05', None, 'Marte', 'Moe', 'DEMO-HAT', 'Feeder'),
    ('D-06', None, 'Nora', 'Nilsen', 'DEMO-NUR', 'Technician'),
    ('D-07', None, 'Olav', 'Opsahl', 'DEMO-NUR', 'Student helper'),
    ('D-08', 'demo_hr', 'Hilde', 'Resources', 'DEMO-FIN', 'HR officer'),
    ('D-09', None, 'Frida', 'Foss', 'DEMO-FIN', 'Accountant'),
)


def build(by, accounts=None):
    """The company, idempotent. `by` writes every record no demonstration account writes; `accounts` ({username:
    user}, the demonstration's sign-ins) are given only on a developer's database: then the leads manage their
    departments, the people of an account are that account's, the staff member files their own leave and a lead
    enters the presence. Returns {employee number: Employee}."""
    accounts = accounts or {}

    def who(username):
        return accounts.get(username, by)

    with transaction.atomic():
        site, _ = Site.objects.get_or_create(code='DEMO-FJORD',
                                             defaults={'name': 'Demo Fjord', 'timezone': 'Europe/Oslo'})
        departments = {
            'DEMO-HAT': _department(site, 'DEMO-HAT', 'Demo Hatchery', accounts.get('demo_lead_hatchery')),
            'DEMO-NUR': _department(site, 'DEMO-NUR', 'Demo Nursery', accounts.get('demo_lead_nursery')),
            'DEMO-FIN': OfficeDepartment.objects.get_or_create(code='DEMO-FIN',
                                                               defaults={'name': 'Demo Finance', 'site': site})[0],
        }
        people = _people(who('demo_hr'), accounts, departments)
        _time(who, people)
    return people


def _department(site, code, name, manager):
    department, _ = ProductionDepartment.objects.get_or_create(code=code, defaults={'site': site, 'name': name})
    if manager is not None:
        ProductionDepartment.objects.filter(pk=department.pk).update(manager=manager)
        department.refresh_from_db()
    return department


def _people(hr_admin, accounts, departments):
    """The HR administrator takes the people on and places them."""
    start = date(2026, 1, 1)
    people = {}
    for number, username, first, last, department, title in ROSTER:
        account = accounts.get(username) if username else None
        kind = 'student' if title == 'Student helper' else 'staff'
        person = Employee.objects.filter(employee_number=number).first()
        if person is None:
            person = services.add_employee(hr_admin, {
                'employee_number': number, 'user': account, 'first_name': '' if account else first,
                'last_name': '' if account else last, 'joined_on': start, 'employment_type': kind},
                (departments[department], title, start))
        elif not person.postings.exists():
            services.move(hr_admin, person, departments[department], title, start)
        people[number] = person
    return people


def _time(who, people):
    """Shifts, this week planned, a holiday, two leave types, a leave request and one presence entered by hand."""
    today = site_today(None)
    monday = today - timedelta(days=today.weekday())
    shifts = {}
    for code, name, start, end, tone in (('EARLY', 'Early', time(6), time(14), 2), ('LATE', 'Late', time(14), time(22), 3),
                                         ('NIGHT', 'Night', time(22), time(6), 4)):
        shifts[code], _ = Shift.objects.get_or_create(code=code, defaults={
            'name': name, 'starts_at': start, 'ends_at': end, 'break_minutes': 30 if code != 'NIGHT' else 0, 'tone': tone})
    week = [monday + timedelta(days=n) for n in range(5)]
    for number, code in (('D-03', 'EARLY'), ('D-04', 'EARLY'), ('D-05', 'LATE'), ('D-06', 'EARLY'), ('D-07', 'LATE')):
        planned = set(people[number].assignments.filter(day__in=week).values_list('day', flat=True))
        cells = [(people[number], day) for day in week if day not in planned]
        if cells:
            services.plan_shifts(who('demo_hr'), cells, shifts[code])
    Holiday.objects.get_or_create(day=date(today.year, 12, 25), site=None, defaults={'name': 'Christmas Day'})
    annual, _ = LeaveType.objects.get_or_create(code='DEMO-ANNUAL', defaults={'name': 'Annual leave'})
    LeaveType.objects.get_or_create(code='DEMO-SICK', defaults={'name': 'Sick leave', 'needs_approval': False})
    first = monday + timedelta(days=21)
    if not people['D-03'].leave_requests.exists():
        services.file_leave(who('demo_staff'), people['D-03'], annual, first, first + timedelta(days=3), 'Visiting family')
    if not people['D-04'].attendance.exists():
        services.enter_presence(who('demo_lead_hatchery'), people['D-04'], timezone.now() - timedelta(minutes=5), None,
                                'Demonstration: came in through the gate without a phone')
