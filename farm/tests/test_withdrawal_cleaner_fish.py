"""Cleaner fish under a medicine withdrawal beside production fish that were never treated (review F-05 of the flow
faults). The unit-wide withdrawal of S-02 (the owner's decision 1) is about two groups of PRODUCTION fish: a net cannot
tell them apart. Cleaner fish beside them are another species, sorted out at a harvest and never harvested themselves
(they are culled), and whether their withdrawal holds the salmon is the owner's and the vet's to decide. Until they
do, it is as it was before S-02: the cleaner fish's withdrawal is no WARNING on the harvest of the production fish, is
not stored as the production batch's acknowledgement and does not decide their earliest harvest date; the harvest
dialog says it as a NOTE, and the unit's own line still shows it. Production batches that share a unit stay as S-02
built it (farm/tests/test_withdrawal_shared_unit.py), with cleaner fish beside them too."""
import io
import uuid
from decimal import Decimal

from django.core.management import call_command
from django.urls import reverse

from core.models import AuditLog

from .. import withdrawal_gate
from ..handling import check
from ..health import services as health_services, withdrawal
from ..models import HandlingAcknowledgement, Medicine, MedicineWithdrawal, StockMovement
from ..stock import services as stock_services
from ..stock.dates import shown_date
from .helpers import going_on, make_facility, role
from .test_cleaner_fish import CleanerFishTestCase
from .test_harvest import HARVEST_KEEPER


class CleanerWithdrawalTestCase(CleanerFishTestCase):
    """C-01: 2,000 salmon and 10,000 lumpfish, never treated. C-02: 500 lumpfish of another batch and 300 salmon of
    another batch, bathed 3 days ago (7 days: harvest from 5 days ahead)."""

    def setUp(self):
        super().setUp()
        self.user.groups.add(role('Harvest keeper', *HARVEST_KEEPER))
        self.facility = make_facility()
        self.bathed_lump = self.stock(self.cage2, count=500, weight='30', days_ago=8, species=self.lump)
        self.bathed_salmon = self.stock(self.cage2, count=300, weight='125', days_ago=8)
        bath = Medicine.objects.create(name='Salmosan vet.', kind='lice', administration='bath',
                                       active_substance='azamethiphos', lice_report_code='AZAMETHIPHOS')
        with withdrawal_gate.opened('test fixture: a withdrawal row straight in the database'):
            MedicineWithdrawal.objects.create(medicine=bath, species=None, days=7, safety_margin_pct=0, note='')
        self.treatment = health_services.record_treatment(
            self.user, units=[self.cage2], method='bath', reason='sea_lice', start_date=self.day(3),
            end_date=self.day(3), medicine=bath)
        self.until = self.day(-5)

    def join(self, batch, count=200):
        """`count` fish of a bathed batch out of C-02 into C-01, 2 days ago."""
        return going_on(stock_services.record_transfer, self.user, source=self.cage2, batch=batch, day=self.day(2),
                        legs=[(self.cage, count)], reason='density')

    def note(self, batch):
        return (f'Cleaner fish in C-01 are in a medicine withdrawal ({batch.code}, harvest from '
                f'{shown_date(self.until)}): keep them out of the harvest.')

    def withdrawals(self, result):
        return [each for each in result.warnings if each.warning == 'withdrawal']


