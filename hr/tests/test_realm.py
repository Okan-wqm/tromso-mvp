"""The realm (hr.scope): production people are those placed, on the day asked, in a live production department; everyone
else is the office's (an unplaced person never falls out of both). The realm only narrows the existing reach; without one
every rule is as before. Plus the crew a production worker shares a department with, and the two menu courtesies."""
from datetime import date

from django.contrib.auth import get_user_model

from core.models import AuditLog
from farm.models import ProductionDepartment

from .. import scope
from ..models import AttendanceRecord, Employee, OfficeDepartment, Posting
from .helpers import user
from .helpers_people import PeopleTestCase, TOP, employee, place

DAY = date(2026, 3, 2)
OFFICE, PRODUCTION = scope.OFFICE, scope.PRODUCTION


def names(employees):
    return sorted(person.last_name for person in employees)


class RealmTests(PeopleTestCase):
    def setUp(self):
        super().setUp()
        self.unplaced = employee('E-9', 'Unplaced')

    def realm(self, realm, day=DAY):
        return names(Employee.objects.filter(scope.in_realm(realm, day)))

    def test_production_is_a_live_placement_in_a_production_department_and_office_everyone_else(self):
        self.assertEqual(self.realm(PRODUCTION), ['Alfa', 'Bravo'])
        self.assertEqual(self.realm(OFFICE), ['Charlie', 'Unplaced'])
        self.assertEqual(names(scope.production_people(DAY)), ['Alfa', 'Bravo'])

    def test_every_person_is_in_exactly_one_realm(self):
        everyone = names(Employee.objects.all())
        self.assertEqual(sorted(self.realm(PRODUCTION) + self.realm(OFFICE)), everyone)

    def test_no_realm_is_no_narrowing(self):
        self.assertEqual(self.realm(None), names(Employee.objects.all()))
        self.assertEqual(names(scope.team(self.hr, DAY)), names(scope.team(self.hr, DAY, None)))
        self.assertEqual(names(scope.team(self.lead_a, DAY)), names(scope.team(self.lead_a, DAY, None)))

    def test_a_person_who_moved_is_in_each_realm_only_on_its_days(self):
        mover = employee('E-8', 'Hotel')
        place(mover, self.dept_a, TOP, date(2026, 3, 31))
        place(mover, self.finance, date(2026, 4, 1))
        self.assertIn('Hotel', self.realm(PRODUCTION, date(2026, 3, 31)))
        self.assertNotIn('Hotel', self.realm(OFFICE, date(2026, 3, 31)))
        self.assertIn('Hotel', self.realm(OFFICE, date(2026, 4, 1)))
        self.assertNotIn('Hotel', self.realm(PRODUCTION, date(2026, 4, 1)))

    def test_a_placement_not_yet_begun_or_ended_is_not_production(self):
        later = employee('E-10', 'Later')
        place(later, self.dept_a, date(2026, 4, 1))
        self.assertNotIn('Later', self.realm(PRODUCTION))
        self.assertIn('Later', self.realm(OFFICE))

    def test_a_deleted_placement_or_department_leaves_the_person_to_the_office(self):
        placing = Posting.objects.get(employee=self.in_a)
        placing.soft_delete(self.hr)
        self.assertEqual(self.realm(PRODUCTION), ['Bravo'])
        self.assertIn('Alfa', self.realm(OFFICE))
        Posting.all_objects.filter(pk=placing.pk).update(is_deleted=False)
        ProductionDepartment.all_objects.filter(pk=self.dept_b.pk).update(is_deleted=True)
        self.assertEqual(self.realm(PRODUCTION), ['Alfa'])
        self.assertIn('Bravo', self.realm(OFFICE))

    def test_the_team_narrowed_to_a_realm(self):
        self.assertEqual(names(scope.team(self.hr, DAY, PRODUCTION)), ['Alfa', 'Bravo'])
        self.assertEqual(names(scope.team(self.hr, DAY, OFFICE)), ['Charlie', 'Unplaced'])
        self.assertEqual(names(scope.team(self.lead_a, DAY, PRODUCTION)), ['Alfa'])
        self.assertEqual(names(scope.team(self.lead_a, DAY, OFFICE)), [])
        boss = user('boss')
        OfficeDepartment.objects.filter(pk=self.admin_dept.pk).update(manager=boss)
        self.assertEqual(names(scope.team(boss, DAY, OFFICE)), ['Charlie'])
        self.assertEqual(names(scope.team(boss, DAY, PRODUCTION)), [])

    def test_a_person_reaches_themselves_in_their_own_realm_only(self):
        account = get_user_model().objects.create_user('ann', 'ann@example.com', 'x')
        Employee.objects.filter(pk=self.in_a.pk).update(user=account, first_name='', last_name='')
        self.assertEqual([e.pk for e in scope.team(account, DAY, PRODUCTION)], [self.in_a.pk])
        self.assertEqual(list(scope.team(account, DAY, OFFICE)), [])

    def test_records_by_day_narrowed_to_the_realm_of_their_day(self):
        mover = employee('E-8', 'Hotel')
        place(mover, self.dept_a, TOP, date(2026, 3, 31))
        place(mover, self.finance, date(2026, 4, 1))
        before = AttendanceRecord.objects.create(employee=mover, clock_in='2026-03-31T06:00:00+00:00',
                                                 clock_out='2026-03-31T10:00:00+00:00', note='Entered')
        after = AttendanceRecord.objects.create(employee=mover, clock_in='2026-04-01T06:00:00+00:00',
                                                clock_out='2026-04-01T10:00:00+00:00', note='Entered')
        from django.db.models.functions import TruncDate
        records = AttendanceRecord.objects.annotate(clocked_day=TruncDate('clock_in'))

        def found(viewer, realm):
            return {record.pk for record in scope.by_day(viewer, records, 'employee', 'clocked_day', realm)}
        self.assertEqual(found(self.hr, PRODUCTION), {before.pk})
        self.assertEqual(found(self.hr, OFFICE), {after.pk})
        self.assertEqual(found(self.hr, None), {before.pk, after.pk})
        self.assertEqual(found(self.lead_a, PRODUCTION), {before.pk})
        self.assertEqual(found(self.lead_a, OFFICE), set())

    def test_the_days_reached_narrowed_to_the_realm(self):
        mover = employee('E-8', 'Hotel')
        place(mover, self.dept_a, TOP, date(2026, 3, 31))
        place(mover, self.finance, date(2026, 4, 1))
        first, last = date(2026, 3, 30), date(2026, 4, 2)
        production = scope.visible_days(self.hr, first, last, PRODUCTION)
        self.assertEqual(sorted(production[mover.pk]), [date(2026, 3, 30), date(2026, 3, 31)])
        self.assertNotIn(self.in_fin.pk, production)
        self.assertNotIn(self.unplaced.pk, production)
        office = scope.visible_days(self.hr, first, last, OFFICE)
        self.assertEqual(sorted(office[mover.pk]), [date(2026, 4, 1), date(2026, 4, 2)])
        self.assertEqual(len(office[self.unplaced.pk]), 4)
        self.assertNotIn(self.in_a.pk, office)
        lead = scope.visible_days(self.lead_a, first, last, PRODUCTION)
        self.assertEqual(sorted(lead[mover.pk]), [date(2026, 3, 30), date(2026, 3, 31)])
        self.assertEqual(scope.visible_days(self.lead_a, first, last, OFFICE), {})
        self.assertIsNone(scope.visible_days(self.hr, first, last))      # no realm: as before


