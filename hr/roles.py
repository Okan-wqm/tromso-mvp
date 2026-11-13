"""The production roles as data: two starting points for Company › Administration › Roles, made by `manage.py hr_roles` (never
on migrate: nothing is seeded on migrate, and a migration would overwrite what an administrator decided). A role that exists
already is left as it is, whatever was changed in it. Every permission is one the role matrix offers (core.access), so an
administrator can read and change each one there.

- Production manager: Today & attendance (and the Attendance history: the same right) with entering presence by hand and
  correcting a stretch (closing a forgotten clock-out), the Shift schedule with planning and clearing a day, Leave requests
  with deciding, for every production person (All production: a department without a manager too). No voiding of a
  stretch, no Team list, no chart, no settings, no office people, no leave reason. The owner added clearing a day and
  entering and correcting attendance on 2026-11-10 (F-203); migration hr/0012 gives them to a role made before.
- Production worker: their own Today (clock in and out), their own week with the Crew block, their own leave requests."""
from dataclasses import dataclass

from django.contrib.auth.models import Group, Permission
from django.db import transaction


@dataclass(frozen=True)
class Preset:
    name: str
    permissions: tuple       # 'app.codename', as user.has_perm spells them


PRESETS = (
    Preset('Production manager', (
        'hr.view_attendancerecord', 'hr.add_attendancerecord', 'hr.change_attendancerecord',
        'hr.view_shiftassignment', 'hr.add_shiftassignment', 'hr.change_shiftassignment', 'hr.delete_shiftassignment',
        'hr.view_leaverequest', 'hr.add_leaverequest', 'hr.change_leaverequest', 'hr.all_production_employee')),
    Preset('Production worker', (
        'hr.view_attendancerecord', 'hr.view_shiftassignment', 'hr.crew_shiftassignment', 'hr.view_leaverequest',
        'hr.add_leaverequest')),
)


def permission(name):
    app, codename = name.split('.')
    return Permission.objects.get(content_type__app_label=app, codename=codename)


def create():
    """Makes each preset that does not exist yet. Returns [(name, created)]."""
    done = []
    with transaction.atomic():
        for preset in PRESETS:
            group, created = Group.objects.get_or_create(name=preset.name)
            if created:
                group.permissions.set([permission(name) for name in preset.permissions])
            done.append((preset.name, created))
    return done