class CleanerFishBesideTests(CleanerWithdrawalTestCase):
    def setUp(self):
        super().setUp()
        self.join(self.bathed_lump)

    def test_the_cleaner_fishs_withdrawal_is_a_note_on_the_salmons_harvest_not_a_warning(self):
        for batch in (self.salmon_batch, None):
            with self.subTest(batch=batch):
                result = check.assess('harvest', self.cage, self.today, batch)
                self.assertEqual(self.withdrawals(result), [])
                self.assertIn(self.note(self.bathed_lump), result.notes)
                self.assertNotIn('No medicine withdrawal in force.', result.notes)   # one is: the cleaner fish's
                self.assertEqual(result.fingerprint, '')                             # nothing to tick

    def test_it_does_not_decide_the_salmons_earliest_harvest_date_nor_their_plan_rows(self):
        self.assertEqual(check.earliest(self.cage, self.salmon_batch).decides, '')
        self.assertEqual(check.in_force(self.cage, self.today), [])
        # The unit's own line (the units list's mark, the card, check_withdrawal's "held now") still shows it.
        self.assertEqual([held.batch_id for held in withdrawal.of_units([self.cage]).get(self.cage.pk, [])],
                         [self.bathed_lump.pk])
        self.assertEqual([block.batch for block in check.in_force_of([self.cage])[self.cage.pk]], [self.bathed_lump])

    def test_the_dialog_says_it_takes_no_box_and_nothing_is_stored_as_the_salmons_acknowledgement(self):
        url = reverse('farm:stock_harvest', args=[self.cage.pk])
        shown = self.client.get(url)
        self.assertContains(shown, self.note(self.bathed_lump))
        self.assertNotContains(shown, 'Not suitable for harvest')
        self.assertNotContains(shown, 'name="handling_ack"')
        data = {'token': str(uuid.uuid4()), 'batch': str(self.salmon_batch.pk), 'date': self.today.isoformat(),
                'count': '100', 'measured_weight_kg': '13', 'facility': str(self.facility.pk), 'notes': ''}
        self.assertEqual(self.client.post(url, data).status_code, 302)
        line = StockMovement.objects.get(kind='harvest')
        self.assertEqual((line.batch, line.count_delta), (self.salmon_batch, -100))
        self.assertFalse(HandlingAcknowledgement.objects.exists())
        entry = AuditLog.objects.get(entity_type='stock operation', action='create', entity_id=str(line.operation_id))
        self.assertNotEqual(entry.severity, 'critical')
        self.assertNotIn('Handling warnings acknowledged', entry.changes)
        out = io.StringIO()
        call_command('check_withdrawal', stdout=out)
        self.assertIn('No harvest lies inside a medicine withdrawal.', out.getvalue())
        self.assertIn(f'C-01 · {self.bathed_lump.code}: harvest from {self.until.isoformat()}.', out.getvalue())


class ProductionFishBesideTests(CleanerWithdrawalTestCase):
    """The other side, as S-02 built it: bathed SALMON join the untreated salmon of C-01 (and its cleaner fish)."""

    def setUp(self):
        super().setUp()
        self.join(self.bathed_salmon, 100)

    def test_a_production_batchs_withdrawal_still_holds_the_unit_whichever_batch_is_named(self):
        for batch in (self.salmon_batch, self.bathed_salmon, None):
            with self.subTest(batch=batch):
                result = check.assess('harvest', self.cage, self.today, batch)
                [warning] = self.withdrawals(result)
                self.assertEqual((warning.block.batch, warning.block.until, warning.shared),
                                 (self.bathed_salmon, self.until, True))
                self.assertIn('It holds every fish in C-01', warning.message())
        self.assertEqual(check.earliest(self.cage, self.salmon_batch).decides, 'withdrawal')
        self.assertEqual([block.batch for block in check.in_force(self.cage, self.today)], [self.bathed_salmon])

    def test_with_bathed_cleaner_fish_beside_them_too_the_warning_is_the_salmons_and_the_note_the_cleaner_fishs(self):
        self.join(self.bathed_lump)
        result = check.assess('harvest', self.cage, self.today, self.salmon_batch)
        self.assertEqual([each.block.batch for each in self.withdrawals(result)], [self.bathed_salmon])
        self.assertIn(self.note(self.bathed_lump), result.notes)
        seen = result.fingerprint
        operation = stock_services.record_harvest(
            self.user, unit=self.cage, batch=self.salmon_batch, day=self.today, count=100,
            measured_weight_kg=Decimal('13'), facility=self.facility, handling_ack=seen)
        self.assertEqual([(row.warning, row.batch) for row in HandlingAcknowledgement.objects.filter(operation=operation)],
                         [('withdrawal', self.bathed_salmon)])
        out = io.StringIO()
        call_command('check_withdrawal', stdout=out)
        self.assertIn('1 harvest lies inside a medicine withdrawal.', out.getvalue())
        self.assertIn(f'lies inside a withdrawal of {self.bathed_salmon.code}, in the same unit', out.getvalue())
        self.assertNotIn(f'lies inside a withdrawal of {self.bathed_lump.code}', out.getvalue())
