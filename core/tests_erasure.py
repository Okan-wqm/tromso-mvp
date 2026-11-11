"""`manage.py erase_stranger_address` (core/erasure.py; docs/erasure.md, step 8): the address of a stranger an
invitation was mis-sent to is erased on request, in `account_mails` and in the activity log's rows of the account, in
one transaction, with the log's append-only trigger set aside for those updates only and back in force afterwards,
however the command ends. The rows are made through the pages, as a platform admin makes them, and read back from the
database."""
import io
import json
import re
import threading
import time
from datetime import datetime, timedelta, timezone as dt_timezone
from smtplib import SMTPRecipientsRefused
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.mail.backends.base import BaseEmailBackend
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, connection, connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from . import accountmail, erasure
from .models import AccountMail, AuditLog
from .tests import user_data
from .tests_account_mail import BASE, NEW_PASSWORD, link_in, row_of

User = get_user_model()
STRANGER = 'strangr@example.com'
LONGER = 'xstrangr@example.com'               # another person's: the stranger's address is the tail of it
ERASED = {'msgid': 'Erased on request'}
INSTRUCTION = 'DPO instruction of 2026-11-11, ref. DP-17'
# the erasure's own row: a label with an enumerated value (both shown translated), then what a person typed
SAID = {'Erased on request': [None, {'msgid': 'The address of a mis-sent invitation'}],
        'Instruction': [None, INSTRUCTION], 'Carried out by': [None, 'Kari Nordmann']}


class NoSuchUser(BaseEmailBackend):
    """A mail server that refuses the recipient and repeats the address in its reply."""

    def send_messages(self, messages):
        raise SMTPRecipientsRefused({messages[0].to[0]: (550, b'5.1.1 No such user here')})


REFUSING = {'default': {'BACKEND': 'core.tests_erasure.NoSuchUser'}}


def run(*args):
    out = io.StringIO()
    call_command('erase_stranger_address', *args, stdout=out)
    return out.getvalue()


def apply(address=STRANGER):
    return run(address, '--apply', '--instruction', INSTRUCTION, '--carried-out-by', 'Kari Nordmann')


def stored():
    """Everything the erasure may touch, as the database holds it."""
    return (list(AccountMail.objects.order_by('pk').values_list('pk', 'user__username', 'address', 'error')),
            list(AuditLog.objects.order_by('created_at', 'id').values_list('pk', 'user_name', 'action', 'entity_type',
                                                                           'entity_id', 'entity_label', 'changes')))


def holding(text):
    """Where the database still holds the address `text` (as a whole address, whatever its case): the rows of
    account_mails and of the log, by what they are."""
    whole = re.compile(r'(?<![\w.])' + re.escape(text) + r'(?![\w.])', re.IGNORECASE)
    mails, log = stored()
    return ([f'account_mails of {name}' for _pk, name, address, error in mails if whole.search(f'{address} {error}')]
            + [f'{action} of {kind} {label}' for _pk, _who, action, kind, _id, label, changes in log
               if whole.search(json.dumps(changes, ensure_ascii=False))])


@override_settings(PUBLIC_BASE_URL=BASE, COMPANY_NAME='Nordhav Akva')
class ErasureCase(TestCase):
    """Three accounts a mistyped address reached, and what must stay as it is.

    - kari: invited at the stranger's address; the stranger set a password through the link; the admin then put the
      address right (log: Created `Email`, Invited `Sent to`, Password set `Link sent to`, Changed `Email`);
    - ola: invited at the stranger's address in capitals, the mail server refused it and repeated the address in its
      reply (account_mails `error`; the log's own "Not sent" row), the address then put right, no new invitation;
    - liv: invited at the stranger's address, the mail went out, the address put right, no new invitation;
    - per, with his own address, and anna, whose address ends with the stranger's: nothing of theirs may change."""

    def setUp(self):
        self.admin = User.objects.create_superuser('root', 'root@example.com', 'eski-sifre-123')
        self.client.force_login(self.admin)
        self.kari = self.create('kari', STRANGER)
        self.client.logout()
        opened = self.client.get(link_in(mail.outbox[-1]), follow=True)        # the stranger is quicker
        self.client.post(opened.redirect_chain[-1][0], NEW_PASSWORD)
        self.client.force_login(self.admin)
        self.correct(self.kari, 'kari@example.com')
        with override_settings(MAILERS=REFUSING), self.assertLogs('core.accountmail', 'ERROR'):
            self.ola = self.create('ola', 'Strangr@Example.com')
        self.correct(self.ola, 'ola@example.com')
        self.liv = self.create('liv', STRANGER)
        self.correct(self.liv, 'liv@example.com')
        self.per = self.create('per', 'per@example.com')
        with override_settings(MAILERS=REFUSING), self.assertLogs('core.accountmail', 'ERROR'):
            self.anna = self.create('anna', LONGER)
        # the same text where it is not an account's address: under another label of an account's row, in another kind
        # of record's field, and a contact list
        self.other_label = AuditLog.objects.create(user_name='root', action='update', entity_type='user',
                                                   entity_id=str(self.per.pk), entity_label='per',
                                                   changes={'Last name': ['Hansen', STRANGER]})
        self.elsewhere = AuditLog.objects.create(user_name='root', action='update', entity_type='site', entity_id='1',
                                                 entity_label='Bergen', changes={'Site manager': [None, STRANGER]})
        self.contacts = AuditLog.objects.create(
            user_name='root', action='update', entity_type='site', entity_id='1', entity_label='Bergen',
            changes={'Contacts': [None, [['Kari (Vet)', {'msgid': 'Private text', 'rev': '1a2b3c4d', 'of': 'Email'}]]]})
        self.before = stored()

    def create(self, username, address):
        self.client.post(reverse('core:user_create'), user_data(username=username, email=address))
        return User.objects.get(username=username)

    def correct(self, user, address):
        self.client.post(reverse('core:user_edit', args=[user.pk]), user_data(username=user.username, email=address))
        user.refresh_from_db()
        self.assertEqual(user.email, address)

    def changed(self):
        """(the account_mails rows, the log rows) that differ from before, and the rows added since."""
        mails, log = stored()
        old_mails, old_log = self.before
        return ([row for row in mails if row not in old_mails],
                [row for row in log if row not in old_log and row[0] in {old[0] for old in old_log}],
                [row for row in log if row[0] not in {old[0] for old in old_log}])


