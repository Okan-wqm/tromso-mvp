"""The fifth review of the branch (F:/dev/balik-notes/hr-one-path/REVIEW-5.md, R5-3 to R5-5), each as a test that fails
before its fix: one confirmation below the views, one reach of a stretch, one order of a delete's refusals."""
import ast
from datetime import date, datetime, time, timedelta, timezone as utc
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.urls import reverse

from farm.models import ProductionDepartment

from .. import services
from ..models import AttendanceRecord, Shift, ShiftAssignment
from .helpers import user
from .helpers_people import PeopleTestCase, employee, place
from .test_one_path import EVERY_VERB

UTC = utc.utc


class ConfirmationBelowTheViewsTests(PeopleTestCase):
    def test_the_comparison_and_its_sentences_live_below_the_views(self):
        """R5-3: crud and HR's service use the one comparison of core.confirmed; HR's service imports no view layer."""
        from core import confirmed, crud
        self.assertIs(crud.unchanged, confirmed.unchanged)
        self.assertIs(crud.changed_meanwhile, confirmed.changed_meanwhile)
        tree = ast.parse(Path(settings.BASE_DIR, 'hr', 'services.py').read_text(encoding='utf-8'))
        sources = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        sources |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        self.assertNotIn('core.crud', sources)
        self.assertIs(getattr(services, 'as_confirmed', None), confirmed.as_confirmed)     # no second compare


class OneOrderOfADeleteTests(PeopleTestCase):
    """R5-4, R5-5: a delete is refused for the scope, then the record's own rule, then the reach, and last for the
    version its confirmation showed."""

    def setUp(self):
        super().setUp()
        self.lead = user('boss', *EVERY_VERB, group='Lead role')
        ProductionDepartment.objects.filter(pk=self.dept_a.pk).update(manager=self.lead)
        self.own = employee('E-50', '', '', user=self.lead)        # a person with an account: named by it
        place(self.own, self.dept_a)

    def stretch(self, person, day=date(2026, 3, 2)):
        return AttendanceRecord.objects.create(employee=person, clock_in=datetime.combine(day, time(6), tzinfo=UTC),
                                               clock_out=datetime.combine(day, time(14), tzinfo=UTC), via='entered',
                                               note='x')

    def test_a_leads_delete_of_their_own_stretch_or_plan_is_a_403_however_it_is_posted(self):
        early = Shift.objects.create(name='Early', code='EARLY', starts_at=time(6), ends_at=time(14))
        records = {
            'hr:production_attendancerecord_delete': self.stretch(self.own),
            'hr:production_shiftassignment_delete': ShiftAssignment.objects.create(employee=self.own,
                                                                                   day=date(2026, 3, 2), shift=early),
        }
        self.client.force_login(self.lead)
        for name, record in records.items():
            url = reverse(name, args=[record.pk])
            for case, data in (('bare', {}), ('stale', {'version': '99'}), ('current', {'version': '1'})):
                with self.subTest(delete=name, posted=case):
                    self.assertEqual(self.client.post(url, data).status_code, 403)
            record.refresh_from_db()
            self.assertFalse(record.is_deleted)

    def test_void_refuses_a_day_as_correct_and_enter_do_before_the_version(self):
        """R5-4: the lead's person today on a day that is another lead's is told the sentence (services.reached), not a
        bare 403; a person never theirs is NotReached; and both before any word on the version."""
        mo = employee('E-90', 'Mo')
        place(mo, self.dept_b, date(2026, 1, 1), date(2026, 3, 31))
        place(mo, self.dept_a, date(2026, 4, 1))
        theirs_today, never = self.stretch(mo, date(2026, 3, 10)), self.stretch(self.in_b, date(2026, 3, 10))
        for seen in ('', '99', '1'):
            with self.subTest(seen=seen):
                with self.assertRaisesMessage(ValidationError, 'You do not see this person on this day.'):
                    services.void_presence(self.lead, theirs_today, seen)
                with self.assertRaises(services.NotReached):
                    services.void_presence(self.lead, never, seen)
        self.assertEqual(AttendanceRecord.all_objects.filter(is_deleted=True).count(), 0)

    def test_the_version_is_asked_last_and_a_bare_one_is_refused(self):
        """Each HR delete asks the version itself, last: none confirmed nothing, another is a record changed since,
        the one shown deletes."""
        from django.utils import timezone

        from core.confirmed import ChangedMeanwhile, NotConfirmed
        yesterday = timezone.localdate() - timedelta(days=1)
        early = Shift.objects.create(name='Early', code='EARLY', starts_at=time(6), ends_at=time(14))
        deletes = {
            'void_presence': (self.stretch(self.in_a, yesterday), services.void_presence),
            'clear_day': (ShiftAssignment.objects.create(employee=self.in_a, day=yesterday, shift=early),
                          services.clear_day),
        }
        for name, (record, delete) in deletes.items():
            with self.subTest(delete=name):
                with self.assertRaises(NotConfirmed):
                    delete(self.lead, record, '')
                with self.assertRaises(ChangedMeanwhile):
                    delete(self.lead, record, '2')
                delete(self.lead, record, '1')
                self.assertTrue(type(record).all_objects.get(pk=record.pk).is_deleted)
