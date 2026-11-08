import io
import re
import warnings
from datetime import datetime, timedelta, timezone as utc
from unittest import mock
from importlib import import_module

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.paginator import UnorderedObjectListWarning
from django.conf import settings
from django.core import mail
from django.core.management import call_command
from django.db import DatabaseError, connection, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from farm.models import Site
from farm.tests.helpers import site_data

from . import access, audit, navigation
from .crud import Resource
from .audit import message
from .models import AuditedModel, AuditLog


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

    def test_the_migrations_match_the_models(self):
        # Hand-written steps (the water hypertable's RunSQL) must leave Django's state as the models declare it.
        out = io.StringIO()
        call_command('makemigrations', '--check', '--dry-run', stdout=out)
        self.assertIn('No changes detected', out.getvalue())


class AuditLogTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('ali', 'ali@example.com', 'eski-sifre-123')

    def test_a_label_too_long_for_the_column_is_cut_with_an_ellipsis_and_never_fails_the_write(self):
        site = Site.objects.create(name='Bergen', code='BG')
        entry = audit.record(self.user, AuditLog.Action.UPDATE, site, {'Name': ['a', 'b']}, label='x' * 400)
        entry.refresh_from_db()
        self.assertEqual((len(entry.entity_label), entry.entity_label[-2:]), (255, 'x…'))
        short = audit.record(self.user, AuditLog.Action.UPDATE, site, {}, label='y' * 255)
        self.assertEqual(short.entity_label, 'y' * 255)

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

    def test_activity_log_needs_permission(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('core:activity_log')).status_code, 403)

    def test_activity_log_filters(self):
        self.user.user_permissions.add(Permission.objects.get(codename='view_auditlog'))
        self.client.force_login(self.user)
        self.make_entry(entity_label='Bergen (BH)', action=AuditLog.Action.CREATE)
        self.make_entry(entity_label='Tromsø (TS)', action=AuditLog.Action.DELETE, user_name='kari')
        labels = lambda **query: [e.entity_label for e in
                                  self.client.get(reverse('core:activity_log'), query).context['page'].object_list]
        self.assertEqual(sorted(labels()), ['Bergen (BH)', 'Tromsø (TS)'])
        self.assertEqual(labels(q='bh'), ['Bergen (BH)'])
        self.assertEqual(labels(user='kari'), ['Tromsø (TS)'])
        self.assertEqual(labels(action='create'), ['Bergen (BH)'])
        self.assertEqual(labels(**{'from': '01.01.2099'}), [])          # the window of dates ends with 2100

    def test_activity_log_days_and_times_are_the_companys_clock(self):
        """23:30 UTC on 1 March is 00:30 on 2 March in Oslo (settings.COMPANY_TIME_ZONE): the entry is the 2nd's, by
        the filter and on the page, not the server's UTC day."""
        self.user.user_permissions.add(Permission.objects.get(codename='view_auditlog'))
        self.client.force_login(self.user)
        with mock.patch('django.utils.timezone.now', return_value=datetime(2026, 3, 1, 23, 30, tzinfo=utc.utc)):
            self.make_entry(entity_label='Night (NT)')
        url = reverse('core:activity_log')
        labels = lambda **query: [e.entity_label for e in self.client.get(url, query).context['page'].object_list]
        self.assertEqual(labels(**{'from': '02.03.2026', 'to': '02.03.2026'}), ['Night (NT)'])
        self.assertEqual(labels(**{'from': '01.03.2026', 'to': '01.03.2026'}), [])
        self.assertContains(self.client.get(url), '02.03.2026 00:30')


def perms(*names):
    """Permission ids for 'app.codename' names, as the role form posts them."""
    ids = []
    for name in names:
        app_label, codename = name.split('.')
        ids.append(str(Permission.objects.get(content_type__app_label=app_label, codename=codename).pk))
    return ids


def perm_names(group):
    return {f'{p.content_type.app_label}.{p.codename}' for p in group.permissions.select_related('content_type')}


def user_data(**overrides):
    data = {'username': 'kari', 'first_name': 'Kari', 'last_name': 'Nordmann', 'email': 'kari@example.com',
            'is_active': 'on', 'groups': []}
    data.update(overrides)
    return data


