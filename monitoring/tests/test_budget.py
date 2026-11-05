"""The query budget: what a wall of cards costs does not grow with the number of units. The counts at six and at
twenty-four units are EQUAL for every mode, ledger fold and the feeding walk run once per snapshot, and a card
read runs nothing but SELECTs (a poll writes nothing). A hundred units is a live measurement (README, Monitoring)."""
import itertools
from unittest import mock

from django.db import connection
from django.test.utils import CaptureQueriesContext

from farm.feeding import read as feeding_read
from farm.stock import read as stock_read

from .. import read
from . import ALL_RIGHTS, MonitoringCase, chosen

# The ceilings, set at the first green run and never raised without a review: a card read costs this many queries
# for a person who may read everything, whatever the number of units.
PEOPLE = itertools.count()
CEILINGS = {'simple': 80, 'detailed': 100, 'mixed': 100}


class Counting:
    def count(self, units, mode):
        modes = {unit.pk: (mode if mode != 'mixed' else ('detailed' if index % 2 else 'simple'))
                 for index, unit in enumerate(units)}
        user = self.as_person(f'budget-{mode}-{len(units)}-{next(PEOPLE)}', *ALL_RIGHTS)
        read.sections_for(user)                                   # the person's rights are cached on the user
        with CaptureQueriesContext(connection) as log:
            found = read.cards(units, user, chosen(modes))
        self.assertEqual(len(found), len(units))
        for query in log:
            self.assertTrue(query['sql'].lstrip().upper().startswith(('SELECT', 'WITH', 'SAVEPOINT', 'RELEASE')), query['sql'][:80])   # a savepoint keeps a failing chip provider inside it: no write
        return len(log)


class BudgetTests(Counting, MonitoringCase):
    def test_the_counts_at_six_and_twenty_four_units_are_equal_in_every_mode(self):
        units = self.farm_of(24)
        for mode in ('simple', 'detailed', 'mixed'):
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


# The counts recorded before card templates (step 0 of the card-template plan), for a person who may read everything:
# the same at 6, 24 and 200 units. Card templates must not change them without the owner (README, Monitoring).
RECORDED = {'simple': 35, 'detailed': 42, 'mixed': 42}
TEMPLATE_QUERIES = 2


class RecordedCountsTests(Counting, MonitoringCase):
    def test_the_counts_recorded_before_card_templates_at_6_24_and_200_units(self):
        units = self.farm_of(200)
        found = {}
        for mode in ('simple', 'detailed', 'mixed'):
            self.count(units[:6], mode)                               # warm what the first call loads once
            found[mode] = [self.count(units[:size], mode) for size in (6, 24, 200)]
        # card templates add their two queries (the live templates, the live rules), whatever the number of units
        self.assertEqual(found, {mode: [count + TEMPLATE_QUERIES] * 3 for mode, count in RECORDED.items()})
