"""The second review of the branch (F:/dev/balik-notes/hr-one-path/REVIEW-2.md, N-1 and N-3 to N-8), each as a test that
fails before its fix: behaviour, not the spelling of the code."""
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone as utc
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.contrib import admin
from django.contrib.messages import get_messages
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from core.models import AuditLog, PlatformSettings
from core.testing import FrozenClock
from farm.models import ProductionDepartment, Site

from .. import leave, read, services
from ..models import AttendanceRecord, Employee, Holiday, LeaveType, Posting, Shift, ShiftAssignment
from .helpers import user
from .helpers_people import PeopleTestCase, employee, place
from .test_leave import LeaveTestCase
from .test_one_path import EVERY_VERB, PlanPerDayTests

UTC = utc.utc
DECLARED = (AttendanceRecord, Employee, Posting, ShiftAssignment, services.LeaveRequest)


class RestoreTests(PeopleTestCase):
    def test_the_admin_offers_no_restore_of_a_record_its_service_writes(self):
        """N-1: at the layer that offers it; the departments keep theirs."""
        from ..models import OfficeDepartment
        for model in DECLARED:
            with self.subTest(model=model.__name__):
                self.assertNotIn('restore', admin.site._registry[model].actions)
        self.assertIn('restore', admin.site._registry[OfficeDepartment].actions)

    def test_the_data_map_says_why_and_not_restored_in_the_admin(self):
        import json

        from core import datamap
        tables = json.loads(datamap.build()[2])['tables']
        for model in DECLARED:
            table = next(table for table in tables if table['model'] == model._meta.object_name and table['app'] == 'hr')
            with self.subTest(model=model.__name__):
                self.assertNotEqual(table['restore']['status'], 'admin')
                self.assertIn('entered again', table['restore']['why'])


class GoverningReadsTests(PeopleTestCase):
    def test_the_attendance_reads_compute_only_what_they_use(self):
        """N-3: the list shows `zone_name` and owns by `company_day`; nothing else is computed per row."""
        annotated = set(read.governed(AttendanceRecord.objects.all()).query.annotations)
        self.assertEqual(annotated, {'company_day', 'zone_name'})

    def test_which_placement_covers_a_day_is_asked_of_one_helper(self):
        """N-4: the muster's sites, the crew's department and the week's clock come from hr.placed."""
        self.assertFalse(hasattr(read, 'sites_of'))
        from .. import placed
        with mock.patch.object(placed, 'placed_on', wraps=placed.placed_on) as asked:
            read.muster(datetime(2026, 3, 2, 10, tzinfo=UTC), 16)
            read.week(self.hr, date(2026, 3, 2))
        self.assertTrue(asked.called)


class BatchPlanBudgetTests(PlanPerDayTests):
    def cells(self, people, days=5):
        return [(person, date(2026, 3, 9) + timedelta(days=n)) for person in people for n in range(days)]

    def test_the_reach_is_asked_once_for_the_whole_batch(self):
        """N-5: the queries of a paint do not grow with its cells."""
        def count(many):
            people = [employee(f'E-{700 + many + n}', f'Many{n}') for n in range(many)]
            for person in people:
                place(person, self.dept_a)
            with CaptureQueriesContext(connection) as seen:
                response = self.paint(*self.cells(people), shift='off')
            self.assertEqual(response.status_code, 302)
            ShiftAssignment.objects.all().delete()
            return len([query for query in seen.captured_queries if 'shift_assignments' not in query['sql']
                        and 'audit_log' not in query['sql'] and 'INSERT' not in query['sql']])
        self.assertEqual(count(2), count(12))

    def test_more_cells_than_the_platform_allows_are_refused_with_the_reason(self):
        PlatformSettings.objects.update(plan_batch_cells=3)
        response = self.paint(*self.cells([self.in_a], 4))
        self.assertEqual(response.status_code, 302)
        self.assertIn('At most 3 days can be planned at once: select fewer and repeat.',
                      [str(message) for message in get_messages(response.wsgi_request)])
        self.assertEqual(ShiftAssignment.objects.count(), 0)


class LockStrengthTests(PeopleTestCase):
    """N-6: what the services lock, read from the statements they send: a person's row is never locked stronger than
    FOR NO KEY UPDATE (a record being added for them holds a key-share lock on it)."""

    def locks_of_people(self, call):
        with CaptureQueriesContext(connection) as seen:
            call()
        return {query['sql'].split(' FOR ', 1)[1] for query in seen.captured_queries
                if ' FOR ' in query['sql'] and ' FROM "employees"' in query['sql']}

    def test_every_service_locks_a_person_for_no_key_update(self):
        shift = Shift.objects.create(name='Early', code='EARLY', starts_at=time(6), ends_at=time(14))
        worker = user('ann', 'view_attendancerecord', group='Worker role')
        Employee.objects.filter(pk=self.in_b.pk).update(user=worker, first_name='', last_name='')
        self.in_b.refresh_from_db()
        calls = {
            'change_employee': lambda: services.change_employee(self.hr, self.in_a, {'employee_number': 'E-1x'}),
            'move': lambda: services.move(self.hr, self.in_a, self.dept_b, 'Feeder', date(2026, 6, 1)),
            'leave_company': lambda: services.leave_company(self.hr, self.in_fin, date(2026, 9, 30)),
            'plan_shifts': lambda: services.plan_shifts(
                user('allplan', *EVERY_VERB, 'all_employee', group='All plan'), [(self.in_a, date(2026, 3, 2))], shift),
            'clock_in': lambda: services.clock_in(worker),
        }
        for name, call in calls.items():
            with self.subTest(service=name):
                self.assertEqual(self.locks_of_people(call), {'NO KEY UPDATE'})


