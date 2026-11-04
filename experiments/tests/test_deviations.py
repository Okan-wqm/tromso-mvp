"""What happened that the design did not say (`read.deviations`: a batch that came in, fish moved between replicates or out of
the trial, a feed on no band of the diet, a ration that does not follow it), each from the farm's own records and never
blocking them; the Overview that shows them; and `check_experiments`, which checks every started experiment from scratch."""
import io
from datetime import timedelta
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import translation

from farm.feeding import assignments, services as feeding_services
from farm.models import Feed, ProtocolAssignment, Tank
from farm.stock import services as stock_services
from farm.tests.test_stock import make_unit

from .. import integrity, read, services
from ..models import Experiment, Member, ReplicateUnit
from . import D
from .test_overview import RanTrialCase, read_batch


class DeviationCase(RanTrialCase):
    def setUp(self):
        super().setUp()
        translation.activate('en')                 # the texts are read in the active language: a language test leaves its own
        self.addCleanup(translation.deactivate)

    def running(self, other=None, name='Other'):
        """An experiment of its own started by the ORM past the service (what the reads are tested against): a new one, or
        the draft given, which has its tanks by then (a started design cannot change)."""
        other = other or self.experiment(name, starts_on=self.first)
        Experiment.objects.filter(pk=other.pk).update(
            status='running', hypothesis='h', primary_endpoint='bfcr', allocation_method='manual', allocation_note='x')
        other.refresh_from_db()
        return other

    def found(self, code=None, trial=None):
        return [item for item in read.deviations(trial or self.trial) if code in (None, item.code)]

    def shown(self, code=None):
        """What is found as comparable rows: (code, tank, first day, last day, what it is about)."""
        return [(item.code, item.cell.unit.code, item.first, item.last, item.about) for item in self.found(code)]

    def move(self, source, batch, destination, count, days_ago):
        return stock_services.record_transfer(self.user, source=source, batch=batch, day=self.day(days_ago),
                                              legs=[(destination, count)], reason='split')


class NoDeviationTests(DeviationCase):
    def test_a_trial_that_went_as_designed_has_none_and_a_draft_has_none_and_everything_adds_up(self):
        self.assertEqual(self.found(), [])
        draft = self.experiment('Draft', starts_on=self.first)
        self.assertEqual(read.deviations(draft), [])
        self.assertEqual(integrity.problems(), [])
        self.assertEqual(read.deviations(self.running(name='Empty')), [])                  # nothing placed: nothing to read

    def test_a_tank_of_another_species_in_the_replicate_is_never_a_deviation(self):
        cell = read.cells(self.trial)[0]
        ReplicateUnit.objects.create(replicate=cell.replicate, unit=self.tanks[4], from_on=self.first, until_on=self.end)
        self.stock(self.tanks[4], count=500, weight='5', days_ago=20, species=self.trout)
        self.assertEqual(self.found(), [])

    def test_a_placement_that_has_not_begun_is_not_read(self):
        later = self.today + timedelta(days=3)
        cell = read.cells(self.trial)[0]
        ReplicateUnit.objects.create(replicate=cell.replicate, unit=self.tanks[4], from_on=later, until_on=self.end)
        self.assertEqual(self.found(), [])


class ForeignBatchTests(DeviationCase):
    def test_a_batch_of_the_species_that_came_in_after_the_tank_began_is_read_from_the_day_it_came(self):
        batch = self.stock(self.tanks[0], count=100, weight='60', days_ago=10)
        self.assertEqual(self.shown(), [('foreign_batch', 'T-01', self.day(10), self.today, batch.code)])
        self.assertEqual(self.found()[0].text, f'Batch {batch.code} was in T-01, though it was not there on the first day '
                                               'of the tank in the experiment.')
        self.assertEqual(self.found()[0].cell.group.name, 'Control')

    def test_the_days_stop_at_the_last_day_of_the_placement_or_when_the_fish_are_gone(self):
        batch = self.stock(self.tanks[0], count=100, weight='60', days_ago=10)
        self.mortality(batch, 100, days_ago=4, unit=self.tanks[0])
        self.assertEqual(self.shown(), [('foreign_batch', 'T-01', self.day(10), self.day(4), batch.code)])
        ReplicateUnit.objects.filter(unit=self.tanks[0]).update(until_on=self.day(7))
        self.assertEqual(self.shown(), [('foreign_batch', 'T-01', self.day(10), self.day(7), batch.code)])

    def test_the_batch_of_the_first_day_and_a_batch_that_came_with_a_replacement_are_not_deviations(self):
        services.replace_unit(self.user, ReplicateUnit.objects.get(unit=self.tanks[0]), self.tanks[4], self.today,
                              'Pump', Experiment.objects.get(pk=self.trial.pk).version)
        self.stock(self.tanks[4], count=800, weight='60', days_ago=0)                    # in on the tank's first day
        self.assertEqual(self.found(), [])


