"""The account e-mails (core.accountmail): the invitation a new person gets and the password reset, one path for both.
Through the pages, checked against the outbox, the stored rows and the activity log: the link is built from the
configured public address, works once and for a limited time, and says so plainly when it no longer does."""
import json
import re
import socketserver
import threading
import time
from datetime import datetime, timedelta
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.core.mail.backends.base import BaseEmailBackend
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from . import access, accountmail
from .models import AccountMail, AuditLog, Profile
from .tests import user_data

BASE = 'https://farm.example'
NEW_PASSWORD = {'new_password1': 'yeni-sifre-456', 'new_password2': 'yeni-sifre-456'}


def setUpModule():
    call_command('compile_catalogs', verbosity=0)


def link_in(message):
    """The set-password link of an account e-mail, as the path the test client opens."""
    return re.search(re.escape(BASE) + r'(/accounts/reset/\S+)', message.body).group(1)


def later(seconds):
    """The token generator's clock moved `seconds` ahead (Django's own hook for it)."""
    return mock.patch.object(accountmail.tokens, '_now', return_value=datetime.now() + timedelta(seconds=seconds))


@override_settings(PUBLIC_BASE_URL=BASE, COMPANY_NAME='Nordhav Akva')
class AccountMailCase(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser('root', 'root@example.com', 'eski-sifre-123',
                                                               first_name='Ada', last_name='Admin')
        self.client.force_login(self.admin)

    def invite(self, **overrides):
        """Creates kari on the users tab as the platform admin, signs out, and returns her and the invitation."""
        self.client.post(reverse('core:user_create'), user_data(**overrides))
        self.client.logout()
        return get_user_model().objects.get(username='kari'), mail.outbox[-1]

    def set_password(self, link, **headers):
        """Opens a link and sends the new password; the last response."""
        opened = self.client.get(link, follow=True, headers=headers)
        return self.client.post(opened.redirect_chain[-1][0], NEW_PASSWORD)

    def assert_dead(self, response):
        """The page of a link that no longer works: it says so and offers a new link and the sign-in page."""
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['validlink'])
        self.assertContains(response, '<h1>This link no longer works</h1>', html=True)
        self.assertContains(response, 'The link was already used or has expired.')
        self.assertContains(response, 'href="%s"' % reverse('password_reset'))
        self.assertContains(response, 'href="%s"' % reverse('login'))
        self.assertNotContains(response, 'name="new_password1"')


class InvitationTests(AccountMailCase):
    def test_a_new_person_gets_an_invitation_of_its_own(self):
        kari, sent = self.invite()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual((sent.to, sent.from_email), (['kari@example.com'], settings.DEFAULT_FROM_EMAIL))
        self.assertEqual(sent.subject, 'Your farm console account: set your password')
        self.assertEqual((sent.content_subtype, getattr(sent, 'alternatives', [])), ('plain', []))
        for line in ('Hi Kari Nordmann,',
                     'Ada Admin has created an account for you in the farm console of Nordhav Akva.',
                     'Your username is kari.',
                     'Open this link to set your password; then you can sign in:',
                     'The link works once and expires after 24 hours.',
                     f'If it has expired, ask for a new one here:\n{BASE}/accounts/password_reset/',
                     'If you did not expect this email, you can ignore it.'):
            self.assertIn(line, sent.body)

    @override_settings(COMPANY_NAME='', PASSWORD_RESET_TIMEOUT=3600)
    def test_the_invitation_says_how_long_its_link_lives_and_needs_no_company_name(self):
        _kari, sent = self.invite()
        self.assertIn('Ada Admin has created an account for you in the farm console.', sent.body)
        self.assertIn('The link works once and expires after 1 hour.', sent.body)

    @override_settings(ALLOWED_HOSTS=['*'])
    def test_the_link_is_built_from_the_public_address_not_from_the_request(self):
        self.client.post(reverse('core:user_create'), user_data(), headers={'Host': 'evil.example'})
        self.client.logout()
        self.client.post(reverse('password_reset'), {'email': 'kari@example.com'}, headers={'Host': 'evil.example'})
        self.assertEqual(len(mail.outbox), 2)
        for sent in mail.outbox:
            self.assertNotIn('evil.example', sent.body)
            self.assertNotIn('testserver', sent.body)
            self.assertRegex(sent.body, r'\n%s/accounts/reset/[\w-]+/[\w-]+/\n' % re.escape(BASE))

    def test_the_account_cannot_sign_in_until_the_password_is_set(self):
        kari, sent = self.invite()
        self.assertFalse(kari.has_usable_password())
        for password in ('', 'kari', kari.password, 'yeni-sifre-456'):
            self.client.post(reverse('login'), {'username': 'kari', 'password': password})
            self.assertNotIn('_auth_user_id', self.client.session)
        response = self.set_password(link_in(sent))
        self.assertRedirects(response, reverse('password_reset_complete'))
        self.assertNotIn('_auth_user_id', self.client.session)                  # setting it does not sign in
        self.client.post(reverse('login'), {'username': 'kari', 'password': 'yeni-sifre-456'})
        self.assertEqual(self.client.session['_auth_user_id'], str(kari.pk))

    def test_the_link_works_once(self):
        kari, sent = self.invite()
        link = link_in(sent)
        self.set_password(link)
        kari.refresh_from_db()
        self.assertTrue(kari.check_password('yeni-sifre-456'))
        self.assert_dead(self.client.get(link, follow=True))
        # and nothing can be sent to where the form was
        again = self.client.post(link.rsplit('/', 2)[0] + '/set-password/',
                                 {'new_password1': 'baska-sifre-789', 'new_password2': 'baska-sifre-789'})
        self.assert_dead(again)
        kari.refresh_from_db()
        self.assertTrue(kari.check_password('yeni-sifre-456'))

    def test_an_expired_link_says_so_and_the_person_gets_a_new_one_themselves(self):
        kari, sent = self.invite()
        link = link_in(sent)
        with later(settings.PASSWORD_RESET_TIMEOUT + 1):
            self.assert_dead(self.client.get(link, follow=True))
            # the way forward the page offers: a new link, for someone who never had a password too
            self.client.post(reverse('password_reset'), {'email': 'kari@example.com'})
            self.assertEqual(len(mail.outbox), 2)
            self.assertRedirects(self.set_password(link_in(mail.outbox[1])), reverse('password_reset_complete'))
        kari.refresh_from_db()
        self.assertTrue(kari.check_password('yeni-sifre-456'))

    def test_a_link_still_works_just_before_it_expires(self):
        _kari, sent = self.invite()
        with later(settings.PASSWORD_RESET_TIMEOUT - 5):
            self.assertTrue(self.client.get(link_in(sent), follow=True).context['validlink'])

    def test_a_link_opened_in_time_but_sent_after_it_expired_saves_nothing(self):
        kari, sent = self.invite()
        opened = self.client.get(link_in(sent), follow=True)
        with later(settings.PASSWORD_RESET_TIMEOUT + 1):
            self.assert_dead(self.client.post(opened.redirect_chain[-1][0], NEW_PASSWORD))
        kari.refresh_from_db()
        self.assertFalse(kari.has_usable_password())

    def test_one_persons_link_does_not_work_for_another(self):
        kari, sent = self.invite()
        ola = get_user_model().objects.create_user('ola', 'ola@example.com')
        uid, token = link_in(sent).strip('/').split('/')[-2:]
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode
        other = reverse('password_reset_confirm', args=[urlsafe_base64_encode(force_bytes(ola.pk)), token])
        self.assert_dead(self.client.get(other, follow=True))
        self.assert_dead(self.client.post(other.replace(token, 'set-password'), NEW_PASSWORD))
        for person in (kari, ola):
            person.refresh_from_db()
            self.assertFalse(person.has_usable_password())
        # nor a link that names nobody, or a made-up token
        self.assert_dead(self.client.get(reverse('password_reset_confirm', args=['x', token]), follow=True))
        self.assert_dead(self.client.get(reverse('password_reset_confirm', args=[uid, 'abc123-' + '0' * 32]), follow=True))

    def test_a_changed_address_ends_the_link_that_went_to_the_old_one(self):
        kari, sent = self.invite()
        self.client.force_login(self.admin)
        self.client.post(reverse('core:user_edit', args=[kari.pk]), user_data(email='kari@farm.no'))
        self.client.logout()
        self.assert_dead(self.client.get(link_in(sent), follow=True))


