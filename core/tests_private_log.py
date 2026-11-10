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
from pathlib import Path
from unittest import mock

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import CommandError, call_command
from django.db import DatabaseError, connection, transaction
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from . import audit
from .migrations import _private
from .models import AuditLog

LONG = 'kari.nordmann@example.com'
KEY = 'a-key-of-its-own-for-the-digests-of-these-tests'      # the conversion refuses the repository's fallback key


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
# contacts joined by "; ") and what it becomes: the parts the code writes now, or WHOLE when it cannot be taken apart
# safely.
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
    ('Kari (Head of fish health, Bergen, +47 98989898)', [['Kari (Head of fish health, Bergen)', P('+47 98989898')]]),
    ('Kari; Ola (Vet, ola@example.com)', [['Kari'], ['Ola (Vet)', E('ola@example.com')]]),
    ('Kari (kari@example.com, 98989898, primary)', [['Kari (primary)', E('kari@example.com'), P('98989898')]]),
    # a role alone, and a role that only looks like a number: kept (the real data has roles; a phone is five digits or more)
    ('Kari (Vet, primary)', [['Kari (Vet, primary)']]),
    ('Ola (24/7, 55 12 34 56)', [['Ola (24/7)', P('55 12 34 56')]]),
    # a bracket inside a role or a phone (review R19): the brackets balance, so the sentence is read
    ('Kjetil Ness (Service manager (24 h line), service@nordicpumps.example, +47 800 45 600, primary)',
     [['Kjetil Ness (Service manager (24 h line), primary)', E('service@nordicpumps.example'), P('+47 800 45 600')]]),
    ('Şule Çağrı (Veteriner, sule@example.com, (0532) 123 45 67)',
     [['Şule Çağrı (Veteriner)', E('sule@example.com'), P('(0532) 123 45 67')]]),
    ('Şule Çağrı (Veteriner, +90 (532) 123 45 67)', [['Şule Çağrı (Veteriner)', P('+90 (532) 123 45 67')]]),
    ('Kari (vet) Nordmann (Vet, kari@example.com)', [['Kari (vet) Nordmann (Vet)', E('kari@example.com')]]),
    ('Kari (vet)', [['Kari (vet)']]),
    # everything right of the address is the phone, whatever its form: a "; " inside it, two numbers, words
    ('Kari (Vet, kari@example.com, 123; 456)', [['Kari (Vet)', E('kari@example.com'), P('123; 456')]]),
    ('Kari (Vet, kari@example.com, 55 12 34 56, 90 00 00 00)',
     [['Kari (Vet)', E('kari@example.com'), P('55 12 34 56, 90 00 00 00')]]),
    ('Kari (kari@example.com, ask reception)', [['Kari', E('kari@example.com'), P('ask reception')]]),
    ('Kari (Vet, 55 12 34 56, 90 00 00 00)', [['Kari (Vet)', P('55 12 34 56, 90 00 00 00')]]),
    # an address is whatever the contact form takes as one (review R20): these two pass its e-mail field
    ('Kari (kari@localhost)', [['Kari', E('kari@localhost')]]),
    ('Kari (Vet, kari@localhost, 98989898)', [['Kari (Vet)', E('kari@localhost'), P('98989898')]]),
    ('Kari ("a,b"@example.com, +47 98989898)', [['Kari', E('"a,b"@example.com'), P('+47 98989898')]]),
    # words without a number typed into the phone box cannot be told from a role, and hold no number: they stay
    ('Kari (ask reception)', [['Kari (ask reception)']]),
    ('Kari (Vet, ask reception)', [['Kari (Vet, ask reception)']]),
    # a number that is not in the form of a phone, an address in the role: the details are private, the name stays
    ('Kari (Vet, mob 98989898); Ola (tlf 55123456)', [['Kari', U('Vet, mob 98989898')], ['Ola', U('tlf 55123456')]]),
    ('Kari (see post@firma.no, +47 98989898)', [['Kari', U('see post@firma.no, +47 98989898')]]),
    ('Kari (a@example.com, b@example.com, primary)', [['Kari (primary)', U('a@example.com, b@example.com')]]),
    # cannot be taken apart safely: the brackets do not balance, a name that holds an address or a number, no name
    ('Kari (Vet, 98 work); 99123456 (home)', WHOLE),      # a phone "98 work); 99123456 (home" reads like two contacts
    ('Kari (Vet, kari@example.com', WHOLE),
    ('Kari Vet), 98989898', WHOLE),
    ('Kari (Vet, 98989898 (work)', WHOLE),
    ('Per; 99123456', WHOLE),
    ('name.box@example.com (Vet); Per', WHOLE),
    ('(Vet, kari@example.com)', WHOLE),
]
# The contact lists the development database's log really holds that the first parser made private whole (the
# coordinator's rehearsal, 2026-11-10): eight people. Every name and role must stay.
REAL = [
    'Kjetil Ness (Service manager (24 h line), service@nordicpumps.example, +47 800 45 600, primary)',
    'Torstein Våge (Key account manager, torstein.vage@fjordfeed.example, +47 915 20 114, primary); Lene Hovland '
    '(Order desk, orders@fjordfeed.example, +47 55 90 21 00); Dr. Rune Aspheim (Nutritionist (R&D diets), '
    'rune.aspheim@fjordfeed.example, +47 934 11 870)',
    'Bjørn Eriksen (Site manager, bjorn.eriksen@nordhav.example, +47 913 40 227, primary); Kristoffer Pedersen (Shift '
    'leader (on call), kristoffer.pedersen@nordhav.example, +47 948 12 650); Ingvild Stene (Veterinarian (Havet '
    'Fiskehelse), ingvild@havetfiskehelse.example, +47 920 44 312); Feed barge Nordhav I (Barge control room, '
    '+47 77 61 40 90)',
]
REAL_KEPT = [
    ['Kjetil Ness (Service manager (24 h line), primary)'],
    ['Torstein Våge (Key account manager, primary)', 'Lene Hovland (Order desk)',
     'Dr. Rune Aspheim (Nutritionist (R&D diets))'],
    ['Bjørn Eriksen (Site manager, primary)', 'Kristoffer Pedersen (Shift leader (on call))',
     'Ingvild Stene (Veterinarian (Havet Fiskehelse))', 'Feed barge Nordhav I (Barge control room)'],
]


