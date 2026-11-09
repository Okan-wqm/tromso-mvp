"""Roles saved through the matrix before its one rule (Crew, All production and Everyone include nothing) kept the Read it
added: a Production manager saved once can open the Team list. The migration puts the two presets back to exactly their
rights; a system check lists any other role whose Read on an area may come only from that old rule, for the
administrator to review (`manage.py check --database default`)."""
from importlib import import_module

from django.apps import apps
from django.contrib.auth.models import Group, Permission

from core import checks

from .. import roles
from .helpers_people import PeopleTestCase

restore = import_module('hr.migrations.0010_restore_preset_rights')


def codenames(group):
    return {f'{p.content_type.app_label}.{p.codename}' for p in group.permissions.select_related('content_type')}


def give(group, *names):
    for name in names:
        app, codename = name.split('.')
        group.permissions.add(Permission.objects.get(content_type__app_label=app, codename=codename))


class PresetRestoreTests(PeopleTestCase):
    def test_both_presets_are_put_back_to_exactly_their_rights(self):
        roles.create()
        for preset in roles.PRESETS:
            give(Group.objects.get(name=preset.name), 'hr.view_employee')
        restore.restore(apps, None)
        for preset in roles.PRESETS:
            self.assertEqual(codenames(Group.objects.get(name=preset.name)), set(preset.permissions), preset.name)

    def test_the_migrations_lists_are_the_presets_today(self):
        self.assertEqual({name: set(rights) for name, rights in restore.PRESETS.items()},
                         {preset.name: set(preset.permissions) for preset in roles.PRESETS})

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