class RevisionTests(TestCase):
    """audit.revision(): the change signal the monitoring wall polls on."""

    def write(self, label='Bergen'):
        site = Site.objects.create(name=label, code=label[:2].upper())
        return audit.record(None, AuditLog.Action.CREATE, site)

    def test_an_empty_log_has_a_token_and_it_does_not_move_without_a_write(self):
        self.assertEqual(audit.revision(), '0')
        self.assertEqual(audit.revision(), audit.revision())

    def test_every_entry_moves_it_and_nothing_else_does(self):
        seen = [audit.revision()]
        for label in ('Alta', 'Bodo', 'Vardo'):
            self.write(label)
            seen.append(audit.revision())
            self.assertEqual(audit.revision(), seen[-1])            # reading never changes it
        self.assertEqual(len(set(seen)), 4)
        Site.objects.create(name='Silent', code='SI')             # a write that is not logged is not seen: the
        self.assertEqual(audit.revision(), seen[-1])             # token test of the writers is what guards that

    def test_an_entry_stamped_before_the_newest_one_moves_it_through_the_count(self):
        first = self.write('Alta')
        before = audit.revision()
        late = timezone.now() - timedelta(minutes=2)
        with mock.patch('django.utils.timezone.now', return_value=late):        # created_at is taken at make time
            second = self.write('Bodo')
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertLess(second.created_at, first.created_at)
        self.assertNotEqual(audit.revision(), before)

    def test_it_costs_two_queries(self):
        self.write()
        with self.assertNumQueries(2):
            audit.revision()


class AdminTestCase(TestCase):
    """Roles and users are managed by the platform admin."""

    def setUp(self):
        self.admin = get_user_model().objects.create_superuser('root', 'root@example.com', 'eski-sifre-123')
        self.client.force_login(self.admin)


class AdminPageTests(AdminTestCase):
    def test_role_and_user_pages_render_as_page_and_in_the_dialog(self):
        role = Group.objects.create(name='Feeder')
        role.permissions.set(Permission.objects.filter(codename__in=['view_site', 'view_auditlog']))
        self.admin.groups.add(role)
        urls = [reverse('core:group_list'), reverse('core:group_create'), reverse('core:group_edit', args=[role.pk]),
                reverse('core:group_delete', args=[role.pk]), reverse('core:user_list'), reverse('core:user_create'),
                reverse('core:user_edit', args=[self.admin.pk])]
        for url in urls:
            for headers in ({}, {'X-Modal': '1'}):
                self.assertEqual(self.client.get(url, headers=headers).status_code, 200, (url, headers))
        self.assertContains(self.client.get(reverse('core:group_list')), 'Sites: read; Activity log: read')


