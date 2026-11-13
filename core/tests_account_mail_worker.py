"""The account e-mails leave after the request, not in it (core.accountmail's worker). The request writes the mail as
waiting in its own transaction and answers; the mail server is talked to afterwards, by the worker thread, outside any
transaction and any lock. These tests run the real worker (the other tests run its jobs at once, in the request), so
each commits for real: what a second connection sees while a mail is at the mail server is what is asked."""
import sys
import threading
import time
from datetime import timedelta
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail.backends.base import BaseEmailBackend
from django.db import connection, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import accountmail
from .models import AccountMail, AuditLog
from .tests import user_data
from .tests_account_mail import BASE, REFUSED

User = get_user_model()


class WaitingBackend(BaseEmailBackend):
    """A mail server that answers only when the test lets it."""
    started = threading.Event()
    release = threading.Event()
    sent = []

    def send_messages(self, messages):
        type(self).started.set()
        type(self).release.wait(timeout=30)
        type(self).sent.extend(messages)
        return len(messages)


WAITING = {'default': {'BACKEND': 'core.tests_account_mail_worker.WaitingBackend'}}
REFUSING = {'default': {'BACKEND': 'core.tests_account_mail.RefusingBackend'}}


def outcomes():
    return [error or ('sent' if sent_at else 'waiting')
            for error, sent_at in AccountMail.objects.order_by('id').values_list('error', 'sent_at')]


@override_settings(MAIL_IN_BACKGROUND=True, MAILERS=WAITING, PUBLIC_BASE_URL=BASE)
class WorkerCase(TransactionTestCase):
    serialized_rollback = True            # the next test finds the rows the migrations made

    def setUp(self):
        WaitingBackend.started.clear(), WaitingBackend.release.clear(), WaitingBackend.sent.clear()
        # whatever a test leaves at the mail server is let go and finished before the database is emptied
        self.addCleanup(self.finish)
        self.admin = User.objects.create_superuser('root', 'root@example.com', 'eski-sifre-123')
        self.client.force_login(self.admin)

    def finish(self):
        WaitingBackend.release.set()
        self.assertTrue(accountmail.worker.drain(30), 'the worker did not finish its mails')

    def at_the_mail_server(self):
        self.assertTrue(WaitingBackend.started.wait(timeout=20), 'no mail reached the mail server')