class HooksCallAWriterTests(PeopleTestCase):
    """N-6: each service tab's hook, run, calls one of hr.services' writers (core/tests_service_rights.py knows them)."""

    def test_each_hook_reaches_a_writer(self):
        from importlib import import_module

        from django.conf import settings

        from core.crud import Resource
        from core.tests_service_rights import NOT_A_WRITER, writers
        import_module(settings.ROOT_URLCONF)
        named = [dotted.rsplit('.', 1)[1] for dotted, _function, _parameters in writers()
                 if dotted.startswith('hr.services.') and dotted not in NOT_A_WRITER]
        form = SimpleNamespace(cleaned_data=defaultdict(mock.MagicMock), fields={}, placement=None,
                               values=lambda: {})
        record = mock.MagicMock()
        for tab in (tab for tab in Resource.registry if tab.service_writes):
            for action, hook in (('add', 'create_record'), ('change', 'change_record'), ('delete', 'delete_record')):
                if not tab.allows(action):
                    continue
                with self.subTest(tab=tab.__name__, hook=hook), mock.patch.multiple(
                        services, **{name: mock.MagicMock(return_value=(mock.MagicMock(), [])) for name in named}):
                    arguments = (form,) if hook == 'create_record' else (form, record) if hook == 'change_record' \
                        else (record,)
                    getattr(tab, hook)(mock.MagicMock(), *arguments)
                    self.assertTrue(any(getattr(services, name).called for name in named))


class ClearConfirmedTests(PeopleTestCase):
    """N-7: the dialog's Delete clears the plan the person confirmed; one replanned meanwhile stays."""

    def setUp(self):
        super().setUp()
        self.planner = user('planner', *EVERY_VERB, group='Planner role')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=self.planner)
        self.early = Shift.objects.create(name='Early', code='EARLY', starts_at=time(6), ends_at=time(14))
        self.late = Shift.objects.create(name='Late', code='LATE', starts_at=time(14), ends_at=time(22))

    def test_a_plan_changed_after_its_delete_was_confirmed_is_not_cleared(self):
        from ..resources.roster import ShiftAssignmentResource
        row = ShiftAssignment.objects.create(employee=self.in_a, day=date(2026, 3, 2), shift=self.early)
        delete = ShiftAssignmentResource.delete_record.__func__

        def raced(cls, request, record):
            ShiftAssignment.objects.filter(pk=row.pk).update(shift=self.late, version=2)      # another lead's change
            return delete(cls, request, record)
        self.client.force_login(self.planner)
        with mock.patch.object(ShiftAssignmentResource, 'delete_record', classmethod(raced)):
            self.client.post(reverse('hr:production_shiftassignment_delete', args=[row.pk]))
        row.refresh_from_db()
        self.assertEqual((row.is_deleted, row.shift), (False, self.late))
        self.assertFalse(AuditLog.objects.filter(entity_id=str(row.pk), action='delete').exists())


class LeaveAcrossAMoveTests(FrozenClock, LeaveTestCase):
    """N-8: Ann moves on Tuesday 10 March from A (Bergen) to a department on another site whose holiday it is that day.
    A request for Monday and Tuesday is charged one day: each day by the holidays of its own site."""
    NOW = datetime(2026, 3, 1, 12, tzinfo=UTC)

    def setUp(self):
        super().setUp()
        other = Site.objects.create(name='Other', code='OT', timezone='UTC')
        far = ProductionDepartment.objects.create(site=other, name='Far', code='FAR', manager=self.lead)
        Posting.objects.filter(employee=self.in_a).update(valid_until=date(2026, 3, 9))
        place(self.in_a, far, start=date(2026, 3, 10))
        Holiday.objects.create(day=date(2026, 3, 10), name='Theirs', site=other)
        self.one = LeaveType.objects.create(name='One day', code='ONE', annual_days=Decimal('1'))

    def test_each_day_is_charged_by_its_own_sites_holidays(self):
        placed = read.placements([self.in_a.pk], date(2026, 3, 9), date(2026, 3, 10))[self.in_a.pk]
        self.assertEqual(leave.leave_days(date(2026, 3, 9), date(2026, 3, 10), placed), Decimal(1))
        request = services.file_leave(self.ann_user, self.in_a, self.one, date(2026, 3, 9), date(2026, 3, 10))
        self.assertEqual(request.status, 'pending')                       # one day of the one allowed