class ShapeTests(ErasureCase):
    def test_the_rows_hold_the_address_under_the_labels_the_command_reads(self):
        """The keys and shapes as the code writes them, read from the stored rows: what the command must find."""
        rows = {(who, action, label): changes for _pk, who, action, kind, _id, label, changes in self.before[1]
                if kind == 'user' and label in ('kari', 'ola')}
        self.assertEqual(rows[('root', 'create', 'kari')]['Email'], [None, STRANGER])
        self.assertEqual(rows[('root', 'invite', 'kari')], {'Sent to': [None, STRANGER]})
        self.assertEqual(rows[('kari', 'password', 'kari')], {'Link sent to': [None, STRANGER]})
        self.assertEqual(rows[('root', 'update', 'kari')], {'Email': [STRANGER, 'kari@example.com']})
        # (the form keeps the capitals of the part before the @ and writes the domain in small letters)
        self.assertEqual(rows[('system', 'invite', 'ola')]['Sent to'], [None, 'Strangr@example.com'])
        self.assertEqual(erasure.labels(), ('Email', 'Sent to', 'Link sent to'))
        self.assertEqual(erasure.user_type(), 'user')
        refused = AccountMail.objects.get(user=self.ola)
        self.assertEqual((refused.address, refused.error),
                         ('Strangr@example.com',
                          "SMTPRecipientsRefused: {'Strangr@example.com': (550, b'5.1.1 No such user here')}"))
        self.assertEqual(sorted(holding(STRANGER)), sorted([
            'account_mails of kari', 'account_mails of ola', 'account_mails of liv',
            'create of user kari', 'invite of user kari', 'password of user kari', 'update of user kari',
            'create of user ola', 'invite of user ola', 'invite of user ola', 'update of user ola',
            'create of user liv', 'invite of user liv', 'update of user liv', 'update of user per',
            'update of site Bergen']))
        self.assertEqual(sorted(holding(LONGER)), ['account_mails of anna', 'create of user anna', 'invite of user anna',
                                                    'invite of user anna'])


class DryRunTests(ErasureCase):
    def test_without_apply_nothing_is_changed_and_every_row_and_label_is_named(self):
        with CaptureQueriesContext(connection) as queries:
            said = run(STRANGER)
        self.assertEqual(stored(), self.before)
        self.assertFalse(any('TRIGGER' in query['sql'].upper() or query['sql'].upper().startswith(('UPDATE', 'INSERT',
                                                                                                    'DELETE', 'LOCK'))
                             for query in queries))
        self.assertIn('Dry run: nothing is changed.', said)
        self.assertIn('3 account_mails row(s) would change:', said)
        for user, what in ((self.kari, 'address'), (self.ola, 'address and error'), (self.liv, 'address')):
            row = AccountMail.objects.get(user=user)
            self.assertRegex(said, rf'account_mails {row.pk}: invitation of [0-9: -]+ UTC for account {user.pk} '
                                   rf'\({user.username}\): {what}\n')
        self.assertIn('11 activity-log row(s) would change:', said)
        for entry in AuditLog.objects.filter(entity_type='user', entity_label='kari'):
            labels = {'create': 'Email', 'invite': 'Sent to', 'password': 'Link sent to', 'update': 'Email'}[entry.action]
            self.assertRegex(said, rf'audit_log {entry.pk}: {entry.action} of [0-9: -]+ UTC on account {self.kari.pk} '
                                   rf'\(kari\): {labels}\n')
        self.assertIn(f'would be added on each account touched: {self.kari.pk}, {self.ola.pk}, {self.liv.pk}.', said)
        self.assertIn(f'activity log {self.elsewhere.pk} (update of site Bergen)', said)       # named, left as it is
        self.assertIn(f'activity log {self.other_label.pk} (update of user per): under “Last name”', said)
        self.assertNotIn(LONGER, said)
        self.assertNotIn('anna', said)

    def test_the_dry_run_says_when_the_erasure_would_be_refused(self):
        said = run('KARI@example.com')
        self.assertIn('REFUSED: KARI@example.com is the address of an account now (kari)', said)
        self.assertEqual(stored(), self.before)