class TransferTests(DeviationCase):
    def test_fish_moved_between_two_replicates_are_read_from_the_tank_they_left(self):
        self.move(self.tanks[0], self.batches[0], self.tanks[2], 100, days_ago=8)
        moves = self.found('transfer')
        self.assertEqual([(item.cell.unit.code, item.first, item.last) for item in moves],
                         [('T-01', self.day(8), self.day(8))])
        self.assertEqual(moves[0].text, f'100 fish were moved from T-01 to T-03 on {self.day(8).isoformat()}, between two '
                                        'replicates.')
        # and the batch that came into T-03 is read as a batch that came in
        self.assertEqual([(item.code, item.cell.unit.code) for item in self.found()],
                         [('transfer', 'T-01'), ('foreign_batch', 'T-03')])

    def test_fish_moved_to_a_tank_that_is_not_in_the_experiment_or_from_one_are_read(self):
        self.move(self.tanks[1], self.batches[1], self.tanks[6], 50, days_ago=7)
        self.stock(self.tanks[7], count=300, weight='50', days_ago=9)
        batch = read_batch(self.tanks[7])
        self.move(self.tanks[7], batch, self.tanks[3], 30, days_ago=6)
        moves = self.found('transfer')
        self.assertEqual([item.text for item in moves], [
            f'50 fish were moved from T-02 to T-07 on {self.day(7).isoformat()}, and T-07 is not a tank of the experiment.',
            f'30 fish were moved from T-08 to T-04 on {self.day(6).isoformat()}, and T-08 is not a tank of the '
            'experiment.'])
        self.assertEqual([item.cell.unit.code for item in moves], ['T-02', 'T-04'])

    def test_a_move_inside_a_replicate_is_a_replacement_and_a_move_after_the_days_is_nothing(self):
        services.replace_unit(self.user, ReplicateUnit.objects.get(unit=self.tanks[0]), self.tanks[4], self.today,
                              'Pump', Experiment.objects.get(pk=self.trial.pk).version)
        self.move(self.tanks[0], self.batches[0], self.tanks[4], 980, days_ago=0)
        self.assertEqual(self.found(), [])
        ReplicateUnit.objects.filter(unit=self.tanks[1]).update(until_on=self.day(9))
        self.move(self.tanks[1], self.batches[1], self.tanks[6], 50, days_ago=7)                  # after its last day
        self.assertEqual(self.found('transfer'), [])

    def test_a_voided_transfer_is_not_read(self):
        operation = self.move(self.tanks[0], self.batches[0], self.tanks[2], 100, days_ago=8)
        self.assertEqual(len(self.found('transfer')), 1)
        stock_services.void(self.user, operation, 'Entered in error')
        self.assertEqual(self.found(), [])


