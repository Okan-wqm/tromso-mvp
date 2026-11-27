"""The one rule of a person's moment (hr.read.governing) and its SQL form (hr.read.governed), the one rule of who reaches a
stretch (hr.scope.reaches_stretch) and its SQL form (hr.scope.stretches): each pair agrees on every case of a matrix of
clocks, moves and moments, so a page that lists and a service that writes cannot answer one question two ways (the
architecture audit of 26.11.2026, M-6)."""
from datetime import date, datetime, time, timedelta, timezone as utc

from django.core.exceptions import PermissionDenied, ValidationError

from farm.models import ProductionDepartment, Site

from .. import read, rules, scope, services
from ..models import AttendanceRecord, Employee, Posting, Shift, ShiftAssignment
from .helpers import user
from .helpers_people import PeopleTestCase, employee, place

UTC = utc.utc
MOVE = date(2026, 3, 3)
MOMENTS = [datetime(2026, 3, 2, hour, minute, tzinfo=UTC) + timedelta(days=days)
           for days in (0, 1) for hour, minute in ((0, 0), (10, 30), (11, 30), (12, 0), (22, 59), (23, 30))]


class Clocks(PeopleTestCase):
    """The company is on Oslo's clock. A is on a site in Auckland, B on one in Los Angeles; Ann moves from A to B on 3
    March; Nomad is placed nowhere; Cy is in Finance (an office department on the UTC site)."""

    def setUp(self):
        super().setUp()
        auckland = Site.objects.create(name='Auckland', code='AK', timezone='Pacific/Auckland')
        angeles = Site.objects.create(name='Los Angeles', code='LA', timezone='America/Los_Angeles')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(site=auckland)
        ProductionDepartment.objects.filter(pk=self.dept_b.pk).update(site=angeles)
        Posting.objects.filter(employee=self.in_a).update(valid_until=MOVE - timedelta(days=1))
        place(self.in_a, self.dept_b, start=MOVE)
        self.nomad = employee('E-70', 'Nomad')
        self.people = [self.in_a, self.in_b, self.in_fin, self.nomad]


class GoverningTests(Clocks):
    def test_the_sql_form_agrees_with_the_rule_on_every_moment(self):
        for person in self.people:
            for moment in MOMENTS:
                AttendanceRecord.objects.create(employee=person, clock_in=moment, clock_out=moment + timedelta(minutes=1),
                                                via='self')
        for record in read.governed(AttendanceRecord.objects.select_related('employee')):
            rule = read.governing(record.employee, record.clock_in)
            with self.subTest(person=record.employee.last_name, moment=record.clock_in):
                self.assertEqual((record.zone_name, record.governing_day), (rule.zone.key, rule.day))

    def test_the_rule_reads_the_placement_of_the_companys_day(self):
        # 12:00 UTC on 2 March: 13:00 on the 2nd in Oslo, so A's placement, and 01:00 on the 3rd on A's clock
        rule = read.governing(self.in_a, datetime(2026, 3, 2, 12, tzinfo=UTC))
        self.assertEqual((rule.posting.production_department, rule.zone.key, rule.day),
                         (self.dept_a, 'Pacific/Auckland', date(2026, 3, 3)))
        # 23:30 UTC on 2 March is the 3rd in Oslo: B's placement, and still the 2nd on B's clock
        rule = read.governing(self.in_a, datetime(2026, 3, 2, 23, 30, tzinfo=UTC))
        self.assertEqual((rule.posting.production_department, rule.zone.key, rule.day),
                         (self.dept_b, 'America/Los_Angeles', date(2026, 3, 2)))
        nowhere = read.governing(self.nomad, datetime(2026, 3, 2, 23, 30, tzinfo=UTC))
        self.assertEqual((nowhere.posting, nowhere.zone.key, nowhere.day), (None, 'Europe/Oslo', date(2026, 3, 3)))

    def test_a_time_typed_is_read_on_the_clock_that_governs_it_and_shown_again_as_typed(self):
        for person in self.people:
            for moment in MOMENTS:
                typed = moment.astimezone(read.governing(person, moment).zone).replace(tzinfo=None)
                with self.subTest(person=person.last_name, typed=typed):
                    found = read.typed_moment(person, typed)
                    self.assertEqual(found.astimezone(read.governing(person, found).zone).replace(tzinfo=None), typed)


class StretchReachTests(Clocks):
    def test_the_sql_form_agrees_with_the_rule_for_every_lead(self):
        leads = [self.lead_a, self.lead_b, self.hr, user('nobody', 'view_attendancerecord', group='Nobody role')]
        Employee.objects.filter(pk=self.in_fin.pk).update(user=leads[-1], first_name='', last_name='')
        for person in self.people:
            for moment in MOMENTS:                      # closed stretches, and the last one still open
                AttendanceRecord.objects.create(employee=person, clock_in=moment, via='self', clock_out=None
                                                if moment == MOMENTS[-1] else moment + timedelta(minutes=1))
        records = list(AttendanceRecord.objects.select_related('employee__user'))
        for lead in leads:
            listed = set(scope.stretches(lead, read.governed(AttendanceRecord.objects.all())).values_list('pk', flat=True))
            for record in records:
                day = read.governing(record.employee, record.clock_in).company_day
                with self.subTest(lead=lead.username, person=record.employee.full_name, moment=record.clock_in):
                    self.assertEqual(record.pk in listed,
                                     scope.reaches_stretch(lead, record.employee, day, record.clock_out is None))


