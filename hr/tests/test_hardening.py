"""The last layer: the checks the database cannot hold, the demonstration seed and the roles it makes, the migrations back and
forth, and the query budgets of the pages that list people."""
from datetime import date, datetime, timezone as utc
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from farm.models import ProductionDepartment, Site

from .. import checks, read
from ..models import (AttendanceRecord, Employee, LeaveRequest, LeaveType, OfficeDepartment, Posting, SchedulingSettings,
                      Shift, ShiftAssignment)
from .helpers import user
from .helpers_people import PeopleTestCase, TOP, employee, place


class CheckHrTests(PeopleTestCase):
    def codes(self):
        return sorted(code for code, _text in checks.problems(date(2026, 6, 1)))

    def test_a_consistent_company_has_no_problem_and_the_command_says_so(self):
        self.assertEqual(self.codes(), [])
        out = StringIO()
        call_command('check_hr', stdout=out)
        self.assertIn('agree', out.getvalue())

    def test_every_disagreement_is_found_and_the_command_fails(self):
        # a last day with a placement that runs past it, and leave after it
        gone = employee('E-50', 'Gone')
        place(gone, self.dept_a, TOP)
        Employee.objects.filter(pk=gone.pk).update(left_on=date(2026, 3, 1))
        kind = LeaveType.objects.create(name='Annual', code='AN')
        LeaveRequest.objects.create(employee=gone, leave_type=kind, first_day=date(2026, 3, 10), last_day=date(2026, 3, 12))
        # a placement before the person joined, a person placed nowhere, an office department without a site
        early = employee('E-51', 'Early', on=date(2026, 5, 1))
        place(early, self.dept_a, date(2026, 4, 1))
        employee('E-52', 'Nowhere')
        loose = OfficeDepartment.objects.create(name='Loose', code='LOO')
        place(employee('E-53', 'Loosely'), loose)
        OfficeDepartment.objects.filter(pk=self.finance.pk).update(status='inactive')
        self.assertEqual(self.codes(), ['inactive_department_with_people', 'leave_after_last_day', 'not_placed',
                                        'office_department_without_site', 'placement_after_last_day',
                                        'placement_before_joined'])
        with self.assertRaises(CommandError):
            call_command('check_hr', stdout=StringIO())

    def test_a_nothing_is_repaired_by_the_check(self):
        gone = employee('E-50', 'Gone')
        posting = place(gone, self.dept_a, TOP)
        Employee.objects.filter(pk=gone.pk).update(left_on=date(2026, 3, 1))
        checks.problems(date(2026, 6, 1))
        posting.refresh_from_db()
        self.assertIsNone(posting.valid_until)


class SeedTests(TestCase):
    def seed(self):
        call_command('seed_hr_demo', stdout=StringIO())

    def counts(self):
        return {model.__name__: model.all_objects.count() for model in (
            Employee, Posting, OfficeDepartment, ProductionDepartment, Shift, ShiftAssignment, LeaveType, LeaveRequest,
            AttendanceRecord, Site)} | {'users': get_user_model().objects.count()}

    def test_it_refuses_unless_debug_is_on(self):
        with override_settings(DEBUG=False):
            with self.assertRaises(CommandError):
                self.seed()
        self.assertEqual(Employee.objects.count(), 0)

    @override_settings(DEBUG=True)
    def test_it_is_idempotent_and_makes_a_company_that_reads_through_every_page(self):
        self.seed()
        first = self.counts()
        self.seed()
        self.assertEqual(self.counts(), first)
        self.assertGreater(first['Employee'], 5)
        self.assertEqual(checks.problems(), [])                          # the demonstration is consistent with its own checks
        self.assertEqual(SchedulingSettings.objects.count(), 1)

    @override_settings(DEBUG=True)
    def test_the_four_roles_see_what_the_walk_through_expects(self):
        self.seed()
        client = self.client

        def names(username, route, key='objects'):
            client.force_login(get_user_model().objects.get(username=username))
            response = client.get(reverse(route))
            self.assertEqual(response.status_code, 200, (username, route))
            return response

        hatchery = names('demo_lead_hatchery', 'hr:production_employee_list').context['objects']
        self.assertEqual({e.last_name or e.user.last_name for e in hatchery},
                         {'Hatchery', 'Staff', 'Brekke', 'Moe'})                 # their own team, not the nursery or finance
        nursery = names('demo_lead_nursery', 'hr:production_employee_list').context['objects']
        self.assertEqual({e.last_name or e.user.last_name for e in nursery}, {'Nursery', 'Nilsen', 'Opsahl'})
        # Everyone: the office people in Company and the production people in Production, each person in one of them
        everyone = list(names('demo_hr', 'hr:employee_list').context['objects']) + list(
            names('demo_hr', 'hr:production_employee_list').context['objects'])
        self.assertEqual(len(everyone), Employee.objects.count())
        self.assertEqual(len(names('demo_auditor', 'hr:employee_list').context['objects'])
                         + len(names('demo_auditor', 'hr:production_employee_list').context['objects']), Employee.objects.count())
        # the staff member has no Team list, reads Today, the schedule and their own leave
        client.force_login(get_user_model().objects.get(username='demo_staff'))
        self.assertEqual(client.get(reverse('hr:production_employee_list')).status_code, 403)
        for route in ('hr:production_today', 'hr:production_shiftassignment_list', 'hr:production_leaverequest_list'):
            self.assertEqual(client.get(reverse(route)).status_code, 200, route)
        self.assertEqual({r.employee.user.username for r in client.get(reverse('hr:production_shiftassignment_list')).context['week'].rows},
                         {'demo_staff'})
        # a lead cannot open the other team's person by address, or the HR settings
        other = Employee.objects.get(employee_number='D-06')
        client.force_login(get_user_model().objects.get(username='demo_lead_hatchery'))
        self.assertEqual(client.get(reverse('hr:production_employee_detail', args=[other.pk])).status_code, 404)
        self.assertEqual(client.get(reverse('hr:schedulingsettings_list')).status_code, 403)
        self.assertEqual(client.get(reverse('core:database')).status_code, 403)

    @override_settings(DEBUG=True)
    def test_no_role_it_makes_can_see_pay_because_there_is_none_to_see(self):
        self.seed()
        from django.contrib.auth.models import Permission
        offered = set(Permission.objects.filter(group__name__startswith='Demo').values_list('codename', flat=True))
        from .test_boundary import FORBIDDEN
        for codename in offered:
            self.assertIsNone(FORBIDDEN.search(codename), codename)
        lead = Permission.objects.filter(group__name='Demo lead').values_list('codename', flat=True)
        self.assertNotIn('all_employee', lead)
        self.assertNotIn('change_schedulingsettings', lead)


