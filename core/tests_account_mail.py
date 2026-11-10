"""The account e-mails (core.accountmail): the invitation a new person gets and the password reset, one path for both.
Through the pages, checked against the outbox, the stored rows and the activity log: the link is built from the
configured public address, works once and for a limited time, and says so plainly when it no longer does."""
import json
import re
import threading
from datetime import datetime, timedelta
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.mail.backends.base import BaseEmailBackend
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings
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
    return mock.patch.object(default_token_generator, '_now', return_value=datetime.now() + timedelta(seconds=seconds))


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
    'en': ('Reset your password', 'Hi ali,', 'Open this link to set a new password:',
           'The link works once and expires after 24 hours.'),
    'nb': ('Tilbakestill passordet ditt', 'Hei ali,', 'Åpne denne lenken for å velge nytt passord:',
           'Lenken virker én gang og utløper etter 24 timer.'),
    'tr': ('Parolanızı sıfırlayın', 'Merhaba ali,', 'Yeni parola belirlemek için bu bağlantıyı açın:',
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
        raise ConnectionRefusedError(111, 'Connection refused')


class SilentBackend(BaseEmailBackend):
    """A mail server that takes nothing and says nothing."""

    def send_messages(self, messages):
        return 0


REFUSING = {'default': {'BACKEND': 'core.tests_account_mail.RefusingBackend'}}
SILENT = {'default': {'BACKEND': 'core.tests_account_mail.SilentBackend'}}


def invite_rows():
    """The activity log's invitation rows, oldest first: (who, action, record type, record, changes)."""
    return [(row.user_name, row.action, row.entity_type, row.entity_label, row.changes)
            for row in AuditLog.objects.filter(action='invite').order_by('created_at')]


def stored(*fields):
    return list(AccountMail.objects.order_by('created_at', 'id').values_list(*fields))


def row_of(response, username):
    """The users table's row of `username`, as text without its markup."""
    for row in re.findall(r'<tr>.*?</tr>', response.content.decode(), re.S):
        if f'>{username}</a>' in row:
            return ' '.join(re.sub(r'<[^>]+>', ' ', row).split())
    raise AssertionError(f'no row of {username}')


class InvitationRecordTests(AccountMailCase):
    """What is kept of an invitation: one row per mail (never its link), a line in the activity log (who invited whom,
    when, and whether it went out), and where the person stands on the users tab."""

    def users(self):
        self.client.force_login(self.admin)
        return self.client.get(reverse('core:user_list'))

    def test_the_invitation_is_recorded_and_logged_without_its_link(self):
        kari, sent = self.invite()
        self.assertEqual(stored('user', 'kind', 'address', 'requested_by', 'error'),
                         [(kari.pk, 'invitation', 'kari@example.com', self.admin.pk, '')])
        self.assertEqual(invite_rows(), [('root', 'invite', 'user', 'kari', {
            'Invitation': [None, {'msgid': 'Sent'}], 'Sent to': [None, 'kari@example.com']})])
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

    def test_the_admin_is_told_that_it_went_out(self):
        response = self.client.post(reverse('core:user_create'), user_data(), follow=True)
        self.assertEqual([(str(message), message.level_tag) for message in response.context['messages']],
                         [('Invitation sent to kari@example.com.', 'success'), ('User “kari” created.', 'success')])

    @override_settings(MAILERS=REFUSING)
    def test_a_failed_send_keeps_the_user_and_shows_on_their_row_why(self):
        with self.assertLogs('core.accountmail', 'ERROR') as logged:
            response = self.client.post(reverse('core:user_create'), user_data(), follow=True)
        self.assertEqual(len(logged.records), 1)                                  # the server's log has the line
        self.assertIn('was not sent: ConnectionRefusedError: [Errno 111] Connection refused', logged.output[0])
        kari = get_user_model().objects.get(username='kari')                      # the user is there
        self.assertEqual(mail.outbox, [])
        self.assertEqual([(str(message), message.level_tag) for message in response.context['messages']], [
            ('The invitation to kari@example.com was not sent: ConnectionRefusedError: [Errno 111] Connection refused',
             'error'),
            ('User “kari” created.', 'success')])
        self.assertEqual(stored('user', 'kind', 'address', 'error'), [
            (kari.pk, 'invitation', 'kari@example.com', 'ConnectionRefusedError: [Errno 111] Connection refused')])
        self.assertEqual(invite_rows(), [('root', 'invite', 'user', 'kari', {
            'Invitation': [None, {'msgid': 'Not sent'}], 'Sent to': [None, 'kari@example.com'],
            'Reason': [None, 'ConnectionRefusedError: [Errno 111] Connection refused']})])
        self.assertEqual(AuditLog.objects.filter(action='create', entity_type='user').count(), 1)
        row = row_of(self.users(), 'kari')
        self.assertIn('Invitation not sent', row)
        self.assertIn('ConnectionRefusedError: [Errno 111] Connection refused', row)
        self.assertIn('Send invitation again', row)

    @override_settings(MAILERS=SILENT)
    def test_a_mail_server_that_takes_nothing_counts_as_not_sent(self):
        with self.assertLogs('core.accountmail', 'ERROR'):
            self.client.post(reverse('core:user_create'), user_data())
        self.assertEqual(stored('error'), [('The mail server took no message.',)])

    @override_settings(PUBLIC_BASE_URL='')
    def test_without_a_public_address_nothing_is_sent_and_the_row_says_so(self):
        with self.assertLogs('core.accountmail', 'ERROR'):
            self.client.post(reverse('core:user_create'), user_data())
        self.assertEqual(mail.outbox, [])
        self.assertTrue(get_user_model().objects.filter(username='kari').exists())
        self.assertIn('PUBLIC_BASE_URL is not set', stored('error')[0][0])

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

    def test_a_user_without_an_address_is_created_and_the_row_says_what_then(self):
        response = self.client.post(reverse('core:user_create'), user_data(email=''), follow=True)
        kari = get_user_model().objects.get(username='kari')
        self.assertEqual((kari.email, kari.has_usable_password()), ('', False))
        self.assertEqual((mail.outbox, stored('id'), invite_rows()), ([], [], []))
        self.assertEqual([(str(message), message.level_tag) for message in response.context['messages']], [
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
        AccountMail.objects.update(created_at=timezone.now() - timedelta(seconds=settings.PASSWORD_RESET_TIMEOUT + 60))
        row = row_of(self.users(), 'kari')
        self.assertIn('its link has expired', row)
        self.assertIn('Send invitation again', row)
        # the address changed since: the link that went to the old one is dead
        AccountMail.objects.update(created_at=timezone.now())
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
        self.assertEqual([str(message) for message in response.context['messages']],
                         ['Invitation sent to kari@example.com.'])
        self.assertEqual([(sent.to, sent.subject) for sent in mail.outbox],
                         [(['kari@example.com'], 'Your farm console account: set your password')] * 2)
        self.assertEqual(stored('kind', 'address', 'requested_by', 'error'),
                         [('invitation', 'kari@example.com', self.admin.pk, '')] * 2)
        self.assertEqual(invite_rows(), [('root', 'invite', 'user', 'kari', {
            'Invitation': [None, {'msgid': 'Sent'}], 'Sent to': [None, 'kari@example.com']})] * 2)
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
        self.assertEqual([(str(message), message.level_tag) for message in response.context['messages']], [(
            'The invitation to kari@example.com was not sent: ConnectionRefusedError: [Errno 111] Connection refused',
            'error')])
        self.assertIn('Invitation not sent', row_of(response, 'kari'))
        self.client.post(self.url)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual([error for (error,) in stored('error')],
                         ['', 'ConnectionRefusedError: [Errno 111] Connection refused', ''])
        self.assertEqual([changes['Invitation'][1]['msgid'] for *_row, changes in invite_rows()],
                         ['Sent', 'Not sent', 'Sent'])
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
                response = self.client.post(self.url, follow=True)
                self.assertEqual([(str(message), message.level_tag) for message in response.context['messages']],
                                 [(refusal, 'error')])
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
        self.assertEqual(stored('kind', 'error'),
                         [('reset', 'ConnectionRefusedError: [Errno 111] Connection refused')])
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


class WaitingBackend(BaseEmailBackend):
    """A mail server that answers only when the test lets it, so two requests are under way at once."""
    started = threading.Event()
    release = threading.Event()
    sent = []

    def send_messages(self, messages):
        type(self).started.set()
        type(self).release.wait(timeout=20)
        type(self).sent.extend(messages)
        return len(messages)


class ResetLimitAtOnceTests(TransactionTestCase):
    """The hourly limit holds for requests that arrive together: each waits for the one before it on the account's
    row, so a burst of requests does not get past the count (they would all read "none sent yet")."""

    @override_settings(MAILERS={'default': {'BACKEND': 'core.tests_account_mail.WaitingBackend'}},
                       PASSWORD_RESET_MAILS_PER_HOUR=1, PUBLIC_BASE_URL=BASE)
    def test_two_requests_at_once_send_one_mail(self):
        ali = get_user_model().objects.create_user('ali', 'ali@example.com', 'eski-sifre-123')
        WaitingBackend.started.clear(), WaitingBackend.release.clear(), WaitingBackend.sent.clear()
        results = []

        def ask():
            try:
                results.append(accountmail.reset(get_user_model().objects.get(pk=ali.pk)))
            finally:
                connection.close()

        first, second = threading.Thread(target=ask), threading.Thread(target=ask)
        first.start()
        self.assertTrue(WaitingBackend.started.wait(timeout=20))               # the first is at the mail server
        with self.assertLogs('core.accountmail', 'WARNING'):
            second.start()
            second.join(timeout=1)
            self.assertTrue(second.is_alive())                                      # the second waits its turn
            WaitingBackend.release.set()
            first.join(timeout=20), second.join(timeout=20)
        self.assertFalse(first.is_alive() or second.is_alive())
        self.assertEqual((len(WaitingBackend.sent), AccountMail.objects.count()), (1, 1))
        self.assertEqual(sorted(result is None for result in results), [False, True])