class RoleTests(AdminTestCase):
    def test_role_create_read_edit_delete(self):
        # Create
        self.client.post(reverse('core:group_create'), {
            'name': ' Feeder ', 'permissions': perms('farm.view_site', 'farm.add_site', 'core.view_auditlog'),
        })
        role = Group.objects.get()
        self.assertEqual(role.name, 'Feeder')
        self.assertEqual(perm_names(role), {'farm.view_site', 'farm.add_site', 'core.view_auditlog'})

        # Read: the list shows it with what it allows, the form is filled from the database
        response = self.client.get(reverse('core:group_list'))
        self.assertContains(response, 'Feeder')
        self.assertContains(response, 'Sites: read, create; Activity log: read')
        form = self.client.get(reverse('core:group_edit', args=[role.pk])).context['form']
        self.assertEqual(sorted(form['permissions'].value()),
                         sorted(int(pk) for pk in perms('farm.view_site', 'farm.add_site', 'core.view_auditlog')))

        # Edit: rename, take create and the activity log away, give edit
        self.client.post(reverse('core:group_edit', args=[role.pk]), {
            'name': 'Site editor', 'permissions': perms('farm.view_site', 'farm.change_site'),
        })
        role.refresh_from_db()
        self.assertEqual(role.name, 'Site editor')
        self.assertEqual(perm_names(role), {'farm.view_site', 'farm.change_site'})

        # Delete
        self.assertContains(self.client.get(reverse('core:group_delete', args=[role.pk])), 'Delete “Site editor”?')
        self.client.post(reverse('core:group_delete', args=[role.pk]))
        self.assertFalse(Group.objects.exists())

    def test_create_edit_and_delete_imply_read(self):
        self.client.post(reverse('core:group_create'), {'name': 'Cleaner', 'permissions': perms('farm.delete_site')})
        self.assertEqual(perm_names(Group.objects.get()), {'farm.view_site', 'farm.delete_site'})

    def test_matrix_offers_only_the_access_areas(self):
        form = self.client.get(reverse('core:group_create')).context['form']
        offered = {f'{p.content_type.app_label}.{p.codename}' for p in form.fields['permissions'].queryset}
        self.assertEqual(offered, {area.perm(action) for area in access.areas() for action in area.actions})
        response = self.client.post(reverse('core:group_create'), {
            'name': 'Sneaky', 'permissions': perms('auth.change_user'),
        })
        self.assertIn('permissions', response.context['form'].errors)
        self.assertFalse(Group.objects.exists())

    def test_matrix_ties_create_edit_and_delete_to_their_read_box(self):
        html = self.client.get(reverse('core:group_create')).content.decode()
        tied = 0
        for area in access.areas():
            if access.READ not in area.actions:
                continue
            read_id = re.search(r'value="%s" id="(\w+)"' % perms(area.perm(access.READ))[0], html).group(1)
            for action in area.actions:
                if action in access.INCLUDES_READ:     # Crew, All production and Everyone widen rows only
                    tied += 1
                    self.assertRegex(
                        html, r'value="%s" id="\w+" data-requires="%s"' % (perms(area.perm(action))[0], read_id))
        self.assertEqual(html.count('data-requires="'), tied)    # an area that offers Read only has none

    def test_names_are_unique(self):
        Group.objects.create(name='Feeder')
        response = self.client.post(reverse('core:group_create'), {'name': 'Feeder'})
        self.assertEqual(response.context['form'].errors['name'], ['Another role already uses this name.'])

    def test_list_counts_users(self):
        role = Group.objects.create(name='Feeder')
        get_user_model().objects.create_user('ola').groups.add(role)
        response = self.client.get(reverse('core:group_list'))
        self.assertEqual([len(r.user_set.all()) for r in response.context['objects']], [1])
        self.assertContains(response, 'Nothing yet')

    def test_permission_changes_are_logged(self):
        self.client.post(reverse('core:group_create'), {'name': 'Feeder', 'permissions': perms('farm.view_site')})
        role = Group.objects.get()
        self.client.post(reverse('core:group_edit', args=[role.pk]), {
            'name': 'Feeder', 'permissions': perms('farm.add_site', 'core.view_auditlog'),
        })
        self.client.post(reverse('core:group_delete', args=[role.pk]))
        log = list(AuditLog.objects.order_by('created_at').values_list('action', 'entity_type', 'entity_id', 'changes'))
        self.assertEqual(log, [
            ('create', 'role', str(role.pk), {'Role name': [None, 'Feeder'], 'Permissions': [None, 'Sites: read']}),
            ('update', 'role', str(role.pk),
             {'Permissions': ['Sites: read', 'Sites: read, create; Activity log: read']}),
            ('delete', 'role', str(role.pk), {}),
        ])


