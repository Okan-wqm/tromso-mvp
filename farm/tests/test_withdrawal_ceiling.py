"""A medicine withdrawal whose END IS UNKNOWN stops holding after a ceiling (the owner's decision 10 of 17.11.2026;
withdrawal rule 8): the platform owner's setting "An unknown withdrawal end holds for (days)", 180 until they set
another, counted from the course's last day (the medicated feeding's day).

Inside the ceiling it holds and spreads as any other hold. After it the fish are not held (no warning, no delete
block), and the course is listed as an unresolved old course on the Treatments page and by `check_withdrawal`, with
what the farm must enter to give it an end. The two records it covers: a medicine with no withdrawal row for the
species, a medicated feeding with no treatment. **It does not apply to a degree-day withdrawal** (decision 11 of
18.11.2026, following decision 9): degree-days that are short, or cannot be counted for want of a temperature, hold
until the farm records the water temperature or sets the species' assumed temperature, as they always did.
Changing the ceiling is a rule change: the guard asks when a shorter one would free fish held today, and when a longer
one would hold fish again or bring a recorded harvest inside a withdrawal; the data layer refuses it anywhere else."""
import io
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.urls import reverse
from django.utils import translation

from core.models import AuditLog, PlatformSettings

from .. import withdrawal_gate
from ..feeding import services as feeding_services
from ..handling import check
from ..health import withdrawal
from ..models import Feed, HandlingAcknowledgement, WithdrawalAcknowledgement
from ..stock import services as stock_services
from .helpers import correction_window, going_on, may_record, role
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
            may_record(self.user, 'add_feedingrecord')  # the feeding service asks (L-6)
            record = going_on(feeding_services.record_feeding, self.user, unit=self.t2, day=self.day(200), feed=feed,
                              amount_kg=Decimal('2'))
            recent = going_on(feeding_services.record_feeding, self.user, unit=self.t2, day=self.day(100), feed=feed,
                              amount_kg=Decimal('2'))
        [held] = self.held(self.t2)                                      # the recent one holds; the old one does not
        self.assertEqual((held.feeding, held.until), (recent, None))
        self.assertEqual(self.listed(), [(self.o.code, record)])
        self.assertIn('Record the treatment under Health › Treatments.', self.command())

    def test_degree_days_that_cannot_be_counted_hold_whatever_their_age_and_say_what_gives_an_end(self):
        self.assertIsNone(self.salmon.withdrawal_temperature_c)
        self.old_course(200, self.medicine(name='Slice vet.', degree_days=500))
        [held] = self.held(self.t2)
        self.assertEqual((held.batch_id, held.until, held.gives_up), (self.o.pk, None, None))
        self.assertEqual(self.listed(), [])
        text = withdrawal.describe(held)
        self.assertIn('The end cannot be worked out: record the water temperature.', text)
        self.assertIn('are counted as 0 °C: set the species’ assumed temperature in Reference data › Species.', text)

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


