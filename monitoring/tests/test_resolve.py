"""Which template a unit's card gets (monitoring/cards/resolve.py), rung by rung, and what the card read then reads
(monitoring/read.py: SOURCES, `needs`, one bulk call per needed source, an optional source failing open): the board's
row, then the unit, its system, the system's type, the species, the kind, then the board's default (or the page's own
choice), then the global rule; a flip shows the template's flip target; a broken stored layout falls back visibly."""
import itertools
import logging
from types import SimpleNamespace
from unittest import mock

from django.db import connection
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext

from core import softdelete
from farm.models import System

from .. import read
from ..cards import builtin, resolve
from ..cards.resolve import Choice
from ..models import CardTemplate, CardTemplateAssignment, MonitorBoard, MonitorBoardUnit
from . import ALL_RIGHTS, MonitoringCase

PEOPLE = itertools.count()
TASKS_ONLY = {'schema': 1, 'widgets': [{'id': 'w1', 'type': 'tasks', 'x': 0, 'y': 0, 'w': 6, 'h': 2}]}
FISH_ONLY = {'schema': 1, 'widgets': [{'id': 'w1', 'type': 'fish', 'x': 0, 'y': 0, 'w': 12, 'h': 5}]}


def template(pk, expanded=None, layout=None):
    return SimpleNamespace(pk=pk, name=f'T{pk}', shown_name=f'T{pk}', is_builtin=False, layout=layout or TASKS_ONLY,
                           expanded_id=expanded, version=1)


def rule(template_id, **scope):
    values = {'unit_id': None, 'system_id': None, 'system_type': None, 'species_id': None, 'kind': None}
    values.update(scope)
    return SimpleNamespace(template_id=template_id, **values)


