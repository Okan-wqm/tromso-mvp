"""A unit that holds two batches, one of them under a medicine withdrawal (flow fault S-02): a net cannot separate the
batches of one unit, so the withdrawal of ANY fish in the unit holds a harvest of it, whichever batch the dialog names.
The harvest dialog warns and takes its box, the acknowledgement and the critical log line name the batch that is held,
the earliest suitable harvest date is the unit's, a treatment entered afterwards is asked about such a harvest (the
withdrawal guard), check_withdrawal lists it, and the harvest locks every batch in its unit, so it and a write that
changes one of their withdrawals take turns. Which fish a withdrawal holds (the whole batch) is not changed here."""
import io
import uuid
from decimal import Decimal

from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from core.models import AuditLog

from ..handling import check
from ..models import HandlingAcknowledgement, StockMovement, Treatment, WithdrawalAcknowledgement
from ..stock import services as stock_services
from .test_harvest_inside_withdrawal import HarvestInsideTestCase
from .test_stock import make_unit


class SharedUnitTestCase(HarvestInsideTestCase):
    """T-01: batch A (2,000 fish, 10 days). T-02: batch B (3,000 fish, 9 days), never treated."""

    def setUp(self):
        super().setUp()
        self.a = self.batch
        self.b = self.stock(self.t2, count=3000, days_ago=9)

    def move(self, days_ago, count=500):
        """`count` fish of A out of T-01 into T-02, beside B."""
        return stock_services.record_transfer(self.user, source=self.t1, batch=self.a, day=self.day(days_ago),
                                              legs=[(self.t2, count)], reason='density')

    def harvest_b(self, days_ago, count=100, kilos='13', **fields):
        return stock_services.record_harvest(self.user, unit=self.t2, batch=self.b, day=self.day(days_ago),
                                             count=count, measured_weight_kg=Decimal(kilos), facility=self.facility,
                                             **fields)


class HeldUnitTests(SharedUnitTestCase):
    """A is bathed in T-01 6 days ago (7 days: free from 2 days ahead), then 500 of it join B in T-02."""

    def setUp(self):
        super().setUp()
        self.treatment = self.treat(self.medicine(days=7), 6, 6)
        self.move(4)
        self.until = self.day(-2)

    def test_the_check_of_the_untreated_batch_sees_the_withdrawal_of_the_batch_beside_it(self):
        for batch in (self.b, self.a, None):
            with self.subTest(batch=batch):
                result = check.assess('harvest', self.t2, self.today, batch)
                [warning] = [each for each in result.warnings if each.warning == 'withdrawal']
                self.assertEqual((warning.block.batch, warning.block.until), (self.a, self.until))
                self.assertIn(f'medicine withdrawal of {self.a.code}', warning.message())
                self.assertIn('T-02', warning.message())                    # the unit it holds as a whole
                self.assertNotIn('No medicine withdrawal in force.', result.notes)
        # One answer for the unit: the box's value does not depend on the batch chosen.
        self.assertEqual(check.assess('harvest', self.t2, self.today, self.b).fingerprint,
                         check.assess('harvest', self.t2, self.today, self.a).fingerprint)
        # T-01 holds A alone: its warning is the same withdrawal, and says nothing of other fish.
        [alone] = check.assess('harvest', self.t1, self.today, self.a).warnings
        self.assertNotIn('T-01', alone.message())

    def test_the_earliest_suitable_harvest_date_of_the_untreated_batch_is_the_units(self):
        found = check.earliest(self.t2, self.b)
        self.assertEqual((found.decides, found.day, found.until), ('withdrawal', self.until, self.until))
        self.assertEqual([block.batch for block in check.in_force(self.t2, self.today)], [self.a])

    def test_the_dialog_warns_takes_its_box_and_stores_the_batch_that_is_held(self):
        url = reverse('farm:stock_harvest', args=[self.t2.pk])
        shown = self.client.get(url, {'batch': str(self.b.pk)})
        self.assertContains(shown, f'medicine withdrawal of {self.a.code}')
        self.assertContains(shown, 'name="handling_ack"')
        self.assertNotContains(shown, 'No medicine withdrawal in force.')
        data = {'token': str(uuid.uuid4()), 'batch': str(self.b.pk), 'date': self.today.isoformat(), 'count': '100',
                'measured_weight_kg': '13', 'facility': str(self.facility.pk), 'notes': ''}
        refused = self.client.post(url, data)
        self.assertEqual(refused.status_code, 422)
        self.assertContains(refused, 'Tick the box to go on despite these warnings.', status_code=422)
        self.assertFalse(StockMovement.objects.filter(kind='harvest').exists())
        fingerprint = refused.context['form'].handling.fingerprint
        self.assertEqual(self.client.post(url, {**data, 'handling_ack': fingerprint}).status_code, 302)
        line = StockMovement.objects.get(kind='harvest')
        self.assertEqual((line.batch, line.unit, line.count_delta), (self.b, self.t2, -100))
        row = HandlingAcknowledgement.objects.get()
        self.assertEqual((row.operation, row.warning, row.batch, row.withdrawal_until, row.withdrawal_source),
                         (line.operation, 'withdrawal', self.a, self.until, f'treatment:{self.treatment.pk}'))
        entry = AuditLog.objects.get(entity_type='stock operation', action='create', entity_id=str(line.operation_id))
        self.assertEqual(entry.severity, 'critical')
        self.assertIn(f'medicine withdrawal of {self.a.code}', entry.changes['Handling warnings acknowledged'][1])
        self.assertIn(self.b.code, entry.entity_label)                       # the harvest is of B, the hold of A

    def test_check_withdrawal_lists_the_harvest_of_the_untreated_batch(self):
        seen = check.assess('harvest', self.t2, self.today, self.b).fingerprint
        self.harvest_b(0, handling_ack=seen)
        out = io.StringIO()
        call_command('check_withdrawal', stdout=out)
        self.assertIn(f'Harvest of {self.today.isoformat()} from T-02 · {self.b.code} (100 fish to '
                      f'{self.facility.name}) lies inside a withdrawal of {self.a.code}, in the same unit (harvest '
                      f'from {self.until.isoformat()}):', out.getvalue())
        self.assertIn('Acknowledged when the harvest was recorded.', out.getvalue())
        self.assertIn('1 harvest lies inside a medicine withdrawal.', out.getvalue())

    def test_a_unit_that_never_held_the_treated_fish_is_not_held(self):
        """The other side, unchanged: fish in a unit the held batch is not in are asked nothing."""
        t3 = make_unit('T-03', self.hall)
        other = self.stock(t3, count=100, days_ago=3)
        result = check.assess('harvest', t3, self.today, other)
        self.assertEqual(result.warnings, [])
        self.assertIn('No medicine withdrawal in force.', result.notes)

    def test_the_harvest_locks_every_batch_in_its_unit(self):
        seen = check.assess('harvest', self.t2, self.today, self.b).fingerprint
        with CaptureQueriesContext(connection) as queries:
            self.harvest_b(0, handling_ack=seen)
        locks = [query['sql'] for query in queries.captured_queries
                 if 'FOR UPDATE' in query['sql'] and 'FROM "batches"' in query['sql']]
        self.assertTrue(any(str(self.a.pk) in sql and str(self.b.pk) in sql for sql in locks), locks)
        first_units = next(index for index, query in enumerate(queries.captured_queries)
                           if 'FOR UPDATE' in query['sql'] and 'FROM "tanks"' in query['sql'])
        first_both = next(index for index, query in enumerate(queries.captured_queries)
                          if 'FOR UPDATE' in query['sql'] and 'FROM "batches"' in query['sql']
                          and str(self.a.pk) in query['sql'])
        self.assertLess(first_both, first_units)                             # the fish first, then the units