class QueryBudgetTests(PeopleTestCase):
    """The pages that list people run the same number of queries for a few and for many."""

    made = 0

    def measure(self, call, people):
        for _n in range(people):
            self.made += 1
            place(employee(f'E-{9000 + self.made}', f'Many{self.made}'), self.dept_a)
        with CaptureQueriesContext(connection) as queries:
            call()
        return len(queries)

    def test_the_team_list_the_departments_and_the_week_do_not_grow_with_the_people(self):
        self.client.force_login(self.hr)
        for route in ('hr:employee_list', 'hr:officedepartment_list'):
            self.client.get(reverse(route))                                  # warm the permission cache
            small = self.measure(lambda: self.client.get(reverse(route)), 3)
            large = self.measure(lambda: self.client.get(reverse(route)), 30)
            self.assertEqual(small, large, route)


class MigrationTests(TransactionTestCase):
    """The HR migrations go back and forth: the tables, the constraints, the triggers and the one seeded row."""

    serialized_rollback = True

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)

    def tables(self):
        return set(connection.introspection.table_names())

    def functions(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT proname FROM pg_proc WHERE proname IN ('office_departments_no_cycle', "
                           "'leave_requests_no_self_decision')")
            return {row[0] for row in cursor.fetchall()}

    def constraints(self, table):
        with connection.cursor() as cursor:
            cursor.execute('SELECT conname FROM pg_constraint WHERE conrelid = %s::regclass', [table])
            return {row[0] for row in cursor.fetchall()}

    def setUp(self):
        self.addCleanup(self.restore)

    def restore(self):
        """Forward to the latest state, and the one row the migration seeds (a database that is kept between runs does not
        bring the rows of migrations back after the flush that follows a transaction test)."""
        self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())
        SchedulingSettings.get()

    def test_back_to_nothing_and_forward_again_with_the_one_seeded_row(self):
        self.migrate([('hr', None)])
        self.assertFalse({'office_departments', 'employees', 'postings', 'shifts', 'holidays', 'scheduling_settings',
                          'shift_assignments', 'leave_types', 'leave_requests', 'attendance_records'} & self.tables())
        self.assertEqual(self.functions(), set())
        self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())
        self.assertTrue({'office_departments', 'employees', 'postings', 'shifts', 'holidays', 'scheduling_settings',
                         'shift_assignments', 'leave_types', 'leave_requests', 'attendance_records'} <= self.tables())
        self.assertEqual(self.functions(), {'office_departments_no_cycle', 'leave_requests_no_self_decision'})
        self.assertEqual(SchedulingSettings.objects.count(), 1)               # the seed made it once
        self.assertIn('chk_shifts_break_shorter', self.constraints('shifts'))
        for name in ('excl_postings_employee_period', 'chk_postings_one_department'):
            self.assertIn(name, self.constraints('postings'))
        self.assertIn('excl_attendance_employee_span', self.constraints('attendance_records'))
        self.assertIn('excl_leave_requests_employee_days', self.constraints('leave_requests'))

    def test_the_seed_does_not_make_a_second_row_when_run_again(self):
        from django.apps import apps
        import importlib
        module = importlib.import_module('hr.migrations.0003_scheduling')
        module.make_the_row(apps, None)
        module.make_the_row(apps, None)
        self.assertEqual(SchedulingSettings.objects.count(), 1)

    def test_hr_does_not_depend_on_the_farm_beyond_its_production_departments(self):
        loader = MigrationExecutor(connection).loader
        for key, migration in loader.graph.nodes.items():
            if key[0] != 'hr':
                continue
            farm = {dependency for dependency in migration.dependencies if dependency[0] == 'farm'}
            self.assertLessEqual(farm, {('farm', '0004_production_departments')}, key)

    def test_the_farm_can_move_back_and_forward_under_the_hr_tables(self):
        """HR depends on farm 0004 only, so the farm's later migrations (reports, withdrawals, purging) neither need HR nor
        disturb it: with HR rows in place the farm goes back to 0022 and forward again and they are untouched."""
        site = Site.objects.create(name='Bergen', code='BG')
        hall = ProductionDepartment.objects.create(site=site, name='Hall A', code='HA')
        person = Employee.objects.create(employee_number='E-1', last_name='Alfa', joined_on=TOP)
        Posting.objects.create(employee=person, production_department=hall, valid_from=TOP)
        self.migrate([('farm', '0022_purging_degree_days')])
        self.assertEqual((Employee.objects.count(), Posting.objects.count()), (1, 1))
        self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())
        self.assertEqual((Employee.objects.count(), Posting.objects.count()), (1, 1))