def old_describe(name, role, email, phone, primary):
    """main's ContactList.describe, the sentence the rows written before hold."""
    details = [value for value in (role, email, phone) if value] + (['primary'] if primary else [])
    return f'{name} ({", ".join(details)})' if details else name


def plain_of(made):
    """What a converted sentence leaves in plain text: the first part of each contact (the rest are private values)."""
    return [parts[0] for parts in made] if isinstance(made, list) else []


def digits(text):
    return sum(character.isdigit() for character in text)


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

    def test_the_parser_and_the_contact_form_agree_on_what_an_address_is(self):
        """One definition (review R20): what the form's e-mail field accepts is what the conversion reads as the
        e-mail, so an address the form took is never left standing as a role."""
        from django import forms
        from farm.models import SiteContact
        field = SiteContact._meta.get_field('email').formfield()
        for text in ('kari@example.com', 'kari@localhost', '"a,b"@example.com', 'kari@bedrift-æøå.no',
                     'kari.nordmann+farm@example.co.uk', 'Vet', 'see post@firma.no', 'kari@', '@example.com',
                     'kari@example', 'a@b@c.no', '+47 98989898', 'Head of fish health', ''):
            try:
                field.clean(text)
                taken = bool(text)
            except forms.ValidationError:
                taken = False
            self.assertEqual(_private.is_email(text), taken, text)

    def test_the_real_lists_keep_every_name_and_role_and_hide_every_address_and_number(self):
        for sentence, kept in zip(REAL, REAL_KEPT):
            made, kind = _private.contacts(sentence)
            self.assertEqual((kind, plain_of(made)), ('kept', kept))
            for parts in made:
                self.assertTrue(all(part.get('of') in ('Email', 'Phone') for part in parts[1:]), parts)
            self.assertNotIn('@', str(plain_of(made)))
            self.assertNotIn('+47', str(plain_of(made)))
        self.assertEqual(sum(len(kept) for kept in REAL_KEPT), 8)

    def test_no_address_and_no_number_comes_out_plain_on_a_grid_of_every_field_shape(self):
        """The reviewer's grid (review/p2_parser.py), built with main's own describe: 5 names x 8 roles x 5 addresses x
        13 phones x primary or not = 5,200 sentences, with commas, brackets, digits and an address inside a role,
        addresses the form accepts in odd forms, phones with brackets, words, two numbers, a "; " and unbalanced
        brackets. No e-mail address and no number of five digits or more is left in plain text; the only sentences made
        private whole are those whose phone holds an unbalanced bracket that reads like a second contact; everywhere
        else the name stays."""
        import itertools
        import re
        names = ['Kari', 'Nordmann, Kari', 'Åse Ødegård', 'Kari (vet) Nordmann', 'Feed barge Nordhav I']
        roles = ['', 'Vet', 'Head of fish health, Bergen', '24/7', 'Service manager (24 h line)',
                 'Nutritionist (R&D diets)', 'Veterinarian (Havet Fiskehelse)', 'see post@firma.no']
        emails = ['', 'kari@example.com', 'kari@localhost', '"a,b"@example.com', 'kari@bedrift-æøå.no']
        phones = ['', '+47 98989898', '989 89 898', '(0532) 123 45 67', '+90 (532) 123 45 67', 'mob 98989898',
                  '55 12 34 56, 90 00 00 00', '55 12 34 56; 90 00 00 00', 'ask reception', '98989898 (work)',
                  'mob 98989898, 55 12 34 56', '98 work); 99123456 (home', '98989898); Ola (Diver']
        kinds, leaks, lost = {}, [], []
        for name, role, email, phone, primary in itertools.product(names, roles, emails, phones, (False, True)):
            sentence = old_describe(name, role, email, phone, primary)
            made, kind = _private.contacts(sentence)
            kinds[kind] = kinds.get(kind, 0) + 1
            text = ' | '.join(plain_of(made))
            numbers = [found for found in re.findall(r'\d[\d ]{3,}\d', phone) if digits(found) >= 5]
            if (email and email in text) or any(number in text for number in numbers):
                leaks.append((sentence, text))
            if kind == 'whole':
                if phone != '98 work); 99123456 (home':
                    lost.append(sentence)
            elif name not in text:
                lost.append(sentence)
        self.assertEqual(sum(kinds.values()), 5200)
        self.assertEqual(leaks, [])
        self.assertEqual(lost, [])
        self.assertEqual(kinds['whole'], 400)                               # 5 names x 8 roles x 5 addresses x 2

    def test_nothing_that_looks_like_an_address_or_a_number_is_kept_in_any_shape(self):
        for sentence, _expected in SHAPES:
            made, _kind = _private.contacts(sentence)
            self.assertTrue(isinstance(made, dict) or all(isinstance(part, dict) for parts in made for part in parts[1:]))
            for text in plain_of(made):
                self.assertNotIn('@', text, sentence)
                self.assertLess(max((digits(run) for run in text.split(',')), default=0), 5, sentence)

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