class AfterTheRequestTests(WorkerCase):
    def test_a_new_user_is_there_and_the_admin_answered_while_the_invitation_is_still_being_sent(self):
        response = self.client.post(reverse('core:user_create'), user_data())    # returns: the mail server has not
        self.assertEqual(response.status_code, 302)
        self.at_the_mail_server()
        self.assertFalse(WaitingBackend.release.is_set())
        kari = User.objects.get(username='kari')                                 # committed before the send began
        self.assertEqual(outcomes(), ['waiting'])
        self.assertEqual(list(AuditLog.objects.filter(action='invite').values_list('user_name', 'changes')),
                         [('root', {'Sent to': [None, 'kari@example.com']})])
        self.assertContains(self.client.get(reverse('core:user_list')), 'The invitation to kari@example.com is being sent')
        # a second click while it is under way sends no second mail
        self.client.post(reverse('core:user_invite', args=[kari.pk]))
        self.finish()
        self.assertEqual((outcomes(), [sent.to for sent in WaitingBackend.sent]), (['sent'], [['kari@example.com']]))
        self.assertContains(self.client.get(reverse('core:user_list')), 'Invitation sent')

    def test_sending_again_answers_before_the_mail_server_does_and_holds_no_lock_meanwhile(self):
        kari = User.objects.create_user('kari', 'kari@example.com')
        response = self.client.post(reverse('core:user_invite', args=[kari.pk]))
        self.assertEqual(response.status_code, 302)
        self.at_the_mail_server()
        # the person's row is free while the mail is at the mail server: an edit of it goes through at once
        edited = self.client.post(reverse('core:user_edit', args=[kari.pk]), user_data(first_name='Kari Anne'))
        self.assertEqual(edited.status_code, 302)
        self.assertEqual(User.objects.get(pk=kari.pk).first_name, 'Kari Anne')
        self.finish()
        self.assertEqual(outcomes(), ['sent'])

    def test_a_send_that_fails_after_the_answer_marks_the_row_and_the_log(self):
        with override_settings(MAILERS=REFUSING), self.assertLogs('core.accountmail', 'ERROR') as logged:
            response = self.client.post(reverse('core:user_create'), user_data())
            self.assertEqual(response.status_code, 302)                          # the admin's answer says nothing of it
            self.assertTrue(accountmail.worker.drain(30))
        self.assertEqual(len(logged.records), 1)
        self.assertTrue(User.objects.filter(username='kari').exists())
        self.assertEqual(outcomes(), [REFUSED])
        self.assertEqual(list(AuditLog.objects.filter(action='invite').order_by('created_at')
                              .values_list('user_name', flat=True)), ['root', 'system'])
        page = self.client.get(reverse('core:user_list'))
        self.assertContains(page, 'Invitation not sent')
        self.assertContains(page, 'Send invitation again')

    def test_a_save_that_fails_sends_nothing(self):
        # any fault before the commit (here the log's own insert): no user, no row, and no mail to a person who does
        # not exist
        self.client.raise_request_exception = False
        with mock.patch('core.resources.audit.record', side_effect=RuntimeError('the connection went away')):
            response = self.client.post(reverse('core:user_create'), user_data())
        self.assertEqual(response.status_code, 500)
        self.assertTrue(accountmail.worker.drain(30))
        self.assertFalse(WaitingBackend.started.is_set())
        self.assertEqual((User.objects.filter(username='kari').exists(), AccountMail.objects.count()), (False, 0))

    def test_a_reset_mail_under_way_does_not_hold_up_the_persons_sign_in(self):
        ali = User.objects.create_user('ali', 'ali@example.com', 'eski-sifre-123')
        asked = Client().post(reverse('password_reset'), {'email': 'ali@example.com'})
        self.assertEqual((asked.status_code, asked['Location']), (302, reverse('password_reset_done')))
        self.at_the_mail_server()
        result = {}

        def sign_in():
            try:
                result['response'] = Client().post(reverse('login'), {'username': 'ali', 'password': 'eski-sifre-123'})
            finally:
                connection.close()

        signing_in = threading.Thread(target=sign_in)
        signing_in.start()
        signing_in.join(timeout=10)
        self.assertFalse(signing_in.is_alive(), 'the sign-in waits for the mail server')
        self.assertEqual(result['response'].status_code, 302)
        self.assertIsNotNone(User.objects.get(pk=ali.pk).last_login)
        self.finish()
        self.assertEqual(outcomes(), ['sent'])

    @override_settings(PASSWORD_RESET_MAILS_PER_HOUR=1)
    def test_two_server_processes_asked_at_once_take_turns_on_the_accounts_row(self):
        # One process has one worker, which takes its jobs in turn; two processes (two workers) can be at one account
        # together, and are two threads here. Both are made to arrive while the account's row is held: with the count
        # taken under the row's lock the second sees the first one's mail; without it both would read "none yet" and
        # two mails would go out.
        User.objects.create_user('ali', 'ali@example.com', 'eski-sifre-123')
        WaitingBackend.release.set()
        accountmail.held_told.clear()

        def job():
            try:
                accountmail.reset_now('ali@example.com', 'en')
            finally:
                connection.close()

        workers = [threading.Thread(target=job), threading.Thread(target=job)]
        with self.assertLogs('core.accountmail', 'WARNING'):
            with transaction.atomic():
                User.objects.select_for_update().get(username='ali')
                for one in workers:
                    one.start()
                time.sleep(1)                                                        # both are at the row by now
            for one in workers:
                one.join(timeout=20)
        self.assertEqual((outcomes(), len(WaitingBackend.sent)), (['sent'], 1))

    def test_the_form_answers_before_the_address_is_even_looked_up(self):
        # the worker is busy with another mail: the request for a known address is answered all the same, and the
        # account's mail is written only when the worker gets to it
        User.objects.create_user('ali', 'ali@example.com', 'eski-sifre-123')
        self.client.post(reverse('core:user_create'), user_data())                # kari's invitation holds the worker
        self.at_the_mail_server()
        asked = Client().post(reverse('password_reset'), {'email': 'ali@example.com'})
        self.assertEqual((asked.status_code, asked['Location']), (302, reverse('password_reset_done')))
        self.assertEqual(list(AccountMail.objects.values_list('kind', flat=True)), ['invitation'])
        self.finish()
        self.assertEqual(sorted(AccountMail.objects.filter(sent_at__isnull=False).values_list('kind', flat=True)),
                         ['invitation', 'reset'])


