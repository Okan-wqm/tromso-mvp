"""Roles saved through the matrix before its one rule (Crew, All production and Everyone include nothing) kept the Read it
added: a Production manager saved once can open the Team list. The migration puts the two presets back to exactly their
rights; a system check lists any other role whose Read on an area may come only from that old rule, for the
administrator to review (`manage.py check --database default`)."""
from importlib import import_module

from django.apps import apps
from django.contrib.auth.models import Group, Permission
from django.db import connection

from core import checks

from .. import roles
from .helpers_people import PeopleTestCase

restore = import_module('hr.migrations.0010_restore_preset_rights')


def manager_rights():
    """hr/0012: the three rights the owner added to the Production manager preset (F-203)."""
    return import_module('hr.migrations.0012_production_manager_rights')


def codenames(group):
    return {f'{p.content_type.app_label}.{p.codename}' for p in group.permissions.select_related('content_type')}


def give(group, *names):
    for name in names:
        app, codename = name.split('.')
        group.permissions.add(Permission.objects.get(content_type__app_label=app, codename=codename))


class PresetRestoreTests(PeopleTestCase):
    def test_both_presets_are_put_back_to_exactly_their_rights(self):
        """The restore (0010) and the rights the owner gave the Production manager since (0012, F-203) leave each preset
        as it is today: the Read on the Team list the old matrix rule added (F-046) is gone and stays gone."""
        roles.create()
        for preset in roles.PRESETS:
            give(Group.objects.get(name=preset.name), 'hr.view_employee')
        restore.restore(apps, None)
        with connection.schema_editor() as editor:
            manager_rights().grant(apps, editor)
        for preset in roles.PRESETS:
            self.assertEqual(codenames(Group.objects.get(name=preset.name)), set(preset.permissions), preset.name)
            self.assertNotIn('hr.view_employee', codenames(Group.objects.get(name=preset.name)))

    def test_the_migrations_lists_are_the_presets_today(self):
        """0010's lists are the presets as they were then; with what 0012 gives the Production manager they are the
        presets today (a migration never reads live code, so each writes its own list)."""
        frozen = {name: set(rights) for name, rights in restore.PRESETS.items()}
        frozen[manager_rights().ROLE] |= set(manager_rights().RIGHTS)
        self.assertEqual(frozen, {preset.name: set(preset.permissions) for preset in roles.PRESETS})

    def test_no_preset_and_other_roles_are_left_alone(self):
        other = Group.objects.create(name='Night shift')
        give(other, 'hr.view_employee', 'hr.all_production_employee')
        restore.restore(apps, None)
        self.assertFalse(Group.objects.filter(name__in=[preset.name for preset in roles.PRESETS]).exists())
        self.assertEqual(codenames(other), {'hr.view_employee', 'hr.all_production_employee'})


class ImpliedReadCheckTests(PeopleTestCase):
    def test_a_role_whose_read_may_come_only_from_a_widening_column_is_listed(self):
        widened = Group.objects.create(name='Widened')
        give(widened, 'hr.view_employee', 'hr.all_production_employee')
        edits = Group.objects.create(name='Edits')
        give(edits, 'hr.view_employee', 'hr.change_employee', 'hr.all_production_employee')
        plain = Group.objects.create(name='Plain')
        give(plain, 'hr.all_production_employee')
        found = checks.implied_reads(None)
        self.assertEqual([warning.id for warning in found], ['core.W003'])
        self.assertIn('Widened', found[0].msg)
        self.assertIn('Employees', found[0].msg)
        self.assertNotIn('Edits', found[0].msg)
        self.assertNotIn('Plain', found[0].msg)

    def test_crew_is_read_on_its_own_areas_page_so_read_beside_it_is_never_a_leftover(self):
        """Review R13: Crew is drawn only on the Shift schedule's own page, which needs Read on that area, so Read with
        Crew is the one way Crew does anything; it is what the Production worker preset holds. The access model says
        which widening columns are read so (core.access.OWN_PAGE), and the check leaves them alone. All production and
        Everyone widen other areas' rows and stand without Read on Employees: Read beside them alone is still listed."""
        from core import access
        self.assertEqual(access.OWN_PAGE, ('crew',))
        roles.create()
        self.assertEqual(checks.implied_reads(None), [])                    # the two presets as they are made
        office = Group.objects.create(name='Office staff')
        give(office, 'hr.view_shiftassignment', 'hr.crew_shiftassignment', 'hr.view_attendancerecord')
        self.assertEqual(checks.implied_reads(None), [])
        everyone = Group.objects.create(name='Sees everyone')
        give(everyone, 'hr.view_employee', 'hr.all_employee')
        found = checks.implied_reads(None)
        self.assertEqual([warning.id for warning in found], ['core.W003'])
        self.assertIn('Sees everyone (Employees)', found[0].msg)
        self.assertNotIn('Office staff', found[0].msg)
        self.assertNotIn('Production worker', found[0].msg)
