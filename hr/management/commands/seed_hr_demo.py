from datetime import date, time, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import transaction

from core.management.devtool import DevCommand
from farm.models import ProductionDepartment, Site
from farm.stock.dates import site_today

from ...models import (AttendanceRecord, Employee, Holiday, LeaveRequest, LeaveType, OfficeDepartment, Posting,
                       Shift, ShiftAssignment)

PASSWORD = 'demo-password-1'

HR_AREAS = ('employee', 'officedepartment', 'shiftassignment', 'attendancerecord', 'leaverequest', 'leavetype', 'shift',
            'holiday', 'schedulingsettings')
# The roles of the live walk-through, made here like any role is made in the UI: the matrix columns, nothing else.
ROLES = {
    # a team lead: reads their team and the departments, plans, enters presence, files and decides leave; no Everyone, no settings
    'Demo lead': ['view_employee', 'view_officedepartment', 'view_shiftassignment', 'add_shiftassignment',
                  'change_shiftassignment', 'delete_shiftassignment', 'view_attendancerecord', 'add_attendancerecord',
                  'change_attendancerecord', 'delete_attendancerecord', 'view_leaverequest', 'add_leaverequest',
                  'change_leaverequest', 'view_auditlog'],
    # staff: read and file their own, read the schedule
    'Demo staff': ['view_attendancerecord', 'view_leaverequest', 'add_leaverequest', 'view_shiftassignment'],
    # HR administration: every HR area and Everyone
    'Demo HR admin': [f'{action}_{area}' for area in HR_AREAS for action in ('view', 'add', 'change', 'delete')
                      if not (area == 'schedulingsettings' and action in ('add', 'delete'))
                      and not (area in ('leaverequest', 'employee') and action == 'delete')]
                     + ['all_employee', 'view_auditlog'],
    # the auditor: reads everything HR holds, including the log
    'Demo auditor': [f'view_{area}' for area in HR_AREAS] + ['all_employee', 'view_auditlog'],
}


