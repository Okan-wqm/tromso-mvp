"""The account e-mails leave after the request, not in it (core.accountmail's worker). The request writes the mail as
waiting in its own transaction and answers; the mail server is talked to afterwards, by the worker thread, outside any
transaction and any lock. These tests run the real worker (the other tests run its jobs at once, in the request), so
each commits for real: what a second connection sees while a mail is at the mail server is what is asked."""
import threading
import time
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.mail.backends.base import BaseEmailBackend
from django.db import connection, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse

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
        from django.db.backends.base.base import BaseDatabaseWrapper
        connects, opened = [], BaseDatabaseWrapper.connect

        def counted(wrapper):
            if threading.current_thread().name == 'account-mail':
                connects.append(1)
            return opened(wrapper)

        def open_connections():
            with connection.cursor() as cursor:
                cursor.execute('SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()')
                return cursor.fetchone()[0]

        self.assertTrue(accountmail.worker.drain(30))
        before = open_connections()
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
        self.assertEqual(open_connections(), before)                              # and none left open afterwards

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