class LadderTests(SimpleTestCase):
    """template_of, pure: each rung wins over every rung below it."""

    def setUp(self):
        self.templates = {pk: template(pk) for pk in range(1, 10)}
        self.unit = SimpleNamespace(pk='u', kind='tank', system_id='s', system=SimpleNamespace(type='ras'))
        self.rules = resolve.Rules([rule(1, unit_id='u'), rule(2, system_id='s'), rule(3, system_type='ras'),
                                    rule(4, species_id='salmon'), rule(5, kind='tank'), rule(7)])

    def resolved(self, rules=None, species='salmon', row=None, board=None, flipped=False):
        return resolve.template_of(self.unit, species, row, board, rules or self.rules, self.templates, flipped)

    def test_each_rung_wins_over_the_ones_below(self):
        self.assertEqual(self.resolved(row=9, board=6).why, resolve.ROW)
        rules = list(self.rules.all)
        for why, pk in ((resolve.UNIT, 1), (resolve.SYSTEM, 2), (resolve.SYSTEM_TYPE, 3), (resolve.SPECIES, 4),
                        (resolve.KIND, 5)):
            with self.subTest(rung=why):
                found = self.resolved(resolve.Rules(rules), board=6)
                self.assertEqual((found.template.pk, found.why), (pk, why))
                rules = [each for each in rules if each.template_id != pk]           # take this rung away
        found = self.resolved(resolve.Rules(rules), board=6)
        self.assertEqual((found.template.pk, found.why), (6, resolve.BOARD))
        found = self.resolved(resolve.Rules(rules))
        self.assertEqual((found.template.pk, found.why), (7, resolve.GLOBAL))

    def test_an_empty_unit_has_no_species_and_falls_to_the_kind(self):
        rules = resolve.Rules([rule(4, species_id='salmon'), rule(5, kind='tank'), rule(7)])
        self.assertEqual(self.resolved(rules, species=None).why, resolve.KIND)
        self.assertEqual(self.resolved(rules).why, resolve.SPECIES)

    def test_a_unit_outside_a_system_skips_the_system_rungs(self):
        self.unit = SimpleNamespace(pk='u', kind='pond', system_id=None, system=None)
        rules = resolve.Rules([rule(2, system_id='s'), rule(3, system_type='ras'), rule(7)])
        self.assertEqual(self.resolved(rules, species=None).why, resolve.GLOBAL)

    def test_a_rule_or_pointer_to_a_template_that_is_gone_is_passed_over(self):
        rules = resolve.Rules([rule(99, unit_id='u'), rule(7)])
        self.assertEqual(self.resolved(rules, row=98, board=97).why, resolve.GLOBAL)

    def test_with_no_rule_at_all_the_card_is_simple_from_the_code(self):
        found = self.resolved(resolve.Rules([]), species=None)
        self.assertEqual((found.template, found.why, found.layout), (None, resolve.FALLBACK, builtin.SIMPLE_LAYOUT))

    def test_a_flip_shows_the_flip_target_and_its_link_goes_back(self):
        self.templates[7] = template(7, expanded=8)
        rules = resolve.Rules([rule(7)])
        plain = self.resolved(rules, species=None)
        self.assertEqual((plain.template.pk, plain.flip_to.pk, plain.flipped), (7, 8, False))
        flipped = self.resolved(rules, species=None, flipped=True)
        self.assertEqual((flipped.template.pk, flipped.flip_to.pk, flipped.flipped, flipped.why), (8, 7, True, resolve.FLIP))
        self.templates[7] = template(7)                                    # no flip target: no link, a flip does nothing
        self.assertEqual((self.resolved(rules, species=None, flipped=True).template.pk,
                          self.resolved(rules, species=None).flip_to), (7, None))

    def test_a_broken_stored_layout_falls_back_to_detailed_and_says_so_logging_once(self):
        self.templates[7] = template(7, layout={'schema': 1, 'widgets': [{'id': 'w1', 'type': 'gauge', 'x': 0, 'y': 0,
                                                                         'w': 3, 'h': 2}]})
        resolve.LOGGED.clear()
        with self.assertLogs('monitoring.cards.resolve', logging.ERROR) as logged:
            found = self.resolved(resolve.Rules([rule(7)]), species=None)
            self.resolved(resolve.Rules([rule(7)]), species=None)
        self.assertEqual((found.template.pk, found.error, found.layout), (7, True, builtin.DETAILED_LAYOUT))
        self.assertEqual(len(logged.records), 1)

    def test_the_why_is_said_in_words(self):
        for why in (resolve.ROW, resolve.UNIT, resolve.SYSTEM, resolve.SYSTEM_TYPE, resolve.SPECIES, resolve.KIND,
                    resolve.BOARD, resolve.ADDRESS, resolve.GLOBAL, resolve.FLIP, resolve.FALLBACK):
            with self.subTest(why=why):
                self.assertTrue(resolve.Resolved(None, {}, why).because)