class FeedTests(DeviationCase):
    def test_feed_on_no_band_of_the_groups_protocol_is_read_with_its_days_count_and_kilos(self):
        starter = Feed.objects.create(name='Starter 2', code='ST-2', feed_type='starter', pellet_size_mm=D(2))
        for ago, kilos in ((3, 2), (2, 3)):
            feeding_services.record_feeding(self.user, unit=self.tanks[1], day=self.day(ago), feed=starter,
                                            amount_kg=Decimal(kilos))
        found = self.found('feed_off_band')
        self.assertEqual([(item.cell.unit.code, item.first, item.last, item.about) for item in found],
                         [('T-02', self.day(3), self.day(2), 'Starter 2')])
        self.assertEqual(found[0].text, 'T-02 was fed Starter 2 (2 feedings, 5.0 kg), which is on no band of Low protein.')

    def test_the_feed_of_a_band_is_never_one_and_neither_is_a_feed_before_or_after_the_days(self):
        starter = Feed.objects.create(name='Starter 2', code='ST-2', feed_type='starter', pellet_size_mm=D(2))
        feeding_services.record_feeding(self.user, unit=self.tanks[1], day=self.day(2), feed=self.feed, amount_kg=D(2))
        ReplicateUnit.objects.filter(unit=self.tanks[1]).update(until_on=self.day(8))
        feeding_services.record_feeding(self.user, unit=self.tanks[1], day=self.day(2), feed=starter, amount_kg=D(2))
        self.assertEqual(self.found('feed_off_band'), [])

    def test_a_group_without_a_diet_has_no_band_to_be_off(self):
        other = self.experiment('No diet', starts_on=self.first)
        self.placement(self.replicate(self.group(other, 'A'), 1), self.tanks[6], first=-20)
        other = self.running(other)
        self.stock(self.tanks[6], count=100, weight='50', days_ago=20)
        starter = Feed.objects.create(name='Starter 2', code='ST-2', feed_type='starter', pellet_size_mm=D(2))
        feeding_services.record_feeding(self.user, unit=self.tanks[6], day=self.day(2), feed=starter, amount_kg=D('0.2'))
        self.assertEqual(read.deviations(other), [])


class RationTests(DeviationCase):
    def test_a_protocol_assigned_to_the_batch_in_the_unit_beats_the_units_and_is_read_for_its_days(self):
        ProtocolAssignment.objects.create(protocol=self.high, unit=self.tanks[0], batch=self.batches[0], valid_from=self.day(5))
        found = self.found('ration_off_diet')
        self.assertEqual([(item.cell.unit.code, item.first, item.last, item.about) for item in found],
                         [('T-01', self.day(5), self.today, 'High protein')])
        self.assertEqual(found[0].text, 'The ration of T-01 follows High protein, though Low protein is the diet of its '
                                        f'group, from {self.day(5).isoformat()} to {self.today.isoformat()}.')

    def test_a_tank_whose_diet_row_was_ended_has_no_protocol_for_the_days_after(self):
        row = ProtocolAssignment.objects.get(unit=self.tanks[1], notes__startswith=self.trial.code)
        assignments.end(self.user, row, self.day(1))
        found = self.found('ration_off_diet')
        self.assertEqual([(item.cell.unit.code, item.first, item.last, item.about) for item in found],
                         [('T-02', self.today, self.today, '')])
        self.assertEqual(found[0].text, 'No feeding protocol reaches T-02, though Low protein is the diet of its group, '
                                        f'from {self.today.isoformat()} to {self.today.isoformat()}.')

    def test_separate_runs_of_days_are_separate_deviations(self):
        ProtocolAssignment.objects.create(protocol=self.high, unit=self.tanks[0], batch=self.batches[0], valid_from=self.day(9),
                                          valid_until=self.day(7))
        ProtocolAssignment.objects.create(protocol=self.high, unit=self.tanks[0], batch=self.batches[0], valid_from=self.day(4),
                                          valid_until=self.day(3))
        self.assertEqual([(item.first, item.last) for item in self.found('ration_off_diet')],
                         [(self.day(9), self.day(7)), (self.day(4), self.day(3))])


