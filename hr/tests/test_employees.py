from datetime import date

from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.urls import reverse

from core.softdelete import plan_delete

from ..models import Employee, Posting
from .helpers import fields_of
from .helpers_people import PeopleTestCase, TOP, employee, place
from core.testing import delete_confirmed


def data(department=None, **overrides):
    values = {'employee_number': 'E-100', 'user': '', 'first_name': 'Nora', 'last_name': 'Berg',
              'employment_type': 'staff', 'joined_on': '2026-02-01', 'left_on': '', 'department': department or '',
              'title': 'Analyst', 'from_day': ''}
    values.update(overrides)
    return values


class EmployeeRoundTripTests(PeopleTestCase):
    def test_create_read_edit_every_column_and_no_delete(self):
        # Create (the HR administrator, who holds Everyone)
        self.client.force_login(self.hr)
        from ..units import token
        self.client.post(reverse('hr:employee_create'), data(token(self.finance)))
        person = Employee.objects.get(employee_number='E-100')
        stored = {name: getattr(person, name) for name in fields_of(Employee)}
        self.assertEqual(stored, {
            'employee_number': 'E-100', 'user': None, 'first_name': 'Nora', 'last_name': 'Berg',
            'employment_type': 'staff', 'joined_on': date(2026, 2, 1), 'left_on': None})
        self.assertEqual(person.created_by, self.hr)
        placement = Posting.objects.get(employee=person)
        self.assertEqual((placement.office_department, placement.production_department, placement.title,
                          placement.valid_from, placement.valid_until),
                         (self.finance, None, 'Analyst', date(2026, 2, 1), None))
        # Read: the list and the read page, and the form is filled from the stored rows
        listed = list(self.client.get(reverse('hr:employee_list')).context['objects'])
        self.assertIn(person, listed)
        row = next(item for item in listed if item.pk == person.pk)
        self.assertEqual((row.department_name, row.current_title), ('Finance', 'Analyst'))
        self.assertContains(self.client.get(reverse('hr:employee_detail', args=[person.pk])), 'Analyst')
        form = self.client.get(reverse('hr:employee_edit', args=[person.pk])).context['form']
        self.assertEqual((form['title'].value(), form['department'].value(), form['last_name'].value()),
                         ('Analyst', token(self.finance), 'Berg'))
        # Edit: the person's own columns, and a new placement from a day (the old one ends the day before)
        self.client.post(reverse('hr:employee_edit', args=[person.pk]), data(
            token(self.dept_a), employee_number='E-101', last_name='Berg-Hansen', employment_type='researcher',
            title='Researcher', from_day='2026-06-01', version='1'))
        person.refresh_from_db()
        self.assertEqual((person.employee_number, person.last_name, person.employment_type, person.version),
                         ('E-101', 'Berg-Hansen', 'researcher', 2))
        old, new = Posting.objects.filter(employee=person).order_by('valid_from')
        self.assertEqual((old.valid_until, old.office_department), (date(2026, 5, 31), self.finance))
        self.assertEqual((new.valid_from, new.valid_until, new.production_department, new.title),
                         (date(2026, 6, 1), None, self.dept_a, 'Researcher'))
        # There is no delete: a person leaves with a last day
        self.assertEqual(delete_confirmed(self.client, f'/hr/team/{person.pk}/delete/').status_code, 404)

    def test_a_person_with_an_account_is_named_by_it(self):
        self.client.force_login(self.hr)
        account = get_user_model().objects.create_user('nora', 'nora@example.com', 'x', first_name='Nora',
                                                       last_name='Account')
        from ..units import token
        self.client.post(reverse('hr:production_employee_create'), data(token(self.dept_a), user=str(account.pk)))
        person = Employee.objects.get(employee_number='E-100')
        self.assertEqual((person.user, person.first_name, person.last_name, person.full_name),
                         (account, '', '', 'Nora Account'))
        # the account is taken now: not offered again
        form = self.client.get(reverse('hr:production_employee_create')).context['form']
        self.assertNotIn(account, form.fields['user'].queryset)

    def test_the_form_asks_for_what_the_rules_need(self):
        self.client.force_login(self.hr)
        errors = self.client.post(reverse('hr:production_employee_create'), data(last_name='', department='')
                                  ).context['form'].errors
        self.assertEqual(set(errors), {'last_name', 'department'})
        errors = self.client.post(reverse('hr:production_employee_create'), data('production:not-an-id')).context['form'].errors
        self.assertIn('department', errors)
        from ..units import token
        errors = self.client.post(reverse('hr:production_employee_create'), data(token(self.dept_a), left_on='2026-01-01')
                                  ).context['form'].errors
        self.assertIn('left_on', errors)
        self.assertEqual(Employee.objects.count(), 3)

    def test_a_change_of_placement_needs_a_day_not_before_the_current_one(self):
        self.client.force_login(self.hr)
        from ..units import token
        base = data(token(self.dept_b), employee_number='E-1', last_name='Alfa', first_name='Ann', joined_on='2026-01-01',
                    title='Technician', version='1')
        errors = self.client.post(reverse('hr:production_employee_edit', args=[self.in_a.pk]), base).context['form'].errors
        self.assertIn('from_day', errors)
        errors = self.client.post(reverse('hr:production_employee_edit', args=[self.in_a.pk]), {**base, 'from_day': '2025-12-01'}
                                  ).context['form'].errors
        self.assertIn('from_day', errors)
        self.assertEqual(Posting.objects.filter(employee=self.in_a).count(), 1)

    def test_a_second_new_person_in_a_department_is_a_new_row_with_a_new_number(self):
        self.client.force_login(self.hr)
        from ..units import token
        errors = self.client.post(reverse('hr:production_employee_create'), data(token(self.dept_a), employee_number='E-1')
                                  ).context['form'].errors
        self.assertIn('employee_number', errors)


