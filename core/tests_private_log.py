"""Personal data in the append-only activity log (owner decision F-059 / F-061 / F-179 / F-050, 2026-11-10). A contact's
e-mail and phone and people's free text are logged as private values with the one keyed digest of core.audit: the log
shows that the value changed and whether two values were probably the same, never the value. The rows written before
are converted by migration core/0011 (core/migrations/_private.py) in the same way: an old contact-list sentence is
taken apart into its contacts and only the e-mail and the phone become private (review R1); what cannot be told apart
is made private and counted, never left plain. The conversion is one-way. The log stays readable only with
core.view_auditlog (core.tests.AuditLogTests), and no page prints a digest (farm.tests.test_private_contacts)."""
import hashlib
import hmac
from importlib import import_module
from io import StringIO

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.db import DatabaseError, connection, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from . import audit
from .migrations import _private
from .models import AuditLog

LONG = 'kari.nordmann@example.com'


def migration():
    return import_module('core.migrations.0011_private_log_values')


def old(entity_type, changes, action='update', label='A record'):
    """A row as the code before the decision wrote it."""
    return AuditLog.objects.create(user_name='ali', action=action, entity_type=entity_type, entity_id='1',
                                   entity_label=label, changes=changes)


def E(value):
    return audit.private(value, 'Email')


def P(value):
    return audit.private(value, 'Phone')


def U(value):
    return audit.private(value, 'Role or phone')


class DigestTests(TestCase):
    def test_a_private_value_is_the_enumerated_private_text_with_a_short_keyed_digest(self):
        value = audit.private(LONG)
        expected = hmac.new(settings.SECRET_KEY.encode(), LONG.encode(), hashlib.sha256).hexdigest()[:8]
        self.assertEqual(value, {'msgid': 'Private text', 'rev': expected})
        self.assertEqual(audit.digest(LONG), expected)
        self.assertNotIn(LONG, str(value))
        self.assertEqual(audit.private(LONG, 'Email'), {'msgid': 'Private text', 'rev': expected, 'of': 'Email'})

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


# An old contact-list sentence (main's ContactList.describe: `name` or `name (role?, email?, phone?, primary?)`, the
# contacts joined by "; ") and what it becomes: the parts the code writes now, or WHOLE when it cannot be taken apart.
WHOLE = object()
SHAPES = [
    ('Kari Nordmann (Vet, kari@example.com, +47 98989898, primary); Ola Hansen (Diver, ola@example.com)',
     [['Kari Nordmann (Vet, primary)', E('kari@example.com'), P('+47 98989898')],
      ['Ola Hansen (Diver)', E('ola@example.com')]]),
    ('Per', [['Per']]),
    ('Kari (primary)', [['Kari (primary)']]),
    ('Kari (+47 98989898)', [['Kari', P('+47 98989898')]]),
    ('Kari (Vet, 98 98 98 98)', [['Kari (Vet)', P('98 98 98 98')]]),
    ('Kari (Head of fish health, Bergen, kari@example.com)', [['Kari (Head of fish health, Bergen)', E('kari@example.com')]]),
    ('Kari; Ola (Vet, ola@example.com)', [['Kari'], ['Ola (Vet)', E('ola@example.com')]]),
    ('Kari (kari@example.com, 98989898, primary)', [['Kari (primary)', E('kari@example.com'), P('98989898')]]),
    # a role and a phone that cannot be told apart (the phone was free text): both private, the name and primary stay
    ('Kari (Vet, primary)', [['Kari (primary)', U('Vet')]]),
    ('Kari (ask reception)', [['Kari', U('ask reception')]]),
    ('Kari (Vet, ask reception)', [['Kari', U('Vet, ask reception')]]),
    # cannot be taken apart: a "; " or a bracket typed inside a field, two addresses
    ('Kari (Vet, kari@example.com, 123; 456)', WHOLE),
    ('Kari (vet) Nordmann (Vet, kari@example.com)', WHOLE),
    ('Kari (a@example.com, b@example.com)', WHOLE),
]


