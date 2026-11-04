from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase

from farm.tests.helpers import role

from .people import person_name, who_can


class PeopleTests(TestCase):
    def person(self, username, first='', last='', **fields):
        return get_user_model().objects.create_user(username, f'{username}@example.com', 'x', first_name=first,
                                                    last_name=last, **fields)

    def test_a_person_is_named_by_their_full_name_else_their_username(self):
        self.assertEqual(person_name(self.person('kari', 'Kari', 'Nord')), 'Kari Nord')
        self.assertEqual(person_name(self.person('olav')), 'olav')

    def test_who_can_are_the_active_holders_of_the_permission_by_name_and_the_platform_admin(self):
        by_role, direct = self.person('ali', 'Ali', 'Kaya'), self.person('berit', 'Berit', 'Sjef')
        by_role.groups.add(role('Readers', 'view_task'))
        direct.user_permissions.add(Permission.objects.get(codename='view_task'))
        self.person('gone', 'Gone', 'Away', is_active=False).groups.add(role('Gone', 'view_task'))
        self.person('other', 'Other', 'Person').groups.add(role('Sites', 'view_site'))
        root = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        self.assertEqual([user.username for user in who_can('tasks', 'view_task')], ['root', 'ali', 'berit'])
        self.assertEqual([user.username for user in who_can('farm', 'view_site')], ['root', 'other'])
        self.assertEqual([user.username for user in who_can('experiments', 'view_experiment')], [root.username])