class EraseTests(ErasureCase):
    def test_the_address_is_replaced_in_the_mails_and_in_the_accounts_log_rows_and_nowhere_else(self):
        said = apply()
        mails, log, added = self.changed()
        self.assertEqual(sorted((name, address, error) for _pk, name, address, error in mails), [
            ('kari', 'erased@invalid', ''),
            ('liv', 'erased@invalid', ''),
            ('ola', 'erased@invalid', "SMTPRecipientsRefused: {'erased@invalid': (550, b'5.1.1 No such user here')}")])
        self.assertEqual(sorted((label, action, who, json.dumps(changes, sort_keys=True))
                                for _pk, who, action, _kind, _id, label, changes in log), sorted(
            (label, action, who, json.dumps(changes, sort_keys=True)) for label, action, who, changes in [
                ('kari', 'create', 'root', {**self.was('kari', 'create'), 'Email': [None, ERASED]}),
                ('kari', 'invite', 'root', {'Sent to': [None, ERASED]}),
                ('kari', 'password', 'kari', {'Link sent to': [None, ERASED]}),
                ('kari', 'update', 'root', {'Email': [ERASED, 'kari@example.com']}),
                ('ola', 'create', 'root', {**self.was('ola', 'create'), 'Email': [None, ERASED]}),
                ('ola', 'invite', 'root', {'Sent to': [None, ERASED]}),
                ('ola', 'invite', 'system', {**self.was('ola', 'invite', 'system'), 'Sent to': [None, ERASED]}),
                ('ola', 'update', 'root', {'Email': [ERASED, 'ola@example.com']}),
                ('liv', 'create', 'root', {**self.was('liv', 'create'), 'Email': [None, ERASED]}),
                ('liv', 'invite', 'root', {'Sent to': [None, ERASED]}),
                ('liv', 'update', 'root', {'Email': [ERASED, 'liv@example.com']}),
            ]))
        # who, when and which record of every changed row are what they were: only `changes` was written
        untouched = {row[0]: row[:6] for row in self.before[1]}
        self.assertTrue(all(row[:6] == untouched[row[0]] for row in log))
        times = dict(AuditLog.objects.values_list('pk', 'created_at'))
        self.assertEqual({pk: times[pk] for pk in self.times}, self.times)
        # one new row on each account touched, by nobody signed in, with the instruction and who carried it out
        self.assertEqual(sorted((who, action, kind, pk, label, json.dumps(changes))
                                for _id, who, action, kind, pk, label, changes in added), sorted(
            ('system', 'update', 'user', str(user.pk), user.username, json.dumps(SAID))
            for user in (self.kari, self.ola, self.liv)))
        # nothing of anybody else, of another kind of record or of a contact list
        self.assertEqual(sorted(holding(STRANGER)), ['update of site Bergen', 'update of user per'])
        self.assertEqual(sorted(holding(LONGER)), ['account_mails of anna', 'create of user anna', 'invite of user anna',
                                                    'invite of user anna'])
        self.assertEqual(AuditLog.objects.get(pk=self.other_label.pk).changes, {'Last name': ['Hansen', STRANGER]})
        self.assertEqual(AuditLog.objects.get(pk=self.contacts.pk).changes, self.contacts.changes)
        self.assertEqual({user.username: user.email for user in User.objects.exclude(username='root')}, {
            'kari': 'kari@example.com', 'ola': 'ola@example.com', 'liv': 'liv@example.com', 'per': 'per@example.com',
            'anna': LONGER})
        self.assertIn('3 account_mails row(s) changed:', said)
        self.assertIn('11 activity-log row(s) changed:', said)
        self.assertIn('The activity log\'s append-only trigger is in force.', said)

    def setUp(self):
        super().setUp()
        self.times = dict(AuditLog.objects.values_list('pk', 'created_at'))

    def was(self, label, action, who='root'):
        return next(changes for _pk, by, did, kind, _id, name, changes in self.before[1]
                    if (kind, name, did, by) == ('user', label, action, who))

    def test_the_trigger_is_back_and_refuses_an_ordinary_change_of_the_log(self):
        apply()
        with connection.cursor() as cursor:
            self.assertTrue(erasure.trigger_in_force(cursor))
        for change in (lambda: AuditLog.objects.filter(pk=self.elsewhere.pk).update(entity_label='x'),
                       lambda: AuditLog.objects.filter(pk=self.elsewhere.pk).delete()):
            with self.assertRaisesMessage(DatabaseError, 'append-only'), transaction.atomic():
                change()

    def test_run_again_it_finds_nothing_and_touches_nothing(self):
        apply()
        after = stored()
        with CaptureQueriesContext(connection) as queries:
            said = apply()
        self.assertEqual(stored(), after)
        self.assertIn(f'Nothing found: no account_mails row and no activity-log row of a user account holds {STRANGER}.',
                      said)
        self.assertFalse(any('TRIGGER' in query['sql'].upper() and 'ALTER' in query['sql'].upper() for query in queries))

    def test_an_address_nobody_has_seen_is_reported_and_the_trigger_is_never_set_aside(self):
        with CaptureQueriesContext(connection) as queries:
            said = apply('nobody@example.org')
        self.assertEqual(stored(), self.before)
        self.assertIn('Nothing found', said)
        self.assertFalse(any('ALTER TABLE' in query['sql'].upper() for query in queries))

    def test_a_reply_that_grows_past_its_column_with_the_placeholder_is_cut_like_any_reason(self):
        short = 'a@b.no'                                                   # six characters; the placeholder has fourteen
        reply = ('refused ' + short + ' ') * 33 + 'x' * 5                  # 500 characters, the column's length
        self.assertEqual(len(reply), AccountMail._meta.get_field('error').max_length)
        AccountMail.objects.filter(user=self.per).update(error=reply)
        apply(short)
        kept = AccountMail.objects.get(user=self.per)
        self.assertEqual((len(kept.error), kept.error[-1], short in kept.error), (500, '…', False))
        self.assertTrue(kept.error.startswith('refused erased@invalid refused erased@invalid '))
        self.assertEqual(kept.address, 'per@example.com')                 # the row is per's: only the reply was changed

    def test_case_and_the_spaces_around_the_address_do_not_matter(self):
        apply('  STRANGR@EXAMPLE.COM ')
        self.assertEqual(sorted(holding(STRANGER)), ['update of site Bergen', 'update of user per'])


