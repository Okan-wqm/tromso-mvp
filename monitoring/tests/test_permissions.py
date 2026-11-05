"""Who sees what on a card: one right for each section, a section the person may not read is not read at all (no
query on its tables, no value in its place), and the state says what it was worked out from."""
from datetime import timedelta
from unittest import mock

from django.db import connection
from django.test.utils import CaptureQueriesContext

from farm.health import read as health_read
from farm.feeding import read as feeding_read
from farm.water import read as water_read
from tasks import read as tasks_read

from .. import read
from . import ALL_RIGHTS, MonitoringCase, chosen

# What a section's records live in, to look for in the SQL a card ran.
TABLES = {
    'feeding': ('feeding_records',), 'water': ('water_measurements',),
    'treatments': ('treatments', 'treatment_units'), 'events': ('health_events', 'health_event_units'),
    'lice': ('lice_counts',), 'tasks': ('tasks', 'task_assignees'),
}
RIGHT = {'feeding': 'view_feedingrecord', 'water': 'view_watermeasurement', 'treatments': 'view_treatment',
         'events': 'view_healthevent', 'lice': 'view_licecount', 'tasks': 'view_task'}


class SectionsTests(MonitoringCase):
    def test_one_right_for_each_section_and_nothing_else_spells_a_permission(self):
        self.assertEqual(read.sections_for(self.as_person('nobody')), frozenset())
        self.assertEqual(read.sections_for(self.as_person('everyone', *ALL_RIGHTS)), frozenset(read.SECTIONS))
        for section, right in {'stock': 'view_stockoperation', **RIGHT}.items():
            with self.subTest(section=section):
                self.assertEqual(read.sections_for(self.as_person(f'only-{section}', right)), frozenset({section}))
        # the rights are the owners' own constants
        rights = {source.name: source.permission for source in read.SOURCES}
        self.assertEqual((rights['water'], rights['tasks']), ('farm.view_watermeasurement', 'tasks.view_task'))


class HiddenSectionsTests(MonitoringCase):
    """A person without a right gets no read of the section and no value of it."""

    def run_cards(self, user, mode):
        units = read.units_for(read.Params())
        with mock.patch.object(read.harvest_views, 'withdrawals', return_value={}), \
                CaptureQueriesContext(connection) as log:         # (the withdrawal registry reads its own tables)
            found = read.cards(units, user, chosen({unit.pk: mode for unit in units}))
        return found, ' '.join(query['sql'] for query in log)

    def test_per_missing_right_no_statement_on_its_tables_and_no_value(self):
        for section, right in RIGHT.items():
            for mode in ('simple', 'detailed'):
                with self.subTest(without=section, mode=mode):
                    # (A ration is worked out from the water temperature, so a person who may read feeding but not
                    # water still has the feeding walk read the water's table: the card shows no water value of it.
                    # The table is looked for where the feeding is hidden too.)
                    lacking = {right, RIGHT['feeding']} if section == 'water' else {right}
                    user = self.as_person(f'no-{section}-{mode}', *[each for each in ALL_RIGHTS if each not in lacking])
                    found, sql = self.run_cards(user, mode)
                    for table in TABLES[section]:
                        self.assertNotIn(f'"{table}"', sql, f'{table} was read without the right')
                    card = next(each for each in found if each.unit.code == 'T-02')
                    shown = {'feeding': (card.feeding, card.day), 'water': card.water,
                             'treatments': card.treatments, 'events': card.events, 'lice': card.lice,
                             'tasks': card.tasks}[section]
                    self.assertFalse(shown if not isinstance(shown, tuple) else any(shown))

    def test_the_owners_reads_are_not_called_for_a_hidden_section(self):
        user = self.as_person('stock-only', 'view_stockoperation')
        units = read.units_for(read.Params())
        modes = {unit.pk: 'detailed' for unit in units}
        with mock.patch.object(feeding_read, 'figures') as feeding, mock.patch.object(water_read, 'points_water') as water, \
                mock.patch.object(health_read, 'open_events') as events, \
                mock.patch.object(health_read, 'recent_treatments') as treatments, \
                mock.patch.object(health_read, 'latest_counts') as counts, \
                mock.patch.object(tasks_read, 'per_unit') as tasks:
            found = read.cards(units, user, chosen(modes))
        for owner in (feeding, water, events, treatments, counts, tasks):
            owner.assert_not_called()
        card = found[0]
        self.assertEqual(card.hidden, ('feeding', 'water', 'health', 'tasks'))
        self.assertEqual(card.state.basis, ('stock',))
        self.assertIsNotNone(card.stock)                              # the fish are the stock right's
        self.assertEqual(card.state.key, 'ok')                        # never blind about a water it may not read

    def test_a_stock_only_person_still_sees_the_withdrawal_chip(self):
        from farm.handling.withdrawal import WithdrawalBlock
        user = self.as_person('stock-only', 'view_stockoperation')
        block = WithdrawalBlock(self.fish, self.today + timedelta(days=3), False, 'x', None)
        units = read.units_for(read.Params())
        with mock.patch('farm.handling.withdrawal._providers', [lambda each, day: {unit.pk: [block] for unit in each}]):
            found = read.cards(units, user, chosen({unit.pk: 'simple' for unit in units}))
        self.assertTrue(all(card.withdrawal for card in found))

    def test_without_the_stock_right_there_are_no_fish_and_no_card_of_them(self):
        user = self.as_person('water-only', 'view_watermeasurement')
        units = read.units_for(read.Params())
        self.assertEqual(read.cards(units, user, chosen({unit.pk: 'simple' for unit in units})), [])