class ResetMailTests(AccountMailCase):
    def setUp(self):
        super().setUp()
        self.client.logout()
        self.ali = get_user_model().objects.create_user('ali', 'ali@example.com', 'eski-sifre-123')

    def test_the_reset_mail_takes_the_same_path(self):
        response = self.client.post(reverse('password_reset'), {'email': 'ali@example.com'})
        self.assertRedirects(response, reverse('password_reset_done'))
        sent = mail.outbox[0]
        self.assertEqual((sent.to, sent.from_email, sent.subject),
                         (['ali@example.com'], settings.DEFAULT_FROM_EMAIL, 'Reset your password'))
        for line in ('Hi ali,', 'Open this link to set a new password:',
                     'The link works once and expires after 24 hours.',
                     'If you did not ask for this, you can ignore this email.'):
            self.assertIn(line, sent.body)
        self.assertNotIn('has created an account', sent.body)
        self.assertRedirects(self.set_password(link_in(sent)), reverse('password_reset_complete'))
        self.ali.refresh_from_db()
        self.assertTrue(self.ali.check_password('yeni-sifre-456'))
        self.assert_dead(self.client.get(link_in(sent), follow=True))

    def test_the_reset_mail_names_the_username_which_is_what_signs_in(self):
        # (review R5) someone who forgot both sets a new password and still needs the name to sign in with
        get_user_model().objects.create_user('k.nordmann', 'kari@example.com', 'x', first_name='Kari',
                                             last_name='Nordmann')
        self.client.post(reverse('password_reset'), {'email': 'kari@example.com'})
        body = mail.outbox[-1].body
        self.assertIn('Hi Kari Nordmann,', body)
        self.assertIn('Your username is k.nordmann.', body)

    def test_the_old_password_works_until_a_new_one_is_set(self):
        self.client.post(reverse('password_reset'), {'email': 'ali@example.com'})
        self.client.post(reverse('login'), {'username': 'ali', 'password': 'eski-sifre-123'})
        self.assertEqual(self.client.session['_auth_user_id'], str(self.ali.pk))


INVITATION = {
    'en': ('Your farm console account: set your password', 'Hi Kari Nordmann,',
           'Ada Admin has created an account for you in the farm console of Nordhav Akva.', 'Your username is kari.',
           'The link works once and expires after 24 hours.'),
    'nb': ('Kontoen din i driftskonsollen: velg passord', 'Hei Kari Nordmann,',
           'Ada Admin har opprettet en konto til deg i driftskonsollen til Nordhav Akva.', 'Brukernavnet ditt er kari.',
           'Lenken virker én gang og utløper etter 24 timer.'),
    'tr': ('Çiftlik konsolu hesabınız: parolanızı belirleyin', 'Merhaba Kari Nordmann,',
           'Ada Admin, Nordhav Akva çiftlik konsolunda sizin için bir hesap oluşturdu.', 'Kullanıcı adınız: kari.',
           'Bağlantı bir kez kullanılabilir ve 24 saat sonra geçerliliğini yitirir.'),
}
RESET = {
    'en': ('Reset your password', 'Hi ali,', 'Your username is ali.', 'Open this link to set a new password:',
           'The link works once and expires after 24 hours.'),
    'nb': ('Tilbakestill passordet ditt', 'Hei ali,', 'Brukernavnet ditt er ali.',
           'Åpne denne lenken for å velge nytt passord:',
           'Lenken virker én gang og utløper etter 24 timer.'),
    'tr': ('Parolanızı sıfırlayın', 'Merhaba ali,', 'Kullanıcı adınız: ali.',
           'Yeni parola belirlemek için bu bağlantıyı açın:',
           'Bağlantı bir kez kullanılabilir ve 24 saat sonra geçerliliğini yitirir.'),
}
SET_PASSWORD_HEADING = {'en': 'Set a new password', 'nb': 'Velg nytt passord', 'tr': 'Yeni parola belirleyin'}