class CrewTests(PeopleTestCase):
    """The colleagues of a production worker: the people placed in the same production department on the same day."""

    def setUp(self):
        super().setUp()
        self.worker = get_user_model().objects.create_user('ann', 'ann@example.com', 'x')
        Employee.objects.filter(pk=self.in_a.pk).update(user=self.worker, first_name='', last_name='')
        self.peer = employee('E-4', 'Delta')
        place(self.peer, self.dept_a)

    def test_the_crew_is_the_others_in_the_same_department_on_each_day(self):
        crew = scope.colleagues(self.worker, date(2026, 3, 2), date(2026, 3, 8))
        self.assertEqual(set(crew), {self.peer.pk})
        self.assertEqual(len(crew[self.peer.pk]), 7)

    def test_a_colleague_who_moved_is_crew_only_on_the_days_in_the_department(self):
        Posting.objects.filter(employee=self.peer).update(valid_until=date(2026, 3, 4))
        place(self.peer, self.dept_b, date(2026, 3, 5))
        crew = scope.colleagues(self.worker, date(2026, 3, 2), date(2026, 3, 8))
        self.assertEqual(sorted(crew[self.peer.pk]), [date(2026, 3, 2), date(2026, 3, 3), date(2026, 3, 4)])

    def test_the_viewer_who_moved_has_the_crew_of_each_day(self):
        Posting.objects.filter(employee=self.in_a).update(valid_until=date(2026, 3, 4))
        place(self.in_a, self.dept_b, date(2026, 3, 5))
        crew = scope.colleagues(self.worker, date(2026, 3, 2), date(2026, 3, 8))
        self.assertEqual(sorted(crew[self.peer.pk]), [date(2026, 3, 2), date(2026, 3, 3), date(2026, 3, 4)])
        self.assertEqual(sorted(crew[self.in_b.pk]), [date(2026, 3, 5), date(2026, 3, 6), date(2026, 3, 7),
                                                      date(2026, 3, 8)])

    def test_no_crew_without_a_production_placement_or_another_department(self):
        self.assertEqual(scope.colleagues(user('nobody'), date(2026, 3, 2), date(2026, 3, 8)), {})
        office = get_user_model().objects.create_user('cy', 'cy@example.com', 'x')
        Employee.objects.filter(pk=self.in_fin.pk).update(user=office, first_name='', last_name='')
        self.assertEqual(scope.colleagues(office, date(2026, 3, 2), date(2026, 3, 8)), {})
        crew = scope.colleagues(self.worker, date(2026, 3, 2), date(2026, 3, 8))
        self.assertNotIn(self.in_b.pk, crew)
        self.assertNotIn(self.in_a.pk, crew)                      # never the viewer themselves

    def test_a_deleted_colleague_or_placement_is_no_crew(self):
        self.peer.soft_delete(self.hr)
        self.assertEqual(scope.colleagues(self.worker, date(2026, 3, 2), date(2026, 3, 8)), {})

    def test_people_the_viewer_already_reaches_are_not_crew(self):
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=self.worker)
        self.assertEqual(scope.colleagues(self.worker, date(2026, 3, 2), date(2026, 3, 8)), {})

    def test_the_crew_writes_and_logs_nothing(self):
        logs = AuditLog.objects.count()
        scope.colleagues(self.worker, date(2026, 3, 2), date(2026, 3, 8))
        self.assertEqual(AuditLog.objects.count(), logs)


