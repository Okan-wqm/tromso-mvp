"""Personal data in the append-only activity log (owner decision F-059 / F-061 / F-179 / F-050, 2026-11-10). A contact's
e-mail and phone and a task's free-text notes are logged as private values with the one keyed digest of core.audit: the
log shows that the value changed and whether two values were equal, never the value. The rows written before are
converted by migration core/0011 in the same way (the append-only trigger set aside inside its transaction, and back),
counted and said in the log. The log stays readable only with core.view_auditlog (core.tests.AuditLogTests)."""
import hashlib
import hmac
from importlib import import_module

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import DatabaseError, connection, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from . import audit
from .models import AuditLog

LONG = 'kari.nordmann@example.com'


def migration():
    return import_module('core.migrations.0011_private_log_values')


def old(entity_type, changes, action='update', label='A record'):
    """A row as the code before the decision wrote it."""
    return AuditLog.objects.create(user_name='ali', action=action, entity_type=entity_type, entity_id='1',
                                   entity_label=label, changes=changes)


class DigestTests(TestCase):
    def test_a_private_value_is_the_enumerated_private_text_with_a_short_keyed_digest(self):
        value = audit.private(LONG)
        expected = hmac.new(settings.SECRET_KEY.encode(), LONG.encode(), hashlib.sha256).hexdigest()[:8]
        self.assertEqual(value, {'msgid': 'Private text', 'rev': expected})
        self.assertEqual(audit.digest(LONG), expected)
        self.assertNotIn(LONG, str(value))

    def test_equal_values_are_equal_in_the_log_and_different_ones_differ(self):
        self.assertEqual(audit.private('+47 98989898'), audit.private('+47 98989898'))
        self.assertNotEqual(audit.private('+47 98989898'), audit.private('+47 98989899'))

    def test_the_digest_is_keyed_another_key_gives_another_digest(self):
        here = audit.digest(LONG)
        with override_settings(SECRET_KEY='another-key-entirely'):
            self.assertNotEqual(audit.digest(LONG), here)

    def test_a_snapshot_keeps_using_it_for_a_tabs_private_fields(self):
        from farm.models import Site
        site = Site(name='Bergen', code='BG', description='Words of a person')
        self.assertEqual(audit.snapshot(site, ['description'], private=('description',)),
                         {'Description': audit.private('Words of a person')})


class LogPageTests(TestCase):
    def test_the_page_says_private_text_and_never_the_value(self):
        reader = get_user_model().objects.create_user('reader', 'reader@example.com', 'x')
        role = Group.objects.create(name='Log reader')
        role.permissions.add(Permission.objects.get(codename='view_auditlog'))
        reader.groups.add(role)
        old('site', {'Contact email': [audit.private('old@example.com'), audit.private(LONG)]})
        self.client.force_login(reader)
        page = self.client.get(reverse('core:activity_log'))
        self.assertContains(page, 'Private text')
        self.assertNotContains(page, LONG)
        self.assertNotContains(page, 'old@example.com')
        self.assertNotContains(page, audit.digest(LONG))                 # the digest is for comparing, not for showing
        self.client.force_login(get_user_model().objects.create_user('other', 'other@example.com', 'x'))
        self.assertEqual(self.client.get(reverse('core:activity_log')).status_code, 403)