class TreatmentEnteredAfterwardsTests(SharedUnitTestCase):
    """500 of A join B in T-02 7 days ago; B is harvested from T-02 3 days ago; then a bath of T-01 of 8 days ago (7
    days: A is held to yesterday, wherever it is) is entered: the harvest took fish out of a unit that held A."""

    def setUp(self):
        super().setUp()
        self.move(7)
        self.harvest = self.harvest_b(3, count=500, kilos='70')

    def test_the_treatment_is_asked_about_the_harvest_and_the_acknowledgement_names_the_held_batch(self):
        bath = self.medicine(days=7)
        change = self.change_of(self.treat, bath, 8, 8)
        self.assertFalse(Treatment.all_objects.exists())
        [found] = change.harvested
        self.assertEqual((found.operation_id, found.batch, found.line.batch, found.until),
                         (self.harvest.pk, self.a, self.b, self.today))
        [message] = change.messages()
        self.assertIn(f'from T-02 ({self.b.code}, 500 fish to {self.facility.name})', message)
        self.assertIn(self.a.code, message)
        treatment = self.treat(bath, 8, 8, withdrawal_ack=change.fingerprint)
        row = WithdrawalAcknowledgement.objects.get()
        self.assertEqual((row.record_id, row.harvest, row.batch, row.warning, row.source),
                         (str(treatment.pk), self.harvest, self.a, 'harvested', f'treatment:{treatment.pk}'))
        out = io.StringIO()
        call_command('check_withdrawal', stdout=out)
        self.assertIn(f'from T-02 · {self.b.code} (500 fish to {self.facility.name}) lies inside a withdrawal of '
                      f'{self.a.code}, in the same unit (harvest from {self.today.isoformat()}):', out.getvalue())
        self.assertIn('Acknowledged when the treatment was recorded.', out.getvalue())

    def test_a_harvest_before_the_held_fish_came_into_the_unit_is_not_inside(self):
        early = self.harvest_b(8, count=100)                                 # A came into T-02 the day after
        self.assertNotEqual(early.pk, self.harvest.pk)
        change = self.change_of(self.treat, self.medicine(days=7), 9, 9)     # held from 9 days ago to 2 days ago
        self.assertEqual([found.operation_id for found in change.harvested], [self.harvest.pk])
