"""Reading an experiment: every figure of the overview equals the farm's own number for the same stay and days, no figure
is stored or copied, the queries do not grow with the tanks, the placements a tank has on a day, and the read page's
Overview and Data tabs."""
from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from farm.feeding import read as feeding_read, services as feeding_services
from farm.models import StockMovement
from farm.stock import read as stock_read, services as stock_services
from farm.tests.test_stock import make_unit

from .. import read, services
from ..models import Experiment, ReplicateUnit
from . import D
from farm.tests.helpers import may_record, role

from .test_pages import RESEARCHER, PageTestCase, person
from .test_start import StartTestCase


class RanTrialCase(StartTestCase):
    """A trial that began 20 days ago: four tanks of 1,000 salmon of 50 g stocked on day 0, 2 kg fed a day to each from day 1
    to day 13, weighed at 70 g on day 14 in the control group's tanks (T-01, T-02) and not in the other two, 20 fish lost in
    T-01 on day 15; started."""

    days_ago = 20

    def setUp(self):
        super().setUp()
        self.user.groups.add(role('Researcher', *RESEARCHER),
                             role('Farm reader', 'view_feedingrecord', 'view_treatment', 'view_licecount',
                                  'view_watermeasurement', 'view_stockoperation'))
        may_record(self.user)                     # the fixture's feedings and weighings: the services ask (L-6)
        self.start()
        for tank in self.tanks[:4]:
            for ago in range(19, 6, -1):
                feeding_services.record_feeding(self.user, unit=tank, day=self.day(ago), feed=self.feed,
                                                amount_kg=Decimal(2))
        for tank, batch in zip(self.tanks[:2], self.batches[:2]):
            stock_services.record_weighing(self.user, unit=tank, batch=batch, day=self.day(6), avg_weight_g=D(70))
        self.mortality(self.batches[0], 20, days_ago=5, unit=self.tanks[0])
        self.trial.refresh_from_db()

    def row(self, number=1, group='Control', trial=None):
        return next(row for row in read.overview(trial or self.trial)
                    if (row.group.name, row.replicate.number) == (group, number))