class WorkerTests(WorkerCase):
    def test_the_worker_goes_on_after_a_job_that_raised(self):
        done = threading.Event()

        def broken():
            raise RuntimeError('a fault in a job')

        with self.assertLogs('core.accountmail', 'ERROR') as logged:
            self.assertTrue(accountmail.background(broken))
            self.assertTrue(accountmail.background(done.set))
            self.assertTrue(accountmail.worker.drain(30))
        self.assertTrue(done.is_set())
        self.assertIn('a fault in a job', logged.output[0])

    def test_a_full_queue_refuses_and_the_invitation_is_marked_not_sent(self):
        with mock.patch.object(accountmail.worker, 'put', return_value=False), \
                self.assertLogs('core.accountmail', 'ERROR'):
            response = self.client.post(reverse('core:user_create'), user_data(), follow=True)
        self.assertEqual(outcomes(), ['Too many mails are waiting to be sent.'])
        self.assertTrue(User.objects.filter(username='kari').exists())
        self.assertFalse(WaitingBackend.started.is_set())
        self.assertContains(response, 'The invitation to kari@example.com was not sent: Too many mails are waiting to be sent.')

    def test_requests_from_outside_cannot_crowd_out_the_admins_mails(self):
        # (review S2) two lines: the admin's mails and anybody's requests. With the requests' line full a request is
        # refused, an invitation is still taken, and it is sent before the requests that were waiting.
        blocker, gate, order = threading.Event(), threading.Event(), []

        def wait():
            blocker.set()
            gate.wait(timeout=30)

        self.addCleanup(gate.set)
        self.assertTrue(accountmail.background(wait))
        self.assertTrue(blocker.wait(timeout=20))
        asked = [accountmail.background(order.append, 'request', anonymous=True) for _ in range(accountmail.QUEUE_SIZE + 3)]
        self.assertEqual((asked.count(True), asked.count(False)), (accountmail.QUEUE_SIZE, 3))
        self.assertTrue(accountmail.background(order.append, 'mail'))
        gate.set()
        self.assertTrue(accountmail.worker.drain(30))
        self.assertEqual(order, ['mail'] + ['request'] * accountmail.QUEUE_SIZE)

    def test_the_worker_keeps_its_database_connection_while_jobs_wait_and_closes_it_when_none_does(self):
        # (review S2) a connection opened for every job made the worker seven times slower than requests arrive
        #
        # What "none left open" is asked of, and how. The worker has closed its connection by the time it rests
        # (`drain`): that is asked of the connection itself. The database is asked too, but it goes on listing a
        # connection until its server process has ended, which follows the client's close in the server's own time
        # (measured on 13.11.2026: 2 to 22 ms alone, up to 64 ms beside other runs), and it lists its own autovacuum
        # workers beside the clients. A count of everything listed, asked at once, failed for both in the whole suite
        # of 28c4c18 and in 1 of 20 runs alone, 3 of 20 under load. So: the clients' connections by their process id,
        # those that were not there before, waited for with a bound.
        from django.db.backends.base.base import BaseDatabaseWrapper
        connects, opened = [], BaseDatabaseWrapper.connect

        def counted(wrapper):
            if threading.current_thread().name == 'account-mail':
                connects.append(wrapper)
            return opened(wrapper)

        def clients():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pid FROM pg_stat_activity WHERE datname = current_database() "
                               "AND backend_type = 'client backend'")
                return {row[0] for row in cursor.fetchall()}

        def left_open(before, seconds=20):
            """The clients' connections the database lists that it did not list `before`, once there is none or
            `seconds` are over."""
            deadline = time.monotonic() + seconds
            while (found := clients() - before) and time.monotonic() < deadline:
                time.sleep(0.01)
            return found

        self.assertTrue(accountmail.worker.drain(30))
        before = clients()
        blocker, gate = threading.Event(), threading.Event()

        def wait():
            blocker.set()
            gate.wait(timeout=30)

        self.addCleanup(gate.set)
        with mock.patch.object(BaseDatabaseWrapper, 'connect', counted):
            self.assertTrue(accountmail.background(wait))
            self.assertTrue(blocker.wait(timeout=20))
            for n in range(40):
                self.assertTrue(accountmail.background(accountmail.reset_now, f'nobody{n}@example.com', 'en',
                                                       anonymous=True))
            gate.set()
            self.assertTrue(accountmail.worker.drain(30))
        self.assertEqual(len(connects), 1)                                        # forty lookups, one connection
        self.assertEqual([wrapper.connection for wrapper in connects], [None])    # closed by the worker, now at rest
        self.assertEqual(left_open(before), set())                                # and none left open at the database

    def test_two_hundred_lookups_of_addresses_nobody_has_are_emptied_in_a_moment(self):
        # measured before: 4.8 s for 200 (42 a second); the connection kept: well under a second
        start = time.perf_counter()
        for n in range(accountmail.QUEUE_SIZE):
            accountmail.background(accountmail.reset_now, f'nobody{n}@example.com', 'en', anonymous=True)
        self.assertTrue(accountmail.worker.drain(30))
        self.assertLess(time.perf_counter() - start, 2.5)
        self.assertEqual(AccountMail.objects.count(), 0)

    def test_the_queue_is_bounded(self):
        blocker, gate = threading.Event(), threading.Event()

        def wait():
            blocker.set()
            gate.wait(timeout=30)

        self.addCleanup(gate.set)
        self.assertTrue(accountmail.background(wait))
        self.assertTrue(blocker.wait(timeout=20))                                 # the worker is busy with the first
        taken = [accountmail.background(int) for _ in range(accountmail.QUEUE_SIZE + 5)]
        self.assertEqual((taken.count(True), taken.count(False)), (accountmail.QUEUE_SIZE, 5))
        gate.set()
        self.assertTrue(accountmail.worker.drain(30))

    def test_draining_waits_for_a_mail_under_way_and_gives_up_at_its_limit(self):
        self.client.post(reverse('core:user_create'), user_data())
        self.at_the_mail_server()
        self.assertFalse(accountmail.worker.drain(0.5))                           # still at the mail server
        self.assertEqual(outcomes(), ['waiting'])
        WaitingBackend.release.set()
        self.assertTrue(accountmail.worker.drain(30))
        self.assertEqual(outcomes(), ['sent'])