class LanguageTests(AccountMailCase):
    """Each mail in the recipient's saved language, whatever language the admin or the browser asking reads."""

    def test_the_invitation_in_each_language(self):
        for language, (subject, *lines) in INVITATION.items():
            with self.subTest(language=language):
                mail.outbox.clear()
                get_user_model().objects.filter(username='kari').delete()
                self.client.force_login(self.admin)                              # the admin reads English
                _kari, sent = self.invite(language=language)
                self.assertEqual(sent.subject, subject)
                for line in lines:
                    self.assertIn(line, sent.body)
                self.assertIn(f'{BASE}/accounts/reset/', sent.body)

    def test_the_reset_mail_in_each_language(self):
        self.client.logout()
        ali = get_user_model().objects.create_user('ali', 'ali@example.com', 'eski-sifre-123')
        profile = Profile.objects.create(user=ali, language='en')
        for language, (subject, *lines) in RESET.items():
            with self.subTest(language=language):
                mail.outbox.clear()
                Profile.objects.filter(pk=profile.pk).update(language=language)
                self.client.post(reverse('password_reset'), {'email': 'ali@example.com'},
                                 headers={'Accept-Language': 'en'})
                self.assertEqual(mail.outbox[0].subject, subject)
                for line in lines:
                    self.assertIn(line, mail.outbox[0].body)

    @override_settings(PASSWORD_RESET_TIMEOUT=3600)
    def test_one_hour_is_singular_in_each_language(self):
        for language, line in (('en', 'expires after 1 hour.'), ('nb', 'utløper etter 1 time.'),
                               ('tr', '1 saat sonra geçerliliğini yitirir.')):
            with self.subTest(language=language):
                mail.outbox.clear()
                get_user_model().objects.filter(username='kari').delete()
                self.client.force_login(self.admin)
                _kari, sent = self.invite(language=language)
                self.assertIn(line, sent.body)

    def test_the_set_password_page_is_in_the_persons_saved_language(self):
        for language, heading in SET_PASSWORD_HEADING.items():
            with self.subTest(language=language):
                mail.outbox.clear()
                get_user_model().objects.filter(username='kari').delete()
                self.client.force_login(self.admin)
                _kari, sent = self.invite(language=language)
                # a browser that asks for another language: the link says who it is for, and their language wins
                page = self.client.get(link_in(sent), follow=True, headers={'Accept-Language': 'en' if language != 'en' else 'tr'})
                self.assertContains(page, f'<h1>{heading}</h1>', html=True)
                self.assertContains(page, f'<html lang="{language}"')

    def test_without_a_saved_language_the_page_follows_the_browser_and_so_does_a_dead_link(self):
        _kari, sent = self.invite()
        page = self.client.get(link_in(sent), follow=True, headers={'Accept-Language': 'nb'})
        self.assertContains(page, '<h1>Velg nytt passord</h1>', html=True)
        Profile.objects.update_or_create(user=_kari, defaults={'language': 'tr'})
        dead = self.client.get(reverse('password_reset_confirm', args=['x', 'y']), headers={'Accept-Language': 'nb'})
        self.assertContains(dead, '<h1>Denne lenken fungerer ikke lenger</h1>', html=True)



class RefusingBackend(BaseEmailBackend):
    """A mail server that is not there."""

    def send_messages(self, messages):
        raise OSError('no mail server')


class SilentBackend(BaseEmailBackend):
    """A mail server that takes nothing and says nothing."""

    def send_messages(self, messages):
        return 0


REFUSING = {'default': {'BACKEND': 'core.tests_account_mail.RefusingBackend'}}
SILENT = {'default': {'BACKEND': 'core.tests_account_mail.SilentBackend'}}
REFUSED = 'OSError: no mail server'


def invite_rows():
    """The activity log's invitation rows, oldest first: (who, action, record type, record, changes)."""
    return [(row.user_name, row.action, row.entity_type, row.entity_label, row.changes)
            for row in AuditLog.objects.filter(action='invite').order_by('created_at')]


def invited(address='kari@example.com'):
    """The log row of the admin inviting kari."""
    return 'root', 'invite', 'user', 'kari', {'Sent to': [None, address]}


def not_sent(reason, address='kari@example.com'):
    """The log row the platform writes when an invitation did not go out."""
    return 'system', 'invite', 'user', 'kari', {
        'Invitation': [None, {'msgid': 'Not sent'}], 'Sent to': [None, address], 'Reason': [None, reason]}


def stored(*fields):
    return list(AccountMail.objects.order_by('created_at', 'id').values_list(*fields))


def outcomes():
    """What became of each mail, oldest first: 'sent', 'waiting' or why it did not go out."""
    return [error or ('sent' if sent_at else 'waiting') for error, sent_at in stored('error', 'sent_at')]


def row_of(response, username):
    """The users table's row of `username`, as text without its markup."""
    for row in re.findall(r'<tr>.*?</tr>', response.content.decode(), re.S):
        if f'>{username}</a>' in row:
            return ' '.join(re.sub(r'<[^>]+>', ' ', row).split())
    raise AssertionError(f'no row of {username}')


def flashes(response):
    return [(str(message), message.level_tag) for message in response.context['messages']]


BEING_SENT = ('The invitation to kari@example.com is being sent: this person’s row says whether it went out.',
              'success')


