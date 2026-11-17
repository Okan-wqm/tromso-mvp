"""A medicine withdrawal whose END IS UNKNOWN stops holding after a ceiling (the owner's decision 10 of 17.11.2026;
withdrawal rule 8): the platform owner's setting "An unknown withdrawal end holds for (days)", 180 until they set
another, counted from the course's last day (the medicated feeding's day).

Inside the ceiling it holds and spreads as any other hold. After it the fish are not held (no warning, no delete
block), and the course is listed as an unresolved old course on the Treatments page and by `check_withdrawal`, with
what the farm must enter to give it an end. The three records that make an unknown end: a medicine with no
withdrawal row, a medicated feeding with no treatment, a degree-day end with no temperature. Changing the ceiling is a
rule change: the guard asks when it would free fish held today; the data layer refuses it anywhere else."""
import io
from decimal import Decimal

from django.core.management import call_command
from django.urls import reverse

from core.models import AuditLog, PlatformSettings

from .. import withdrawal_gate
from ..feeding import services as feeding_services
from ..handling import check
from ..health import withdrawal
from ..models import Feed, WithdrawalAcknowledgement
from ..stock import services as stock_services
from .helpers import correction_window, going_on, role
from .test_harvest_inside_withdrawal import HarvestInsideTestCase
from .test_stock import make_unit


class CeilingTestCase(HarvestInsideTestCase):
    """T-01: batch A (the fixture's, 10 days). OLD: batch O, stocked 720 days ago in T-02."""

    def setUp(self):
        super().setUp()
        self.a = self.batch
        self.t3 = make_unit('T-03', self.hall)
        with correction_window(3650):
            self.o = self.stock(self.t2, count=3000, days_ago=720)

    def old_course(self, days_ago, medicine=None, units=None):
        """A course `days_ago` days back (default medicine: one with no withdrawal row)."""
        with correction_window(3650):
            return self.going_on(self.treat, medicine or self.medicine(name='No row'), days_ago, days_ago,
                                 units=units or [self.t2])

    def ends(self, unit, day=None):
        return [(held.batch_id, held.until) for held in self.held(unit, day)]

    def command(self):
        out = io.StringIO()
        call_command('check_withdrawal', stdout=out)
        return out.getvalue()

    def listed(self):
        return [(batch.code, held.source) for batch, held in withdrawal.unresolved()]


class UnknownEndCeilingTests(CeilingTestCase):
    def test_the_reviewers_course_of_700_days_ago_with_no_row_holds_nobody_and_is_listed(self):
        course = self.old_course(700)
        with correction_window(3650):                                   # its fish went on beside A, long ago
            going_on(stock_services.record_transfer, self.user, source=self.t2, batch=self.o, day=self.day(600),
                     legs=[(self.t3, 500)], reason='density')
        for unit in (self.t1, self.t2, self.t3):
            self.assertEqual(self.ends(unit), [], unit.code)
        result = check.assess('harvest', self.t2, self.today, self.o)
        self.assertEqual([each for each in result.warnings if each.warning == 'withdrawal'], [])
        self.assertIn('No medicine withdrawal in force.', result.notes)
        self.assertEqual(self.t2.withdrawal_blockers(), [])
        self.assertEqual(self.listed(), [(self.o.code, course)])
        out = self.command()
        self.assertIn('0 of 3 units with fish are under a medicine withdrawal.', out)
        self.assertIn(f'Unresolved old course · {self.o.code}: No row, bath from ', out)
        self.assertIn('No withdrawal is recorded for Atlantic salmon of No row: add it in Reference data › Medicines.',
                      out)
        self.assertIn('1 unresolved old course: the end is unknown and the fish are no longer held', out)

    def test_inside_the_ceiling_it_holds_and_spreads_and_is_not_listed(self):
        self.old_course(170)
        with correction_window(3650):
            going_on(stock_services.record_transfer, self.user, source=self.t2, batch=self.o, day=self.day(100),
                     legs=[(self.t1, 500)], reason='density')            # in beside A: A is held with them
        self.assertEqual(self.ends(self.t2), [(self.o.pk, None)])
        self.assertCountEqual(self.ends(self.t1), [(self.o.pk, None)])
        [warning] = [each for each in check.assess('harvest', self.t1, self.today, self.a).warnings
                     if each.warning == 'withdrawal']
        self.assertIsNone(warning.block.until)
        self.assertEqual(self.listed(), [])
        self.assertTrue(self.t2.withdrawal_blockers())
        # The last held day is the 180th after the course's last day; the day after, nobody is held.
        self.assertEqual(self.ends(self.t2, self.day(-10)), [(self.o.pk, None)])
        self.assertEqual(self.ends(self.t2, self.day(-11)), [])
        self.assertEqual(self.ends(self.t1, self.day(-11)), [])

    def test_medicated_feed_with_no_treatment_gives_up_and_is_listed(self):
        feed = Feed.objects.create(name='Medisinfôr', code='MED-1', feed_type='medicated')
        with correction_window(3650):
            record = going_on(feeding_services.record_feeding, self.user, unit=self.t2, day=self.day(200), feed=feed,
                              amount_kg=Decimal('2'))
            recent = going_on(feeding_services.record_feeding, self.user, unit=self.t2, day=self.day(100), feed=feed,
                              amount_kg=Decimal('2'))
        [held] = self.held(self.t2)                                      # the recent one holds; the old one does not
        self.assertEqual((held.feeding, held.until), (recent, None))
        self.assertEqual(self.listed(), [(self.o.code, record)])
        self.assertIn('Record the treatment under Health › Treatments.', self.command())

    def test_degree_days_that_cannot_be_counted_give_up_and_say_the_species_temperature(self):
        self.assertIsNone(self.salmon.withdrawal_temperature_c)
        course = self.old_course(200, self.medicine(name='Slice vet.', degree_days=500))
        self.assertEqual(self.ends(self.t2), [])
        self.assertEqual(self.listed(), [(self.o.code, course)])
        [(batch, held)] = withdrawal.unresolved()
        text = withdrawal.unresolved_text(batch, held)
        self.assertIn('The end cannot be worked out: record the water temperature.', text)
        self.assertIn('Or set the assumed water temperature of Atlantic salmon in Reference data › Species', text)

    def test_a_course_with_a_known_end_is_never_listed_however_old(self):
        self.old_course(700, self.medicine(days=7))
        self.assertEqual(self.listed(), [])
        self.assertNotIn('Unresolved old course', self.command())

    def test_the_treatments_page_lists_the_unresolved_course_with_what_to_enter(self):
        self.user.groups.add(role('Treatments reader', 'view_treatment'))
        self.old_course(700)
        page = self.client.get(reverse('farm:treatments'))
        self.assertContains(page, 'Unresolved old courses')
        self.assertContains(page, f'{self.o.code}: No row, bath from ')
        self.assertContains(page, 'add it in Reference data › Medicines.')
        self.assertContains(page, 'older than 180 days')


