from datetime import date

from django.core.exceptions import PermissionDenied, ValidationError

from core.models import AuditLog

from .. import services
from ..models import Employee, Posting
from .helpers_people import PeopleTestCase, TOP, employee, place


class MoveTests(PeopleTestCase):
    def state(self):
        return (list(Posting.all_objects.order_by('valid_from', 'pk').values_list(
                    'employee__employee_number', 'production_department', 'office_department', 'title', 'valid_from',
                    'valid_until', 'is_deleted', 'version')),
                AuditLog.objects.count())

    def test_a_first_placement_just_starts(self):
        person = employee('E-30', 'Juliet')
        posting = services.move(self.hr, person, self.dept_a, 'Feeder', date(2026, 2, 1))
        self.assertEqual((posting.production_department, posting.valid_from, posting.valid_until, posting.created_by),
                         (self.dept_a, date(2026, 2, 1), None, self.hr))
        log = AuditLog.objects.get(entity_id=str(posting.pk))
        self.assertEqual((log.action, log.entity_type, log.changes['Production department']),
                         ('create', 'placement', [None, 'Hatchery A (HAT-A)']))

    def test_a_move_closes_the_open_placement_the_day_before_and_logs_both(self):
        old = Posting.objects.get(employee=self.in_a)
        new = services.move(self.hr, self.in_a, self.finance, 'Controller', date(2026, 6, 1))
        old.refresh_from_db()
        self.assertEqual((old.valid_until, old.version), (date(2026, 5, 31), 2))
        self.assertEqual((new.office_department, new.production_department, new.valid_from, new.valid_until),
                         (self.finance, None, date(2026, 6, 1), None))
        log = {(entry.entity_id, entry.action): entry.changes for entry in AuditLog.objects.filter(entity_type='placement')}
        self.assertEqual(log[(str(old.pk), 'update')], {'Until': [None, '2026-05-31']})
        self.assertIn((str(new.pk), 'create'), log)

    def test_the_same_department_and_title_is_no_change(self):
        before = self.state()
        services.move(self.hr, self.in_a, self.dept_a, 'Technician', date(2026, 6, 1))
        self.assertEqual(self.state(), before)

    def test_a_new_title_in_the_same_department_is_a_new_placement(self):
        services.move(self.hr, self.in_a, self.dept_a, 'Senior technician', date(2026, 6, 1))
        titles = list(Posting.objects.filter(employee=self.in_a).order_by('valid_from').values_list('title', flat=True))
        self.assertEqual(titles, ['Technician', 'Senior technician'])

    def test_a_change_dated_the_first_day_corrects_the_placement_in_place(self):
        placed = Posting.objects.get(employee=self.in_a)
        services.move(self.hr, self.in_a, self.dept_b, 'Technician', TOP)
        placed.refresh_from_db()
        self.assertEqual((placed.production_department, placed.version), (self.dept_b, 2))
        self.assertEqual(Posting.objects.filter(employee=self.in_a).count(), 1)

    def test_every_refusal_changes_no_row_and_logs_nothing(self):
        before = self.state()
        for call, error in (
                (lambda: services.move(self.hr, self.in_a, self.dept_b, 'X', date(2025, 12, 31)), ValidationError),   # before joined
                (lambda: services.move(self.lead_a, self.in_b, self.dept_a, 'X', date(2026, 6, 1)), PermissionDenied),  # not his team
                (lambda: services.move(self.lead_a, self.in_a, self.dept_b, 'X', date(2026, 6, 1)), PermissionDenied),  # no verb
        ):
            with self.assertRaises(error):
                call()
        self.assertEqual(self.state(), before)

    def test_it_refuses_a_day_before_the_current_placement_or_after_the_last_day(self):
        mover = employee('E-31', 'Kilo')
        place(mover, self.dept_a, date(2026, 2, 1))
        before = self.state()
        with self.assertRaises(ValidationError):
            services.move(self.hr, mover, self.dept_b, 'X', date(2026, 1, 15))     # before the current began
        Employee.objects.filter(pk=mover.pk).update(left_on=date(2026, 3, 1))
        with self.assertRaises(ValidationError):
            services.move(self.hr, mover, self.dept_b, 'X', date(2026, 3, 2))      # after the last day
        self.assertEqual(self.state(), before)

    def test_it_refuses_to_place_into_a_closed_past(self):
        mover = employee('E-32', 'Lima')
        place(mover, self.dept_a, date(2026, 2, 1), date(2026, 2, 28))
        with self.assertRaises(ValidationError):
            services.move(self.hr, mover, self.dept_b, 'X', date(2026, 2, 28))


class LeaveCompanyTests(PeopleTestCase):
    def test_the_last_day_ends_the_placement_and_removes_later_ones(self):
        person = employee('E-40', 'Mike')
        place(person, self.dept_a, TOP, date(2026, 3, 31))
        place(person, self.dept_b, date(2026, 4, 1))
        services.leave_company(self.hr, person, date(2026, 3, 15))
        person.refresh_from_db()
        self.assertEqual(person.left_on, date(2026, 3, 15))
        postings = Posting.all_objects.filter(employee=person).order_by('valid_from')
        self.assertEqual([(p.valid_until, p.is_deleted) for p in postings],
                         [(date(2026, 3, 15), False), (None, True)])
        log = AuditLog.objects.filter(entity_type='employee', entity_id=str(person.pk)).get()
        self.assertEqual(log.changes, {'Left on': [None, '2026-03-15']})

    def test_a_last_day_before_joining_is_refused_and_nothing_changes(self):
        person = employee('E-41', 'November', on=date(2026, 5, 1))
        before = AuditLog.objects.count()
        with self.assertRaises(ValidationError):
            services.leave_company(self.hr, person, date(2026, 4, 30))
        person.refresh_from_db()
        self.assertIsNone(person.left_on)
        self.assertEqual(AuditLog.objects.count(), before)

    def test_only_someone_who_reaches_the_person_can_close_them(self):
        with self.assertRaises(PermissionDenied):
            services.leave_company(self.lead_a, self.in_b, date(2026, 3, 1))

    def test_the_form_route_agrees_the_placements_with_a_last_day(self):
        from django.urls import reverse
        from ..units import token
        self.client.force_login(self.hr)
        self.client.post(reverse('hr:employee_edit', args=[self.in_a.pk]), {
            'employee_number': 'E-1', 'last_name': 'Alfa', 'first_name': 'Ann', 'employment_type': 'staff',
            'joined_on': '2026-01-01', 'left_on': '2026-03-15', 'department': token(self.dept_a),
            'title': 'Technician', 'from_day': '2026-01-01', 'version': '1'})
        placed = Posting.objects.get(employee=self.in_a)
        self.assertEqual(placed.valid_until, date(2026, 3, 15))
        self.in_a.refresh_from_db()
        self.assertEqual(self.in_a.left_on, date(2026, 3, 15))