class OverviewTests(DeviationCase):
    def setUp(self):
        super().setUp()
        self.url = reverse('experiments:experiment_detail', args=[self.trial.pk])

    def test_the_overview_says_there_is_none_or_lists_each_with_its_replicate_tank_and_days(self):
        page = self.client.get(self.url)
        self.assertContains(page, 'Deviations from the design')
        self.assertContains(page, 'No deviation from the design is found in the farm')
        ProtocolAssignment.objects.create(protocol=self.high, unit=self.tanks[0], batch=self.batches[0], valid_from=self.day(5))
        page = self.client.get(self.url)
        self.assertNotContains(page, 'No deviation from the design is found')
        self.assertContains(page, 'The ration of T-01 follows High protein, though Low protein is the diet of its group')
        self.assertContains(page, 'Control R1')
        self.assertEqual([item.code for item in page.context['deviations']], ['ration_off_diet'])

    def test_a_draft_shows_what_is_wrong_and_no_deviations(self):
        draft = self.experiment('Draft', starts_on=self.first)
        page = self.client.get(reverse('experiments:experiment_detail', args=[draft.pk]))
        self.assertNotContains(page, 'Deviations from the design')

    def test_the_texts_come_in_the_readers_language(self):
        from core.models import Profile
        ProtocolAssignment.objects.create(protocol=self.high, unit=self.tanks[0], batch=self.batches[0], valid_from=self.day(5))
        for language, words in {'tr': ('Tasarımdan sapmalar', 'T-01 rasyonu'), 'nb': ('Avvik fra opplegget', 'Rasjonen til T-01')}.items():
            Profile.objects.update_or_create(user=self.user, defaults={'language': language})
            page = self.client.get(self.url)
            for word in words:
                self.assertContains(page, word, msg_prefix=language)
            self.assertNotIn('%(', page.content.decode())


class BudgetTests(DeviationCase):
    """The queries do not grow with the tanks: 6 or 60 (a diet, feeding, batches and a transfer in each)."""

    def trial_of(self, count):
        trial = self.experiment(f'{count} tanks', starts_on=self.day(10))
        units = [make_unit(f'D{count}-{number:02d}', self.hall) for number in range(count)]
        stock_services.record_input(self.user, species=self.salmon, input_stage='fry', origin='own_hatchery',
                                    day=self.day(10), lines=[(unit, 100, D(50)) for unit in units])
        factor = self.factor(trial)
        level = self.level(factor, self.protocol(f'Protocol {count}'))
        group = self.group(trial, 'A')
        self.group_level(group, level)
        for number, unit in enumerate(units, start=1):
            ReplicateUnit.objects.create(replicate=self.replicate(group, number), unit=unit, from_on=self.day(10),
                                         until_on=self.day(10) + timedelta(days=56))
            ProtocolAssignment.objects.create(protocol=level.protocol, unit=unit, valid_from=self.day(10),
                                              valid_until=self.day(10) + timedelta(days=56))
            feeding_services.record_feeding(self.user, unit=unit, day=self.day(5), feed=self.feed, amount_kg=D('0.2'))
        Experiment.objects.filter(pk=trial.pk).update(
            status='running', hypothesis='h', primary_endpoint='bfcr', allocation_method='manual', allocation_note='x')
        trial.refresh_from_db()
        return trial, units

    def count(self, call):
        with CaptureQueriesContext(connection) as queries:
            call()
        return len(queries)

    def test_deviations_cost_the_same_for_6_tanks_and_60(self):
        small, small_units = self.trial_of(6)
        large, large_units = self.trial_of(60)
        self.assertEqual(self.found(trial=small), [])
        for trial, units in ((small, small_units), (large, large_units)):                # something of every rule to read
            self.stock(units[0], count=10, weight='60', days_ago=4)
            self.move(units[1], read_batch(units[1]), units[2], 5, days_ago=3)
            ProtocolAssignment.objects.create(protocol=self.high, unit=units[3], batch=read_batch(units[3]), valid_from=self.day(2))
            starter = Feed.objects.get_or_create(code='ST-2', defaults={
                'name': 'Starter 2', 'feed_type': 'starter', 'pellet_size_mm': D(2)})[0]
            feeding_services.record_feeding(self.user, unit=units[4], day=self.day(2), feed=starter, amount_kg=D('0.2'))
        codes = lambda trial: sorted({item.code for item in read.deviations(trial)})
        self.assertEqual(codes(small), codes(large))
        self.assertEqual(codes(large), ['feed_off_band', 'foreign_batch', 'ration_off_diet', 'transfer'])
        self.assertEqual(self.count(lambda: read.deviations(small)), self.count(lambda: read.deviations(large)))