class MenuCourtesyTests(PeopleTestCase):
    """`leads` and `production_only` choose menu lines, and a line the menu leaves out is refused at its address too
    (test_menu_access)."""

    def test_leads_is_a_production_manager_or_a_holder_of_everyone(self):
        self.assertTrue(scope.leads(self.lead_a))
        self.assertTrue(scope.leads(self.hr))
        self.assertFalse(scope.leads(user('nobody')))
        boss = user('boss')
        OfficeDepartment.objects.filter(pk=self.admin_dept.pk).update(manager=boss)
        self.assertFalse(scope.leads(boss))

    def test_production_only_is_a_person_placed_in_production_with_nothing_in_the_office(self):
        worker = get_user_model().objects.create_user('ann', 'ann@example.com', 'x')
        Employee.objects.filter(pk=self.in_a.pk).update(user=worker, first_name='', last_name='')
        self.assertTrue(scope.production_only(worker, DAY))
        self.assertFalse(scope.not_production_only(worker, DAY))
        OfficeDepartment.objects.filter(pk=self.finance.pk).update(manager=worker)
        self.assertFalse(scope.production_only(worker, DAY))

    def test_office_unplaced_and_everyone_holders_are_not_production_only(self):
        office = get_user_model().objects.create_user('cy', 'cy@example.com', 'x')
        Employee.objects.filter(pk=self.in_fin.pk).update(user=office, first_name='', last_name='')
        self.assertFalse(scope.production_only(office, DAY))
        self.assertFalse(scope.production_only(user('nobody'), DAY))
        Employee.objects.filter(pk=self.in_b.pk).update(user=self.hr, first_name='', last_name='')
        self.assertFalse(scope.production_only(self.hr, DAY))
