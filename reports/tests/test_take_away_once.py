"""Reopening a closed duty and taking away a duty recorded as done lock the row first and log after it is gone: a second
press on a page shown before the first (two tabs, a double click) is refused and leaves one log entry (audit F-077)."""
from datetime import date

from django.core.exceptions import ValidationError

from core.models import AuditLog

from .. import services
from ..models import DueClosure, OutsideDutyDone
from .test_due import DueTestCase


class TakeAwayOnceTests(DueTestCase):
    def test_a_closure_is_reopened_once(self):
        closure = DueClosure.objects.create(kind='slaughter_planned', facility=self.facility,
                                            period_start=date(2026, 10, 19), reason='No harvest', closed_by=self.user)
        stale = DueClosure.objects.get(pk=closure.pk)
        services.reopen(self.user, closure)
        with self.assertRaises(ValidationError):
            services.reopen(self.user, stale)
        self.assertEqual(AuditLog.objects.filter(action='delete', entity_id=str(closure.pk)).count(), 1)

    def test_a_duty_done_is_taken_away_once(self):
        record = OutsideDutyDone.objects.create(duty='lice_plan', site=self.sea, year=2026, done_on=date(2026, 9, 1),
                                                recorded_by=self.user)
        stale = OutsideDutyDone.objects.get(pk=record.pk)
        services.undo_duty_done(self.user, record)
        with self.assertRaises(ValidationError):
            services.undo_duty_done(self.user, stale)
        self.assertEqual(AuditLog.objects.filter(action='delete', entity_id=str(record.pk)).count(), 1)
