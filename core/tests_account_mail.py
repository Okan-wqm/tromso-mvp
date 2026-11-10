"""The account e-mails (core.accountmail): the invitation a new person gets and the password reset, one path for both.
Through the pages, checked against the outbox, the stored rows and the activity log: the link is built from the
configured public address, works once and for a limited time, and says so plainly when it no longer does."""
import re
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from unittest import mock

from .models import Profile
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
