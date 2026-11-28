from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import transaction

from core.management.devtool import DevCommand

from hr import demo_company

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
            demo_company.build(users['demo_hr'], users)       # the company (hr/demo_company.py)
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