class RefusalTests(ErasureCase):
    def test_an_address_that_is_an_accounts_own_is_refused_whatever_its_case_and_the_account_active_or_not(self):
        User.objects.filter(pk=self.per.pk).update(is_active=False)
        for address in ('kari@example.com', ' Kari@Example.COM ', 'per@example.com', LONGER):
            with self.subTest(address=address), CaptureQueriesContext(connection) as queries:
                with self.assertRaisesMessage(CommandError, 'is the address of an account now'):
                    apply(address)
                self.assertFalse(any('ALTER TABLE' in query['sql'].upper() for query in queries))
        self.assertEqual(stored(), self.before)

    def test_the_stranger_who_later_got_an_account_is_not_erased(self):
        self.create('stranger', STRANGER)
        before = stored()
        with self.assertRaisesMessage(CommandError, f'{STRANGER} is the address of an account now (stranger)'):
            apply()
        self.assertEqual(stored(), before)

    def test_a_mail_to_the_address_still_being_sent_is_waited_for(self):
        AccountMail.objects.filter(user=self.liv).update(sent_at=None, error='')
        with self.assertRaisesMessage(CommandError, 'is being sent right now'):
            apply()
        self.assertEqual(AccountMail.objects.get(user=self.liv).address, STRANGER)

    def test_apply_needs_the_instruction_and_who_carries_it_out_and_an_address(self):
        for args in ((STRANGER, '--apply'), (STRANGER, '--apply', '--instruction', INSTRUCTION),
                     (STRANGER, '--apply', '--carried-out-by', 'Kari Nordmann'),
                     (STRANGER, '--apply', '--instruction', '  ', '--carried-out-by', 'Kari Nordmann')):
            with self.subTest(args=args), self.assertRaisesMessage(CommandError, '--apply needs --instruction'):
                run(*args)
        for address in ('not an address', 'Stranger <strangr@example.com>', ''):
            with self.subTest(address=address), self.assertRaisesMessage(CommandError, 'is not an e-mail address'):
                run(address)
        self.assertEqual(stored(), self.before)


class HalfWayTests(ErasureCase):
    """The command fails after it has set the trigger aside: nothing is kept, and the trigger is in force."""

    def assert_nothing_happened(self):
        self.assertEqual(stored(), self.before)
        with connection.cursor() as cursor:
            self.assertTrue(erasure.trigger_in_force(cursor))
        with self.assertRaisesMessage(DatabaseError, 'append-only'), transaction.atomic():
            AuditLog.objects.filter(pk=self.elsewhere.pk).update(entity_label='x')

    def test_a_fault_between_two_of_the_logs_updates(self):
        rewrite, done = erasure._rewrite, []

        def second_fails(cursor, entry, changes):
            if done:
                raise RuntimeError('the database went away half-way')
            done.append(entry.pk)
            rewrite(cursor, entry, changes)

        with mock.patch.object(erasure, '_rewrite', side_effect=second_fails), \
                self.assertRaisesMessage(RuntimeError, 'half-way'):
            apply()
        self.assertEqual(len(done), 1)                         # one row of the log had been rewritten
        self.assert_nothing_happened()

    def test_a_fault_while_the_erasures_own_rows_are_written(self):
        with mock.patch.object(erasure, '_say', side_effect=RuntimeError('half-way')), \
                self.assertRaisesMessage(RuntimeError, 'half-way'):
            apply()
        self.assert_nothing_happened()

    def test_a_trigger_that_did_not_come_back_keeps_nothing(self):
        with mock.patch.object(erasure, 'trigger_in_force', return_value=False), \
                self.assertRaisesMessage(RuntimeError, 'is not in force: nothing is kept'):
            apply()
        self.assertEqual(stored(), self.before)


class PagesTests(ErasureCase):
    """The log stays honest and every page that reads those rows still reads: an invitation went out, a link was
    used, an address was changed, only not to which address."""

    WORDS = {
        'en': ('through the link sent to an address that was erased on request, which is not this account’s address now',
               'to an address that was erased on request; the address has changed since, so its link no longer works',
               'to an address that was erased on request:', 'Erased on request'),
        'nb': ('via lenken sendt til en adresse som er slettet på forespørsel, som ikke er denne kontoens adresse nå',
               'til en adresse som er slettet på forespørsel; adressen er endret siden, så lenken virker ikke lenger',
               'til en adresse som er slettet på forespørsel:', 'Slettet på forespørsel'),
        'tr': ('talep üzerine silinmiş bir adrese gönderilen bağlantıyla belirlendi; bu adres artık bu hesabın adresi '
               'değil',
               'talep üzerine silinmiş bir adrese; adres o zamandan beri değişti, bu yüzden bağlantı artık çalışmıyor',
               'talep üzerine silinmiş bir adrese:', 'Talep üzerine silindi'),
    }

    def test_the_users_tab_the_log_and_the_history_read_an_erased_row_in_every_language(self):
        apply()
        for language, (password, changed, refused, erased) in self.WORDS.items():
            with self.subTest(language=language):
                headers = {'Accept-Language': language}
                users = self.client.get(reverse('core:user_list'), headers=headers)
                self.assertEqual(users.status_code, 200)
                self.assertIn(password, row_of(users, 'kari'))
                self.assertIn(changed, row_of(users, 'liv'))
                self.assertIn(refused, row_of(users, 'ola'))
                self.assertIn('No such user here', row_of(users, 'ola'))          # why it was not sent is still said
                for name in ('kari', 'liv'):                       # the placeholder itself is shown in no sentence
                    self.assertNotIn('erased@invalid', row_of(users, name))
                for name in ('kari', 'liv', 'ola'):
                    self.assertNotIn('strangr', row_of(users, name).lower())
                log = self.client.get(reverse('core:activity_log'), headers=headers)
                self.assertEqual(log.status_code, 200)
                self.assertContains(log, erased)
                self.assertNotContains(log, 'Strangr@example.com')
                history = self.client.get(reverse('core:user_edit', args=[self.kari.pk]), headers=headers)
                self.assertEqual(history.status_code, 200)
                self.assertContains(history, erased)
                self.assertNotContains(history, STRANGER)

    def test_the_standing_of_each_account_says_what_happened_without_the_address(self):
        apply()
        people = {user.username: accountmail.standing(user) for user in User.objects.all()}
        self.assertEqual((people['kari'].state, people['kari'].link_erased, people['kari'].link_address),
                         ('password_set', True, ''))
        self.assertIsNotNone(people['kari'].set_at)                                  # when it was set is still known
        self.assertEqual((people['liv'].state, people['liv'].mail_erased, people['liv'].can_send),
                         ('address_changed', True, True))
        self.assertEqual((people['ola'].state, people['ola'].mail_erased, people['ola'].can_send),
                         ('not_sent', True, True))
        self.assertEqual((people['per'].state, people['per'].mail_erased), ('sent', False))

    def test_the_account_can_be_invited_again_after_the_erasure(self):
        apply()
        self.client.post(reverse('core:user_invite', args=[self.liv.pk]))
        self.assertEqual(mail.outbox[-1].to, ['liv@example.com'])
        self.assertIn('Invitation sent', row_of(self.client.get(reverse('core:user_list')), 'liv'))


