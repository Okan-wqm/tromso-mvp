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
from farm.models import ProductionDepartment, Site

from .. import leave, read, services
from ..models import AttendanceRecord, Employee, Holiday, LeaveType, Posting, Shift, ShiftAssignment
from ..placed import placements
from .helpers import user
from .helpers_people import PeopleTestCase, employee, place
from .test_leave import LeaveTestCase
from .test_one_path import EVERY_VERB, PlanPerDayTests
from core.testing import delete_confirmed

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
        """N-4: the muster's sites, the crew's department, the week's clock and leave come from hr.placed's helpers."""
        self.assertFalse(hasattr(read, 'sites_of'))
        self.assertFalse(hasattr(leave, 'holidays_for'))
        import inspect
        for module in (read, leave):                    # they use hr.placed's helpers and define none of their own
            own = {name for name, function in inspect.getmembers(module, inspect.isfunction)
                   if function.__module__ == module.__name__}
            with self.subTest(module=module.__name__):
                self.assertFalse(own & {'placed_on', 'placements', 'site_of_day', 'site_of_posting'})
        place(employee('E-71', 'Muster'), self.dept_a)
        AttendanceRecord.objects.create(employee=self.in_a, clock_in=datetime(2026, 3, 2, 8, tzinfo=UTC), via='self')
        AttendanceRecord.objects.create(employee=self.in_fin, clock_in=datetime(2026, 3, 2, 8, tzinfo=UTC), via='self')
        self.assertEqual(read.muster(datetime(2026, 3, 2, 10, tzinfo=UTC), 16)[:2], (2, ()))      # one site: Bergen


class BatchPlanBudgetTests(PlanPerDayTests):
    def cells(self, people, days=5):
        return [(person, date(2026, 3, 9) + timedelta(days=n)) for person in people for n in range(days)]

    def test_the_reach_is_asked_once_for_the_whole_batch(self):
        """N-5: the reach of a paint is one question for all its cells, whose queries do not grow with them (the rules
        of the plan run per person, as they must)."""
        from .. import scope

        def reach_queries(many):
            people = [employee(f'E-{700 + many + n}', f'Many{n}') for n in range(many)]
            for person in people:
                place(person, self.dept_a)
            with mock.patch.object(scope, 'can_reach', side_effect=AssertionError('asked per cell')), \
                    mock.patch.object(scope, 'cells_reached', wraps=scope.cells_reached) as asked:
                response = self.paint(*self.cells(people), shift='off')
            self.assertEqual((response.status_code, asked.call_count), (302, 1))
            cells = {(person.pk, day) for person, day in self.cells(people)}
            scope.cells_reached(self.planner, cells)            # the person's rights read once (Django keeps them)
            with CaptureQueriesContext(connection) as seen:
                scope.cells_reached(self.planner, cells)
            return len(seen.captured_queries)
        self.assertEqual(reach_queries(2), reach_queries(12))

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
            response = delete_confirmed(self.client, reverse('hr:production_shiftassignment_delete', args=[row.pk]))
        row.refresh_from_db()           # the other lead's change went with the refused delete (one transaction)
        self.assertFalse(row.is_deleted)
        self.assertFalse(AuditLog.objects.filter(entity_id=str(row.pk), action='delete').exists())
        self.assertIn('This plan was changed while you were looking at it: check it and delete it again.',
                      [str(message) for message in get_messages(response.wsgi_request)])


class LeaveAcrossAMoveTests(LeaveTestCase):
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
        placed = placements([self.in_a.pk], date(2026, 3, 9), date(2026, 3, 10))[self.in_a.pk]
        self.assertEqual(leave.leave_days(date(2026, 3, 9), date(2026, 3, 10), placed), Decimal(1))
        request = services.file_leave(self.ann_user, self.in_a, self.one, date(2026, 3, 9), date(2026, 3, 10))
        self.assertEqual(request.status, 'pending')                       # one day of the one allowed


# ---- the third review (F:/dev/balik-notes/hr-one-path/REVIEW-3.md) ------------------------------------------------
class ConfirmedPlanVersionTests(PeopleTestCase):
    """F-3: the dialog's Delete clears the plan at the version the person confirmed: one changed between the
    confirmation and the click is left, with the reason."""

    def test_a_plan_changed_between_the_confirmation_and_the_click_is_not_cleared(self):
        planner = user('planner', *EVERY_VERB, group='Planner role')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=planner)
        early = Shift.objects.create(name='Early', code='EARLY', starts_at=time(6), ends_at=time(14))
        late = Shift.objects.create(name='Late', code='LATE', starts_at=time(14), ends_at=time(22))
        row = ShiftAssignment.objects.create(employee=self.in_a, day=date(2026, 3, 2), shift=early)
        self.client.force_login(planner)
        url = reverse('hr:production_shiftassignment_delete', args=[row.pk])
        self.assertContains(self.client.get(url), 'name="version" value="1"')
        ShiftAssignment.objects.filter(pk=row.pk).update(shift=late, version=2)          # another lead, in between
        response = self.client.post(url, {'version': '1'})
        row.refresh_from_db()
        self.assertEqual((row.is_deleted, row.shift), (False, late))
        self.assertTrue(any('This plan was changed while you were looking at it' in str(message)
                            for message in get_messages(response.wsgi_request)))


