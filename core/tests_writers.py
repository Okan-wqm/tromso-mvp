"""One writer per record, held at run time (core.writers; the review of wip/hr-one-path, N-2 c): a model that declares
`service_written` refuses a write made outside its service's writing context, whatever spells it. Production code is
stood in for by code compiled under a production file name (a view, a command): a write a test module makes itself is
the test laying out its rows, and passes."""
from datetime import date, time

from django.db import transaction
from django.test import TestCase

from hr import services
from hr.models import AttendanceRecord, Employee, Posting, Shift, ShiftAssignment
from hr.tests.helpers_people import PeopleTestCase


def as_production(source, filename='/app/hr/views.py', **names):
    """Runs `source` as code of a production module (`filename`), with `names` in its globals."""
    exec(compile(source, filename, 'exec'), dict(names))      # noqa: S102 (the test's own source)


class TripwireTests(PeopleTestCase):
    def refused(self, source, filename='/app/hr/views.py', **names):
        from core.writers import NotTheWriter
        with self.assertRaises(NotTheWriter), transaction.atomic():
            as_production(source, filename, **names)

    def test_a_write_from_a_view_is_refused_however_spelled(self):
        shift = Shift.objects.create(name='Early', code='EARLY', starts_at=time(6), ends_at=time(14))
        row = ShiftAssignment.objects.create(employee=self.in_a, day=date(2026, 3, 2), shift=shift)
        names = {'Employee': Employee, 'ShiftAssignment': ShiftAssignment, 'person': self.in_a, 'row': row,
                 'shift': shift, 'date': date, 'hr_user': self.hr}
        for source in (
                'person.left_on = date(2026, 6, 1)\nperson.save()',                           # a row in a variable
                'Employee.objects.filter(pk=person.pk).update(left_on=date(2026, 6, 1))',     # a queryset
                'Employee.all_objects.filter(pk=person.pk).delete()',
                'person.assignments.create(day=date(2026, 3, 3), shift=shift)',                # a related manager
                'person.assignments.filter(pk=row.pk).update(note="x")',
                'ShiftAssignment.objects.bulk_create([ShiftAssignment(employee=person, day=date(2026, 3, 4))])',
                'row.soft_delete(hr_user)',
                'row.delete()'):
            with self.subTest(source=source):
                self.refused(source, **names)
        self.refused('person.postings.create(valid_from=date(2026, 7, 1), title="x", production_department=dept)',
                     '/app/hr/management/commands/seed_hr_demo.py', person=self.in_a, date=date, dept=self.dept_a)

    def test_a_form_saved_outside_the_service_is_refused(self):
        from hr.forms.roster import ShiftAssignmentForm
        form = ShiftAssignmentForm({'employee': str(self.in_a.pk), 'day': '2026-03-02', 'shift': '', 'note': ''},
                                   user=self.hr)
        self.assertTrue(form.is_valid(), form.errors)
        self.refused('form.save()', form=form)

    def test_the_services_own_writes_pass_and_other_records_are_not_held(self):
        as_production('services.leave_company(hr_user, person, date(2026, 6, 30))', services=services,
                      hr_user=self.hr, person=self.in_a, date=date)
        self.in_a.refresh_from_db()
        self.assertEqual(self.in_a.left_on, date(2026, 6, 30))
        as_production('Shift.objects.create(name="Late", code="LATE", starts_at=time(14), ends_at=time(22))',
                      Shift=Shift, time=time)                                  # a record its tab writes: not held
        self.assertTrue(Shift.objects.filter(code='LATE').exists())

    def test_a_tests_own_rows_pass(self):
        Posting.objects.filter(employee=self.in_a).update(title='Set by the test')
        AttendanceRecord.objects.create(employee=self.in_a, clock_in=self.in_a.created_at, via='self')


class WritingContextTests(TestCase):
    def test_entering_needs_a_reason_and_ends_with_the_block(self):
        from core import writers
        with self.assertRaises(ValueError), writers.writing('hr', ''):
            pass
        with writers.writing('hr', 'the test'):
            self.assertIn('hr', writers._entered.get())
        self.assertNotIn('hr', writers._entered.get())

    def test_only_a_services_module_enters_it(self):
        """Nothing in the production code enters a writing context but a services module (core/writers.py defines it;
        the test world, a test module, enters it with its reason)."""
        import ast

        from .tests_data_access import production_modules
        found = sorted({path for path, tree in production_modules() for node in ast.walk(tree)
                        if isinstance(node, ast.Call) and getattr(node.func, 'attr', getattr(node.func, 'id', ''))
                        in ('writing', 'writer') and path != 'core/writers.py'})
        self.assertEqual(found, ['hr/services.py'])