class OwnedMailsTests(WorkerCase):
    """A waiting mail belongs to the server process that queued it (review S3): only that process can send it, so it
    is the one that keeps saying "I still have it", and a mail is called not sent when its owner has stopped saying
    so, never by its age."""

    def test_a_send_still_under_way_long_after_is_being_sent_and_cannot_be_sent_twice(self):
        self.client.post(reverse('core:user_create'), user_data())
        self.at_the_mail_server()
        kari = User.objects.get(username='kari')
        mine = AccountMail.objects.get()
        self.assertEqual(mine.owner, accountmail.WORKER)
        AccountMail.objects.update(created_at=mine.created_at - timedelta(hours=1))   # an hour on, the send still going
        page = self.client.get(reverse('core:user_list'))
        self.assertContains(page, 'The invitation to kari@example.com is being sent')
        self.assertNotContains(page, 'Invitation not sent')
        refused = self.client.post(reverse('core:user_invite', args=[kari.pk]), follow=True)
        self.assertContains(refused, 'An invitation to kari is being sent right now')
        self.finish()
        self.assertEqual((outcomes(), [sent.to for sent in WaitingBackend.sent]), (['sent'], [['kari@example.com']]))

    def test_the_owner_renews_what_waits_behind_the_job_it_is_at(self):
        blocker, gate = threading.Event(), threading.Event()

        def wait():
            blocker.set()
            gate.wait(timeout=30)

        self.addCleanup(gate.set)
        self.client.post(reverse('core:user_create'), user_data())                # at the mail server
        self.at_the_mail_server()
        self.assertTrue(accountmail.background(wait))                             # the next job
        self.client.post(reverse('core:user_create'), user_data(username='ola', email='ola@example.com'))   # behind it
        long_ago = timezone.now() - timedelta(hours=1)
        AccountMail.objects.update(alive_at=long_ago)
        with mock.patch.object(accountmail, 'RENEW_EVERY', 0):
            WaitingBackend.release.set()                                          # kari's goes; the worker starts `wait`
            self.assertTrue(blocker.wait(timeout=20))
            behind = AccountMail.objects.get(user__username='ola')
            self.assertEqual((behind.sent_at, behind.error), (None, ''))          # still waiting,
            self.assertGreater(behind.alive_at, long_ago)                         # and its owner has just said so
            gate.set()
            self.assertTrue(accountmail.worker.drain(30))
        self.assertEqual(outcomes(), ['sent', 'sent'])

    def test_a_mail_whose_job_was_lost_is_not_vouched_for_and_can_be_sent_again(self):
        """Review T1: a job lost to a database fault left its row waiting under the living process's name, and the
        process renewed everything with its name at every other job, so the row said "being sent" for good and the
        invitation could not be sent again."""
        from django.db import OperationalError
        WaitingBackend.release.set()
        lost = OperationalError('server closed the connection unexpectedly')
        with mock.patch.object(accountmail, 'deliver', side_effect=lost),                 self.assertLogs('core.accountmail', 'ERROR') as logged:
            self.client.post(reverse('core:user_create'), user_data())            # its job fails on the database
            self.assertTrue(accountmail.worker.drain(30))
        self.assertIn('A background job of the account e-mails failed: OperationalError', logged.output[0])
        kari = User.objects.get(username='kari')
        row = AccountMail.objects.get()
        self.assertEqual((outcomes(), row.owner), (['waiting'], accountmail.WORKER))     # this process's, by name
        # the process lives on and has other work, long after: it does not say "I still have it" of that row
        long_ago = timezone.now() - accountmail.lease() - timedelta(seconds=1)
        AccountMail.objects.update(alive_at=long_ago)
        with mock.patch.object(accountmail, 'RENEW_EVERY', 0):
            self.client.post(reverse('password_reset'), {'email': 'nobody@example.com'})   # anybody's request: a job
            self.assertTrue(accountmail.background(int))
            self.assertTrue(accountmail.worker.drain(30))
        self.assertEqual(AccountMail.objects.get().alive_at, long_ago)
        with self.assertLogs('core.accountmail', 'ERROR'):                         # the next look closes it, once
            page = self.client.get(reverse('core:user_list'))
        self.assertContains(page, 'Invitation not sent')
        self.assertContains(page, 'Send invitation again')
        interrupted = 'The sending was interrupted: the server stopped, or the mail server never answered.'
        self.assertEqual(outcomes(), [interrupted])
        self.client.post(reverse('core:user_invite', args=[kari.pk]))             # and it can be sent again
        self.assertTrue(accountmail.worker.drain(30))
        self.assertEqual((outcomes(), [sent.to for sent in WaitingBackend.sent]),
                         ([interrupted, 'sent'], [['kari@example.com']]))
        self.assertEqual(accountmail.worker.held, set())                          # nothing is held once its job is done

    def test_the_job_after_the_database_dropped_the_kept_connection_is_not_lost(self):
        """Review T1: the worker keeps its connection while jobs wait; the first job after the database dropped it
        failed on the dead connection, and its mail was lost."""
        first, second, go_on, finish = threading.Event(), threading.Event(), threading.Event(), threading.Event()

        def wait(reached, gate):
            reached.set()
            gate.wait(timeout=30)

        self.addCleanup(go_on.set)
        self.addCleanup(finish.set)
        WaitingBackend.release.set()
        self.assertTrue(accountmail.worker.drain(30))
        self.assertTrue(accountmail.background(wait, first, go_on))
        self.assertTrue(first.wait(timeout=20))
        # behind it, in the same line: a lookup, which opens the worker's connection, and a job that keeps the worker
        # busy with that connection kept
        self.assertTrue(accountmail.background(accountmail.reset_now, 'nobody@example.com', 'en'))
        self.assertTrue(accountmail.background(wait, second, finish))
        go_on.set()
        self.assertTrue(second.wait(timeout=20))
        with connection.cursor() as cursor:                                       # the database drops every other connection
            cursor.execute('SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity '
                           'WHERE datname = current_database() AND pid <> pg_backend_pid()')
            self.assertEqual(cursor.fetchone()[0], 1)                             # the worker's kept one
        with self.assertNoLogs('core.accountmail', 'ERROR'):
            self.client.post(reverse('core:user_create'), user_data())            # the next job: an invitation
            finish.set()
            self.assertTrue(accountmail.worker.drain(30))
        self.assertEqual((outcomes(), [sent.to for sent in WaitingBackend.sent]), (['sent'], [['kari@example.com']]))

    def test_a_restart_closes_what_a_stopped_process_left_and_leaves_a_living_ones_alone(self):
        kari = User.objects.create_user('kari', 'kari@example.com')
        late = timezone.now() - timedelta(seconds=3 * settings.MAIL_SEND_SECONDS + 5)
        left = AccountMail.objects.create(user=kari, kind='invitation', address='kari@example.com', owner='stopped')
        AccountMail.objects.filter(pk=left.pk).update(alive_at=late)
        alive = AccountMail.objects.create(user=kari, kind='reset', address='kari@example.com', owner='the-other-process')
        # this process's worker thread ends and starts anew, as after a restart: its first job
        self.assertTrue(accountmail.worker.drain(30))
        ended = accountmail.worker.thread
        accountmail.background(sys.exit)
        if ended is not None:
            ended.join(timeout=20)
        with self.assertLogs('core.accountmail', 'ERROR'):
            self.assertTrue(accountmail.background(int))
            self.assertTrue(accountmail.worker.drain(30))
        self.assertEqual(outcomes(), ['The sending was interrupted: the server stopped, or the mail server never answered.',
                                      'waiting'])
        self.assertEqual(list(AuditLog.objects.filter(action='invite').values_list('user_name', flat=True)), ['system'])
        self.assertEqual(AccountMail.objects.get(pk=alive.pk).error, '')

    def test_a_process_that_stops_with_mails_still_queued_says_so_itself(self):
        self.client.post(reverse('core:user_create'), user_data())
        self.at_the_mail_server()
        self.client.post(reverse('core:user_create'), user_data(username='ola', email='ola@example.com'))
        other = AccountMail.objects.create(user=self.admin, kind='reset', address='root@example.com', owner='another')
        with self.assertLogs('core.accountmail', 'ERROR') as logged:
            self.assertFalse(accountmail.shut_down(0.3))                          # the exit hook, its time up
        interrupted = 'The sending was interrupted: the server stopped, or the mail server never answered.'
        self.assertEqual(outcomes(), [interrupted, interrupted, 'waiting'])       # its own two; not another process's
        self.assertEqual(len(logged.records), 2)
        self.assertEqual(AccountMail.objects.get(pk=other.pk).error, '')
        self.finish()
        self.assertEqual(outcomes(), [interrupted, interrupted, 'waiting'])       # a closed row is not sent late