class Command(DevCommand):
    forcible = False        # it makes accounts with a known password: never with DEBUG off, not even when told twice

    help = ('Makes a small demonstration company in the HR area for walking through it in a browser: a site on Oslo time, two '
            'production departments with their managers, an office department, people placed in them, shifts, a week of plans, '
            'leave and four roles with a sign-in each. Idempotent. It refuses to run unless DEBUG is on: it makes accounts '
            'with a known password.')

    def handle(self, *args, **options):
        with transaction.atomic():
            groups = self.roles()
            users = self.users(groups)
            site = self.company()
            people = self.people(users, site)
            self.time(people)
        self.stdout.write(f'HR demo ready. Sign in as demo_lead_hatchery, demo_lead_nursery, demo_staff, demo_hr or demo_auditor '
                          f'with the password {PASSWORD}.')

    def roles(self):
        groups = {}
        for name, codenames in ROLES.items():
            group, _ = Group.objects.get_or_create(name=name)
            group.permissions.set(Permission.objects.filter(content_type__app_label__in=('hr', 'core'),
                                                            codename__in=codenames))
            groups[name] = group
        return groups

    def users(self, groups):
        users = {}
        for username, role, first, last in (
                ('demo_lead_hatchery', 'Demo lead', 'Hanne', 'Hatchery'), ('demo_lead_nursery', 'Demo lead', 'Nils', 'Nursery'),
                ('demo_staff', 'Demo staff', 'Siri', 'Staff'), ('demo_hr', 'Demo HR admin', 'Hilde', 'Resources'),
                ('demo_auditor', 'Demo auditor', 'Arne', 'Auditor')):
            user, created = get_user_model().objects.get_or_create(username=username, defaults={
                'email': f'{username}@example.com', 'first_name': first, 'last_name': last})
            if created:
                user.set_password(PASSWORD)
                user.save()
            user.groups.set([groups[role]])
            users[username] = user
        return users

    def company(self):
        site, _ = Site.objects.get_or_create(code='DEMO-FJORD', defaults={'name': 'Demo Fjord', 'timezone': 'Europe/Oslo'})
        return site

    def department(self, site, code, name, manager):
        department, _ = ProductionDepartment.objects.get_or_create(code=code, defaults={'site': site, 'name': name})
        ProductionDepartment.objects.filter(pk=department.pk).update(manager=manager)
        department.refresh_from_db()
        return department

    def people(self, users, site):
        hatchery = self.department(site, 'DEMO-HAT', 'Demo Hatchery', users['demo_lead_hatchery'])
        nursery = self.department(site, 'DEMO-NUR', 'Demo Nursery', users['demo_lead_nursery'])
        finance, _ = OfficeDepartment.objects.get_or_create(code='DEMO-FIN', defaults={'name': 'Demo Finance', 'site': site})
        start = date(2026, 1, 1)
        roster = [
            ('D-01', users['demo_lead_hatchery'], '', '', hatchery, 'Hatchery lead'),
            ('D-02', users['demo_lead_nursery'], '', '', nursery, 'Nursery lead'),
            ('D-03', users['demo_staff'], '', '', hatchery, 'Technician'),
            ('D-04', None, 'Bjorn', 'Brekke', hatchery, 'Feeder'),
            ('D-05', None, 'Marte', 'Moe', hatchery, 'Feeder'),
            ('D-06', None, 'Nora', 'Nilsen', nursery, 'Technician'),
            ('D-07', None, 'Olav', 'Opsahl', nursery, 'Student helper'),
            ('D-08', users['demo_hr'], '', '', finance, 'HR officer'),
            ('D-09', None, 'Frida', 'Foss', finance, 'Accountant'),
        ]
        people = {}
        for number, account, first, last, department, title in roster:
            kind = 'student' if title == 'Student helper' else 'staff'
            person, _ = Employee.objects.get_or_create(employee_number=number, defaults={
                'user': account, 'first_name': first, 'last_name': last, 'joined_on': start, 'employment_type': kind})
            if not Posting.objects.filter(employee=person).exists():
                field = 'production_department' if isinstance(department, ProductionDepartment) else 'office_department'
                Posting.objects.create(employee=person, valid_from=start, title=title, **{field: department})
            people[number] = person
        return people

    def time(self, people):
        today = site_today(None)
        monday = today - timedelta(days=today.weekday())
        shifts = {}
        for code, name, start, end, tone in (('EARLY', 'Early', time(6), time(14), 2), ('LATE', 'Late', time(14), time(22), 3),
                                             ('NIGHT', 'Night', time(22), time(6), 4)):
            shifts[code], _ = Shift.objects.get_or_create(code=code, defaults={
                'name': name, 'starts_at': start, 'ends_at': end, 'break_minutes': 30 if code != 'NIGHT' else 0, 'tone': tone})
        for number, code in (('D-03', 'EARLY'), ('D-04', 'EARLY'), ('D-05', 'LATE'), ('D-06', 'EARLY'), ('D-07', 'LATE')):
            for n in range(5):
                ShiftAssignment.objects.get_or_create(employee=people[number], day=monday + timedelta(days=n),
                                                      defaults={'shift': shifts[code]})
        Holiday.objects.get_or_create(day=date(today.year, 12, 25), site=None, defaults={'name': 'Christmas Day'})
        annual, _ = LeaveType.objects.get_or_create(code='DEMO-ANNUAL', defaults={'name': 'Annual leave'})
        LeaveType.objects.get_or_create(code='DEMO-SICK', defaults={'name': 'Sick leave', 'needs_approval': False})
        first = monday + timedelta(days=21)
        if not LeaveRequest.objects.filter(employee=people['D-03']).exists():
            LeaveRequest.objects.create(employee=people['D-03'], leave_type=annual, first_day=first,
                                        last_day=first + timedelta(days=3), reason='Visiting family')
        if not AttendanceRecord.objects.filter(employee=people['D-04']).exists():
            from django.utils import timezone
            AttendanceRecord.objects.create(employee=people['D-04'], clock_in=timezone.now() - timedelta(minutes=5),
                                            via='self')