class ConversionTests(TestCase):
    """core/0011 on rows as they were written before it."""

    def run_migration(self):
        with connection.schema_editor() as editor:
            return migration().convert(apps, editor)

    def setUp(self):
        self.contacts = old('site', {'Contacts': [None, 'Kari (Vet, kari@example.com, +47 98989898, primary)']})
        self.replaced = old('supplier', {'Contacts': ['Kari (Sales, kari@example.com)', 'Ola (Sales, ola@example.com)']})
        self.site = old('site', {'Contact email': ['old@example.com', LONG], 'Contact phone': [None, '+47 98989898'],
                                 'Site name': ['Bergen', 'Bergen havn']})
        self.report = old('regulatory report', {'Contact e-mail': [None, LONG], 'Contact telephone': [None, '+47 1'],
                                                'Contact person': [None, 'Kari Nord']}, action='create')
        self.note = old('task', {'Note': [None, 'Ola was ill today, I took his round']})
        self.done = old('task', {'Completion note': [None, '2 dead fish removed'],
                                 'Status': [{'msgid': 'Open'}, {'msgid': 'Done'}]})
        self.cancelled = old('task', {'Reason for cancelling': [None, 'The unit was emptied']})
        self.reopened = old('task', {'Reason for cancelling': ['The unit was emptied', None]})
        # not theirs: the same labels on other kinds of record, and values that are private already
        self.plan = old('plan', {'Note': [None, audit.private('swap')]})
        self.role = old('role', {'Permissions': [None, 'Attendance: edit'], 'Note': [None, 'hr 0012: a migration said so']})
        self.species = old('species', {'Notes': [None, 'Grows slowly']})

    def changes(self, entry):
        return AuditLog.objects.get(pk=entry.pk).changes

    def test_the_plain_values_become_private_ones_and_everything_else_stays(self):
        p = audit.private
        counted = self.run_migration()
        self.assertEqual(self.changes(self.contacts),
                         {'Contacts': [None, p('Kari (Vet, kari@example.com, +47 98989898, primary)')]})
        self.assertEqual(self.changes(self.replaced), {'Contacts': [p('Kari (Sales, kari@example.com)'),
                                                                    p('Ola (Sales, ola@example.com)')]})
        self.assertEqual(self.changes(self.site), {'Contact email': [p('old@example.com'), p(LONG)],
                                                   'Contact phone': [None, p('+47 98989898')],
                                                   'Site name': ['Bergen', 'Bergen havn']})
        self.assertEqual(self.changes(self.report), {'Contact e-mail': [None, p(LONG)],
                                                     'Contact telephone': [None, p('+47 1')],
                                                     'Contact person': [None, 'Kari Nord']})
        self.assertEqual(self.changes(self.note), {'Note': [None, p('Ola was ill today, I took his round')]})
        self.assertEqual(self.changes(self.done), {'Completion note': [None, p('2 dead fish removed')],
                                                   'Status': [{'msgid': 'Open'}, {'msgid': 'Done'}]})
        self.assertEqual(self.changes(self.cancelled), {'Reason for cancelling': [None, p('The unit was emptied')]})
        # the same reason set and cleared is the same private value in both rows: the log still says they were equal
        self.assertEqual(self.changes(self.reopened), {'Reason for cancelling': [p('The unit was emptied'), None]})
        for untouched in (self.plan, self.role, self.species):
            self.assertEqual(self.changes(untouched), untouched.changes)
        self.assertEqual(counted, {'rows': 8, 'values': 12})
        everything = str(list(AuditLog.objects.values_list('changes', flat=True)))
        for word in ('kari@example.com', LONG, '+47 98989898', 'Ola was ill', 'dead fish', 'emptied'):
            self.assertNotIn(word, everything)

    def test_who_when_and_which_record_are_not_touched(self):
        before = list(AuditLog.objects.order_by('pk').values_list(
            'pk', 'created_at', 'user_name', 'action', 'entity_type', 'entity_id', 'entity_label', 'severity'))
        self.run_migration()
        after = list(AuditLog.objects.exclude(user_name='system').order_by('pk').values_list(
            'pk', 'created_at', 'user_name', 'action', 'entity_type', 'entity_id', 'entity_label', 'severity'))
        self.assertEqual(after, before)

    def test_the_conversion_is_counted_in_the_log_and_running_it_again_changes_nothing(self):
        self.run_migration()
        said = AuditLog.objects.get(user_name='system', entity_type='activity log')
        self.assertEqual((said.action, said.changes['Entries converted'], said.changes['Values made private']),
                         ('update', [None, '8'], [None, '12']))
        self.assertIn('core 0011', said.changes['Note'][1])
        rows = AuditLog.objects.count()
        self.assertEqual(self.run_migration(), {'rows': 0, 'values': 0})
        self.assertEqual(AuditLog.objects.count(), rows)                    # nothing converted, nothing said

    def test_the_log_is_append_only_again_afterwards(self):
        self.run_migration()
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("UPDATE audit_log SET user_name = 'x'")
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute('DELETE FROM audit_log')

    def test_the_migrations_digest_and_fields_are_the_codes(self):
        """A migration never reads live code, so it writes its own digest and its own list: both are held to the code's."""
        from farm.resources.contact import ContactList
        from farm.resources.site import SiteResource
        from reports.resources import ReportResource
        from tasks import services as tasks
        from tasks.models import Task
        self.assertEqual(migration().private('Words'), audit.private('Words'))
        label = lambda model, name: str(model._meta.get_field(name).verbose_name)
        with audit.source_language():
            expected = {
                ('site', str(ContactList.label)), ('supplier', str(ContactList.label)),
                *((SiteResource.entity_type(), label(SiteResource.model, name)) for name in SiteResource.private_fields),
                *((ReportResource.entity_type(), label(ReportResource.model, name))
                  for name in ReportResource.private_fields),
                (audit.entity_type_of(Task), str(tasks.NOTE)),
                *((audit.entity_type_of(Task), label(Task, name)) for name in tasks.PRIVATE),
            }
        self.assertEqual(set(migration().PRIVATE), expected)