class OverviewTests(RanTrialCase):
    def test_a_replicates_figures_are_the_farms_own_for_the_same_stay_and_days(self):
        row = self.row()
        self.assertEqual(([tank.code for tank in row.tanks], [batch.code for batch in row.batches]),
                         (['T-01'], [self.batches[0].code]))
        shown = feeding_read.figures(stock_read.stock_of([self.tanks[0]]))[self.tanks[0].pk].conversion
        self.assertEqual((row.conversion.feed_kg, row.conversion.gain_kg, row.conversion.economic_gain_kg),
                         (shown.feed_kg, shown.gain_kg, shown.economic_gain_kg))
        self.assertEqual((row.conversion.feed_kg, row.conversion.gain_kg), (26, 20))     # 13 days of 2 kg; 50 -> 70 kg
        self.assertEqual((row.conversion.biological, row.conversion.economic), (Decimal('1.3'), Decimal('1.3')))
        self.assertEqual((row.fish, row.biomass_kg), (980, Decimal('68.6')))
        self.assertEqual(row.survival, Decimal('98'))
        # the same through the farm's own bounded window: baseline day 0, the weighing of day 14
        found = feeding_read.windows_in([self.tanks[0].pk], self.first, self.day(6))
        self.assertEqual(feeding_read.Conversion(list(found.values())).biological, row.conversion.biological)

    def test_a_replicate_without_a_weighing_has_a_dash_that_says_why_and_the_others_are_untouched(self):
        row = self.row(1, 'High feed')
        self.assertEqual((row.fish, row.biomass_kg, row.survival), (1000, Decimal(50), Decimal(100)))
        self.assertEqual((row.conversion.biological, row.conversion.why_no_biological),
                         (None, 'Not weighed since the fish came in.'))
        self.assertEqual(self.row(2).conversion.biological, Decimal('1.3'))

    def test_a_replicates_conversion_sums_its_tanks_feed_and_gain_not_their_ratios(self):
        replicate = design_replicate(self.trial, 'Control', 1)
        ReplicateUnit.objects.create(replicate=replicate, unit=self.tanks[4], from_on=self.first, until_on=self.end)
        self.stock(self.tanks[4], count=1000, weight='50', days_ago=20)
        for ago in range(19, 6, -1):
            feeding_services.record_feeding(self.user, unit=self.tanks[4], day=self.day(ago), feed=self.feed,
                                            amount_kg=Decimal(4))
        stock_services.record_weighing(self.user, unit=self.tanks[4], batch=read_batch(self.tanks[4]), day=self.day(6),
                                       avg_weight_g=D(65))
        row = self.row()
        self.assertEqual((row.conversion.feed_kg, row.conversion.gain_kg), (26 + 52, 20 + 15))      # ratio of sums

    def test_a_batch_of_another_species_in_a_tank_of_the_replicate_never_counts(self):
        replicate = design_replicate(self.trial, 'Control', 1)
        ReplicateUnit.objects.create(replicate=replicate, unit=self.tanks[4], from_on=self.first, until_on=self.end)
        cleaner = self.stock(self.tanks[4], count=500, weight='5', days_ago=20, species=self.trout)
        for ago in range(19, 6, -1):
            feeding_services.record_feeding(self.user, unit=self.tanks[4], day=self.day(ago), feed=self.feed,
                                            amount_kg=Decimal('0.2'))
        stock_services.record_weighing(self.user, unit=self.tanks[4], batch=cleaner, day=self.day(6), avg_weight_g=D(9))
        row = self.row()
        self.assertEqual([batch.code for batch in row.batches], [self.batches[0].code])
        self.assertEqual((row.conversion.feed_kg, row.fish), (26, 980))

    def test_a_replacement_without_a_weighing_at_the_move_leaves_a_gap_the_overview_says_so(self):
        replicate = design_replicate(self.trial, 'Control', 1)
        ReplicateUnit.objects.filter(replicate=replicate).update(until_on=self.day(10))                 # T-01 leaves
        ReplicateUnit.objects.create(replicate=replicate, unit=self.tanks[4], from_on=self.day(9), until_on=self.end)
        self.stock(self.tanks[4], count=800, weight='60', days_ago=9)
        stock_services.record_weighing(self.user, unit=self.tanks[4], batch=read_batch(self.tanks[4]), day=self.day(6),
                                       avg_weight_g=D(70))
        for ago in range(8, 6, -1):
            feeding_services.record_feeding(self.user, unit=self.tanks[4], day=self.day(ago), feed=self.feed,
                                            amount_kg=Decimal(3))
        row = self.row()
        self.assertEqual(row.gap, ['T-01'])
        self.assertEqual((row.conversion.feed_kg, row.conversion.gain_kg), (6, 8))         # T-05 only: 48 -> 56 kg
        self.assertEqual([cell.unit.code for cell in row.cells], ['T-01', 'T-05'])
        page = self.client.get(reverse('experiments:experiment_detail', args=[self.trial.pk]))
        self.assertContains(page, 'Its feed conversion leaves out T-01: no weighing at the move.')

    def test_a_draft_has_its_tanks_and_no_figures_and_a_closed_experiment_no_now(self):
        draft = self.experiment('Draft', starts_on=self.first)
        slot = self.replicate(self.group(draft, 'A'), 1)
        ReplicateUnit.objects.create(replicate=slot, unit=self.tanks[5], from_on=self.first, until_on=self.end)
        row = read.overview(draft)[0]
        self.assertEqual(([tank.code for tank in row.tanks], row.batches, row.fish, row.survival,
                          row.conversion.windows), (['T-06'], [], None, None, []))
        ReplicateUnit.objects.filter(replicate__group__experiment=self.trial).update(until_on=self.day(6))  # to the weighing
        Experiment.objects.filter(pk=self.trial.pk).update(status='closed')
        self.trial.refresh_from_db()
        closed = self.row()
        self.assertEqual((closed.fish, closed.biomass_kg, closed.conversion.biological), (None, None, Decimal('1.3')))
        self.assertEqual(closed.survival, Decimal(100))              # the fish lost on day 15 came after its last day

    def test_a_slot_without_a_tank_is_a_row_with_nothing(self):
        other = self.experiment('Other', starts_on=self.first)
        group = self.group(other, 'A')
        placed, empty_slot = self.replicate(group, 1), self.replicate(group, 2)
        ReplicateUnit.objects.create(replicate=placed, unit=self.tanks[6], from_on=self.first, until_on=self.end)
        Experiment.objects.filter(pk=other.pk).update(
            status='running', hypothesis='h', primary_endpoint='bfcr', allocation_method='manual', allocation_note='x')
        other.refresh_from_db()
        empty = next(row for row in read.overview(other) if row.replicate.pk == empty_slot.pk)
        self.assertEqual((empty.cells, empty.batches, empty.fish, empty.survival), ([], [], None, None))

    def test_the_conversion_to_the_last_day_is_bounded_by_the_weighing_of_that_day(self):
        """Once a placement's last day has come, its conversion is read to the weighing of that day, not the latest."""
        ReplicateUnit.objects.filter(replicate__group__experiment=self.trial).update(until_on=self.day(6))
        self.assertEqual(self.row().conversion.biological, Decimal('1.3'))         # to the weighing of its last day
        ReplicateUnit.objects.filter(replicate__group__experiment=self.trial).update(until_on=self.day(8))
        self.assertIsNone(self.row().conversion.biological)         # no measured point on day 8 ago: no window, no guess
        self.assertEqual(self.row().unmeasured, f'T-01 has no weighing on {self.day(8).isoformat()}, its last day: the feed '
                         'conversion is read from the weighing of the first day to the weighing of the last.')
        page = self.client.get(reverse('experiments:experiment_detail', args=[self.trial.pk]))
        self.assertContains(page, 'T-01 has no weighing on')                     # the dash says why, not "not weighed"

    def test_a_placement_that_ends_today_is_read_to_its_last_day_not_to_the_latest_weighing(self):
        self.assertEqual(self.row().unmeasured, '')
        ReplicateUnit.objects.filter(unit=self.tanks[0]).update(until_on=self.today)
        self.assertIsNone(self.row().conversion.biological)         # the last day has come, and was not weighed
        self.assertNotEqual(self.row().unmeasured, '')