class UsersTabTests(WorkerCase):
    """The users tab closes the mails nobody is sending any more before it lists the people (review T3): a list page
    does not fail because that housekeeping could not be written."""

    def lapsed(self):
        kari = User.objects.create_user('kari', 'kari@example.com')
        return AccountMail.objects.create(user=kari, kind='invitation', address=kari.email, requested_by=self.admin,
                                          owner='gone:1:00000000', alive_at=timezone.now() - timedelta(hours=1))

    def test_the_list_is_drawn_and_the_fault_logged_when_the_database_takes_no_writes(self):
        self.client.get(reverse('core:user_list'))                      # signed in, the session read: no write is left
        self.lapsed()
        with connection.cursor() as cursor:                             # the database takes no writes from here
            cursor.execute('SET default_transaction_read_only = on')
        self.addCleanup(self.writable)
        with self.assertLogs('core.accountmail', 'ERROR') as logged:
            page = self.client.get(reverse('core:user_list'))
        self.writable()
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'The invitation to kari@example.com is being sent')     # not closed: it could not be
        self.assertEqual(len(logged.records), 1)
        self.assertIn('could not be closed before the users were listed (InternalError: cannot execute UPDATE '
                      'in a read-only transaction)', logged.output[0])
        self.assertEqual(outcomes(), ['waiting'])
        with self.assertLogs('core.accountmail', 'ERROR'):              # the next look, the database writable again
            self.assertContains(self.client.get(reverse('core:user_list')), 'Invitation not sent')

    def writable(self):
        with connection.cursor() as cursor:
            cursor.execute('SET default_transaction_read_only = off')

    def test_a_fault_of_the_code_is_not_swallowed(self):
        self.lapsed()
        with mock.patch.object(accountmail, 'sweep', side_effect=RuntimeError('a fault in the code')),                 self.assertRaisesMessage(RuntimeError, 'a fault in the code'):
            self.client.get(reverse('core:user_list'))