class TemplatesForTests(MonitoringCase):
    def test_two_queries_whatever_the_number_of_units(self):
        units = self.farm_of(24)
        for count in (6, 24):
            with self.assertNumQueries(2):
                found = resolve.templates_for(units[:count], {}, Choice())
            self.assertEqual({each.template.pk for each in found.values()}, {builtin.SIMPLE})

    def test_rules_of_deleted_units_systems_species_and_templates_do_not_count_and_come_back(self):
        mine = CardTemplate.objects.create(name='Mine', layout=TASKS_ONLY)
        unit_rule = CardTemplateAssignment.objects.create(template=mine, unit=self.t1)
        units = read.units_for(read.Params())
        self.assertEqual(resolve.templates_for(units, {}, Choice())[self.t1.pk].why, resolve.UNIT)
        softdelete.execute(softdelete.plan_delete(self.t1), None)
        self.assertEqual(resolve.templates_for(units, {}, Choice())[self.t1.pk].why, resolve.GLOBAL)
        softdelete.restore(self.t1, None)
        self.assertEqual(resolve.templates_for(units, {}, Choice())[self.t1.pk].why, resolve.UNIT)
        unit_rule.refresh_from_db()
        system = System.objects.create(site=self.bergen, production_department=self.hall, name='RAS 9', code='R9',
                                       type='ras')
        CardTemplateAssignment.objects.create(template=mine, system=system)
        self.t2.system = system
        self.t2.save()
        units = read.units_for(read.Params())
        self.assertEqual(resolve.templates_for(units, {}, Choice())[self.t2.pk].why, resolve.SYSTEM)
        System.objects.filter(pk=system.pk).update(is_deleted=True)
        units = read.units_for(read.Params())
        self.assertEqual(resolve.templates_for(units, {}, Choice())[self.t2.pk].why, resolve.GLOBAL)
        species_rule = CardTemplateAssignment.objects.create(template=mine, species=self.salmon)
        self.assertEqual(resolve.templates_for(units, {self.t2.pk: self.salmon.pk}, Choice())[self.t2.pk].why,
                         resolve.SPECIES)
        type(self.salmon).objects.filter(pk=self.salmon.pk).update(is_deleted=True)
        self.assertEqual(resolve.templates_for(units, {self.t2.pk: self.salmon.pk}, Choice())[self.t2.pk].why,
                         resolve.GLOBAL)
        self.assertFalse(species_rule.is_deleted)
        mine.soft_delete(None)
        self.assertEqual(resolve.templates_for(units, {}, Choice())[self.t1.pk].why, resolve.GLOBAL)

    def test_the_board_and_the_page(self):
        board = MonitorBoard.objects.create(name='Wall', default_template_id=builtin.DETAILED)
        MonitorBoardUnit.objects.create(board=board, unit=self.t1, template_id=builtin.OPERATOR)
        board = MonitorBoard.objects.prefetch_related('rows').get(pk=board.pk)
        units = read.units_for(read.Params())
        found = resolve.templates_for(units, {}, Choice.of(board, read.Params()))
        self.assertEqual((found[self.t1.pk].template.pk, found[self.t1.pk].why), (builtin.OPERATOR, resolve.ROW))
        self.assertEqual((found[self.t2.pk].template.pk, found[self.t2.pk].why), (builtin.DETAILED, resolve.BOARD))
        page = resolve.templates_for(units, {}, Choice.of(None, read.Params(mode='detailed')))
        self.assertEqual((page[self.t2.pk].template.pk, page[self.t2.pk].why), (builtin.DETAILED, resolve.ADDRESS))
        flipped = resolve.templates_for(units, {}, Choice.of(None, read.Params(flip=frozenset({str(self.t2.pk)}))))
        self.assertEqual((flipped[self.t2.pk].template.pk, flipped[self.t1.pk].template.pk),
                         (builtin.DETAILED, builtin.SIMPLE))


