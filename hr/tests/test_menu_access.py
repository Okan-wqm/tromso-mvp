"""One rule for the menu and the address bar: a page a person's menu leaves out is refused at its address too, and a page it
shows opens. Walked for every role the production roles start from (hr/roles.py), a production department's manager, an
office person and the platform admin, over every line of every panel's menu (core.navigation.entries; a line the menu
never shows, `hidden`, is reached from another page and is not walked)."""
from datetime import date, datetime, timezone as utc

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.urls import get_resolver, reverse

from core import navigation

from .. import roles
from ..models import AttendanceRecord, Employee, LeaveRequest, LeaveType, ShiftAssignment
from .helpers_people import PeopleTestCase

OPEN = (200, 302)


def hr_routes():
    """(name, pattern) of every named route in the hr namespace, both mounts."""
    def walk(patterns, namespace=''):
        for pattern in patterns:
            if hasattr(pattern, 'url_patterns'):
                yield from walk(pattern.url_patterns, f'{namespace}{pattern.namespace}:' if pattern.namespace else namespace)
            elif pattern.name and namespace == 'hr:':
                yield f'hr:{pattern.name}', str(pattern.pattern)
    return list(walk(get_resolver().url_patterns))


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

    def test_every_address_of_a_tab_follows_its_menu_line_for_a_production_worker(self):
        """Not only the menu line: every route of HR, on the Company mount and on Production's (a record's page, approve,
        cancel, the board, the punch, the planning post), filled with the worker's own records. A route under a line the
        menu hides from the worker is refused; the same route on Production's mount is not refused by the menu."""
        own = LeaveRequest.objects.create(employee=self.in_a, leave_type=LeaveType.objects.create(name='Annual', code='AN'),
                                          first_day=date(2026, 12, 1), last_day=date(2026, 12, 1), status='pending')
        plan = ShiftAssignment.objects.create(employee=self.in_a, day=date(2026, 12, 2), shift=None)
        record = AttendanceRecord.objects.create(employee=self.in_a, clock_in=datetime(2026, 3, 2, 6, tzinfo=utc.utc),
                                                 clock_out=datetime(2026, 3, 2, 14, tzinfo=utc.utc), note='Entered')
        args = {'leaverequest': own.pk, 'shiftassignment': plan.pk, 'attendancerecord': record.pk, 'employee': self.in_a.pk,
                'punch': 'in'}
        self.client.force_login(self.worker)
        checked = []
        for name, pattern in hr_routes():
            needs = [value for key, value in args.items() if name.split(':')[1].replace('production_', '').startswith(key)]
            if '<' in pattern and not needs:
                continue                                    # a route of another record kind (settings, departments)
            address = reverse(name, args=needs[:1] if '<' in pattern else [])
            status = self.client.get(address).status_code
            refused = navigation.refused(self.worker, address)
            if refused:
                self.assertEqual(status, 403, address)
            if ':production_' in name:
                self.assertFalse(refused, address)
            checked.append((name, refused))
        self.assertIn(('hr:leaverequest_detail', True), checked)
        self.assertIn(('hr:production_leaverequest_detail', False), checked)
        self.assertIn(('hr:punch', True), checked)
        self.assertIn(('hr:production_punch', False), checked)
        self.assertEqual(self.client.get(reverse('hr:production_leaverequest_detail', args=[own.pk])).status_code, 200)

    def test_the_role_matrix_says_where_a_line_is_shown_only_to_some(self):
        """The role matrix names, under an area, the menu lines a person is not offered whatever the role (show_when):
        the Company HR pages for a person whose HR is all in Production, Team overview for one who leads nobody."""
        self.client.force_login(self.admin)
        page = self.client.get(reverse('core:group_edit', args=[Group.objects.get(name='Production worker').pk]))
        self.assertContains(page, 'Company · HR · Shift schedule: not for a person whose HR is all in Production')
        self.assertContains(page, 'Production · Team · Team overview: only for a person who leads production people')

    def test_a_production_worker_is_refused_team_overview_like_its_menu_line(self):
        self.client.force_login(self.worker)
        response = self.client.get(navigation.page('hr:production_overview').entry.url())
        self.assertEqual(response.status_code, 403)