class ContactSentenceTests(TestCase):
    """Review R1: only the e-mail and the phone are hidden; the name, the role and the primary flag stay."""

    def test_every_shape_of_the_old_sentence(self):
        for sentence, expected in SHAPES:
            with self.subTest(sentence=sentence):
                made, kind = _private.contacts(sentence)
                if expected is WHOLE:
                    self.assertEqual((made, kind), (audit.private(sentence), 'whole'))
                else:
                    self.assertEqual(made, expected)
                    self.assertEqual(kind, 'part' if 'Role or phone' in str(expected) else 'kept')

    def test_nothing_that_stood_in_the_email_or_the_phone_field_comes_out_plain(self):
        for sentence, _expected in SHAPES:
            made, _kind = _private.contacts(sentence)
            plain = [parts[0] for parts in made] if isinstance(made, list) else []      # the rest are private values
            self.assertTrue(isinstance(made, dict) or all(isinstance(part, dict) for parts in made for part in parts[1:]))
            for value in ('@', '98989898', '98 98 98 98', '123', '456', 'ask reception'):
                self.assertNotIn(value, str(plain), sentence)

    def test_an_old_row_becomes_exactly_what_the_code_writes_now_so_old_and_new_rows_compare(self):
        from farm.models import Site
        from farm.resources.site import SiteContacts
        site = Site.objects.create(name='Bergen', code='BG')
        site.contacts.create(name='Kari Nordmann', role='Vet', email='kari@example.com', phone='+47 98989898',
                             is_primary=True)
        site.contacts.create(name='Ola Hansen', role='Diver', email='ola@example.com')
        site.contacts.create(name='Per')
        sentence = ('Kari Nordmann (Vet, kari@example.com, +47 98989898, primary); Ola Hansen (Diver, ola@example.com); '
                    'Per')                                                    # as main's describe wrote these three
        with audit.source_language():
            self.assertEqual(_private.contacts(sentence), (SiteContacts.summary(site), 'kept'))