class NeedsTests(MonitoringCase):
    def cards(self, layout, user=None):
        mine = CardTemplate.objects.create(name=f'L{CardTemplate.objects.count()}', layout=layout)
        CardTemplateAssignment.objects.filter(unit=None, system=None, system_type=None, species=None,
                                              kind=None).update(template=mine)
        units = read.units_for(read.Params())
        with mock.patch.object(read.harvest_views, 'withdrawals', return_value={}),                 CaptureQueriesContext(connection) as log:          # (the withdrawal registry reads treatments itself)
            found = read.cards(units, user or self.reader, Choice())
        return found, ' '.join(query['sql'] for query in log)

    def test_a_source_no_widget_needs_is_not_read(self):
        found, sql = self.cards(FISH_ONLY)
        for table in ('"tasks"', '"treatments"', '"lice_counts"'):
            self.assertNotIn(table, sql)
        found, sql = self.cards(TASKS_ONLY)
        self.assertIn('"tasks"', sql)

    def test_the_roll_up_is_read_whatever_the_template_and_the_state_is_the_same(self):
        self.limit('oxygen_mg_l', critical_low=6, warning_low=7)
        self.sample(self.t2, hours=1, temperature_c='13.2', oxygen_mg_l='5')
        states = []
        for layout in (TASKS_ONLY, FISH_ONLY, builtin.DETAILED_LAYOUT, {'schema': 1, 'widgets': []}):
            found, sql = self.cards(layout)
            states.append({card.unit.code: (card.state.key, card.state.reasons) for card in found})
        self.assertEqual(states[0]['T-02'][0], 'critical')                 # no water widget, still critical
        self.assertTrue(all(each == states[0] for each in states))

    def test_needs_is_the_union_of_the_widgets_sources_and_the_roll_up(self):
        units = read.units_for(read.Params())
        resolved = resolve.templates_for(units, {}, Choice())
        needs = read.needs(resolved)
        ids = {unit.pk for unit in units}
        self.assertEqual(needs['tasks'], set())
        self.assertEqual(needs['stock'], ids)
        self.assertEqual(needs['events'], ids)
        self.assertEqual(needs['points'], set())                            # Simple: the middle point only
        detailed = resolve.templates_for(units, {}, Choice.of(None, read.Params(mode='detailed')))
        self.assertEqual(read.needs(detailed)['tasks'], ids)
        self.assertEqual(read.needs(detailed)['points'], ids)
        self.assertEqual(read.needs(detailed)['week'], ids)

    def test_every_source_of_the_catalogue_is_one_the_read_knows_with_its_right(self):
        from ..cards.catalogue import WIDGETS
        known = {source.name for source in read.SOURCES}
        for spec in WIDGETS.values():
            self.assertLessEqual(set(spec.sources), known, spec.type)
        self.assertEqual(read.sections_for(self.reader), frozenset(read.SECTIONS))
        self.assertFalse(hasattr(read, 'PERMISSIONS'))                      # SOURCES replaced it: one table

    def test_an_optional_source_that_fails_leaves_the_card_and_says_which_logging_once_a_minute(self):
        self.cards(builtin.DETAILED_LAYOUT)
        read.FAILED_AT.clear()
        with mock.patch.object(read.tasks_read, 'per_unit', side_effect=RuntimeError('down')), \
                self.assertLogs('monitoring.read', logging.ERROR) as logged:
            found, _sql = self.cards(builtin.DETAILED_LAYOUT)
            again, _sql = self.cards(builtin.DETAILED_LAYOUT)
        self.assertEqual({card.unit.code for card in found}, {'T-01', 'T-02'})
        self.assertTrue(all('tasks' in card.failed for card in found + again))
        self.assertEqual(len(logged.records), 1)

    def test_a_required_source_that_fails_fails_the_read(self):
        with mock.patch.object(read.stock_read, 'stock_of', side_effect=RuntimeError('down')):
            with self.assertRaises(read.Unavailable):
                self.cards(FISH_ONLY)

    def test_a_card_says_its_template_and_why(self):
        found, _sql = self.cards(FISH_ONLY)
        self.assertEqual({card.template.why for card in found}, {resolve.GLOBAL})
        self.assertEqual({card.template.template.name for card in found}, {'L5'})      # (five built-ins before it)


class BudgetWithTemplatesTests(MonitoringCase):
    def count(self, units, choice):
        user = self.as_person(f'budget-{next(PEOPLE)}', *ALL_RIGHTS)
        read.sections_for(user)
        with CaptureQueriesContext(connection) as log:
            read.cards(units, user, choice)
        return len(log)

    def test_the_counts_are_equal_at_6_and_24_units_with_one_and_three_templates(self):
        units = self.farm_of(24)
        one = Choice(address=builtin.DETAILED)
        self.count(units[:6], one)
        self.assertEqual(self.count(units[:6], one), self.count(units, one))
        rows = {unit.pk: (builtin.SIMPLE, builtin.DETAILED, builtin.OPERATOR)[index % 3] for index, unit in enumerate(units)}
        three = Choice(rows=rows)
        self.assertEqual(self.count(units[:6], three), self.count(units, three))
