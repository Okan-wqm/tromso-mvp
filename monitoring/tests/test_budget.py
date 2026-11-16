"""The query budget: what a wall of cards costs does not grow with the number of units. The counts at six and at
twenty-four units are EQUAL for every mode, ledger fold and the feeding walk run once per snapshot, and a card
read runs nothing but SELECTs (a poll writes nothing). A hundred units is a live measurement (README, Monitoring)."""
import itertools
from unittest import mock

from django.db import connection
from django.test.utils import CaptureQueriesContext

from farm.feeding import read as feeding_read
from farm.stock import read as stock_read

from farm.water import calculation

from .. import read
from ..cards import builtin
from ..cards.resolve import Choice
from . import ALL_RIGHTS, MonitoringCase, chosen

# The ceilings, set at the first green run and never raised without a review: a card read costs this many queries
# for a person who may read everything, whatever the number of units.
PEOPLE = itertools.count()
CEILINGS = {'simple': 80, 'detailed': 100, 'mixed': 100, 'small': 80, 'big': 80}


class Counting:
    def count(self, units, mode):
        modes = {unit.pk: (mode if mode != 'mixed' else ('detailed' if index % 2 else 'simple'))
                 for index, unit in enumerate(units)}
        # 'small': the screen's view, every card as the Small template (which shows the unit's chart)
        choice = (Choice(view=builtin.SMALL) if mode == 'small' else Choice(view=builtin.BIG) if mode == 'big'
                  else chosen(modes))
        user = self.as_person(f'budget-{mode}-{len(units)}-{next(PEOPLE)}', *ALL_RIGHTS)
        read.sections_for(user)                                   # the person's rights are cached on the user
        with CaptureQueriesContext(connection) as log:
            found = read.cards(units, user, choice)
        self.assertEqual(len(found), len(units))
        for query in log:
            self.assertTrue(query['sql'].lstrip().upper().startswith(('SELECT', 'WITH', 'SAVEPOINT', 'RELEASE')), query['sql'][:80])   # a savepoint keeps a failing chip provider inside it: no write
        self.savepoints = sum(query['sql'].lstrip().upper().startswith(('SAVEPOINT', 'RELEASE')) for query in log)
        return len(log)


class BudgetTests(Counting, MonitoringCase):
    def test_the_counts_at_six_and_twenty_four_units_are_equal_in_every_mode(self):
        units = self.farm_of(24)
        for mode in ('simple', 'detailed', 'mixed', 'small', 'big'):
            with self.subTest(mode=mode):
                self.count(units[:6], mode)                           # warm what the first call loads once
                six, twenty_four = self.count(units[:6], mode), self.count(units, mode)
                self.assertEqual(six, twenty_four)
                self.assertLessEqual(six, CEILINGS[mode], f'{mode} costs {six} queries')

    def test_the_occupancy_filter_spares_the_heavy_reads_for_units_it_leaves_out(self):
        units = self.farm_of(6)
        with CaptureQueriesContext(connection) as log:
            read.cards(units, self.reader, chosen({unit.pk: 'simple' for unit in units}), occupancy='empty')
        self.assertLess(len(log), 12)                             # nothing stocked: no walk, no water, no feeding

    def test_the_ledger_fold_and_the_feeding_walk_run_once_for_all_the_units(self):
        units = self.farm_of(8)
        modes = {unit.pk: 'detailed' for unit in units}
        with mock.patch.object(stock_read, 'fold', wraps=stock_read.fold) as fold, \
                mock.patch.object(feeding_read, 'project', wraps=feeding_read.project) as project:
            read.cards(units, self.reader, chosen(modes))
        self.assertEqual((fold.call_count, project.call_count), (1, 1))
        # (the fixture has no treatment, event, lice count or task: those sources' bulk reads are checked against the
        # per-unit code in farm/tests/test_health.py, tasks/tests/test_read.py and farm/tests/test_water.py)

    def test_simple_cards_skip_the_detailed_sources(self):
        units = self.farm_of(4)
        with mock.patch.object(read.harvest_views, 'withdrawals', return_value={}):     # (the registry reads treatments)
            with CaptureQueriesContext(connection) as simple:
                read.cards(units, self.reader, chosen({unit.pk: 'simple' for unit in units}))
            with CaptureQueriesContext(connection) as detailed:
                read.cards(units, self.reader, chosen({unit.pk: 'detailed' for unit in units}))
        text = ' '.join(query['sql'] for query in simple)
        for table in ('"treatments"', '"lice_counts"', '"tasks"'):
            self.assertNotIn(table, text)
        self.assertGreater(len(detailed), len(simple))

    def test_only_the_cards_that_show_the_chart_have_it_worked_out(self):
        """The unit's Deffeyes chart is read for a card whose template shows it (the Small card's calculated CO₂ and pH
        window), from the water the card read already holds: no card of Simple or Detailed pays for it, and a mixed
        wall works it out for its small cards alone, once for all of them."""
        units = self.farm_of(6)
        for mode in ('simple', 'detailed'):
            with mock.patch.object(read.water_calculation, 'charts_of', wraps=calculation.charts_of) as charts:
                found = read.cards(units, self.reader, chosen({unit.pk: mode for unit in units}))
            charts.assert_not_called()
            self.assertEqual({card.chart for card in found}, {None})
        small = {unit.pk: builtin.SMALL for unit in units[:2]}
        with mock.patch.object(read.water_calculation, 'charts_of', wraps=calculation.charts_of) as charts:
            found = read.cards(units, self.reader, Choice(rows=small))
        self.assertEqual(charts.call_count, 1)
        self.assertEqual([unit.pk for unit in charts.call_args.args[0]], [unit.pk for unit in units[:2]])
        self.assertEqual([isinstance(card.chart, calculation.UnitChart) or card.chart is not None for card in found],
                         [True, True, False, False, False, False])

    def test_the_chart_of_a_wall_reads_no_sample_and_no_point_again(self):
        units = self.farm_of(8)
        user = self.as_person('budget-chart', *ALL_RIGHTS)
        read.sections_for(user)
        read.cards(units, user, Choice(view=builtin.SMALL))                # warm what the first call loads once
        with CaptureQueriesContext(connection) as simple:
            read.cards(units, user, chosen({unit.pk: 'simple' for unit in units}))
        with CaptureQueriesContext(connection) as small:
            read.cards(units, user, Choice(view=builtin.SMALL))
        count = lambda log, table: sum(f'"{table}"' in query['sql'] for query in log)
        for table in ('water_measurements', 'water_sampling_points'):
            self.assertEqual(count(small, table), count(simple, table), table)