class InvitationRecordTests(AccountMailCase):
    """What is kept of an invitation: one row per mail (never its link), a line in the activity log (who invited whom,
    when, to which address; another when it did not go out), and where the person stands on the users tab."""

    def users(self):
        self.client.force_login(self.admin)
        return self.client.get(reverse('core:user_list'))

    def test_the_invitation_is_recorded_and_logged_without_its_link(self):
        kari, sent = self.invite()
        self.assertEqual(stored('user', 'kind', 'address', 'requested_by', 'error'),
                         [(kari.pk, 'invitation', 'kari@example.com', self.admin.pk, '')])
        self.assertEqual(outcomes(), ['sent'])
        self.assertEqual(invite_rows(), [invited()])
        self.assertEqual(AuditLog.objects.get(action='invite').entity_id, str(kari.pk))
        # the link, its token and the person's id in it are in the mail alone
        uid, token = link_in(sent).strip('/').split('/')[-2:]
        kept = json.dumps([list(AuditLog.objects.values_list('changes', 'entity_label')),
                           list(AccountMail.objects.values())], default=str)
        for secret in (token, token.split('-')[1], f'/{uid}/', 'accounts/reset'):
            self.assertNotIn(secret, kept)
        row = row_of(self.users(), 'kari')
        self.assertIn('Invitation sent', row)
        self.assertIn('to kari@example.com', row)
        self.assertIn('Password not set yet', row)

    def test_the_admin_is_told_where_to_see_what_became_of_it(self):
        response = self.client.post(reverse('core:user_create'), user_data(), follow=True)
        self.assertEqual(flashes(response), [BEING_SENT, ('User “kari” created.', 'success')])

    @override_settings(MAILERS=REFUSING)
    def test_a_failed_send_keeps_the_user_and_shows_on_their_row_why(self):
        with self.assertLogs('core.accountmail', 'ERROR') as logged:
            self.client.post(reverse('core:user_create'), user_data())
        self.assertEqual(len(logged.records), 1)                                  # the server's log has the line
        self.assertIn('was not sent', logged.output[0])
        kari = get_user_model().objects.get(username='kari')                      # the user is there
        self.assertEqual(mail.outbox, [])
        self.assertEqual(stored('user', 'kind', 'address', 'error', 'sent_at'),
                         [(kari.pk, 'invitation', 'kari@example.com', REFUSED, None)])
        # the activity log names the kind of failure; the mail server's words are for the platform admin (below)
        self.assertEqual(invite_rows(), [invited(), not_sent('OSError')])
        self.assertEqual(AuditLog.objects.filter(action='create', entity_type='user').count(), 1)
        row = row_of(self.users(), 'kari')
        self.assertIn('Invitation not sent', row)
        self.assertIn(REFUSED, row)
        self.assertIn('Send invitation again', row)

    @override_settings(MAILERS=REFUSING)
    def test_the_mail_servers_words_are_not_for_every_reader_of_the_activity_log(self):
        # (review R4) a mail server's reply can name relay hosts and its account: the users tab and the database
        # viewer, the platform admin's, show it; the activity log, which a role can be given, does not
        with self.assertLogs('core.accountmail', 'ERROR'):
            self.client.post(reverse('core:user_create'), user_data())
        reader = get_user_model().objects.create_user('ola', 'ola@example.com', 'x')
        role = Group.objects.create(name='Reads the log')
        role.permissions.set(access.permissions().filter(codename='view_auditlog'))
        reader.groups.add(role)
        self.client.force_login(reader)
        log = self.client.get(reverse('core:activity_log'))
        self.assertEqual(log.status_code, 200)
        self.assertContains(log, 'Not sent')
        self.assertContains(log, 'OSError')
        self.assertNotContains(log, 'no mail server')
        self.assertNotIn('no mail server', json.dumps(list(AuditLog.objects.values_list('changes', flat=True))))
        self.assertIn(REFUSED, row_of(self.users(), 'kari'))

    @override_settings(MAILERS=SILENT)
    def test_a_mail_server_that_takes_nothing_counts_as_not_sent(self):
        with self.assertLogs('core.accountmail', 'ERROR'):
            self.client.post(reverse('core:user_create'), user_data())
        self.assertEqual(outcomes(), ['The mail server took no message.'])
        # the platform's own sentence is no mail server's: the log has it, as a value it can show in each language
        self.assertEqual(invite_rows(), [invited(), not_sent({'msgid': 'The mail server took no message.'})])

    @override_settings(PUBLIC_BASE_URL='')
    def test_without_a_public_address_nothing_is_sent_and_the_row_says_so(self):
        with self.assertLogs('core.accountmail', 'ERROR'):
            self.client.post(reverse('core:user_create'), user_data())
        self.assertEqual(mail.outbox, [])
        self.assertTrue(get_user_model().objects.filter(username='kari').exists())
        self.assertIn('PUBLIC_BASE_URL', outcomes()[0])

    def test_a_failed_send_never_keeps_the_link(self):
        class Leaking(BaseEmailBackend):
            def send_messages(self, messages):
                raise RuntimeError(f'could not deliver {messages[0].body}')

        with mock.patch('django.core.mail.handler.import_string', return_value=Leaking), \
                override_settings(MAILERS={'default': {'BACKEND': 'leaking'}}), \
                self.assertLogs('core.accountmail', 'ERROR') as logged:
            self.client.post(reverse('core:user_create'), user_data())
        self.assertNotRegex(logged.output[0], r'[0-9a-z]{6}-[0-9a-f]{32}')         # nor does the server's log
        kari = get_user_model().objects.get(username='kari')
        error = AccountMail.objects.get().error
        self.assertTrue(error.startswith('RuntimeError: could not deliver'))
        self.assertLessEqual(len(error), 500)
        self.assertIn('Hi Kari Nordmann,', error)                                # the mail's words are in it,
        self.assertNotRegex(error, r'[0-9a-z]{6}-[0-9a-f]{32}')                  # its link's token is not
        self.assertNotIn(kari.password, error)
        self.assertEqual(invite_rows()[1][4]['Reason'], [None, 'RuntimeError'])        # the log: its kind alone

    def test_a_user_without_an_address_is_created_and_the_row_says_what_then(self):
        response = self.client.post(reverse('core:user_create'), user_data(email=''), follow=True)
        kari = get_user_model().objects.get(username='kari')
        self.assertEqual((kari.email, kari.has_usable_password()), ('', False))
        self.assertEqual((mail.outbox, stored('id'), invite_rows()), ([], [], []))
        self.assertEqual(flashes(response), [
            ('No invitation was sent: kari has no email address. They cannot sign in until an address is added and '
             'the invitation sent.', 'warning'),
            ('User “kari” created.', 'success')])
        row = row_of(self.users(), 'kari')
        self.assertIn('Not invited: no email address', row)
        self.assertNotIn('Send invitation', row)
        # a second person without an address is no clash, and an address is still one person's only
        self.client.post(reverse('core:user_create'), user_data(username='ola', email=''))
        self.assertTrue(get_user_model().objects.filter(username='ola', email='').exists())
        clash = self.client.post(reverse('core:user_create'), user_data(username='other', email='ROOT@example.com'))
        self.assertEqual(clash.context['form'].errors['email'], ['Another user already uses this email.'])
        # the address added later: the row offers the invitation, and sending it works
        self.client.post(reverse('core:user_edit', args=[kari.pk]), user_data(email='kari@example.com'))
        self.assertEqual(mail.outbox, [])                                         # an edit sends nothing by itself
        row = row_of(self.users(), 'kari')
        self.assertIn('Not invited yet', row)
        self.assertIn('Send invitation', row)
        self.client.post(reverse('core:user_invite', args=[kari.pk]))
        self.assertEqual([sent.to for sent in mail.outbox], [['kari@example.com']])

    def test_an_inactive_person_is_not_invited(self):
        self.client.post(reverse('core:user_create'), user_data(is_active=''))
        self.assertEqual((mail.outbox, stored('id')), ([], []))
        row = row_of(self.users(), 'kari')
        self.assertIn('Not invited: the account is inactive', row)
        self.assertNotIn('Send invitation', row)

    def test_the_row_follows_the_invitation_to_its_end(self):
        kari, sent = self.invite()
        # the link has expired
        AccountMail.objects.update(sent_at=timezone.now() - timedelta(seconds=settings.PASSWORD_RESET_TIMEOUT + 60))
        row = row_of(self.users(), 'kari')
        self.assertIn('its link has expired', row)
        self.assertIn('Send invitation again', row)
        # the address changed since: the link that went to the old one is dead
        AccountMail.objects.update(sent_at=timezone.now())
        self.client.post(reverse('core:user_edit', args=[kari.pk]), user_data(email='kari@farm.no'))
        row = row_of(self.users(), 'kari')
        self.assertIn('to kari@example.com', row)
        self.assertIn('the address has changed since, so its link no longer works', row)
        self.assertIn('Send invitation again', row)
        # the password set: nothing left to send
        self.client.post(reverse('core:user_invite', args=[kari.pk]))
        self.client.logout()
        self.set_password(link_in(mail.outbox[-1]))
        row = row_of(self.users(), 'kari')
        self.assertIn('Password set', row)
        self.assertNotIn('Send invitation', row)
        self.assertIn('Password set', row_of(self.users(), 'root'))

    def test_a_mail_under_way_says_so_and_one_that_never_finished_is_not_sent(self):
        # the row as the request writes it, before the worker has it: waiting
        kari = get_user_model().objects.create_user('kari', 'kari@example.com')
        waiting = AccountMail.objects.create(user=kari, kind='invitation', address='kari@example.com',
                                             requested_by=self.admin)
        row = row_of(self.users(), 'kari')
        self.assertIn('The invitation to kari@example.com is being sent', row)
        self.assertNotIn('Send invitation', row)                                 # not twice at once
        response = self.client.post(reverse('core:user_invite', args=[kari.pk]), follow=True)
        self.assertEqual(flashes(response), [
            ('An invitation to kari is being sent right now: wait for it, the row says what became of it.', 'error')])
        self.assertEqual((mail.outbox, AccountMail.objects.count()), ([], 1))
        # the server stopped before it was sent (or the mail server never answered): it shows as not sent, never as
        # sent, and can be sent again
        AccountMail.objects.filter(pk=waiting.pk).update(
            created_at=timezone.now() - timedelta(seconds=2 * settings.MAIL_SEND_SECONDS + 1))
        row = row_of(self.users(), 'kari')
        self.assertIn('Invitation not sent', row)
        self.assertIn('The sending was interrupted', row)
        self.assertNotIn('Invitation sent', row)
        self.assertIn('Send invitation again', row)
        self.client.post(reverse('core:user_invite', args=[kari.pk]))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(outcomes(), ['waiting', 'sent'])
        self.assertIn('Invitation sent', row_of(self.users(), 'kari'))

    def test_the_row_in_norwegian_and_turkish(self):
        self.invite()
        for language, words in (('nb', 'Invitasjon sendt'), ('tr', 'Davet gönderildi')):
            with self.subTest(language=language):
                self.client.force_login(self.admin)
                response = self.client.get(reverse('core:user_list'), headers={'Accept-Language': language})
                self.assertIn(words, row_of(response, 'kari'))


