"""The two production permissions and their matrix columns: `hr.all_production_employee` (every production person, never the
office's, never a leave reason) and `hr.crew_shiftassignment` (the shift plan of one's crew). Each is a column of the role
matrix, offered by one area only."""
import re
from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import RequestFactory
from django.urls import reverse

from core import access
from farm.models import ProductionDepartment

from .. import scope
from ..models import Employee, LeaveRequest, LeaveType
from ..resources import LeaveRequestResource
from .helpers import user
from .helpers_people import PeopleTestCase, employee, place

DAY = date(2026, 3, 2)
HEAD = ('view_employee', 'all_production_employee', 'view_leaverequest', 'change_leaverequest')


def names(employees):
    return sorted(person.last_name for person in employees)


class MatrixTests(PeopleTestCase):
    def test_the_columns_in_order_everyone_last(self):
        self.assertEqual([action for action, _label in access.ACTIONS],
                         ['view', 'add', 'change', 'delete', 'crew', 'all_production', 'all'])
        self.assertEqual(access.ACTIONS[-1][0], access.ALL)

    def test_the_permission_rows_exist_and_the_matrix_offers_them_on_one_area_each(self):
        for codename in ('all_production_employee', 'crew_shiftassignment'):
            self.assertTrue(Permission.objects.filter(content_type__app_label='hr', codename=codename).exists(), codename)
        offered = {access.perm_name(permission) for permission in access.permissions()}
        self.assertIn('hr.all_production_employee', offered)
        self.assertIn('hr.crew_shiftassignment', offered)
        holders = {area.model for area in access.areas() for action in area.actions if action in ('crew', 'all_production')}
        self.assertEqual(holders, {'hr.Employee', 'hr.ShiftAssignment'})

    def test_each_new_column_implies_read(self):
        self.assertEqual(access.implied({'hr.crew_shiftassignment'}),
                         {'hr.crew_shiftassignment', 'hr.view_shiftassignment'})
        self.assertEqual(access.implied({'hr.all_production_employee'}),
                         {'hr.all_production_employee', 'hr.view_employee'})

    def test_the_role_form_shows_seven_columns_and_the_boxes_where_offered(self):
        admin = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        self.client.force_login(admin)
        html = self.client.get(reverse('core:group_create')).content.decode()
        self.assertIn('>Crew</th>', html)
        self.assertIn('>All production</th>', html)
        rows = re.findall(r'<tr>\s*<th scope="row">(.*?)</th>(.*?)</tr>', html, re.S)
        cells = {label: re.findall(r'<td>(.*?)</td>', body, re.S) for label, body in rows}
        self.assertTrue(all(len(row) == 7 for row in cells.values()))
        self.assertIn('Employees: All production', cells['Employees'][5])
        self.assertIn('Shift schedule: Crew', cells['Shift schedule'][4])
        self.assertEqual(cells['Species'][4].strip(), '')

    def test_the_summary_names_the_columns(self):
        chosen = Permission.objects.filter(content_type__app_label='hr',
                                           codename__in=['view_shiftassignment', 'crew_shiftassignment'])
        self.assertEqual(access.summary(chosen), 'Shift schedule: read, crew')


class AllProductionTests(PeopleTestCase):
    def setUp(self):
        super().setUp()
        self.head = user('head', *HEAD, group='Head of production')

    def test_it_reaches_every_production_person_and_no_office_person(self):
        self.assertEqual(names(scope.team(self.head, DAY)), ['Alfa', 'Bravo'])
        self.assertEqual(names(scope.team(user('plain', 'view_employee'), DAY)), [])

    def test_it_reaches_a_department_without_a_manager_and_one_whose_manager_account_is_gone(self):
        orphan = ProductionDepartment.objects.create(site=self.site, name='Smolt C', code='SMO-C')
        place(employee('E-5', 'Echo'), orphan)
        self.assertIn('Echo', names(scope.team(self.head, DAY)))
        self.assertNotIn('Echo', names(scope.team(self.lead_a, DAY)))
        self.lead_b.delete()
        self.assertIsNone(ProductionDepartment.objects.get(pk=self.dept_b.pk).manager)
        self.assertIn('Bravo', names(scope.team(self.head, DAY)))

    def test_it_reaches_records_by_their_day_and_the_week(self):
        days = scope.visible_days(self.head, date(2026, 3, 2), date(2026, 3, 8))
        self.assertEqual(set(days), {self.in_a.pk, self.in_b.pk})

    def test_it_never_gives_a_leave_reason(self):
        kind = LeaveType.objects.create(name='Annual leave', code='ANNUAL')
        item = LeaveRequest.objects.create(employee=self.in_a, leave_type=kind, first_day=DAY, last_day=DAY,
                                           reason='Private words')
        request = RequestFactory().get('/')
        request.user = self.head
        row = LeaveRequestResource.shown(request, [item])[0]
        self.assertFalse(row['show_reason'])

    def test_a_production_manager_by_permission_leads(self):
        self.assertTrue(scope.leads(self.head))
        self.assertFalse(scope.leads(user('plain', 'view_employee')))
        Employee.objects.filter(pk=self.in_fin.pk).update(user=self.head, first_name='', last_name='')
        self.assertFalse(scope.production_only(self.head, DAY))
