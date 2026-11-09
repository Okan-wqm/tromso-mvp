"""Who is on shift at a moment (hr.read.on_shift), for the alarms that go to the people on shift only: the accounts of
the people whose planned shift runs at that moment on their site's clock (last night's shift until it ends, else today's),
not on approved leave; read with the board's own rule of which shift is current."""
from datetime import time, timedelta

from django.db import connection
from django.test.utils import CaptureQueriesContext

from .. import read
from ..models import LeaveRequest, LeaveType, SchedulingSettings, Shift, ShiftAssignment
from .helpers import user
from .helpers_people import PeopleTestCase, employee, place
from .test_attendance import DAY, at


class OnShiftTests(PeopleTestCase):
    def setUp(self):
        super().setUp()
        self.early = Shift.objects.create(name='Early', code='EARLY', starts_at=time(6), ends_at=time(14))
        self.night = Shift.objects.create(name='Night', code='NIGHT', starts_at=time(22), ends_at=time(6))
        self.ola = user('ola')
        self.kari = user('kari')
        self.ola_person = employee('E-50', '', '', user=self.ola)          # the account names them
        self.kari_person = employee('E-51', '', '', user=self.kari)
        place(self.ola_person, self.dept_a)
        place(self.kari_person, self.dept_b)
        SchedulingSettings.get()

    def plan(self, person, shift, day=DAY):
        return ShiftAssignment.objects.create(employee=person, day=day, shift=shift)

    def test_the_people_whose_shift_runs_now(self):
        self.plan(self.ola_person, self.early)
        self.plan(self.kari_person, None)                              # planned off
        self.plan(self.in_a, self.early)                               # on shift, but no account: never notified
        self.assertEqual(read.on_shift(at(10)), {self.ola.pk})
        self.assertEqual(read.on_shift(at(5, 59)), set())
        self.assertEqual(read.on_shift(at(14)), set())

    def test_last_nights_shift_until_it_ends(self):
        self.plan(self.kari_person, self.night, DAY - timedelta(days=1))
        self.assertEqual(read.on_shift(at(3)), {self.kari.pk})
        self.assertEqual(read.on_shift(at(7)), set())

    def test_approved_leave_is_not_on_shift(self):
        self.plan(self.ola_person, self.early)
        LeaveRequest.objects.create(employee=self.ola_person, leave_type=LeaveType.objects.create(name='Annual', code='AN'),
                                    first_day=DAY, last_day=DAY, status='approved', decided_at=at(1))
        self.assertEqual(read.on_shift(at(10)), set())

    def test_the_queries_do_not_grow_with_the_people(self):
        def count(people):
            for n in range(people):
                person = employee(f'E-{6000 + n + people}', '', '', user=user(f'many{n}x{people}'))
                place(person, self.dept_a)
                self.plan(person, self.early)
            with CaptureQueriesContext(connection) as queries:
                read.on_shift(at(10))
            return len(queries)
        self.assertEqual(count(3), count(30))