class IntegrityTests(DeviationCase):
    def lost(self, sql):
        """A rule broken under the database's guard, by raw SQL with the triggers of the design off (a hand edit in the
        database): the test's own transaction is rolled back, and the triggers with it."""
        with connection.cursor() as cursor:
            cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
            for table in ('experiment_group_levels', 'experiment_replicate_units'):
                cursor.execute(f'ALTER TABLE {table} DISABLE TRIGGER USER')
            cursor.execute(sql)

    def test_everything_adds_up_through_the_scenarios(self):
        self.assertEqual(integrity.problems(), [])
        out = io.StringIO()
        call_command('check_experiments', stdout=out)
        self.assertIn('The experiments add up.', out.getvalue())

    def test_a_running_placement_without_its_diet_row_or_with_one_that_ends_elsewhere_is_found(self):
        row = ProtocolAssignment.objects.get(unit=self.tanks[0], notes__startswith=self.trial.code)
        ProtocolAssignment.all_objects.filter(pk=row.pk).delete()
        ProtocolAssignment.objects.filter(unit=self.tanks[1]).update(valid_until=self.day(-30))
        code = self.trial.code
        self.assertEqual(integrity.problems(), [
            f'{code}: T-01 of Control R1 has no feeding assignment of Low protein from {self.first} (the diet of Control).',
            f'{code}: T-02 of Control R2 is placed until {self.end}, but its feeding assignment of Low protein ends on '
            f'{self.day(-30)}.'])

    def test_a_released_or_replaced_placement_keeps_its_row_to_the_day_it_ends(self):
        placement = ReplicateUnit.objects.get(unit=self.tanks[1])
        services.release_unit(self.user, placement, self.day(1), 'Pump', Experiment.objects.get(pk=self.trial.pk).version)
        placement = ReplicateUnit.objects.get(unit=self.tanks[0])
        services.replace_unit(self.user, placement, self.tanks[4], self.today, 'Pump',
                              Experiment.objects.get(pk=self.trial.pk).version)
        self.assertEqual(integrity.problems(), [])

    def test_a_closed_experiment_is_checked_for_its_design_but_not_for_its_rows(self):
        Experiment.objects.filter(pk=self.trial.pk).update(status='closed')
        ProtocolAssignment.all_objects.filter(unit=self.tanks[0]).delete()
        self.assertEqual(integrity.problems(), [])
        self.lost(f"DELETE FROM experiment_group_levels WHERE group_id = '{read.cells(self.trial)[0].group.pk}'")
        self.assertEqual(integrity.problems(), [f'{self.trial.code}: Group Control has no level of Diet.'])

    def test_a_design_that_lost_a_part_a_tank_off_the_site_or_outside_the_days_or_deleted_is_found(self):
        self.lost(f"UPDATE experiment_replicate_units SET until_on = until_on + 5 WHERE unit_id = '{self.tanks[1].pk}'")
        Tank.objects.filter(pk=self.tanks[2].pk).update(is_deleted=True)
        self.lost(f"DELETE FROM experiment_group_levels WHERE group_id = '{read.cells(self.trial)[3].group.pk}'")
        code = self.trial.code
        self.assertEqual(integrity.problems(), [
            f'{code}: Group High feed has no level of Diet.',
            f'{code}: T-02 of Control R2 is booked outside the days of the experiment.',
            f'{code}: T-03 of High feed R1 was deleted while it is in the experiment.',
            f'{code}: T-02 of Control R2 is placed until {self.end + timedelta(days=5)}, but its feeding assignment of '
            f'Low protein ends on {self.end}.'])

    def test_the_team_without_a_lead_and_a_draft_with_nothing_are_found_and_passed(self):
        Member.objects.filter(experiment=self.trial).delete()
        self.experiment('Draft', starts_on=self.first)                          # a draft is not started: not checked
        self.assertEqual(integrity.problems(), [f'{self.trial.code}: The team has no lead.'])

    def test_the_command_prints_what_it_finds_and_fails(self):
        Member.objects.filter(experiment=self.trial).delete()
        out = io.StringIO()
        with self.assertRaises(CommandError) as caught:
            call_command('check_experiments', stdout=out)
        self.assertEqual(out.getvalue().strip(), f'{self.trial.code}: The team has no lead.')
        self.assertEqual(str(caught.exception), '1 problem(s) in the experiments.')