class ReadFunctionTests(RanTrialCase):
    def test_what_a_tank_is_in_on_a_day_at_most_one_with_the_days_inclusive(self):
        units = [tank.pk for tank in self.tanks[:6]]
        found = read.placements(units, self.first)
        self.assertEqual(sorted(cell.unit.code for cell in found.values()), ['T-01', 'T-02', 'T-03', 'T-04'])
        self.assertEqual(found[self.tanks[0].pk].group.name, 'Control')
        self.assertEqual(found[self.tanks[0].pk].replicate.number, 1)
        self.assertEqual(sorted(read.placements(units, self.end)), sorted(found))
        self.assertEqual(read.placements(units, self.first - timedelta(days=1)), {})
        self.assertEqual(read.placements(units, self.end + timedelta(days=1)), {})
        self.assertEqual(read.placements([], self.first), {})

    def test_a_booking_meets_the_days_asked_on_both_ends_and_not_beyond(self):
        tank = [self.tanks[0].pk]
        other = self.experiment('Other')
        for first, last, expected in ((self.end, self.end + timedelta(days=3), True),
                                      (self.end + timedelta(days=1), self.end + timedelta(days=3), False),
                                      (self.first - timedelta(days=3), self.first, True),
                                      (self.first - timedelta(days=3), self.first - timedelta(days=1), False)):
            with self.subTest(first=first, last=last):
                self.assertEqual(bool(read.booked(tank, first, last, exclude=other)), expected)

    def test_a_deleted_experiments_tanks_are_in_nothing(self):
        other = self.experiment('Gone')
        slot = self.replicate(self.group(other, 'A'), 1)
        ReplicateUnit.objects.create(replicate=slot, unit=self.tanks[6], from_on=self.first, until_on=self.end)
        self.assertEqual(read.placements([self.tanks[6].pk], self.first)[self.tanks[6].pk].group.name, 'A')
        from core import softdelete
        softdelete.execute(softdelete.plan_delete(other), self.user)
        self.assertEqual(read.placements([self.tanks[6].pk], self.first), {})
        self.assertEqual(read.booked([self.tanks[6].pk], self.first, self.end), {})

    def test_progress_is_where_the_experiment_is_in_its_days(self):
        trial = self.trial
        cases = [(self.first - timedelta(days=3), ('before', None, 56, 3)), (self.first, ('during', 0, 56, None)),
                 (self.first + timedelta(days=23), ('during', 23, 56, None)), (self.end, ('during', 56, 56, None)),
                 (self.end + timedelta(days=2), ('after', None, 56, 2))]
        for today, expected in cases:
            with self.subTest(today=today):
                self.assertEqual(read.progress(trial, today), expected)
        self.assertIsNone(read.progress(self.experiment('Undated'), self.today))

    def test_the_data_of_a_tank_counts_its_feeding_records_on_its_days_from_the_farms_read(self):
        found = read.data(self.trial)
        self.assertEqual([(item.cell.unit.code, item.records, item.kilos) for item in found],
                         [('T-01', 13, Decimal(26)), ('T-02', 13, Decimal(26)), ('T-03', 13, Decimal(26)),
                          ('T-04', 13, Decimal(26))])
        ReplicateUnit.objects.filter(replicate=design_replicate(self.trial, 'Control', 1)).update(until_on=self.day(8))
        self.assertEqual(read.data(self.trial)[0].records, 12)            # days 19 to 8: a placement only gets shorter
        self.assertEqual(read.data(self.experiment('Empty')), [])