ENTER = ('view_employee', 'view_attendancerecord', 'add_attendancerecord', 'change_attendancerecord')


class OwnershipTests(Clocks):
    """Who owns a stretch is the lead of the placement that governs it: the placement of the company's day, the one whose
    site gives the clock (the review of wip/hr-one-path, M-1). The site's day stays for what is shown and for the
    employment rule; reach read on it could hand the stretch to a lead whose placement covers the moment on no clock."""

    def setUp(self):
        super().setUp()
        self.boss_a = user('bossa', *ENTER, group='Boss A role')
        self.boss_b = user('bossb', *ENTER, group='Boss B role')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=self.boss_a)
        ProductionDepartment.objects.filter(pk=self.dept_b.pk).update(manager=self.boss_b)

    def owners(self, moment):
        record = AttendanceRecord.objects.create(employee=self.in_a, clock_in=moment, via='self',
                                                 clock_out=moment + timedelta(minutes=1))
        return [lead.username for lead in (self.boss_a, self.boss_b)
                if scope.stretches(lead, read.governed(AttendanceRecord.objects.filter(pk=record.pk))).exists()]

    def test_a_stretch_of_the_companys_last_day_in_a_is_as_though_auckland_reads_the_next_day(self):
        # 12:00 UTC on 2 March: 13:00 on the 2nd in Oslo (A governs), 01:00 on the 3rd in Auckland, 04:00 on the 2nd in LA
        moment = datetime(2026, 3, 2, 12, tzinfo=UTC)
        self.assertEqual(self.owners(moment), ['bossa'])
        with self.assertRaisesMessage(ValidationError, 'You do not see this person on this day.'):   # B's today
            services.enter_presence(self.boss_b, self.in_a, moment + timedelta(hours=1), None, 'Phone was dead')
        entered = services.enter_presence(self.boss_a, self.in_a, moment + timedelta(hours=1), None, 'Phone was dead')
        self.assertEqual(read.governing(self.in_a, entered.clock_in).day, date(2026, 3, 3))    # shown on A's clock

    def test_a_stretch_of_the_companys_first_day_in_b_is_bs_though_los_angeles_reads_the_day_before(self):
        # 23:30 UTC on 2 March: 00:30 on the 3rd in Oslo (B governs), 15:30 on the 2nd in LA, 12:30 on the 3rd in Auckland
        moment = datetime(2026, 3, 2, 23, 30, tzinfo=UTC)
        self.assertEqual(self.owners(moment), ['bossb'])
        with self.assertRaises(PermissionDenied):          # not A's person today: not A's to hear about
            services.enter_presence(self.boss_a, self.in_a, moment + timedelta(hours=1), None, 'Phone was dead')
        services.enter_presence(self.boss_b, self.in_a, moment + timedelta(hours=1), None, 'Phone was dead')


class PlannedDayClockTests(Clocks):
    """A planned day is read on the clock of the site the person is placed on THAT day (the review, L-3): the rules of a
    save (hr.services.evaluate) and the week's grid (hr.read.week) read one answer. Ann works late on Monday 2 March on
    A's clock (Auckland: 01:00 to 09:00 UTC) and early on the 3rd on B's (Los Angeles: 14:00 to 22:00 UTC): 29 hours of
    rest. Read on one clock for both days it would be 8 hours, a rest too short."""

    def setUp(self):
        super().setUp()
        self.late = Shift.objects.create(name='Late', code='LATE', starts_at=time(14), ends_at=time(22))
        self.early = Shift.objects.create(name='Early', code='EARLY', starts_at=time(6), ends_at=time(14))
        ShiftAssignment.objects.create(employee=self.in_a, day=date(2026, 3, 2), shift=self.late)

    def test_the_save_reads_each_day_on_its_own_clock(self):
        found = services.evaluate(self.in_a, {MOVE: self.early})
        self.assertEqual([item.code for item in found if item.code == rules.REST_SHORT], [])

    def test_the_week_reads_each_day_on_its_own_clock(self):
        ShiftAssignment.objects.create(employee=self.in_a, day=MOVE, shift=self.early)
        row = next(row for row in read.week(self.hr, date(2026, 3, 2)).rows if row.employee == self.in_a)
        self.assertEqual([item.code for cell in row.cells for item in cell.findings], [])
        self.assertEqual(row.planned_minutes, 2 * 8 * 60)