def own_rows():
    """The rows the erasure itself wrote."""
    return list(AuditLog.objects.filter(changes__has_key='Erased on request').order_by('created_at', 'id'))


class NothingWrittenHoldsTheAddressTests(ErasureCase):
    """Review Q1: the erasure wrote the address back into the append-only log, in the sentence built from the
    instruction and the name, and as the label of its own row when the account's username was the address; a second
    run then found nothing it could change."""

    def test_an_instruction_or_a_name_that_holds_the_address_is_refused_and_nothing_is_changed(self):
        for instruction, by in ((f'DPO: erase {STRANGER} (ref. DP-17)', 'Kari Nordmann'),
                                (INSTRUCTION, f'Kari Nordmann <{STRANGER}>'),
                                ('Erase STRANGR@EXAMPLE.COM, ref. DP-17', 'Kari Nordmann'),          # another case
                                ('Erase ｓｔｒａｎｇｒ@example.com, ref. DP-17', 'Kari Nordmann')):     # another Unicode form
            with self.subTest(instruction=instruction, by=by), \
                    self.assertRaisesMessage(CommandError, 'holds the address itself'):
                run(STRANGER, '--apply', '--instruction', instruction, '--carried-out-by', by)
        self.assertEqual(stored(), self.before)
        # an address that only contains it is another address: the instruction may name that one
        run(STRANGER, '--apply', '--instruction', f'DP-17, not {LONGER}', '--carried-out-by', 'Kari Nordmann')
        self.assertEqual(len(own_rows()), 3)

    def test_the_erasures_row_is_not_under_a_username_that_is_the_address(self):
        User.objects.filter(pk=self.liv.pk).update(username='Strangr@EXAMPLE.com')       # a username may be an address
        apply()
        written = {row.entity_id: row for row in own_rows()}
        self.assertEqual({pk: row.entity_label for pk, row in written.items()},
                         {str(self.kari.pk): 'kari', str(self.ola.pk): 'ola', str(self.liv.pk): f'account {self.liv.pk}'})
        for row in written.values():                                   # nothing the erasure wrote holds the address
            kept = json.dumps([row.user_name, row.entity_label, row.changes], ensure_ascii=False).lower()
            self.assertNotIn('strangr', kept)
        again = run(STRANGER)                                          # and a second run finds nothing it wrote
        self.assertIn('Nothing found', again)
        self.assertNotIn('Erased on request', again)
        for row in written.values():
            self.assertNotIn(str(row.pk), again)


class WhatIsCheckedTests(ErasureCase):
    """Review Q4: the command checks that the address is no account's address now, and nothing else. It cannot tell a
    stranger's address from a person's own former one, so it says what it checks and shows what the log says of each
    account, for the data-protection officer to judge by; it warns, and still obeys."""

    def test_the_dry_run_says_what_is_checked_and_what_the_log_says_of_each_account(self):
        said = run(STRANGER)
        self.assertIn('Checked: no account has this address now. Not checked: whose address it was', said)
        kari = said[said.index(f'Account {self.kari.pk} (kari):'):said.index(f'Account {self.ola.pk} (ola):')]
        self.assertRegex(kari, r'its own address from [0-9: -]+ UTC \(create by root\) to [0-9: -]+ UTC \(update by root\)')
        self.assertRegex(kari, r'a password was set through a link sent to it: [0-9: -]+ UTC, by kari')
        self.assertRegex(kari, r'an invitation was sent, or tried, to it: [0-9: -]+ UTC, by root')
        ola = said[said.index(f'Account {self.ola.pk} (ola):'):said.index(f'Account {self.liv.pk} (liv):')]
        self.assertIn('no password was set through a link sent to it', ola)
        self.assertNotIn('WARNING', said)               # put right within the hour, the accounts not used meanwhile

    def test_a_persons_own_former_address_is_said_to_look_like_one_and_the_command_still_obeys(self):
        """The review's case: per had per.old@ for a year, set his own password through his own link, worked, then
        changed his address. Nothing in the code can tell this from a stranger's address."""
        per = User.objects.create_user('per2', 'per.new@example.com', 'x')
        then = datetime(2025, 11, 1, 9, 0, tzinfo=dt_timezone.utc)

        def row(when, who, action, kind, pk, label, changes):
            with mock.patch('django.utils.timezone.now', return_value=when):
                return AuditLog.objects.create(user_name=who, action=action, entity_type=kind, entity_id=str(pk),
                                               entity_label=label, changes=changes)

        row(then, 'root', 'create', 'user', per.pk, 'per2', {'Email': [None, 'per.old@example.com']})
        row(then + timedelta(hours=1), 'per2', 'password', 'user', per.pk, 'per2', {'Link sent to': [None, 'per.old@example.com']})
        row(then + timedelta(days=30), 'per2', 'update', 'site', 1, 'Bergen', {'Site name': ['Bergen', 'Bergen havn']})
        row(then + timedelta(days=60), 'per2', 'create', 'task', 7, 'Clean filter', {})
        row(then + timedelta(days=365), 'root', 'update', 'user', per.pk, 'per2',
            {'Email': ['per.old@example.com', 'per.new@example.com']})
        said = run('per.old@example.com')
        self.assertIn('WARNING: this does not look like a stranger’s address', said)
        self.assertIn('it was the account’s own address for 365 day(s)', said)
        self.assertIn('the account wrote 2 other log row(s) itself while it was its address', said)
        self.assertIn('The data-protection officer decides', said)
        apply('per.old@example.com')                      # it informs; it does not judge
        self.assertEqual(AuditLog.objects.filter(entity_id=str(per.pk), changes__has_key='Erased on request').count(), 1)

    def test_the_refusal_and_the_help_say_what_is_checked(self):
        from core.management.commands.erase_stranger_address import Command
        with self.assertRaisesMessage(CommandError, 'This command erases only an address that no account has now'):
            apply('kari@example.com')
        self.assertIn('It checks only that no account has the address now', Command.help)
        self.assertIn('cannot tell a stranger’s address from a person’s own former one', Command.help)