class ResendTests(AccountMailCase):
    """The platform admin sends the invitation again from the person's row."""

    def setUp(self):
        super().setUp()
        self.kari, self.first = self.invite()
        self.client.force_login(self.admin)
        self.url = reverse('core:user_invite', args=[self.kari.pk])

    def test_sending_again_sends_records_and_logs_again(self):
        response = self.client.post(self.url, follow=True)
        self.assertRedirects(response, reverse('core:user_list'))
        self.assertEqual(flashes(response), [BEING_SENT])
        self.assertEqual([(sent.to, sent.subject) for sent in mail.outbox],
                         [(['kari@example.com'], 'Your farm console account: set your password')] * 2)
        self.assertEqual(stored('kind', 'address', 'requested_by', 'error'),
                         [('invitation', 'kari@example.com', self.admin.pk, '')] * 2)
        self.assertEqual(outcomes(), ['sent', 'sent'])
        self.assertEqual(invite_rows(), [invited()] * 2)
        # the new link works; once the password is set, the first one is dead too
        self.client.logout()
        self.assertRedirects(self.set_password(link_in(mail.outbox[1])), reverse('password_reset_complete'))
        self.assert_dead(self.client.get(link_in(self.first), follow=True))

    def test_in_the_dialog_the_page_is_reloaded(self):
        response = self.client.post(self.url, headers={'X-Modal': '1'})
        self.assertEqual((response.status_code, response['X-Modal-Redirect']), (204, reverse('core:user_list')))

    def test_after_a_failed_send_sending_again_goes_out(self):
        with override_settings(MAILERS=REFUSING), self.assertLogs('core.accountmail', 'ERROR'):
            response = self.client.post(self.url, follow=True)
        self.assertIn('Invitation not sent', row_of(response, 'kari'))
        self.client.post(self.url)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(outcomes(), ['sent', REFUSED, 'sent'])
        self.assertEqual(invite_rows(), [invited(), invited(), not_sent('OSError'), invited()])
        self.assertIn('Invitation sent', row_of(self.client.get(reverse('core:user_list')), 'kari'))

    def test_it_goes_to_the_address_the_account_has_now(self):
        self.client.post(reverse('core:user_edit', args=[self.kari.pk]), user_data(email='kari@farm.no'))
        self.client.post(self.url)
        self.assertEqual(mail.outbox[1].to, ['kari@farm.no'])
        self.assertEqual(stored('address'), [('kari@example.com',), ('kari@farm.no',)])

    def test_nothing_is_sent_to_someone_who_set_a_password_is_inactive_or_has_no_address(self):
        cases = {
            'kari has already set a password: they sign in with it, or ask for a new link with “Forgot your password?”.':
                lambda: (self.kari.set_password('yeni-sifre-456'), self.kari.save()),
            'kari is inactive: an inactive person cannot sign in.':
                lambda: get_user_model().objects.filter(pk=self.kari.pk).update(is_active=False, password='!x'),
            'kari has no email address: add one first.':
                lambda: get_user_model().objects.filter(pk=self.kari.pk).update(is_active=True, email=''),
        }
        for refusal, arrange in cases.items():
            with self.subTest(refusal=refusal):
                arrange()
                self.assertEqual(flashes(self.client.post(self.url, follow=True)), [(refusal, 'error')])
        self.assertEqual((len(mail.outbox), AccountMail.objects.count(), len(invite_rows())), (1, 1, 1))

    def test_only_the_platform_admin_sends_it_and_only_by_post(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertEqual(self.client.post(reverse('core:user_invite', args=[987654321])).status_code, 404)
        # a role cannot hold it: users are not an area of the matrix, whatever else the role allows
        manager = get_user_model().objects.create_user('ola', 'ola@example.com', 'x')
        role = Group.objects.create(name='Everything a role can hold')
        role.permissions.set(access.permissions())
        manager.groups.add(role)
        self.client.force_login(manager)
        self.assertEqual(self.client.post(self.url).status_code, 403)
        self.assertEqual(self.client.get(reverse('core:user_list')).status_code, 403)
        self.client.logout()
        response = self.client.post(self.url)
        self.assertEqual((response.status_code, response['Location'].split('?')[0]), (302, reverse('login')))
        self.assertEqual((len(mail.outbox), AccountMail.objects.count(), len(invite_rows())), (1, 1, 1))

    def test_the_invitations_are_on_the_persons_history_and_in_the_activity_log(self):
        self.client.post(self.url)
        history = self.client.get(reverse('core:user_edit', args=[self.kari.pk])).context['history']
        self.assertEqual([entry.action for entry in history], ['invite', 'invite', 'create'])
        log = self.client.get(reverse('core:activity_log'), {'action': 'invite'})
        self.assertEqual(len(log.context['page'].object_list), 2)
        self.assertContains(log, '<span class="audit-action">Invited</span>', html=True)
        self.assertContains(log, 'kari@example.com')
        self.assertNotContains(log, '<del>')                                    # an event, not a change of a value


class ForgotPasswordTests(AccountMailCase):
    """“Forgot your password?”: the answer never says whether an address has an account, and one account is sent only
    so many mails an hour."""

    def setUp(self):
        super().setUp()
        self.client.logout()
        self.ali = get_user_model().objects.create_user('ali', 'ali@example.com', 'eski-sifre-123')

    def ask(self, address, **extra):
        return self.client.post(reverse('password_reset'), {'email': address}, **extra)

    def answer(self, address):
        """What the person asking sees: where they are sent and the page there, without the per-request tokens."""
        response = self.ask(address, follow=True)
        page = re.sub(r'name="csrfmiddlewaretoken" value="[^"]+"|nonce="[^"]+"', '', response.content.decode())
        return response.redirect_chain, response.status_code, page

    def test_the_request_only_hands_the_address_over_whoever_it_belongs_to(self):
        # Nothing in the request looks the address up: the lookup, the limit, the mail and its row are the worker's,
        # after the answer. So the request does the same work, query for query, for an address with an account, one
        # nobody has, an inactive account's and one that has had its share.
        get_user_model().objects.create_user('ola', 'ola@example.com', 'x', is_active=False)
        held = get_user_model().objects.create_user('per', 'per@example.com', 'x')
        for _ in range(settings.PASSWORD_RESET_MAILS_PER_HOUR):
            AccountMail.objects.create(user=held, kind='reset', address=held.email, sent_at=timezone.now())
        seen = {}
        for address in ('ali@example.com', 'nobody@example.com', 'ola@example.com', 'per@example.com'):
            with mock.patch.object(accountmail, 'background', return_value=True) as handed, \
                    CaptureQueriesContext(connection) as queries:
                response = self.ask(address)
            self.assertEqual((response.status_code, response['Location']), (302, reverse('password_reset_done')))
            self.assertEqual(handed.call_args_list, [mock.call(accountmail.reset_now, address, 'en')])
            seen[address] = [query['sql'] for query in queries]
        self.assertEqual(len({len(sql) for sql in seen.values()}), 1, seen)
        self.assertFalse([sql for found in seen.values() for sql in found if 'auth_user' in sql or 'account_mails' in sql])
        self.assertEqual(mail.outbox, [])

    def test_a_full_queue_answers_the_same_and_says_so_in_the_servers_log(self):
        known = self.answer('ali@example.com')
        with mock.patch.object(accountmail, 'background', return_value=False), \
                self.assertLogs('core.accountmail', 'ERROR') as logged:
            self.assertEqual(self.answer('ali@example.com'), known)
        self.assertNotIn('ali@example.com', logged.output[0])
        self.assertEqual(len(mail.outbox), 1)

    def test_an_unknown_address_is_answered_like_a_known_one_and_gets_nothing(self):
        known = self.answer('ali@example.com')
        self.assertEqual(len(mail.outbox), 1)
        get_user_model().objects.filter(pk=self.ali.pk).update(is_active=False)
        for address in ('nobody@example.com', 'ali@example.com', 'ALI@EXAMPLE.COM'):      # unknown, and inactive
            with self.subTest(address=address):
                self.assertEqual(self.answer(address), known)
        self.assertEqual(known[0], [(reverse('password_reset_done'), 302)])
        self.assertIn('If an account uses this address, a reset link is on its way.', known[2])
        self.assertEqual((len(mail.outbox), AccountMail.objects.count()), (1, 1))

    def test_a_reset_is_recorded_as_the_persons_own_and_not_in_the_activity_log(self):
        self.ask('Ali@Example.com')                                               # the address in any case
        self.assertEqual(stored('user', 'kind', 'address', 'requested_by', 'error'),
                         [(self.ali.pk, 'reset', 'ali@example.com', None, '')])
        self.assertEqual(outcomes(), ['sent'])
        self.assertEqual(AuditLog.objects.count(), 0)
        token = link_in(mail.outbox[0]).strip('/').split('/')[-1]
        self.assertNotIn(token, json.dumps(list(AccountMail.objects.values()), default=str))

    def test_one_account_gets_three_reset_mails_an_hour_and_the_fourth_request_is_answered_the_same(self):
        answers = [self.answer('ali@example.com') for _ in range(5)]
        self.assertEqual(len(mail.outbox), 3)
        self.assertEqual(AccountMail.objects.count(), 3)
        self.assertEqual(answers, [answers[0]] * 5)
        # another account is not held back by it
        get_user_model().objects.create_user('ola', 'ola@example.com', 'x')
        self.ask('ola@example.com')
        self.assertEqual(mail.outbox[-1].to, ['ola@example.com'])
        # an hour later the account is sent one again
        AccountMail.objects.filter(user=self.ali).update(created_at=timezone.now() - timedelta(minutes=61))
        self.ask('ali@example.com')
        self.assertEqual([sent.to for sent in mail.outbox].count(['ali@example.com']), 4)

    def test_a_request_held_back_is_written_to_the_servers_log(self):
        with self.assertLogs('core.accountmail', 'WARNING') as logged:
            for _ in range(4):
                self.ask('ali@example.com')
        self.assertEqual(len(logged.records), 1)
        self.assertIn(f'user {self.ali.pk}', logged.output[0])
        self.assertNotIn('ali@example.com', logged.output[0])

    @override_settings(PASSWORD_RESET_MAILS_PER_HOUR=1)
    def test_the_limit_is_a_setting_and_a_failed_send_counts(self):
        with override_settings(MAILERS=REFUSING), self.assertLogs('core.accountmail', 'ERROR'):
            failed = self.answer('ali@example.com')
        self.assertEqual(stored('kind', 'error'), [('reset', REFUSED)])
        self.assertEqual(self.answer('ali@example.com'), failed)                 # the same answer, sent or not
        self.assertEqual((mail.outbox, AccountMail.objects.count()), ([], 1))

    def test_invitations_do_not_count_and_the_admins_resend_is_not_held_back(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('core:user_create'), user_data())
        kari = get_user_model().objects.get(username='kari')
        for _ in range(4):
            self.client.post(reverse('core:user_invite', args=[kari.pk]))
        self.assertEqual(len(mail.outbox), 5)
        self.client.logout()
        self.ask('kari@example.com')                                              # her own request still goes out
        self.assertEqual((len(mail.outbox), mail.outbox[-1].subject), (6, 'Reset your password'))

    def test_two_accounts_on_one_address_each_get_their_own_link(self):
        twin = get_user_model().objects.create_user('ali2', 'ali@example.com', 'x')   # made outside the users tab
        self.ask('ali@example.com')
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(set(stored('user')), {(self.ali.pk,), (twin.pk,)})


class PasswordSetTests(AccountMailCase):
    """A password set through a link is part of the account's history (review R3): who, when, and the address the
    link went to. A link sent to a wrong address and used before the address was put right is then seen, on the row
    and in the log. Deactivating an account ends its links."""

    def password_rows(self):
        return [(row.user_name, row.action, row.entity_type, row.entity_label, row.changes)
                for row in AuditLog.objects.filter(action='password').order_by('created_at')]

    def users(self):
        self.client.force_login(self.admin)
        return self.client.get(reverse('core:user_list'))

    def test_setting_a_password_is_logged_with_the_address_its_link_went_to(self):
        kari, sent = self.invite()
        self.set_password(link_in(sent))
        self.assertEqual(self.password_rows(),
                         [('kari', 'password', 'user', 'kari', {'Link sent to': [None, 'kari@example.com']})])
        self.assertEqual(AuditLog.objects.get(action='password').entity_id, str(kari.pk))
        # a reset's link too, each time
        self.client.post(reverse('password_reset'), {'email': 'kari@example.com'})
        self.set_password(link_in(mail.outbox[-1]))
        self.assertEqual(len(self.password_rows()), 2)
        kept = json.dumps(self.password_rows())
        self.assertNotIn('yeni-sifre-456', kept)
        self.assertNotIn(link_in(sent).strip('/').split('/')[-1], kept)
        # on the person's History tab and in the activity log, as an event of its own
        self.client.force_login(self.admin)
        history = self.client.get(reverse('core:user_edit', args=[kari.pk])).context['history']
        self.assertEqual([entry.action for entry in history], ['password', 'password', 'invite', 'create'])
        log = self.client.get(reverse('core:activity_log'), {'action': 'password'})
        self.assertEqual(len(log.context['page'].object_list), 2)
        self.assertContains(log, '<span class="audit-action">Password set</span>', html=True)
        self.assertContains(log, 'kari@example.com')
        self.assertNotContains(log, '<del>')

    def test_a_refused_password_and_a_dead_link_log_nothing(self):
        kari, sent = self.invite()
        opened = self.client.get(link_in(sent), follow=True)
        refused = self.client.post(opened.redirect_chain[-1][0], {'new_password1': '123', 'new_password2': '123'})
        self.assertEqual(refused.status_code, 200)
        with later(settings.PASSWORD_RESET_TIMEOUT + 1):
            self.assert_dead(self.client.post(opened.redirect_chain[-1][0], NEW_PASSWORD))
        self.assertEqual(self.password_rows(), [])
        kari.refresh_from_db()
        self.assertFalse(kari.has_usable_password())

    def test_the_row_says_when_and_names_an_address_the_account_no_longer_has(self):
        kari, sent = self.invite(email='wrong@example.com')
        self.set_password(link_in(sent))                                          # the wrong recipient is quicker
        row = row_of(self.users(), 'kari')
        self.assertIn('Password set', row)
        self.assertIn('through an emailed link', row)
        self.assertNotIn('Send invitation', row)
        self.client.post(reverse('core:user_edit', args=[kari.pk]), user_data(email='kari@example.com'))
        row = row_of(self.users(), 'kari')
        self.assertIn('through the link sent to wrong@example.com', row)
        self.assertIn('not this account’s address now', row)
        history = self.client.get(reverse('core:user_edit', args=[kari.pk])).context['history']
        self.assertEqual([entry.action for entry in history], ['update', 'password', 'invite', 'create'])
        # an account whose password was not set through a link (the platform admin's own) says only that it is set
        own = row_of(self.users(), 'root')
        self.assertIn('Password set', own)
        self.assertNotIn('through', own)

    def test_the_row_in_norwegian_and_turkish(self):
        _kari, sent = self.invite()
        self.set_password(link_in(sent))
        for language, words in (('nb', 'via en lenke sendt på e-post'), ('tr', 'e-postayla gönderilen bağlantıyla')):
            with self.subTest(language=language):
                self.client.force_login(self.admin)
                response = self.client.get(reverse('core:user_list'), headers={'Accept-Language': language})
                self.assertIn(words, row_of(response, 'kari'))

    def test_deactivating_an_account_ends_its_links(self):
        kari, sent = self.invite()
        self.client.force_login(self.admin)
        self.client.post(reverse('core:user_invite', args=[kari.pk]))            # a second link, as live as the first
        self.client.post(reverse('core:user_edit', args=[kari.pk]), user_data(is_active=''))
        self.client.logout()
        for message in mail.outbox:
            self.assert_dead(self.client.get(link_in(message), follow=True))
        kari.refresh_from_db()
        self.assertFalse(kari.has_usable_password())
        # a reset link of someone who has a password, and a page opened before the account was deactivated
        ali = get_user_model().objects.create_user('ali', 'ali@example.com', 'eski-sifre-123')
        self.client.post(reverse('password_reset'), {'email': 'ali@example.com'})
        opened = self.client.get(link_in(mail.outbox[-1]), follow=True)
        self.assertTrue(opened.context['validlink'])
        get_user_model().objects.filter(pk=ali.pk).update(is_active=False)
        self.assert_dead(self.client.post(opened.redirect_chain[-1][0], NEW_PASSWORD))
        ali.refresh_from_db()
        self.assertTrue(ali.check_password('eski-sifre-123'))
        self.assertEqual(self.password_rows(), [])


class Tarpit(socketserver.BaseRequestHandler):
    """A mail server that answers every step of the conversation, each after `delay` seconds: under the per-step
    timeout every time, far over it in all."""
    delay = 0.6

    def handle(self):
        def answer(line):
            time.sleep(self.delay)
            try:
                self.request.sendall(line)
            except OSError:
                pass
        answer(b'220 tarpit ESMTP\r\n')
        data, buffer = False, b''
        while True:
            try:
                chunk = self.request.recv(4096)
            except OSError:
                return
            if not chunk:
                return
            buffer += chunk
            while b'\r\n' in buffer:
                line, buffer = buffer.split(b'\r\n', 1)
                if data:
                    if line == b'.':
                        data = False
                        answer(b'250 queued\r\n')
                    continue
                verb = line[:4].upper()
                if verb == b'DATA':
                    data = True
                    answer(b'354 go on\r\n')
                elif verb == b'QUIT':
                    answer(b'221 bye\r\n')
                    return
                else:
                    answer(b'250 ok\r\n')


class SendTimeTests(AccountMailCase):
    """A mail is given MAIL_SEND_SECONDS (EMAIL_TIMEOUT) in all, not for each step of the SMTP conversation: a server
    that answers every step just in time is cut off at that, and the mail counts as not sent."""

    def test_a_server_that_answers_every_step_slowly_is_cut_off_at_the_limit(self):
        server = socketserver.ThreadingTCPServer(('127.0.0.1', 0), Tarpit)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        mailers = {'default': {'BACKEND': 'django.core.mail.backends.smtp.EmailBackend', 'OPTIONS': {
            'host': '127.0.0.1', 'port': server.server_address[1], 'username': None, 'password': None,
            'use_tls': False, 'use_ssl': False, 'timeout': 1}}}
        with override_settings(MAILERS=mailers, MAIL_SEND_SECONDS=1, DEFAULT_FROM_EMAIL='console@farm.example'), \
                self.assertLogs('core.accountmail', 'ERROR'):
            start = time.perf_counter()
            self.client.post(reverse('core:user_create'), user_data())
            took = time.perf_counter() - start
        # seven steps of 0.6 s would be over four seconds; the limit is one
        self.assertLess(took, 2.5)
        self.assertEqual(outcomes(), ['The mail server did not finish in time.'])
        self.assertIn('The mail server did not finish in time', row_of(self.client.get(reverse('core:user_list')), 'kari'))