class DegreeDaysTests(CeilingTestCase):
    """Decision 11: the ceiling never frees a degree-day withdrawal. The verifier's schedule (V-5): Slice, 500
    degree-days, given 185 days ago in C-01; 2 °C measured every day until 32 days ago (306 of 500 counted), nothing
    since; the species has no assumed temperature. Main holds these fish, end unknown, until a temperature is recorded."""

    def setUp(self):
        super().setUp()
        self.tank = make_unit('C-01', self.hall)
        self.slice = self.medicine(name='Slice vet.', degree_days=500)
        with correction_window(3650):
            self.p = self.stock(self.tank, count=3000, days_ago=300)
            self.course = self.going_on(self.treat, self.slice, 185, 185, units=[self.tank])

    def cold(self):
        for days_ago in range(32, 185):
            self.temperature(self.tank, days_ago, '2')

    def harvest(self, **fields):
        return stock_services.record_harvest(self.user, unit=self.tank, batch=self.p, day=self.today, count=50,
                                             measured_weight_kg=Decimal('6'), facility=self.facility, **fields)

    def assert_held_as_main_holds_it(self):
        self.assertEqual(self.ends(self.tank), [(self.p.pk, None)])                 # the unit's line
        self.assertEqual(self.ends(self.tank, self.day(-400)), [(self.p.pk, None)])   # and no day it gives up
        result = check.assess('harvest', self.tank, self.today, self.p)             # the harvest dialog
        [warning] = [each for each in result.warnings if each.warning == 'withdrawal']
        self.assertEqual((warning.block.batch, warning.block.until), (self.p, None))
        self.assertTrue(any(note.startswith('Earliest suitable harvest date: not known.') for note in result.notes),
                        result.notes)
        self.assertNotIn('No medicine withdrawal in force.', result.notes)
        [reason] = self.tank.withdrawal_blockers()                                  # the delete block
        self.assertIn(self.p.code, reason)
        with self.assertRaises(ValidationError) as refused:                         # the harvest without the tick
            self.harvest()
        self.assertEqual(refused.exception.message_dict,
                         {'handling_ack': ['Tick the box to go on despite these warnings.']})
        self.assertEqual(self.listed(), [])                                         # not an unresolved old course
        out = self.command()
        self.assertIn(f'C-01 · {self.p.code}: end unknown. Slice vet., bath from ', out)
        self.assertIn('The end cannot be worked out: record the water temperature.', out)
        self.assertIn('are counted as 0 °C: set the species’ assumed temperature in Reference data › Species.', out)
        self.assertNotIn('Unresolved old course', out)
        self.assertIn('No harvest lies inside a medicine withdrawal.', out)

    def test_the_verifiers_cold_course_is_held_on_every_reader(self):
        self.cold()
        self.assert_held_as_main_holds_it()
        [held] = self.held(self.tank)
        self.assertEqual((held.estimated, held.remaining_degree_days, held.gives_up), (True, Decimal('194'), None))

    def test_its_harvest_goes_on_only_past_the_tick_and_is_stored_and_listed(self):
        self.cold()
        seen = check.assess('harvest', self.tank, self.today, self.p).fingerprint
        operation = self.harvest(handling_ack=seen)
        row = HandlingAcknowledgement.objects.get()
        self.assertEqual((row.operation, row.warning, row.batch, row.withdrawal_until),
                         (operation, 'withdrawal', self.p, None))
        out = self.command()
        self.assertIn('lies inside a withdrawal (end unknown)', out)
        self.assertIn('Acknowledged when the harvest was recorded.', out)

    def test_the_treatments_page_holds_it_and_says_what_gives_it_an_end(self):
        self.cold()
        self.user.groups.add(role('Treatments reader', 'view_treatment'))
        page = self.client.get(reverse('farm:treatments'))
        self.assertNotContains(page, 'Unresolved old courses')
        self.assertContains(page, 'class="over-text"')                               # held today
        self.assertContains(page, 'The end cannot be worked out: record the water temperature.')
        self.assertContains(page, 'are counted as 0 °C: set the species’ assumed temperature in Reference data › Species.')

    def test_one_sample_gives_it_an_end_as_it_did(self):
        self.cold()
        self.temperature(self.tank, 1, '2')
        [held] = self.held(self.tank)
        self.assertEqual((held.until, held.estimated), (self.day(-96), True))      # 192 to go at 2 °C: 96 days
        self.assertNotIn('The end cannot be worked out', withdrawal.describe(held))

    def test_a_course_that_ended_today_with_nothing_to_project_at_says_both_records_that_give_an_end(self):
        self.going_on(self.treat, self.slice, 0, 0, units=[self.t2])     # no day to count yet, none measured
        [held] = self.held(self.t2)
        self.assertEqual((held.until, held.days_without_temperature, held.gives_up), (None, 0, None))
        self.assertIn('The end cannot be worked out: record the water temperature. Or set the assumed water '
                      'temperature of Atlantic salmon in Reference data › Species: the days without a measured '
                      'temperature then count.', withdrawal.describe(held))

    def test_a_mean_of_zero_degrees_is_held_too(self):
        for days_ago in range(0, 9):                                                # sea water in winter, every day
            self.temperature(self.tank, days_ago, '0')
        self.assert_held_as_main_holds_it()

    def test_a_mean_below_zero_is_held_too(self):
        for days_ago in range(0, 9):
            self.temperature(self.tank, days_ago, '-0.5')
        self.assert_held_as_main_holds_it()

    def test_no_temperature_at_all_is_held_too(self):
        self.assert_held_as_main_holds_it()

    def test_the_ceiling_made_shorter_asks_nothing_of_it(self):
        self.user.groups.add(role('Platform owner', 'view_platformsettings', 'change_platformsettings'))
        row = PlatformSettings.get()
        data = {'correction_window_days': row.correction_window_days, 'clock_tolerance_seconds': 300,
                'plan_batch_cells': 500,
                'unknown_withdrawal_days': 30, 'version': row.version}
        self.assertEqual(self.client.post(reverse('core:platformsettings_edit', args=[row.pk]), data).status_code, 302)
        self.assertEqual(self.ends(self.tank), [(self.p.pk, None)])
        self.assertFalse(WithdrawalAcknowledgement.objects.exists())