class OtherShapesTests(ErasureCase):
    """Review Q5: a value of another shape or under another label on a user's row is neither changed nor passed over
    in silence, and the dry run shows a value that is stored otherwise than it was typed."""

    def test_what_is_not_changed_on_a_users_row_is_listed(self):
        pk = str(self.per.pk)
        made = {name: AuditLog.objects.create(user_name='root', action='update', entity_type='user', entity_id=pk,
                                              entity_label='per', changes=changes)
                for name, changes in (('with a name', {'Email': [None, f'Stranger <{STRANGER}>']}),
                                      ('a list inside', {'Sent to': [None, [STRANGER]]}),
                                      ('an enumerated value', {'Sent to': [None, {'msgid': STRANGER}]}),
                                      ('the label in small letters', {'email': [None, STRANGER]}),
                                      ('not a pair', {'Email': STRANGER}))}
        three = AuditLog.objects.create(user_name='root', action='update', entity_type='user', entity_id=pk,
                                        entity_label='per', changes={'Email': [None, STRANGER, f' {STRANGER} ']})
        said = run(STRANGER)
        for name, entry in made.items():
            with self.subTest(shape=name):
                self.assertRegex(said, rf'activity log {entry.pk} \(update of user per\): under “[A-Za-z ]+” \(another')
        apply()
        for name, entry in made.items():
            with self.subTest(shape=name):
                self.assertEqual(AuditLog.objects.get(pk=entry.pk).changes, entry.changes)       # left as it is
        self.assertEqual(AuditLog.objects.get(pk=three.pk).changes, {'Email': [None, ERASED, ERASED]})

    def test_a_value_stored_otherwise_than_it_was_typed_is_shown(self):
        said = run(STRANGER)
        ola = AccountMail.objects.get(user=self.ola)
        self.assertRegex(said, rf'account_mails {ola.pk}: .*: address and error \(stored as “Strangr@example.com”\)\n')
        created = AuditLog.objects.get(entity_type='user', entity_label='ola', action='create')
        self.assertRegex(said, rf'audit_log {created.pk}: .*: Email \(stored as “Strangr@example.com”\)\n')
        kari = AuditLog.objects.get(entity_type='user', entity_label='kari', action='create')
        self.assertRegex(said, rf'audit_log {kari.pk}: .*: Email\n')                             # as typed: not repeated

    def test_the_address_in_another_unicode_form_inside_a_reply_is_replaced_and_what_is_not_is_left(self):
        AccountMail.objects.filter(user=self.per).update(
            error=f'refused ＳＴＲＡＮＧＲ@example.com; bounce to strangr=example.com@bounce.example; {STRANGER[:12]}…')
        apply()
        self.assertEqual(AccountMail.objects.get(user=self.per).error,
                         'refused erased@invalid; bounce to strangr=example.com@bounce.example; strangr@exam…')


class ErasuresRowTests(ErasureCase):
    """Review Q9: the erasure's own row is in the log's own shape, so its label and what was erased are shown in the
    reader's language; the instruction and the name are a person's words and stay as typed."""

    WORDS = {'en': ('Erased on request', 'The address of a mis-sent invitation', 'Instruction', 'Carried out by'),
             'nb': ('Slettet på forespørsel', 'Adressen til en feilsendt invitasjon', 'Instruks', 'Utført av'),
             'tr': ('Talep üzerine silindi', 'Yanlış gönderilen bir davetin adresi', 'Talimat', 'Uygulayan')}

    def test_its_row_reads_in_every_language_on_the_history_tab(self):
        apply()
        [row] = [row for row in own_rows() if row.entity_id == str(self.kari.pk)]
        self.assertEqual(row.changes, SAID)
        for language, words in self.WORDS.items():
            with self.subTest(language=language):
                history = self.client.get(reverse('core:user_edit', args=[self.kari.pk]),
                                          headers={'Accept-Language': language})
                for word in (*words, INSTRUCTION, 'Kari Nordmann'):
                    self.assertContains(history, word)


