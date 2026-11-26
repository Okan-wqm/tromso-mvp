"""The write path of protocol assignments (farm/feeding/assignments.py), which the assignment dialog and an
experiment's start both use: the rows it makes, the errors it reports per unit and field, what it stores and logs,
and that the dialog and the service leave the same log entry."""
from datetime import timedelta

from django.core.exceptions import NON_FIELD_ERRORS
from django.db import IntegrityError
from django.urls import reverse

from core.models import AuditLog
from core.crud import tab_fields

from ..feeding import assignments
from ..forms.feeding_protocol import ASSIGNMENT_TABS
from ..models import ProtocolAssignment
from .helpers import may_record
from .test_protocols import ProtocolTestCase


class AssignmentRowsTests(ProtocolTestCase):
    def setUp(self):
        super().setUp()
        self.protocol = self.make_protocol()
        may_record(self.user, 'add_protocolassignment')     # the assignments' save asks who may (L-6)

    def make(self, units=(), batch=None, first=None, last=None, protocol=None, notes=''):
        return assignments.rows(protocol or self.protocol, list(units), batch, first or self.today, last, notes)

    def test_a_row_per_unit_with_one_group_and_nothing_written(self):
        made, errors = self.make([self.t1, self.t2], last=self.today + timedelta(days=9), notes='Trial')
        self.assertEqual(errors, [])
        self.assertEqual([(row.unit, row.batch, row.scope, row.valid_from, row.valid_until, row.notes)
                          for row in made],
                         [(self.t1, None, 'unit', self.today, self.today + timedelta(days=9), 'Trial'),
                          (self.t2, None, 'unit', self.today, self.today + timedelta(days=9), 'Trial')])
        self.assertEqual(len({row.group_id for row in made}), 1)
        self.assertFalse(ProtocolAssignment.objects.exists())

    def test_a_batch_alone_is_one_row_and_a_batch_in_units_a_row_per_unit(self):
        made, errors = self.make(batch=self.batch)
        self.assertEqual([(row.unit, row.scope) for row in made], [(None, 'batch')])
        made, errors = self.make([self.t1, self.t2], batch=self.batch)
        self.assertEqual((errors, [(row.unit, row.scope) for row in made]),
                         ([], [(self.t1, 'batch_in_unit'), (self.t2, 'batch_in_unit')]))

    def test_a_unit_with_a_row_in_force_is_an_error_of_that_unit_and_its_neighbour_is_still_made(self):
        self.assign(self.protocol, unit=self.t1, days_ago=2)
        made, errors = self.make([self.t1, self.t2])
        self.assertEqual([row.unit for row in made], [self.t2])
        self.assertEqual([(error.unit, error.field, error.message) for error in errors],
                         [(self.t1, NON_FIELD_ERRORS, 'Another protocol is assigned to this unit on some of these '
                                                     'days.')])

    def test_what_is_wrong_with_a_field_is_reported_on_that_field(self):
        draft = self.make_protocol(name='Draft', status='draft')
        made, errors = self.make([self.t1], protocol=draft)
        self.assertEqual((made, [(error.unit, error.field) for error in errors]), ([], [(self.t1, 'protocol')]))
        trout = self.make_protocol(name='Trout', species=self.trout)
        made, errors = self.make(batch=self.batch, protocol=trout)
        self.assertEqual((made, [(error.unit, error.field) for error in errors]), ([], [(None, 'batch')]))
        made, errors = self.make([self.t1], first=self.today, last=self.today - timedelta(days=1))
        self.assertEqual((made, [error.field for error in errors]), ([], ['valid_until']))

    def test_save_writes_the_rows_by_the_user_and_logs_each_and_a_clash_leaves_nothing(self):
        made, _errors = self.make([self.t1, self.t2])
        self.assign(self.protocol, unit=self.t2, days_ago=0)          # written for the same fish meanwhile
        with self.assertRaises(IntegrityError):
            assignments.save(self.user, made)
        self.assertEqual(list(ProtocolAssignment.objects.values_list('unit__code', flat=True)), ['T-02'])
        self.assertFalse(AuditLog.objects.filter(entity_type='protocol assignment').exists())
        ProtocolAssignment.objects.all().delete()
        made, _errors = self.make([self.t1, self.t2])
        assignments.save(self.user, made)
        stored = ProtocolAssignment.objects.order_by('unit__code')
        self.assertEqual([(row.unit.code, row.created_by, row.updated_by, row.version) for row in stored],
                         [('T-01', self.user, self.user, 1), ('T-02', self.user, self.user, 1)])
        self.assertEqual(AuditLog.objects.filter(entity_type='protocol assignment', action='create',
                                                 user=self.user).count(), 2)

    def test_the_dialog_and_the_service_log_the_same_entry(self):
        self.client.post(reverse('farm:protocolassignment_create'), {
            'protocol': str(self.protocol.pk), 'valid_from': self.today.isoformat(),
            'valid_until': (self.today + timedelta(days=9)).isoformat(), 'notes': 'Trial',
            'batch': '', 'units': [str(self.t1.pk)]}, headers={'X-Modal': '1'})
        made, _errors = self.make([self.t2], last=self.today + timedelta(days=9), notes='Trial')
        assignments.save(self.user, made)
        # Equal but for the unit: one entry shape, whichever door the row came through.
        dialog, service = (AuditLog.objects.get(entity_type='protocol assignment', entity_id=str(
            ProtocolAssignment.objects.get(unit=unit).pk)).changes for unit in (self.t1, self.t2))
        self.assertEqual({key: value for key, value in dialog.items() if key != 'Unit'},
                         {key: value for key, value in service.items() if key != 'Unit'})
        self.assertEqual(set(dialog), {'Feeding protocol', 'Unit', 'From', 'Until', 'Notes'})

    def test_the_fields_the_log_shows_are_the_fields_of_the_assignment_form(self):
        self.assertEqual(tab_fields(ASSIGNMENT_TABS), list(assignments.FIELDS))