@override_settings(AUDIT_DIGEST_KEY=KEY)
class ConversionTests(TestCase):
    """core/0011 on rows as they were written before it."""

    def run_migration(self):
        with connection.schema_editor() as editor:
            return migration().convert(apps, editor)

    def setUp(self):
        self.contacts = old('site', {'Contacts': [None, 'Kari (Vet, kari@example.com, +47 98989898, primary)']})
        self.replaced = old('supplier', {'Contacts': ['Kari (Sales, kari@example.com); Ola (Diver, mob 98989898)',
                                                      'Kari (Sales, kari@example.com)']})          # Ola was taken off
        self.odd = old('site', {'Contacts': ['Per', 'Per; Kari (Vet, 98 work); 99123456 (home)']})
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
            [['Kari (Sales)', E('kari@example.com')], ['Ola', U('Diver, mob 98989898')]],
            [['Kari (Sales)', E('kari@example.com')]]]})
        # a sentence that cannot be taken apart is made private whole; the one beside it is not
        self.assertEqual(self.changes(self.odd), {'Contacts': [
            [['Per']], p('Per; Kari (Vet, 98 work); 99123456 (home)')]})
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
                     "  9 value(s) made private (a site's, a supplier's or a report's own e-mail or phone; a person's "
                     "free text on a task)",
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
        self.assertEqual(_private.private('Words'), audit.private('Words'))
        self.assertEqual(_private.private('Words', 'Email'), audit.private('Words', 'Email'))
        label = lambda model, name: str(model._meta.get_field(name).verbose_name)
        with audit.source_language():
            self.assertEqual(set(_private.CONTACTS), {('site', str(ContactList.label)), ('supplier', str(ContactList.label))})
            self.assertEqual(_private.CONTACT_FIELDS, tuple(label(SiteContact, name) for name in ContactList.PRIVATE))
        # the fields: MoreDecidedPrivateTests.test_the_conversions_list_is_every_private_field_of_the_code