class SurvivalTests(RanTrialCase):
    """Survival over a replicate that had a tank replaced: the fish moved to the replacement are the same fish."""

    def replace_with_the_fish(self, moved):
        from farm.handling import check
        from farm.models.handling import KIND_OF_OPERATION
        from farm.models.stock import OperationKind
        services.replace_unit(self.user, ReplicateUnit.objects.get(unit=self.tanks[1]), self.tanks[5], self.today, 'Pump',
                              Experiment.objects.get(pk=self.trial.pk).version)
        day = self.day(0)
        seen = check.assess(KIND_OF_OPERATION[OperationKind.TRANSFER], self.tanks[1], day, self.batches[1],
                            with_earliest=False).fingerprint
        stock_services.record_transfer(self.user, source=self.tanks[1], batch=self.batches[1], day=day,
                                       legs=[(self.tanks[5], moved)], reason='split', handling_ack=seen)

    def test_the_fish_that_moved_with_a_replacement_are_not_counted_twice_and_the_losses_before_and_after_are(self):
        self.mortality(self.batches[1], 50, days_ago=3, unit=self.tanks[1])
        self.replace_with_the_fish(950)
        self.assertEqual(self.row(2).survival, Decimal(95))              # 1,000 at day 0, 50 lost
        self.mortality(self.batches[1], 10, days_ago=0, unit=self.tanks[5])      # lost in the replacement on its first day
        self.assertEqual(self.row(2).survival, Decimal(94))


class QueryBudgetTests(PageTestCase):
    """The queries do not grow with the tanks: 6 or 60."""

    def trial_of(self, count):
        trial = self.experiment(f'{count} tanks', starts_on=self.day(10))
        units = [make_unit(f'Q{count}-{number:02d}', self.hall) for number in range(count)]
        stock_services.record_input(self.user, species=self.salmon, input_stage='fry', origin='own_hatchery',
                                    day=self.day(10), lines=[(unit, 100, D(50)) for unit in units])
        group = self.group(trial, 'A')
        for number, unit in enumerate(units, start=1):
            ReplicateUnit.objects.create(replicate=self.replicate(group, number), unit=unit, from_on=self.day(10),
                                         until_on=self.day(10) + timedelta(days=56))
        Experiment.objects.filter(pk=trial.pk).update(
            status='running', hypothesis='h', primary_endpoint='bfcr', allocation_method='manual', allocation_note='x')
        trial.refresh_from_db()
        return trial, units

    def count(self, call):
        with CaptureQueriesContext(connection) as queries:
            call()
        return len(queries)

    def test_the_overview_the_cells_the_placements_and_the_data_cost_the_same_for_6_tanks_and_60(self):
        small, small_units = self.trial_of(6)
        large, large_units = self.trial_of(60)
        for name, call in (('overview', lambda trial, units: read.overview(trial)),
                           ('cells', lambda trial, units: read.cells(trial)),
                           ('data', lambda trial, units: read.data(trial)),
                           ('placements', lambda trial, units: read.placements([u.pk for u in units], self.day(5)))):
            with self.subTest(name=name):
                self.assertEqual(self.count(lambda: call(small, small_units)), self.count(lambda: call(large, large_units)))
        rows = read.overview(large)
        self.assertEqual((len(rows), rows[0].fish, rows[59].fish), (60, 100, 100))

    def test_the_list_and_the_read_page_cost_the_same_for_6_tanks_and_60(self):
        small, _units = self.trial_of(6)
        pages = (reverse('experiments:experiment_list'), reverse('experiments:experiment_detail', args=[small.pk]))
        for url in pages:
            self.client.get(url)                                  # the first request fills the permission caches
        before = [self.count(lambda: self.client.get(url)) for url in pages]
        self.trial_of(60)
        after = [self.count(lambda: self.client.get(url)) for url in pages]
        self.assertEqual(before, after)


