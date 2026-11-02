import re

from django.contrib.auth import get_user_model
from django.core import mail
from django.db import DatabaseError, connection, transaction
from django.test import TestCase
from django.urls import reverse

from .models import AuditLog


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


class ShellTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user('ali', 'ali@example.com', 'eski-sifre-123')
        self.client.force_login(user)

    def test_home_renders_shell_with_current_page_marked(self):
        response = self.client.get(reverse('home'))
        self.assertContains(response, 'id="rail"')
        self.assertContains(response, 'data-nav-toggle')
        self.assertContains(response, 'aria-current="page"', count=1)
        self.assertContains(response, 'action="%s"' % reverse('logout'))

    def test_password_change_uses_shell(self):
        response = self.client.get(reverse('password_change'))
        self.assertContains(response, 'id="rail"')
        self.assertContains(response, '<h1>Change password</h1>', html=True)


class DatabaseTests(TestCase):
    def test_timescaledb_extension_is_installed(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'")
            self.assertIsNotNone(cursor.fetchone())


class AuditLogTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('ali', 'ali@example.com', 'eski-sifre-123')

    def make_entry(self, **fields):
        defaults = dict(user=self.user, user_name='ali', action=AuditLog.Action.UPDATE,
                        entity_type='site', entity_id='1', entity_label='Site A (SA)')
        return AuditLog.objects.create(**{**defaults, **fields})

    def test_entries_cannot_be_changed_or_deleted(self):
        entry = self.make_entry()
        with self.assertRaises(DatabaseError), transaction.atomic():
            AuditLog.objects.filter(pk=entry.pk).update(user_name='someone else')
        with self.assertRaises(DatabaseError), transaction.atomic():
            AuditLog.objects.filter(pk=entry.pk).delete()
        self.assertEqual(AuditLog.objects.get(pk=entry.pk).user_name, 'ali')

    def test_deleting_a_user_keeps_their_history(self):
        self.make_entry()
        self.user.delete()
        self.assertEqual(AuditLog.objects.get().user_name, 'ali')

    def test_activity_log_filters(self):
        self.client.force_login(self.user)
        self.make_entry(entity_label='Bergen (BH)', action=AuditLog.Action.CREATE)
        self.make_entry(entity_label='Tromsø (TS)', action=AuditLog.Action.DELETE, user_name='kari')
        labels = lambda **query: [e.entity_label for e in
                                  self.client.get(reverse('core:activity_log'), query).context['page'].object_list]
        self.assertEqual(sorted(labels()), ['Bergen (BH)', 'Tromsø (TS)'])
        self.assertEqual(labels(q='bh'), ['Bergen (BH)'])
        self.assertEqual(labels(user='kari'), ['Tromsø (TS)'])
        self.assertEqual(labels(action='create'), ['Bergen (BH)'])
        self.assertEqual(labels(**{'from': '2999-01-01'}), [])
