import re

from django.contrib.auth import get_user_model
from django.core import mail
from django.db import connection
from django.test import TestCase
from django.urls import reverse


class AuthFlowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            'ali', 'ali@example.com', 'eski-sifre-123'
        )

    def test_home_requires_login(self):
        response = self.client.get(reverse('home'))
        self.assertRedirects(response, reverse('login') + '?next=/')

    def test_login_and_logout(self):
        response = self.client.post(
            reverse('login'), {'username': 'ali', 'password': 'eski-sifre-123'}
        )
        self.assertRedirects(response, reverse('home'))
        self.assertContains(self.client.get(reverse('home')), 'Welcome, ali')

        response = self.client.post(reverse('logout'))
        self.assertRedirects(response, reverse('login'))
        self.assertEqual(self.client.get(reverse('home')).status_code, 302)

    def test_wrong_password_is_rejected(self):
        response = self.client.post(
            reverse('login'), {'username': 'ali', 'password': 'yanlis'}
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_password_reset_by_email(self):
        response = self.client.post(
            reverse('password_reset'), {'email': 'ali@example.com'}
        )
        self.assertRedirects(response, reverse('password_reset_done'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['ali@example.com'])

        link = re.search(r'http://testserver(\S+)', mail.outbox[0].body).group(1)
        response = self.client.get(link, follow=True)
        self.assertTrue(response.context['validlink'])
        response = self.client.post(
            response.redirect_chain[-1][0],
            {'new_password1': 'yeni-sifre-456', 'new_password2': 'yeni-sifre-456'},
        )
        self.assertRedirects(response, reverse('password_reset_complete'))

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('yeni-sifre-456'))

    def test_unknown_email_sends_nothing(self):
        self.client.post(reverse('password_reset'), {'email': 'yok@example.com'})
        self.assertEqual(len(mail.outbox), 0)


class DatabaseTests(TestCase):
    def test_timescaledb_extension_is_installed(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'")
            self.assertIsNotNone(cursor.fetchone())