@override_settings(AUDIT_DIGEST_KEY=KEY)
class MoreDecidedPrivateTests(TestCase):
    """Review R7, decided with the conversion so that no second one is ever needed: a supplier's own e-mail and phone
    (a supplier may be one person) and the description of a task and of a recurring task (a person's free text) are
    private too. What stays plain, and why, is in docs/erasure.md."""

    def test_they_are_converted_and_the_plain_ones_beside_them_stay(self):
        p = audit.private
        supplier = old('supplier', {'Email': [None, 'per@example.com'], 'Phone': ['+47 1', '+47 2'],
                                    'Name': [None, 'Per Dykker'], 'City': [None, 'Bergen']})
        task = old('task', {'Description': [None, 'Call Kari on 98989898'], 'Title': [None, 'Feed'],
                            'Checklist': [None, 'Brush the screens']}, action='create')
        series = old('recurring task', {'Description': ['Call Kari', 'Call Ola'], 'Title': ['Round', 'Oxygen round']})
        account = old('user', {'Email address': ['kari@example.com', 'kari@new.example'], 'Username': [None, 'kari']})
        with connection.schema_editor() as editor:
            counts = migration().convert(apps, editor)
        changes = lambda entry: AuditLog.objects.get(pk=entry.pk).changes
        self.assertEqual(changes(supplier), {'Email': [None, p('per@example.com')], 'Phone': [p('+47 1'), p('+47 2')],
                                             'Name': [None, 'Per Dykker'], 'City': [None, 'Bergen']})
        self.assertEqual(changes(task), {'Description': [None, p('Call Kari on 98989898')], 'Title': [None, 'Feed'],
                                         'Checklist': [None, 'Brush the screens']})
        self.assertEqual(changes(series), {'Description': [p('Call Kari'), p('Call Ola')],
                                           'Title': ['Round', 'Oxygen round']})
        self.assertEqual(changes(account), account.changes)       # an account's address is kept, by decision (F-050)
        self.assertEqual((counts['rows'], counts['values']), (3, 6))

    def test_the_conversions_list_is_every_private_field_of_the_code(self):
        from farm.resources.site import SiteResource
        from farm.resources.supplier import SupplierResource
        from reports.resources import ReportResource
        from tasks import services as tasks
        from tasks.models import Task, TaskSeries
        label = lambda model, name: str(model._meta.get_field(name).verbose_name)
        with audit.source_language():
            expected = {
                *((resource.entity_type(), label(resource.model, name))
                  for resource in (SiteResource, SupplierResource, ReportResource) for name in resource.private_fields),
                (audit.entity_type_of(Task), str(tasks.NOTE)),
                *((audit.entity_type_of(Task), label(Task, name)) for name in tasks.PRIVATE),
                *((audit.entity_type_of(TaskSeries), label(TaskSeries, name)) for name in tasks.SERIES_PRIVATE),
            }
        self.assertEqual(SupplierResource.private_fields, ('email', 'phone'))
        self.assertEqual((tasks.PRIVATE, tasks.SERIES_PRIVATE),
                         (('description', 'completion_note', 'cancel_reason'), ('description',)))
        self.assertEqual(set(_private.PRIVATE), expected)