class UserTests(AdminTestCase):
    def setUp(self):
        super().setUp()
        self.feeder = Group.objects.create(name='Feeder')
        self.vet = Group.objects.create(name='Vet')

    def test_user_create_read_edit_deactivate(self):
        # Create: no password yet, an invitation instead
        self.client.post(reverse('core:user_create'), user_data(groups=[self.feeder.pk]))
        kari = get_user_model().objects.get(username='kari')
        self.assertEqual((kari.first_name, kari.last_name, kari.email, kari.is_active, kari.is_superuser),
                         ('Kari', 'Nordmann', 'kari@example.com', True, False))
        self.assertEqual(list(kari.groups.all()), [self.feeder])
        self.assertFalse(kari.has_usable_password())

        # Read
        response = self.client.get(reverse('core:user_list'))
        self.assertContains(response, 'kari@example.com')
        self.assertContains(response, 'Kari Nordmann')
        form = self.client.get(reverse('core:user_edit', args=[kari.pk])).context['form']
        self.assertEqual((form['email'].value(), list(form['groups'].value())), ('kari@example.com', [self.feeder.pk]))

        # Edit: change the details and the roles
        self.client.post(reverse('core:user_edit', args=[kari.pk]),
                         user_data(email='kari@farm.no', last_name='Berg', groups=[self.vet.pk, self.feeder.pk]))
        kari.refresh_from_db()
        self.assertEqual((kari.last_name, kari.email), ('Berg', 'kari@farm.no'))
        self.assertEqual(set(kari.groups.all()), {self.vet, self.feeder})

        # Deactivate (there is no delete)
        self.client.post(reverse('core:user_edit', args=[kari.pk]), user_data(is_active='', groups=[]))
        kari.refresh_from_db()
        self.assertFalse(kari.is_active)
        self.assertFalse(kari.groups.exists())
        self.assertEqual(self.client.get(f'/users/{kari.pk}/delete/').status_code, 404)
        self.assertNotContains(self.client.get(reverse('core:user_list')), '/delete/')

    def test_new_user_is_invited_and_can_set_a_password(self):
        self.client.post(reverse('core:user_create'), user_data())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['kari@example.com'])
        link = re.search(r'http://testserver(\S+)', mail.outbox[0].body).group(1)

        self.client.logout()
        response = self.client.get(link, follow=True)
        self.client.post(response.redirect_chain[-1][0],
                         {'new_password1': 'yeni-sifre-456', 'new_password2': 'yeni-sifre-456'})
        self.assertTrue(get_user_model().objects.get(username='kari').check_password('yeni-sifre-456'))

    def test_editing_sends_no_invitation(self):
        kari = get_user_model().objects.create_user('kari', 'kari@example.com')
        self.client.post(reverse('core:user_edit', args=[kari.pk]), user_data(first_name='Kari Anne'))
        kari.refresh_from_db()
        self.assertEqual(kari.first_name, 'Kari Anne')
        self.assertEqual(mail.outbox, [])

    def test_invited_user_can_ask_for_a_new_link(self):
        get_user_model().objects.create_user('kari', 'kari@example.com')    # no usable password
        self.client.logout()
        self.client.post(reverse('password_reset'), {'email': 'kari@example.com'})
        self.assertEqual(len(mail.outbox), 1)

    def test_email_is_required_and_unique(self):
        response = self.client.post(reverse('core:user_create'), user_data(email=''))
        self.assertIn('email', response.context['form'].errors)
        response = self.client.post(reverse('core:user_create'), user_data(username='other', email='ROOT@example.com'))
        self.assertEqual(response.context['form'].errors['email'], ['Another user already uses this email.'])
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_admin_cannot_deactivate_own_account(self):
        response = self.client.post(reverse('core:user_edit', args=[self.admin.pk]),
                                    user_data(username='root', email='root@example.com', is_active=''))
        self.assertEqual(response.context['form'].errors['is_active'], ['You cannot deactivate your own account.'])
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_platform_admin_is_marked_and_stays_admin_when_edited(self):
        self.assertContains(self.client.get(reverse('core:user_list')), 'Platform admin')
        self.client.post(reverse('core:user_edit', args=[self.admin.pk]),
                         user_data(username='root', email='root@example.com', is_superuser=''))
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_superuser)

    def test_user_changes_are_logged(self):
        self.client.post(reverse('core:user_create'), user_data(groups=[self.feeder.pk]))
        kari = get_user_model().objects.get(username='kari')
        self.client.post(reverse('core:user_edit', args=[kari.pk]), user_data(is_active='', groups=[self.vet.pk]))
        created, edited = AuditLog.objects.order_by('created_at').values_list('action', 'entity_type', 'changes')
        self.assertEqual(created, ('create', 'user', {
            'Username': [None, 'kari'], 'First name': [None, 'Kari'], 'Last name': [None, 'Nordmann'],
            'Email': [None, 'kari@example.com'], 'Active': [None, message('Yes')], 'Roles': [None, 'Feeder'],
        }))
        self.assertEqual(edited, ('update', 'user', {'Active': [message('Yes'), message('No')], 'Roles': ['Feeder', 'Vet']}))