class ConversionTests(TestCase):
    """core/0011 on rows as they were written before it."""

    def run_migration(self):
        with connection.schema_editor() as editor:
            return migration().convert(apps, editor)

    def setUp(self):
        self.contacts = old('site', {'Contacts': [None, 'Kari (Vet, kari@example.com, +47 98989898, primary)']})
        self.replaced = old('supplier', {'Contacts': ['Kari (Sales, kari@example.com); Ola (Diver)', 'Kari (Sales, '
                                                      'kari@example.com)']})          # Ola was taken off
        self.odd = old('site', {'Contacts': ['Per', 'Per; Kari (vet) Nordmann (Vet, kari@example.com)']})
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
        self.user = old('user', {'Email address': [None, 'kari@example.com']})         # an account's address: kept

    def changes(self, entry):
        return AuditLog.objects.get(pk=entry.pk).changes

    def test_only_what_was_decided_private_is_hidden_and_everything_else_stays(self):
        p = audit.private
        counted = self.run_migration()
        self.assertEqual(self.changes(self.contacts), {'Contacts': [None, [
            ['Kari (Vet, primary)', E('kari@example.com'), P('+47 98989898')]]]})
        # who was taken off the list is still said, by name and role
        self.assertEqual(self.changes(self.replaced), {'Contacts': [
            [['Kari (Sales)', E('kari@example.com')], ['Ola', U('Diver')]], [['Kari (Sales)', E('kari@example.com')]]]})
        # a sentence that cannot be taken apart is made private whole; the one beside it is not
        self.assertEqual(self.changes(self.odd), {'Contacts': [
            [['Per']], p('Per; Kari (vet) Nordmann (Vet, kari@example.com)')]})
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
        self.assertEqual(self.changes(self.reopened), {'Reason for cancelling': [p('The unit was emptied'), None]})
        for untouched in (self.plan, self.role, self.species, self.user):
            self.assertEqual(self.changes(untouched), untouched.changes)
        self.assertEqual(counted, {'rows': 9, 'values': 9, 'contact_values': 4, 'parts': 1, 'whole': 1,
                                   'whole_ids': [str(self.odd.pk)]})
        everything = str(list(AuditLog.objects.exclude(pk=self.user.pk).values_list('changes', flat=True)))
        for word in ('kari@example.com', LONG, '+47 98989898', 'Ola was ill', 'dead fish', 'emptied'):
            self.assertNotIn(word, everything)

    def test_who_when_and_which_record_are_not_touched(self):
        columns = ('pk', 'created_at', 'user_name', 'action', 'entity_type', 'entity_id', 'entity_label', 'severity')
        before = list(AuditLog.objects.order_by('pk').values_list(*columns))
        self.run_migration()
        self.assertEqual(list(AuditLog.objects.exclude(user_name='system').order_by('pk').values_list(*columns)), before)

    def test_the_conversion_is_counted_in_the_log_with_the_entries_it_could_not_take_apart(self):
        self.run_migration()
        said = AuditLog.objects.get(user_name='system', entity_type='activity log')
        self.assertEqual((said.action, said.entity_id, said.changes), ('update', 'core.0011', {
            'Entries converted': [None, '9'], 'Values made private': [None, '9'],
            'Contact e-mails and phones made private, the contact kept': [None, '4'],
            'Roles made private with a phone they could not be told apart from': [None, '1'],
            'Contact lists made private whole': [None, '1'],
            'Entries whose contact list was made private whole': [None, str(self.odd.pk)],
            'Note': [None, _private.SAID]}))
        rows = AuditLog.objects.count()
        self.assertEqual(self.run_migration()['rows'], 0)                   # again: nothing converted, nothing said
        self.assertEqual(AuditLog.objects.count(), rows)

    def test_the_log_is_append_only_again_afterwards(self):
        self.run_migration()
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("UPDATE audit_log SET user_name = 'x'")
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute('DELETE FROM audit_log')

    def test_the_dry_run_says_what_will_be_converted_and_what_cannot_be_taken_apart_and_writes_nothing(self):
        before = list(AuditLog.objects.order_by('pk').values_list('pk', 'changes'))
        out = StringIO()
        call_command('private_log_values', '--dry-run', stdout=out)
        self.assertEqual(list(AuditLog.objects.order_by('pk').values_list('pk', 'changes')), before)
        said = out.getvalue()
        for line in ('Dry run: nothing is written.',
                     '9 activity-log row(s) hold plain values that were decided private:',
                     '  9 value(s) made private (a contact e-mail or phone of a site, a supplier or a report; a note)',
                     '  4 contact e-mail(s) and phone(s) made private, the contact (name, role, primary) kept',
                     '  1 role(s) made private together with a phone they could not be told apart from, the name kept',
                     '  1 contact list(s) made private whole: they could not be taken apart',
                     f'    {self.odd.pk}  site  A record'):
            self.assertIn(line, said)
        for word in ('kari@example.com', 'Nordmann', 'Ola was ill'):
            self.assertNotIn(word, said)                                    # it names the entries, never the words
        out = StringIO()
        call_command('private_log_values', stdout=out)                      # the same conversion, for real
        self.assertIn('9 activity-log row(s) converted', out.getvalue())
        self.assertEqual(self.changes(self.note), {'Note': [None, audit.private('Ola was ill today, I took his round')]})
        out = StringIO()
        call_command('private_log_values', '--dry-run', stdout=out)
        self.assertIn('No plain value under a private label: nothing to convert.', out.getvalue())

    def test_there_is_no_way_back_once_a_row_was_converted(self):
        with connection.schema_editor() as editor:
            migration().no_way_back(apps, editor)                           # nothing converted yet: going back is free
        self.run_migration()
        with self.assertRaisesMessage(RuntimeError, 'core 0011 cannot be reversed'), connection.schema_editor() as editor:
            migration().no_way_back(apps, editor)
        self.assertEqual(self.changes(self.note), {'Note': [None, audit.private('Ola was ill today, I took his round')]})

    def test_the_migrations_digest_and_fields_are_the_codes(self):
        """A migration never reads live code, so its helper writes its own digest and its own list: both are held to
        the code's here."""
        from farm.models import SiteContact
        from farm.resources.contact import ContactList
        from farm.resources.site import SiteResource
        from reports.resources import ReportResource
        from tasks import services as tasks
        from tasks.models import Task
        self.assertEqual(_private.private('Words'), audit.private('Words'))
        self.assertEqual(_private.private('Words', 'Email'), audit.private('Words', 'Email'))
        label = lambda model, name: str(model._meta.get_field(name).verbose_name)
        with audit.source_language():
            self.assertEqual(set(_private.CONTACTS), {('site', str(ContactList.label)), ('supplier', str(ContactList.label))})
            self.assertEqual(_private.CONTACT_FIELDS, tuple(label(SiteContact, name) for name in ContactList.PRIVATE))
            expected = {
                *((SiteResource.entity_type(), label(SiteResource.model, name)) for name in SiteResource.private_fields),
                *((ReportResource.entity_type(), label(ReportResource.model, name))
                  for name in ReportResource.private_fields),
                (audit.entity_type_of(Task), str(tasks.NOTE)),
                *((audit.entity_type_of(Task), label(Task, name)) for name in tasks.PRIVATE),
            }
        self.assertEqual(set(_private.PRIVATE), expected)