class DigestKeyTests(TestCase):
    """Review R3: the conversion is one-way, so the key in force when it runs is the key of every converted value for
    good. The digest has a key of its own (settings.AUDIT_DIGEST_KEY, the secret key when it is not set), and the
    conversion refuses to run on real data under a key that is printed in the repository."""

    FALLBACK = 'django-insecure-local-development-only'

    def convert(self):
        with connection.schema_editor() as editor:
            return migration().convert(apps, editor)

    def test_the_digest_uses_its_own_key_and_the_secret_key_when_it_has_none(self):
        self.assertEqual(settings.AUDIT_DIGEST_KEY, '')                     # not set here: the secret key stands in
        plain = audit.digest(LONG)
        with override_settings(AUDIT_DIGEST_KEY=KEY):
            own = audit.digest(LONG)
            self.assertEqual(own, hmac.new(KEY.encode(), LONG.encode(), hashlib.sha256).hexdigest()[:8])
            self.assertEqual(_private.private(LONG), audit.private(LONG))
            with override_settings(SECRET_KEY='the-secret-key-was-rotated'):
                self.assertEqual(audit.digest(LONG), own)                   # signing everyone out does not touch the log
        self.assertNotEqual(own, plain)

    def test_real_data_is_not_converted_under_the_repositorys_key_or_an_insecure_one(self):
        entry = old('task', {'Note': [None, 'Ola was ill today']})
        for key in ('', self.FALLBACK, 'django-insecure-anything'):
            with self.subTest(key=key), override_settings(AUDIT_DIGEST_KEY=key, SECRET_KEY=self.FALLBACK, DEBUG=False):
                with self.assertRaisesMessage(RuntimeError, 'core 0011 will not convert'):
                    self.convert()
                with self.assertRaises(CommandError):
                    call_command('private_log_values', stdout=StringIO())
                out = StringIO()
                call_command('private_log_values', '--dry-run', stdout=out)   # the dry run says it, and still counts
                self.assertIn('would be refused', out.getvalue())
                self.assertIn('1 activity-log row(s) hold plain values', out.getvalue())
        self.assertEqual(AuditLog.objects.get(pk=entry.pk).changes, {'Note': [None, 'Ola was ill today']})
        self.assertFalse(AuditLog.objects.filter(user_name='system').exists())

    def test_a_development_database_and_an_empty_log_are_not_held_up(self):
        with override_settings(AUDIT_DIGEST_KEY='', SECRET_KEY=self.FALLBACK, DEBUG=False):
            self.assertEqual(self.convert()['rows'], 0)                     # nothing to convert: a fresh database migrates
        old('task', {'Note': [None, 'Ola was ill today']})
        with override_settings(AUDIT_DIGEST_KEY='', SECRET_KEY=self.FALLBACK, DEBUG=True):
            self.assertEqual(self.convert()['rows'], 1)                     # the developer's own machine

    def test_a_real_key_converts(self):
        old('task', {'Note': [None, 'Ola was ill today']})
        with override_settings(AUDIT_DIGEST_KEY='', SECRET_KEY='a-long-random-production-key', DEBUG=False):
            self.assertEqual(self.convert()['rows'], 1)