class ReadPageTests(RanTrialCase):
    def setUp(self):
        super().setUp()
        self.url = reverse('experiments:experiment_detail', args=[self.trial.pk])

    def test_the_overview_says_the_day_shows_each_replicate_and_marks_the_control(self):
        page = self.client.get(self.url)
        self.assertContains(page, 'Day 20 of 56')
        self.assertContains(page, '<span class="badge badge-experimental">Control</span>', html=True)
        rows = page.context['rows']
        self.assertEqual([(row.group.name, row.replicate.number) for row in rows],
                         [('Control', 1), ('Control', 2), ('High feed', 1), ('High feed', 2)])
        html = page.content.decode()
        for text in ('R1', 'T-01', self.batches[0].code, '980', '98.0 %', '1.30'):
            self.assertIn(text, html)
        self.assertContains(page, 'title="Not weighed since the fish came in."')
        self.assertNotContains(page, 'To fix before it can start')

    def test_a_draft_shows_what_is_wrong_before_its_rows(self):
        draft = self.experiment('Draft')
        page = self.client.get(reverse('experiments:experiment_detail', args=[draft.pk]))
        self.assertContains(page, 'To fix before it can start')
        self.assertContains(page, 'The design has no group.')
        self.assertContains(page, 'No group.')

    def test_the_data_tab_has_a_row_a_tank_with_links_to_the_farms_lists_with_the_tank_and_the_days_chosen(self):
        page = self.client.get(self.url, {'tab': 'data'})
        tank = self.tanks[0]
        days = f'unit={tank.pk}&amp;from={self.first.isoformat()}&amp;to={self.end.isoformat()}'
        for name, extra in (('feeding_records', ''), ('treatments', ''), ('lice_counts', ''), ('water', '&amp;view=history')):
            self.assertContains(page, f'href="{reverse(f"farm:{name}")}?{days}{extra}"')
        self.assertContains(page, f'href="{reverse("farm:production_units")}?unit={tank.pk}"')
        self.assertContains(page, '<td class="num">13</td>', html=True)
        self.assertContains(page, '26 kg')
        self.assertEqual(len(page.context['tanks']), 4)

    def test_only_the_lists_the_person_may_read_are_linked(self):
        reader = person('reader', 'view_experiment', 'view_feedingrecord')
        self.client.force_login(reader)
        links = self.client.get(self.url, {'tab': 'data'}).context['tanks'][0]['links']
        self.assertEqual([label for label, _url in links], ['Feeding records'])
        self.client.force_login(person('none', 'view_experiment'))
        self.assertEqual(self.client.get(self.url, {'tab': 'data'}).context['tanks'][0]['links'], [])

    def test_the_team_tab_and_a_tab_that_is_not_one(self):
        team = self.client.get(self.url, {'tab': 'team'})
        self.assertContains(team, 'ali (Lead)')
        self.assertNotContains(team, 'Replicate')
        self.assertEqual(self.client.get(self.url, {'tab': 'nonsense'}).context['tab'], 'overview')
        self.assertContains(self.client.get(self.url), 'aria-current="page">Overview</a>')

    def test_the_phase_is_said_before_the_start_and_after_the_end(self):
        later = self.experiment('Later', starts_on=self.today + timedelta(days=5))
        self.assertContains(self.client.get(reverse('experiments:experiment_detail', args=[later.pk])),
                            'Day 0 is in 5 days')
        over = self.experiment('Over', starts_on=self.today - timedelta(days=60))
        self.assertContains(self.client.get(reverse('experiments:experiment_detail', args=[over.pk])),
                            'The final weighing was 4 days ago')


def design_group(trial, name):
    from ..models import ExperimentGroup
    return ExperimentGroup.objects.get(experiment=trial, name=name)


def design_replicate(trial, group, number):
    from ..models import Replicate
    return Replicate.objects.get(group__experiment=trial, group__name=group, number=number)


def read_batch(tank):
    """The batch with fish in a tank (the one stocked there)."""
    return StockMovement.objects.filter(unit=tank).first().batch
