"""Where a lead may place people, and their own record.

A lead with Edit on Employees reaches the people of the departments they manage. A move is a placement in a department,
so the department moved to must be one they manage too: a lead cannot hand a person to another manager or into the
office. And a lead does not write their own record (placement, title, last day): like their own attendance and plan, that
is for a holder of Everyone. Every refusal writes nothing and logs nothing."""
from datetime import date

from django.core.exceptions import PermissionDenied
from django.urls import reverse

from core.models import AuditLog
from farm.models import ProductionDepartment

from .. import services
from ..models import Employee, Posting
from ..units import token
from .helpers import user
from .helpers_people import PeopleTestCase, place

MOVE_DAY = date(2026, 3, 2)


class OwnRecordAndTargetTests(PeopleTestCase):
    def setUp(self):
        super().setUp()
        self.editor = user('editor', 'view_employee', 'change_employee', group='Edit role')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=self.editor)
        self.dept_a.refresh_from_db()
        self.own = Employee.objects.create(employee_number='E-7', user=self.editor, joined_on=date(2026, 1, 1))
        place(self.own, self.dept_a, title='Lead')

    def snapshot(self):
        return (list(Employee.all_objects.order_by('pk').values_list('pk', 'left_on', 'version', 'is_deleted')),
                list(Posting.all_objects.order_by('pk').values_list(
                    'pk', 'production_department', 'office_department', 'valid_until', 'title', 'is_deleted')),
                AuditLog.objects.count())

    def post_edit(self, person, **changes):
        data = {'employee_number': person.employee_number, 'last_name': person.last_name or '',
                'first_name': person.first_name or '', 'employment_type': person.employment_type,
                'joined_on': '2026-01-01', 'department': token(self.dept_a), 'title': 'Technician',
                'from_day': '2026-01-01', 'version': str(person.version), **changes}
        return self.client.post(reverse('hr:production_employee_edit', args=[person.pk]), data)

    # ---- the department moved to ----------------------------------------------------------------------------------
    def test_a_lead_cannot_move_their_person_into_a_department_they_do_not_manage(self):
        before = self.snapshot()
        for department in (self.dept_b, self.finance):
            with self.subTest(department=str(department)):
                with self.assertRaises(PermissionDenied):
                    services.move(self.editor, self.in_a, department, 'Feeder', MOVE_DAY)
                self.assertEqual(self.snapshot(), before)

    def test_the_form_refuses_such_a_move_and_writes_nothing(self):
        self.client.force_login(self.editor)
        before = self.snapshot()
        for department in (self.dept_b, self.finance):
            with self.subTest(department=str(department)):
                response = self.post_edit(self.in_a, department=token(department), from_day='2026-03-02')
                self.assertEqual(response.status_code, 200)              # not offered: the chooser refuses it
                self.assertIn('department', response.context['form'].errors)
                self.assertEqual(self.snapshot(), before)

    def test_a_lead_still_changes_a_title_inside_their_own_department(self):
        services.move(self.editor, self.in_a, self.dept_a, 'Senior technician', MOVE_DAY)
        self.assertEqual(Posting.objects.get(employee=self.in_a, valid_until__isnull=True).title, 'Senior technician')

    def test_all_production_moves_between_production_departments_but_not_into_the_office(self):
        wide = user('wide', 'view_employee', 'change_employee', 'all_production_employee', group='Wide role')
        services.move(wide, self.in_a, self.dept_b, 'Feeder', MOVE_DAY)
        self.assertEqual(Posting.objects.get(employee=self.in_a, valid_until__isnull=True).production_department,
                         self.dept_b)
        with self.assertRaises(PermissionDenied):
            services.move(wide, self.in_b, self.finance, 'Clerk', MOVE_DAY)

    def test_everyone_moves_anyone_anywhere(self):
        services.move(self.hr, self.in_a, self.finance, 'Clerk', MOVE_DAY)
        self.assertEqual(Posting.objects.get(employee=self.in_a, valid_until__isnull=True).office_department,
                         self.finance)

    # ---- one's own record -----------------------------------------------------------------------------------------
    def test_a_lead_cannot_move_themselves_or_give_themselves_a_last_day(self):
        before = self.snapshot()
        with self.assertRaises(PermissionDenied):
            services.move(self.editor, self.own, self.dept_a, 'Head of everything', MOVE_DAY)
        with self.assertRaises(PermissionDenied):
            services.leave_company(self.editor, self.own, date(2026, 6, 30))
        self.assertEqual(self.snapshot(), before)

    def test_a_lead_cannot_open_or_save_their_own_record(self):
        self.client.force_login(self.editor)
        before = self.snapshot()
        self.assertEqual(self.client.get(reverse('hr:production_employee_edit', args=[self.own.pk])).status_code, 403)
        response = self.post_edit(self.own, title='Head of everything', from_day='2026-03-02', left_on='2026-06-30')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.snapshot(), before)

    def test_a_holder_of_everyone_edits_their_own_record(self):
        own = Employee.objects.create(employee_number='E-8', user=self.hr, joined_on=date(2026, 1, 1))
        place(own, self.finance, title='HR')
        services.move(self.hr, own, self.finance, 'Head of HR', MOVE_DAY)
        services.leave_company(self.hr, own, date(2026, 6, 30))
        own.refresh_from_db()
        self.assertEqual(own.left_on, date(2026, 6, 30))

    def test_the_edit_link_is_not_offered_for_ones_own_row(self):
        self.client.force_login(self.editor)
        page = self.client.get(reverse('hr:production_employee_list')).content.decode()
        edit = 'href="{}"'.format
        self.assertIn(edit(reverse('hr:production_employee_edit', args=[self.in_a.pk])), page)
        self.assertNotIn(edit(reverse('hr:production_employee_edit', args=[self.own.pk])), page)
        self.assertIn(edit(reverse('hr:production_employee_detail', args=[self.own.pk])), page)

    def test_the_form_offers_a_lead_only_the_departments_they_manage(self):
        self.client.force_login(self.editor)
        form = self.client.get(reverse('hr:production_employee_edit', args=[self.in_a.pk])).context['form']
        offered = {value for _group, options in form.fields['department'].choices if isinstance(options, list)
                   for value, _label in options}
        self.assertEqual(offered, {token(self.dept_a)})
        self.client.force_login(self.hr)
        form = self.client.get(reverse('hr:employee_edit', args=[self.in_fin.pk])).context['form']
        offered = {value for _group, options in form.fields['department'].choices if isinstance(options, list)
                   for value, _label in options}
        self.assertEqual(offered, {token(self.dept_a), token(self.dept_b), token(self.admin_dept), token(self.finance)})