@override_settings(AUDIT_DIGEST_KEY=KEY)
class LeftoverTests(TestCase):
    """Review R4: a server still running the code from before writes plain values after the conversion, and the
    migration cannot know. The conversion takes the table's lock before it reads, so no writer slips between its read
    and its updates; a check finds what an old server wrote afterwards; the command converts it."""

    def test_the_conversion_locks_the_log_against_writers_before_it_reads_it(self):
        old('task', {'Note': [None, 'Ola was ill today']})
        with CaptureQueriesContext(connection) as queries, connection.schema_editor() as editor:
            migration().convert(apps, editor)
        statements = [query['sql'] for query in queries if 'audit_log' in query['sql']]
        self.assertEqual(statements[0], 'LOCK TABLE audit_log IN SHARE ROW EXCLUSIVE MODE')
        self.assertTrue(statements[1].startswith('SELECT'), statements[1])

    def test_the_check_finds_a_plain_value_written_after_the_conversion_and_the_command_converts_it(self):
        from core import checks
        self.assertEqual(checks.plain_private_values(None), [])
        old('task', {'Note': [None, 'written by a server that still ran the old code']})
        old('site', {'Contacts': [None, 'Kari (Vet, kari@example.com)']})
        old('user', {'Email address': [None, 'kari@example.com']})          # not decided private: not counted
        found = checks.plain_private_values(None)
        self.assertEqual([warning.id for warning in found], ['core.W004'])
        self.assertIn('2 activity-log row(s)', found[0].msg)
        self.assertIn('private_log_values', found[0].hint)
        self.assertNotIn('kari@example.com', found[0].msg + found[0].hint)
        call_command('private_log_values', stdout=StringIO())
        self.assertEqual(checks.plain_private_values(None), [])

    def test_the_check_waits_for_the_migration_and_is_quiet_before_it_has_run(self):
        from core import checks
        old('task', {'Note': [None, 'Ola was ill today']})
        with mock.patch.object(checks, 'conversion_applied', return_value=False):
            self.assertEqual(checks.plain_private_values(None), [])

    def test_the_landing_recipe_stops_the_server_before_it_migrates(self):
        recipe = (Path(settings.BASE_DIR) / 'CLAUDE.md').read_text(encoding='utf-8')
        step = next(line for line in recipe.splitlines() if line.startswith('5. '))
        self.assertLess(step.index('stop the dev server'), step.index('`migrate`'))


class LogWordsTests(TestCase):
    """Review R10 and R14: what a data migration writes into the log is shown translated like every other row, and
    one function writes a migration's log row."""

    def test_the_words_the_conversion_writes_are_in_both_catalogs(self):
        from django.utils import translation
        words = [_private.RECORD[0], *_private.COUNTS.values(), _private.WHOLE_IDS, _private.UNSURE, 'Note']
        for word in words:
            self.assertIn(word, [*audit.MIGRATION_WORDS, 'Note'], word)
            for language in ('nb', 'tr'):
                with translation.override(language):
                    self.assertNotEqual(translation.gettext(word), word, (language, word))

    def test_the_conversions_row_reads_in_the_readers_language(self):
        from django.utils import translation
        entry = AuditLog(user_name='system', action='update', entity_type=_private.RECORD[0], entity_id='core.0011',
                         entity_label='Private values', changes={_private.COUNTS['rows']: [None, '9']})
        with translation.override('nb'):
            self.assertEqual((entry.shown_type(), entry.shown_changes()),
                             ('aktivitetslogg', [('Oppføringer konvertert', None, '9')]))

    def test_one_function_writes_a_migrations_log_row(self):
        writers = [path.relative_to(settings.BASE_DIR).as_posix()
                   for path in Path(settings.BASE_DIR).glob('*/migrations/*.py')
                   if 'INSERT INTO audit_log' in path.read_text(encoding='utf-8')]
        self.assertEqual(writers, ['core/migrations/_log.py'])