class AccessTests(AdminTestCase):
    """Only the platform admin manages roles and users; a role grants exactly what its matrix says."""

    def test_roles_and_users_are_closed_to_everyone_else(self):
        ola = get_user_model().objects.create_user('ola', 'ola@example.com', 'eski-sifre-123')
        everything = Group.objects.create(name='Everything')
        everything.permissions.set(Permission.objects.filter(codename__in=[
            'view_site', 'add_site', 'change_site', 'delete_site', 'view_auditlog']))
        ola.groups.add(everything)
        self.client.force_login(ola)
        for url in (reverse('core:group_list'), reverse('core:group_create'),
                    reverse('core:group_edit', args=[everything.pk]),
                    reverse('core:user_list'), reverse('core:user_create'),
                    reverse('core:user_edit', args=[ola.pk])):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        home = self.client.get(reverse('home'))
        self.assertNotContains(home, reverse('core:group_list'))
        self.assertNotContains(home, reverse('core:user_list'))
        self.assertContains(home, reverse('farm:site_list'))

    def test_admin_sees_roles_and_users_in_the_menu(self):
        home = self.client.get(reverse('home'))
        self.assertContains(home, reverse('core:group_list'))
        self.assertContains(home, reverse('core:user_list'))

    def test_a_role_given_through_the_pages_allows_exactly_what_it_says(self):
        site = Site.objects.create(name='Site A', code='SA')
        self.client.post(reverse('core:group_create'), {
            'name': 'Site clerk', 'permissions': perms('farm.view_site', 'farm.add_site'),
        })
        self.client.post(reverse('core:user_create'), user_data(groups=[Group.objects.get().pk]))
        self.client.force_login(get_user_model().objects.get(username='kari'))

        self.assertEqual(self.client.get(reverse('farm:site_list')).status_code, 200)
        self.client.post(reverse('farm:site_create'), site_data(name='Site B', code='SB'))
        self.assertTrue(Site.objects.filter(code='SB').exists())
        self.assertEqual(self.client.post(reverse('farm:site_edit', args=[site.pk]),
                                          site_data(name='Renamed', code='SA', version='1')).status_code, 403)
        self.assertEqual(self.client.post(reverse('farm:site_delete', args=[site.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse('core:activity_log')).status_code, 403)
        site.refresh_from_db()
        self.assertEqual((site.name, site.is_deleted), ('Site A', False))


class ListOrderTests(TestCase):
    """Every tab's list is read and paged in a fixed order. A filter that counts with a GROUP BY (an
    annotated Count) drops the model's ordering, since Django leaves Meta.ordering out of such queries; a
    page of an unordered list can show a record twice and another never."""

    def test_every_list_page_is_paged_in_order(self):
        import_module(settings.ROOT_URLCONF)    # declares every resource
        self.client.force_login(get_user_model().objects.create_superuser('root', 'root@example.com', 'x-123-y'))
        with warnings.catch_warnings():
            warnings.simplefilter('error', UnorderedObjectListWarning)
            for tab in Resource.registry:
                if tab.page_size:
                    self.assertEqual(self.client.get(reverse(tab.url_name('list'))).status_code, 200, tab.__name__)


class TabRulesTests(TestCase):
    """What every tab (a Resource on a farm record) must have. A tab added without one of these
    fails here, so none can be forgotten: reachable by a role, in the menu, logged consistently."""

    @classmethod
    def setUpTestData(cls):
        import_module(settings.ROOT_URLCONF)    # declares every resource
        cls.tabs = [tab for tab in Resource.registry if issubclass(tab.model, AuditedModel)]

    def test_the_tabs_are_found(self):
        self.assertTrue(self.tabs)

    def test_every_tab_can_be_given_to_a_role_in_the_permission_matrix(self):
        offered = {(area.model, action) for area in access.areas() for action in area.actions}
        for tab in self.tabs:
            for action in ('view', *tab.actions):
                self.assertIn((tab.model._meta.label, action), offered,
                              f'{tab.__name__}: add {tab.model._meta.label} to config/access.py')

    def test_every_tab_has_a_menu_entry_for_its_read_permission(self):
        menu = {entry.perm for entry in navigation.entries()}
        for tab in self.tabs:
            self.assertIn(tab.perm('view'), menu, f'{tab.__name__}: add it to config/navigation.py')

    def test_the_activity_log_names_a_tabs_records_as_the_delete_plan_does(self):
        # The delete plan logs the records it touches by their model's name; a tab searches the history
        # by its own. If the two drifted apart, a record's History tab would miss those entries.
        for tab in self.tabs:
            self.assertEqual(tab.entity_type(), audit.entity_type_of(tab.model), tab.__name__)