class SettingTestCase(CeilingTestCase):
    """The platform owner edits the setting on its page."""

    def setUp(self):
        super().setUp()
        self.user.groups.add(role('Platform owner', 'view_platformsettings', 'change_platformsettings'))
        self.row = PlatformSettings.get()

    def edit(self, days, **more):
        data = {'correction_window_days': self.row.correction_window_days, 'clock_tolerance_seconds': 300,
                'plan_batch_cells': 500,
                'unknown_withdrawal_days': days, 'version': PlatformSettings.get().version, **more}
        return self.client.post(reverse('core:platformsettings_edit', args=[self.row.pk]), data)


class CeilingMadeLongerTests(SettingTestCase):
    """A course 200 days ago with no row gave up 20 days ago (the ceiling is 180): O in T-02 is free. A longer ceiling
    is a change of the rule too (verification of S-03, V-7): it holds those fish again, and a harvest recorded since
    the course gave up lies inside the withdrawal after it. Both are asked, stored and logged as critical."""

    def setUp(self):
        super().setUp()
        self.course = self.old_course(200)

    def harvest(self, days_ago=10):
        return stock_services.record_harvest(self.user, unit=self.t2, batch=self.o, day=self.day(days_ago), count=100,
                                             measured_weight_kg=Decimal('13'), facility=self.facility)

    def again(self, batch, unit):
        return f'{batch.code} in {unit} is not held today and would be held again by a medicine withdrawal'

    def test_it_asks_about_the_harvest_it_brings_inside_and_stores_the_answer(self):
        harvest = self.harvest()                                         # free that day: no tick, no row
        self.assertFalse(HandlingAcknowledgement.objects.exists())
        refused = self.edit(365)
        self.assertEqual(refused.status_code, 422)
        self.assertContains(refused, 'lies inside this withdrawal (end unknown): medicated fish may have gone to food.',
                            status_code=422)
        self.assertContains(refused, self.again(self.o, 'T-02'), status_code=422)
        self.assertContains(refused, 'name="withdrawal_ack"', status_code=422)
        self.assertEqual(PlatformSettings.get().unknown_withdrawal_days, 180)       # nothing saved
        self.assertEqual(self.ends(self.t2), [])
        change = refused.context['withdrawal_change']
        self.assertEqual([found.operation_id for found in change.harvested], [harvest.pk])
        self.assertEqual(self.edit(365, withdrawal_ack=change.fingerprint).status_code, 302)
        self.assertEqual(PlatformSettings.get().unknown_withdrawal_days, 365)
        self.assertEqual(self.ends(self.t2), [(self.o.pk, None)])
        self.assertEqual(self.listed(), [])
        self.assertCountEqual(
            WithdrawalAcknowledgement.objects.values_list('warning', 'batch', 'harvest', 'record_type', 'source'),
            [('harvested', self.o.pk, harvest.pk, 'platform settings', f'treatment:{self.course.pk}'),
             ('held', self.o.pk, None, 'platform settings', f'treatment:{self.course.pk}')])
        entry = AuditLog.objects.get(entity_type='platform settings', severity='critical')
        said = entry.changes['Withdrawal warnings acknowledged'][1]
        self.assertIn('lies inside this withdrawal (end unknown)', said)
        self.assertIn(self.again(self.o, 'T-02'), said)
        out = self.command()
        self.assertIn('Acknowledged when the platform settings was recorded.', out)
        self.assertNotIn('Not acknowledged', out)
        self.assertNotIn('Unresolved old course', out)

    def test_it_asks_before_it_holds_fish_again_the_shared_ones_too(self):
        with correction_window(3650):                                    # O's fish went in beside A while held
            going_on(stock_services.record_transfer, self.user, source=self.t2, batch=self.o, day=self.day(8),
                     legs=[(self.t1, 500)], reason='density')
        self.assertEqual(self.ends(self.t1), [])                         # not held then (given up): nothing asked
        refused = self.edit(365)
        self.assertEqual(refused.status_code, 422)
        change = refused.context['withdrawal_change']
        self.assertEqual(sorted((each.batch.code, each.unit.code) for each in change.held_again),
                         sorted([(self.a.code, 'T-01'), (self.o.code, 'T-01'), (self.o.code, 'T-02')]))
        self.assertEqual((change.harvested, change.released), ([], []))
        for batch, unit in ((self.a, 'T-01'), (self.o, 'T-01'), (self.o, 'T-02')):
            self.assertContains(refused, self.again(batch, unit), status_code=422)
        self.assertEqual(PlatformSettings.get().unknown_withdrawal_days, 180)
        self.assertEqual(self.edit(365, withdrawal_ack=change.fingerprint).status_code, 302)
        self.assertCountEqual(WithdrawalAcknowledgement.objects.values_list('warning', 'batch', 'record_type'),
                              [('held', self.a.pk, 'platform settings'), ('held', self.o.pk, 'platform settings'),
                               ('held', self.o.pk, 'platform settings')])
        self.assertTrue(AuditLog.objects.filter(entity_type='platform settings', severity='critical').exists())
        self.assertCountEqual(self.ends(self.t1), [(self.o.pk, None)])
        self.assertEqual(self.ends(self.t2), [(self.o.pk, None)])

    def test_a_harvest_older_than_the_correction_window_is_asked_about_too(self):
        with correction_window(3650):
            self.old_course(700, self.course.medicine)                   # gave up 520 days ago
            harvest = self.harvest(days_ago=400)                         # 300 days after it: free then
        change = self.edit(365).context['withdrawal_change']
        self.assertEqual([found.operation_id for found in change.harvested], [harvest.pk])

    def test_a_longer_ceiling_that_holds_nobody_again_asks_nothing(self):
        self.assertEqual(self.edit(190).status_code, 302)                # 200 days ago: still given up
        self.assertEqual(PlatformSettings.get().unknown_withdrawal_days, 190)
        self.assertFalse(WithdrawalAcknowledgement.objects.exists())
        self.assertEqual(self.ends(self.t2), [])

    def test_the_question_is_translated(self):
        change = self.edit(365).context['withdrawal_change']
        for language, words in (('nb', 'holdes tilbake igjen'), ('tr', 'yeniden')):
            with translation.override(language):
                self.assertIn(words, change.messages()[0], language)


class CeilingChangedTests(SettingTestCase):
    """A course 170 days ago with no row holds O in T-02 (the ceiling is 180)."""

    def setUp(self):
        super().setUp()
        self.old_course(170)

    def test_making_it_shorter_asks_before_it_frees_fish_held_today(self):
        refused = self.edit(100)
        self.assertEqual(refused.status_code, 422)
        self.assertContains(refused, f'{self.o.code} in T-02 is held today', status_code=422)
        self.assertContains(refused, 'name="withdrawal_ack"', status_code=422)
        self.assertEqual(PlatformSettings.get().unknown_withdrawal_days, 180)
        self.assertEqual(self.ends(self.t2), [(self.o.pk, None)])
        fingerprint = refused.context['withdrawal_change'].fingerprint
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
