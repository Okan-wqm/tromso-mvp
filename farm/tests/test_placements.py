"""The placement registry (farm/placements.py): the chips an app puts beside a unit, and that it fails open: no provider, a
provider that raises, or one that breaks its transaction, leaves the page and the other providers' chips as they are."""
import logging
from unittest import mock

from django.db import connection
from django.test import TestCase

from .. import placements
from ..placements import Placement


def provider_of(label, unit_ids=None):
    def provider(units, user):
        return {unit.pk: [Placement(label)] for unit in units if unit_ids is None or unit.pk in unit_ids}
    return provider


class Unit:
    def __init__(self, pk):
        self.pk = pk


class RegistryTests(TestCase):
    def of(self, providers, units=(1, 2)):
        with mock.patch.object(placements, '_providers', list(providers)):
            return placements.of([Unit(pk) for pk in units], user=None)

    def labels(self, found):
        return {pk: [chip.label for chip in chips] for pk, chips in found.items()}

    def test_with_no_provider_there_is_no_chip(self):
        self.assertEqual(self.of([]), {})

    def test_each_providers_chips_are_merged_in_the_order_they_registered(self):
        found = self.of([provider_of('first', {1}), provider_of('second')])
        self.assertEqual(self.labels(found), {1: ['first', 'second'], 2: ['second']})

    def test_no_units_asks_no_provider(self):
        calls = []
        self.assertEqual(self.of([lambda units, user: calls.append(units) or {}], units=()), {})
        self.assertEqual(calls, [])

    def test_a_provider_that_raises_is_logged_and_left_out_and_the_others_still_answer(self):
        def broken(units, user):
            raise RuntimeError('the experiments are down')
        with self.assertLogs(placements.logger, logging.ERROR) as logged:
            found = self.of([broken, provider_of('kept')])
        self.assertEqual(self.labels(found), {1: ['kept'], 2: ['kept']})
        self.assertIn('the experiments are down', '\n'.join(logged.output))

    def test_a_provider_that_breaks_the_database_transaction_does_not_break_the_page(self):
        def bad_sql(units, user):
            with connection.cursor() as cursor:
                cursor.execute('SELECT * FROM a_table_that_is_not_there')
        with self.assertLogs(placements.logger, logging.ERROR):
            found = self.of([bad_sql, provider_of('kept')])
        self.assertEqual(sorted(found), [1, 2])
        with connection.cursor() as cursor:                    # the connection still works: the failure stayed in its savepoint
            cursor.execute('SELECT 1')

    def test_a_provider_that_answers_something_else_is_left_out_too(self):
        for answer in (None, [], {1: None}, {1: Placement}, {1: 'x'}):
            with self.subTest(answer=answer), self.assertLogs(placements.logger, logging.ERROR):
                found = self.of([lambda units, user, answer=answer: answer, provider_of('kept')])
            self.assertEqual(self.labels(found), {1: ['kept'], 2: ['kept']})

    def test_registering_twice_registers_once(self):
        with mock.patch.object(placements, '_providers', []):
            provider = provider_of('x')
            placements.register(provider)
            placements.register(provider)
            self.assertEqual(placements._providers, [provider])
