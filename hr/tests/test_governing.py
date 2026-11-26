"""The one rule of a person's moment (hr.read.governing) and its SQL form (hr.read.governed), the one rule of who reaches a
stretch (hr.scope.reaches_stretch) and its SQL form (hr.scope.stretches): each pair agrees on every case of a matrix of
clocks, moves and moments, so a page that lists and a service that writes cannot answer one question two ways (the
architecture audit of 26.11.2026, M-6)."""
from datetime import date, datetime, timedelta, timezone as utc

from farm.models import ProductionDepartment, Site

from .. import read, scope
from ..models import AttendanceRecord, Employee, Posting
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
                day = read.governing(record.employee, record.clock_in).day
                with self.subTest(lead=lead.username, person=record.employee.full_name, moment=record.clock_in):
                    self.assertEqual(record.pk in listed,
                                     scope.reaches_stretch(lead, record.employee, day, record.clock_out is None))