class RealCase(TransactionTestCase):
    """The erasure with real commits and a second session (the review's experiments, kept as tests): what another
    session sees of the trigger and of the rows, before, during and after."""
    serialized_rollback = True            # the next test finds the rows the migrations made

    def setUp(self):
        self.kari = User.objects.create_user('kari', 'kari@example.com', 'x')
        for action, changes in (('create', {'Email': [None, STRANGER], 'Username': [None, 'kari']}),
                                ('invite', {'Sent to': [None, STRANGER]}),
                                ('password', {'Link sent to': [None, STRANGER]}),
                                ('update', {'Email': [STRANGER, 'kari@example.com']})):
            AuditLog.objects.create(user_name='root', action=action, entity_type='user', entity_id=str(self.kari.pk),
                                    entity_label='kari', changes=changes)
        self.bergen = AuditLog.objects.create(user_name='root', action='update', entity_type='site', entity_id='1',
                                              entity_label='Bergen', changes={'Site name': ['a', 'b']})
        AccountMail.objects.create(user=self.kari, kind='invitation', address=STRANGER, sent_at=timezone.now())
        self.other = connections['default'].copy()
        self.addCleanup(self.other.close)

    def elsewhere(self, sql, params=None, connection=None):
        """Runs on the second session (autocommit) and returns its rows."""
        with (connection or self.other).cursor() as cursor:
            cursor.execute(sql, params or [])
            return cursor.fetchall() if cursor.description else None

    def seen_elsewhere(self):
        """(the trigger's state, how many log rows hold the address, the mails' addresses) as the second session sees them."""
        enabled = self.elsewhere("SELECT tgenabled FROM pg_trigger WHERE tgname = 'trg_audit_log_append_only' "
                                 "AND tgrelid = 'audit_log'::regclass")
        holding = self.elsewhere('SELECT count(*) FROM audit_log WHERE changes::text ILIKE %s', [f'%{STRANGER}%'])
        return [row[0] for row in enabled], holding[0][0], [row[0] for row in self.elsewhere(
            'SELECT address FROM account_mails ORDER BY id')]

    UNTOUCHED, ERASED_STATE = (['O'], 4, [STRANGER]), (['O'], 0, ['erased@invalid'])
    INSERT = ("INSERT INTO audit_log (id, created_at, user_name, action, entity_type, entity_id, entity_label, changes, "
              "severity) VALUES (gen_random_uuid(), now(), 'x', 'update', 'site', '1', 'x', '{}'::jsonb, 'normal')")

    def assert_the_log_is_append_only_elsewhere(self):
        for change in ("UPDATE audit_log SET entity_label = 'x' WHERE id = %s", 'DELETE FROM audit_log WHERE id = %s'):
            with self.assertRaisesMessage(DatabaseError, 'append-only'):
                self.elsewhere(change, [self.bergen.pk])


class TriggerTests(RealCase):
    """Every guarantee about the trigger, with real transactions."""

    def test_a_real_commit(self):
        self.assertTrue(connection.get_autocommit())
        self.assertEqual(self.seen_elsewhere(), self.UNTOUCHED)
        apply()
        self.assertFalse(connection.in_atomic_block)
        self.assertEqual(self.seen_elsewhere(), self.ERASED_STATE)
        self.assert_the_log_is_append_only_elsewhere()
        self.assertEqual(len(own_rows()), 1)

    def test_a_real_rollback_when_the_erasures_own_row_fails(self):
        with mock.patch.object(erasure, '_say', side_effect=RuntimeError('half-way')), \
                self.assertRaisesMessage(RuntimeError, 'half-way'):
            apply()
        self.assertFalse(connection.in_atomic_block)
        self.assertEqual(self.seen_elsewhere(), self.UNTOUCHED)
        self.assert_the_log_is_append_only_elsewhere()

    def test_a_fault_and_an_interrupt_while_the_trigger_is_set_aside(self):
        for fault in (RuntimeError('boom'), KeyboardInterrupt()):
            with self.subTest(fault=type(fault).__name__):
                seen = []

                def fails(cursor, entry, changes, fault=fault, seen=seen):
                    cursor.execute("SELECT tgenabled FROM pg_trigger WHERE tgname = 'trg_audit_log_append_only'")
                    seen.append(cursor.fetchone()[0])
                    raise fault

                with mock.patch.object(erasure, '_rewrite', side_effect=fails), self.assertRaises(type(fault)):
                    apply()
                self.assertEqual(seen, ['D'])                              # it really was set aside in that transaction
                self.assertFalse(connection.in_atomic_block)
                self.assertEqual(self.seen_elsewhere(), self.UNTOUCHED)
                self.assert_the_log_is_append_only_elsewhere()
                with connection.cursor() as cursor:
                    self.assertTrue(erasure.trigger_in_force(cursor))

    def test_another_session_sees_the_trigger_in_force_and_cannot_write_while_it_is_set_aside(self):
        rewrite, seen = erasure._rewrite, {}

        def look(cursor, entry, changes):
            if not seen:
                self.elsewhere("SET lock_timeout = '700ms'")
                seen['catalog'] = self.elsewhere(
                    "SELECT tgenabled FROM pg_trigger WHERE tgname = 'trg_audit_log_append_only'")[0][0]
                seen['read'] = self.elsewhere('SELECT count(*) FROM audit_log')[0][0]
                for name, sql, params in (('update', "UPDATE audit_log SET entity_label = 'x' WHERE id = %s",
                                           [self.bergen.pk]),
                                          ('delete', 'DELETE FROM audit_log WHERE id = %s', [self.bergen.pk]),
                                          ('insert', self.INSERT, [])):
                    try:
                        self.elsewhere(sql, params)
                        seen[name] = 'done'
                    except DatabaseError as refusal:
                        seen[name] = ' '.join(str(refusal).split())[:40]
                self.elsewhere('SET lock_timeout = 0')
            rewrite(cursor, entry, changes)

        with mock.patch.object(erasure, '_rewrite', side_effect=look):
            apply()
        self.assertEqual((seen['catalog'], seen['read']), ('O', 5))        # readers go on; the catalog is not theirs to see
        for name in ('update', 'delete', 'insert'):
            self.assertIn('lock timeout', seen[name])                      # writers wait: nothing slips past the trigger
        self.assertEqual(self.seen_elsewhere(), self.ERASED_STATE)
        self.assertEqual(AuditLog.objects.get(pk=self.bergen.pk).entity_label, 'Bergen')

    def test_the_connection_is_lost_while_the_trigger_is_set_aside(self):
        def killed(cursor, entry, changes):
            cursor.execute('SELECT pg_backend_pid()')
            self.elsewhere('SELECT pg_terminate_backend(%s)', [cursor.fetchone()[0]])
            cursor.execute('SELECT 1')

        with mock.patch.object(erasure, '_rewrite', side_effect=killed), self.assertRaises(DatabaseError):
            apply()
        connection.close()
        self.assertEqual(self.seen_elsewhere(), self.UNTOUCHED)
        self.assert_the_log_is_append_only_elsewhere()

    def test_inside_a_callers_transaction_that_catches_the_fault_and_commits(self):
        with transaction.atomic():
            with mock.patch.object(erasure, '_rewrite', side_effect=RuntimeError('boom')), \
                    self.assertRaisesMessage(RuntimeError, 'boom'):
                erasure.erase(STRANGER, INSTRUCTION, 'Kari Nordmann')
            with connection.cursor() as cursor:
                self.assertTrue(erasure.trigger_in_force(cursor))
                cursor.execute("SELECT current_setting('lock_timeout')")
                self.assertEqual(cursor.fetchone()[0], '0')                # the caller's own waits are as they were
        self.assertEqual(self.seen_elsewhere(), self.UNTOUCHED)
        self.assert_the_log_is_append_only_elsewhere()

    def test_with_autocommit_off(self):
        transaction.set_autocommit(False)
        try:
            with mock.patch.object(erasure, '_rewrite', side_effect=RuntimeError('boom')), \
                    self.assertRaisesMessage(RuntimeError, 'boom'):
                erasure.erase(STRANGER, INSTRUCTION, 'Kari Nordmann')
            with connection.cursor() as cursor:
                self.assertTrue(erasure.trigger_in_force(cursor))
            transaction.commit()
        finally:
            transaction.set_autocommit(True)
        self.assertEqual(self.seen_elsewhere(), self.UNTOUCHED)
        self.assert_the_log_is_append_only_elsewhere()