class CellsReachedMatrixTests(PeopleTestCase):
    """F-9: the reach of many cells (scope.cells_reached, intervals in Python) is the reach of each (scope.can_reach,
    SQL), for every kind of viewer and person, on every day around their moves."""

    def test_the_two_forms_agree(self):
        from .. import scope
        from ..models import OfficeDepartment
        sub = OfficeDepartment.objects.create(site=self.site, name='Planning', code='PLN', parent=self.finance)
        boss = user('officeboss', 'view_employee', group='Office boss role')
        OfficeDepartment.objects.filter(pk=self.admin_dept.pk).update(manager=boss)
        moved, left, gone = employee('E-81', 'Moved'), employee('E-82', 'Left'), employee('E-83', 'Gone')
        place(moved, self.dept_a, date(2026, 1, 1), date(2026, 3, 2))
        place(moved, sub, date(2026, 3, 3))
        place(left, self.dept_b, date(2026, 1, 1), date(2026, 3, 3))
        Employee.objects.filter(pk=left.pk).update(left_on=date(2026, 3, 3))
        place(gone, self.dept_a)
        gone.soft_delete(self.hr)
        closed = ProductionDepartment.objects.create(site=self.site, name='Closed', code='CLO', manager=self.lead_a)
        shut = employee('E-84', 'Shut')
        place(shut, closed)
        closed.soft_delete(self.hr)
        own = user('owner', 'view_employee', group='Own role')
        Employee.objects.filter(pk=self.in_b.pk).update(user=own, first_name='', last_name='')
        viewers = [self.lead_a, self.lead_b, boss, own, self.hr,
                   user('allprod', 'view_employee', 'all_production_employee', group='All production role')]
        people = list(Employee.all_objects.all())
        days = [date(2026, 3, 1) + timedelta(days=n) for n in range(4)]
        for viewer in viewers:
            cells = {(person.pk, day) for person in people for day in days}
            expected = {(person.pk, day) for person in people for day in days
                        if scope.can_reach(viewer, person, day)}
            with self.subTest(viewer=viewer.username):
                self.assertEqual(scope.cells_reached(viewer, cells), expected)


class OneRefusalOfADayTests(PeopleTestCase):
    """R4-6 (review 4): the dialog, the batch plan, leave and attendance refuse a day by one rule (services.reached):
    the user's person today, on a day that is another lead's, is told the sentence; a person who is not theirs at all
    is NotReached (a 403, the batch page's 404). Mo is in B through March and the lead's (A) from April."""

    def test_every_writer_refuses_a_day_the_same_way(self):
        from django.core.exceptions import ValidationError

        from .. import services
        lead = user('boss', *EVERY_VERB, group='Lead role')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=lead)
        mo = employee('E-90', 'Mo')
        place(mo, self.dept_b, date(2026, 1, 1), date(2026, 3, 31))
        place(mo, self.dept_a, date(2026, 4, 1))
        early = Shift.objects.create(name='Early', code='EARLY', starts_at=time(6), ends_at=time(14))
        kind = LeaveType.objects.create(name='Annual', code='AN')
        day = date(2026, 3, 10)
        writes = {
            'plan_day': lambda person: services.plan_day(lead, person, day, early, ''),
            'plan_shifts': lambda person: services.plan_shifts(lead, [(person, day)], early),
            'file_leave': lambda person: services.file_leave(lead, person, kind, day, day),
            'enter_presence': lambda person: services.enter_presence(
                lead, person, datetime(2026, 3, 10, 8, tzinfo=UTC), datetime(2026, 3, 10, 9, tzinfo=UTC), 'Phone'),
        }
        for name, write in writes.items():
            with self.subTest(write=name):
                with self.assertRaises(ValidationError):
                    write(mo)                       # the lead's person today, B's on that day
                with self.assertRaises(services.NotReached):
                    write(self.in_b)                # never the lead's
        self.assertEqual((ShiftAssignment.objects.count(), AttendanceRecord.objects.count()), (0, 0))


class VoidConfirmedTests(PeopleTestCase):
    """R4-3 (review 4): Attendance's void is of the stretch as confirmed: one corrected between crud's read and the
    service's lock is not voided, with the reason (services.as_confirmed, as the plan's delete)."""

    def test_a_stretch_corrected_after_its_void_was_confirmed_is_not_voided(self):
        from ..resources.attendance import AttendanceRecordResource
        lead = user('boss', *EVERY_VERB, group='Lead role')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=lead)
        record = AttendanceRecord.objects.create(employee=self.in_a, clock_in=datetime(2026, 3, 2, 6, tzinfo=UTC),
                                                 clock_out=datetime(2026, 3, 2, 14, tzinfo=UTC), via='entered', note='x')
        delete = AttendanceRecordResource.delete_record.__func__

        def raced(cls, request, confirmed):
            AttendanceRecord.objects.filter(pk=record.pk).update(note='corrected', version=2)   # another lead's
            return delete(cls, request, confirmed)
        self.client.force_login(lead)
        with mock.patch.object(AttendanceRecordResource, 'delete_record', classmethod(raced)):
            response = delete_confirmed(self.client, reverse('hr:production_attendancerecord_delete', args=[record.pk]))
        record.refresh_from_db()
        self.assertFalse(record.is_deleted)
        self.assertIn('This attendance record was changed while you were looking at it: check it and delete it again.',
                      [str(message) for message in get_messages(response.wsgi_request)])
