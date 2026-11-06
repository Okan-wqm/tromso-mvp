"""One rule for the menu and the address bar: a page a person's menu leaves out is refused at its address too, and a page it
shows opens. Walked for every role the production roles start from (hr/roles.py), a production department's manager, an
office person and the platform admin, over every line of every panel's menu (core.navigation.entries; a line the menu
never shows, `hidden`, is reached from another page and is not walked)."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from core import navigation

from .. import roles
from ..models import Employee
from .helpers_people import PeopleTestCase

OPEN = (200, 302)


class MenuAgreesWithAccessTests(PeopleTestCase):
    def setUp(self):
        super().setUp()
        roles.create()
        self.worker = get_user_model().objects.create_user('ann', 'ann@example.com', 'x')
        self.worker.groups.add(Group.objects.get(name='Production worker'))
        Employee.objects.filter(pk=self.in_a.pk).update(user=self.worker, first_name='', last_name='')
        self.manager = get_user_model().objects.create_user('max', 'max@example.com', 'x')
        self.manager.groups.add(Group.objects.get(name='Production manager'))
        self.office = get_user_model().objects.create_user('cy', 'cy@example.com', 'x')
        self.office.groups.add(Group.objects.get(name='Production worker'))
        Employee.objects.filter(pk=self.in_fin.pk).update(user=self.office, first_name='', last_name='')
        self.admin = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')

    def test_every_line_is_shown_exactly_when_its_page_opens(self):
        found = []
        for person in (self.worker, self.manager, self.lead_a, self.office, self.hr, self.admin):
            self.client.force_login(person)
            for entry in navigation.entries():
                if entry.hidden:
                    continue
                shown = entry.shown_to(person)
                status = self.client.get(entry.url()).status_code
                if shown != (status in OPEN):
                    found.append(f'{person.username} {entry.url_name}: shown={shown}, status {status}')
        self.assertEqual(found, [])

    def test_a_production_worker_is_refused_team_overview_like_its_menu_line(self):
        self.client.force_login(self.worker)
        response = self.client.get(navigation.page('hr:production_overview').entry.url())
        self.assertEqual(response.status_code, 403)