class LockTests(RealCase):
    """Review Q3: the command took the lock on the log first and read everything under it, with no limit to its wait:
    every writer of the log, the alarms among them, queued behind it for as long as it waited and read."""

    def locks_on_the_log(self):
        return sorted(row[0] for row in self.elsewhere(
            "SELECT mode FROM pg_locks WHERE relation = 'audit_log'::regclass AND granted AND pid <> pg_backend_pid()"))

    def test_everything_is_read_before_the_lock_is_taken(self):
        plan, seen = erasure.plan, []

        def watched(address):
            found = plan(address)
            seen.append(self.locks_on_the_log())            # what the reading session holds on the log, the read done
            return found

        with mock.patch.object(erasure, 'plan', side_effect=watched):
            apply()
        self.assertEqual(seen, [[]])                        # nothing: no writer waited while it read
        self.assertEqual(self.seen_elsewhere(), self.ERASED_STATE)

    def test_a_log_that_is_being_written_is_waited_for_a_bounded_time_and_then_refused(self):
        holder = connections['default'].copy()
        self.addCleanup(holder.close)
        holder.set_autocommit(False)
        self.elsewhere(self.INSERT, connection=holder)       # a transaction that wrote the log and stays open
        outcome = {}

        def command():
            began = time.monotonic()
            try:
                run(STRANGER, '--apply', '--instruction', INSTRUCTION, '--carried-out-by', 'Kari Nordmann',
                    '--lock-wait', '1')
                outcome['said'] = 'done'
            except CommandError as refusal:
                outcome['said'] = str(refusal)
            finally:
                outcome['took'] = time.monotonic() - began
                connection.close()

        thread = threading.Thread(target=command)
        thread.start()
        thread.join(8)
        waiting = thread.is_alive()
        if waiting:                                           # the old way: it waits for as long as the writer does
            holder.rollback()
            thread.join(30)
        self.assertFalse(waiting, 'the command was still waiting for the lock after 8 seconds')
        self.assertIn('could not be locked within 1 second(s): nothing was changed', outcome['said'])
        self.assertLess(outcome['took'], 6)
        self.elsewhere("SET lock_timeout = '2s'")
        self.elsewhere(self.INSERT)                           # no writer is held up once it has given up
        self.elsewhere('SET lock_timeout = 0')
        holder.rollback()
        self.assertEqual(self.seen_elsewhere(), self.UNTOUCHED)
        self.assert_the_log_is_append_only_elsewhere()

    def test_a_row_of_a_user_written_between_the_read_and_the_lock_refuses_it(self):
        plan = erasure.plan

        def then_a_row_is_written(address):
            found = plan(address)
            self.elsewhere("SET lock_timeout = '700ms'")
            try:                                              # another server process logs a change of a user meanwhile
                self.elsewhere(self.INSERT.replace("'site'", "'user'"))
            except DatabaseError:
                pass                                          # the old way: the log was locked already
            self.elsewhere('SET lock_timeout = 0')
            return found

        with mock.patch.object(erasure, 'plan', side_effect=then_a_row_is_written), \
                self.assertRaisesMessage(CommandError, 'while it was being prepared: nothing was changed'):
            apply()
        self.assertEqual(self.seen_elsewhere(), self.UNTOUCHED)
        self.assert_the_log_is_append_only_elsewhere()