class EmployeeConstraintTests(PeopleTestCase):
    """The database refuses what the form would; raw rows, no form."""

    def refused(self, sql_or_callable):
        with self.assertRaises(IntegrityError), transaction.atomic():
            sql_or_callable()

    def test_the_number_is_unique_among_live_people_and_free_after_a_delete(self):
        self.refused(lambda: employee('E-1', 'Other'))
        self.in_a.soft_delete(self.hr)
        self.assertEqual(employee('E-1', 'Other').employee_number, 'E-1')

    def test_an_account_belongs_to_one_live_employee(self):
        account = get_user_model().objects.create_user('nora', 'nora@example.com', 'x')
        Employee.objects.create(employee_number='E-9', user=account, joined_on=TOP)
        self.refused(lambda: Employee.objects.create(employee_number='E-10', user=account, joined_on=TOP))

    def test_the_name_is_in_one_place(self):
        account = get_user_model().objects.create_user('nora', 'nora@example.com', 'x')
        self.refused(lambda: Employee.objects.create(employee_number='E-9', user=account, last_name='Both',
                                                     joined_on=TOP))
        self.refused(lambda: Employee.objects.create(employee_number='E-9', joined_on=TOP))     # no account, no name
        self.refused(lambda: Employee.objects.create(employee_number='E-9', first_name='Only', joined_on=TOP))

    def test_the_period_the_type_and_the_number_are_checked(self):
        self.refused(lambda: Employee.objects.create(
            employee_number='E-9', last_name='X', joined_on=date(2026, 5, 1), left_on=date(2026, 4, 30)))
        self.refused(lambda: employee('E-9', employment_type='boss'))
        self.refused(lambda: employee('E 9'))
        Employee.objects.create(employee_number='E-9', last_name='X', joined_on=date(2026, 5, 1),
                                left_on=date(2026, 5, 1))                 # a one-day employment is allowed

    def test_the_account_cannot_be_deleted_from_under_an_employee(self):
        account = get_user_model().objects.create_user('nora', 'nora@example.com', 'x')
        Employee.objects.create(employee_number='E-9', user=account, joined_on=TOP)
        from django.db.models import ProtectedError
        with self.assertRaises(ProtectedError):
            account.delete()


class PostingConstraintTests(PeopleTestCase):
    def test_exactly_one_department(self):
        person = employee('E-20', 'Delta')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Posting.objects.create(employee=person, valid_from=TOP)                      # none
        with self.assertRaises(IntegrityError), transaction.atomic():
            Posting.objects.create(employee=person, valid_from=TOP, production_department=self.dept_a,
                                   office_department=self.finance)                       # both

    def test_the_period_is_ordered(self):
        person = employee('E-20', 'Delta')
        with self.assertRaises(IntegrityError), transaction.atomic():
            place(person, self.dept_a, TOP, date(2025, 12, 31))
        place(person, self.dept_a, TOP, TOP)                             # one day

    def test_a_person_has_one_placement_on_any_day(self):
        person = employee('E-20', 'Delta')
        place(person, self.dept_a, date(2026, 1, 1), date(2026, 3, 31))
        with self.assertRaises(IntegrityError), transaction.atomic():
            place(person, self.dept_b, date(2026, 3, 31), None)          # overlaps on the 31st
        with self.assertRaises(IntegrityError), transaction.atomic():
            place(person, self.finance, date(2025, 6, 1), date(2026, 1, 1))
        place(person, self.dept_b, date(2026, 4, 1), None)               # adjacent days are fine
        with self.assertRaises(IntegrityError), transaction.atomic():
            place(person, self.finance, date(2027, 1, 1), None)          # an open one runs on for ever
        place(employee('E-21', 'Echo'), self.dept_b, date(2026, 3, 31), None)   # another person, the same days

    def test_a_deleted_placement_no_longer_blocks(self):
        person = employee('E-20', 'Delta')
        first = place(person, self.dept_a, date(2026, 1, 1), None)
        first.soft_delete(self.hr)
        place(person, self.dept_b, date(2026, 2, 1), None)

    def test_a_department_with_people_placed_in_it_is_not_deleted(self):
        plan = plan_delete(self.dept_a)
        self.assertFalse(plan.can_delete)
        self.assertTrue(any('placement' in blocker.lower() for blocker in plan.blockers), plan.blockers)
        plan = plan_delete(self.finance)
        self.assertFalse(plan.can_delete)
        empty = plan_delete(self.admin_dept.children.model.objects.create(name='Empty', code='EMP', site=self.site))
        self.assertTrue(empty.can_delete)

    def test_the_database_keeps_the_links_protected(self):
        with connection.cursor() as cursor, self.assertRaises(IntegrityError), transaction.atomic():
            cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')        # Django's foreign keys are checked at commit
            cursor.execute('DELETE FROM production_departments WHERE id = %s', [self.dept_a.pk])

    def test_every_column_is_covered(self):
        self.assertEqual(fields_of(Posting), {'employee', 'production_department', 'office_department', 'title',
                                              'valid_from', 'valid_until'})