class HandOverTests(WorkerCase):
    """What the after-commit hook is for (second pass, N4): the mail is handed to the worker only once the save is
    committed, never from inside its transaction."""

    def test_the_invitation_is_handed_over_outside_any_transaction(self):
        seen = []
        handed = accountmail.hand_over

        def watched(mail):
            visible = []
            # asked from another connection: is the row there for anybody but the request that wrote it?
            reader = threading.Thread(target=lambda: (visible.append(AccountMail.objects.filter(pk=mail.pk).exists()),
                                                      connection.close()))
            reader.start()
            reader.join(timeout=20)
            seen.append((connection.in_atomic_block, visible))
            return handed(mail)

        with mock.patch.object(accountmail, 'hand_over', watched):
            self.client.post(reverse('core:user_create'), user_data())
            kari = User.objects.get(username='kari')
            self.finish()
            WaitingBackend.release.clear()
            AccountMail.objects.all().delete()
            self.client.post(reverse('core:user_invite', args=[kari.pk]))
        self.assertEqual(seen, [(False, [True]), (False, [True])])                # the create, then the resend

    def test_a_worker_thread_that_died_is_started_again_by_the_next_job(self):
        # (N21) whatever ended it: the mails queued afterwards are not left waiting
        self.assertTrue(accountmail.background(int))
        self.assertTrue(accountmail.worker.drain(30))
        dead = accountmail.worker.thread
        accountmail.background(sys.exit)                                          # ends the thread, as a fault outside a job would
        dead.join(timeout=20)
        self.assertFalse(dead.is_alive())
        done = threading.Event()
        self.assertTrue(accountmail.background(done.set))
        self.assertTrue(done.wait(timeout=20))
        self.assertIsNot(accountmail.worker.thread, dead)
        self.assertTrue(accountmail.worker.thread.is_alive())
        self.assertTrue(accountmail.worker.drain(30))


class SmallerThingsTests(WorkerCase):
    def test_a_connection_that_will_not_close_does_not_leave_the_worker_counting_a_job_for_good(self):
        # (S5) the job is counted as done before the connections are closed: drain() is true again, the worker goes on
        done = threading.Event()
        with mock.patch.object(accountmail.connections, 'close_all', side_effect=[RuntimeError('will not close'), None,
                                                                                  None, None]), \
                self.assertLogs('core.accountmail', 'ERROR') as logged:
            self.assertTrue(accountmail.background(int))
            self.assertTrue(accountmail.worker.drain(30))
            self.assertTrue(accountmail.background(done.set))
            self.assertTrue(accountmail.worker.drain(30))
        self.assertTrue(done.is_set())
        self.assertIn('will not close', logged.output[0])