# The counts recorded before card templates (step 0 of the card-template plan), for a person who may read everything:
# the same at 6, 24 and 200 units. Card templates must not change them without the owner (README, Monitoring).
RECORDED = {'simple': 35, 'detailed': 42, 'mixed': 42}
RECORDED_SAVEPOINTS = 4       # the chips' savepoint and the one the placement registry opens around its provider
TEMPLATE_QUERIES = 2
SENSOR_QUERIES = 2          # the live values (owner rule A1): the bindings of the cards' points and systems, and their channels'
                            # values, whatever the number of units (sensors/provider.py)
SENSOR_SAVEPOINTS = 4       # the water sources' savepoint and its release around each of its two asks (farm/water/sources.py)
OWN_POINT_QUERIES = 2       # owner rule A9.1: the other points of the units, once for their water (farm/water/read._places)
                            # and once for the ration's temperature (read.water_sources every_point), whatever the number
OWNER_2026_11_08_QUERIES = 2  # the newest temperature before the ration's range (A11, Series carry) and the unit's other
                              # own-water points for the withdrawal's degree-days, whatever the number of units


# What a Big card may read beyond a Small one (the unit's other points): pinned from the first measurement.
BIG_MORE_READS = 6
SMALL_READS = 42            # measured 2026-11-13 at 6, 24 and 200 units: three more than a Simple card's 39 (the fish and
                            # their limits for the chart, once; no experiment chips)


class RecordedCountsTests(Counting, MonitoringCase):
    def test_the_counts_recorded_before_card_templates_at_6_24_and_200_units(self):
        units = self.farm_of(200)
        found, savepoints = {}, {}
        for mode in ('simple', 'detailed', 'mixed'):
            self.count(units[:6], mode)                               # warm what the first call loads once
            found[mode] = []
            for size in (6, 24, 200):
                found[mode].append(self.count(units[:size], mode) - self.savepoints)
                savepoints[mode] = self.savepoints
        # The recording counted the chips' savepoints (theirs and the registry's around its provider); each optional
        # source now has its own (a savepoint and its release: transaction control, no read), so the reads are compared
        # without them. Card templates add their
        # two queries (the live templates, the live rules), whatever the number of units.
        added = TEMPLATE_QUERIES + SENSOR_QUERIES + OWN_POINT_QUERIES + OWNER_2026_11_08_QUERIES
        self.assertEqual(found, {mode: [count - RECORDED_SAVEPOINTS + added] * 3
                                 for mode, count in RECORDED.items()})
        # The Small card (2026-11-13): the roll-up's reads and the unit's chart, worked out from the water already read
        # with ONE read of the fish and their limits for all the cards; the same at 6, 24 and 200 units.
        self.count(units[:6], 'small')
        small = [self.count(units[:size], 'small') - self.savepoints for size in (6, 24, 200)]
        self.assertEqual(small, [SMALL_READS] * 3)
        # The Big card (2026-11-16): the same chart read, and every active point's water for its other points; the
        # core draws each card's figure, which is no query. The same at 6, 24 and 200 units.
        self.count(units[:6], 'big')
        big = [self.count(units[:size], 'big') - self.savepoints for size in (6, 24, 200)]
        self.assertEqual(len(set(big)), 1, big)
        self.assertLessEqual(big[0], SMALL_READS + BIG_MORE_READS, big)
        self.assertEqual(savepoints, {mode: count + SENSOR_SAVEPOINTS for mode, count in
                                      {'simple': 4, 'detailed': 10, 'mixed': 10}.items()})   # chips; + treatments, lice, tasks