class CeilingChangedTests(CeilingTestCase):
    """A course 170 days ago with no row holds O in T-02 (the ceiling is 180)."""

    def setUp(self):
        super().setUp()
        self.old_course(170)
        self.user.groups.add(role('Platform owner', 'view_platformsettings', 'change_platformsettings'))
        self.row = PlatformSettings.get()

    def edit(self, days, **more):
        data = {'correction_window_days': self.row.correction_window_days, 'clock_tolerance_seconds': 300,
                'unknown_withdrawal_days': days, 'version': PlatformSettings.get().version, **more}
        return self.client.post(reverse('core:platformsettings_edit', args=[self.row.pk]), data)

    def test_making_it_shorter_asks_before_it_frees_fish_held_today(self):
        refused = self.edit(100)
        self.assertEqual(refused.status_code, 422)
        self.assertContains(refused, f'{self.o.code} in T-02 is held today', status_code=422)
        self.assertContains(refused, 'name="withdrawal_ack"', status_code=422)
        self.assertEqual(PlatformSettings.get().unknown_withdrawal_days, 180)
        self.assertEqual(self.ends(self.t2), [(self.o.pk, None)])
        fingerprint = refused.context['form'].withdrawal_change.fingerprint
        self.assertEqual(self.edit(100, withdrawal_ack=fingerprint).status_code, 302)
        self.assertEqual(PlatformSettings.get().unknown_withdrawal_days, 100)
        self.assertEqual(self.ends(self.t2), [])
        row = WithdrawalAcknowledgement.objects.get()
        self.assertEqual((row.warning, row.batch, row.record_type), ('released', self.o, 'platform settings'))
        self.assertTrue(AuditLog.objects.filter(entity_type='platform settings', severity='critical').exists())
        self.assertEqual([batch.code for batch, _held in withdrawal.unresolved()], [self.o.code])

    def test_making_it_longer_asks_nothing_and_a_change_that_frees_nobody_neither(self):
        self.assertEqual(self.edit(175).status_code, 302)                # still held: 170 days ago
        self.assertEqual(self.edit(400).status_code, 302)
        self.assertFalse(WithdrawalAcknowledgement.objects.exists())
        self.assertEqual(self.ends(self.t2), [(self.o.pk, None)])

    def test_the_change_is_logged_with_its_old_and_new_value(self):
        self.edit(400)
        entry = AuditLog.objects.filter(entity_type='platform settings', action='update').latest('pk')
        self.assertEqual(entry.changes['An unknown withdrawal end holds for (days)'], ['180', '400'])

    def test_the_data_layer_refuses_the_change_outside_the_guard(self):
        with self.assertRaises(withdrawal_gate.UnguardedWithdrawalWrite):
            PlatformSettings.objects.update(unknown_withdrawal_days=10)
        row = PlatformSettings.get()
        row.unknown_withdrawal_days = 10
        with self.assertRaises(withdrawal_gate.UnguardedWithdrawalWrite):
            row.save()
        self.assertEqual(PlatformSettings.get().unknown_withdrawal_days, 180)
