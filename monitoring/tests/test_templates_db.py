"""Card templates and their assignments in the database (monitoring/models.py, migrations 0002 to 0004): every rule the
database holds, proved by writing past the form (IntegrityError); the built-in templates as the migration froze them and
as monitoring/cards/builtin.py says them; what deleting a template or an assignment does; and the backfill of the
boards' modes into templates, forward and back."""
import json
from importlib import import_module

from django.apps import apps as global_apps
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase
from django.utils import translation

from core import softdelete
from farm.models import Species, System
from farm.tests.helpers import make_species
from farm.tests.test_stock import make_unit
from farm.models import ProductionDepartment, Site

from ..cards import builtin, catalogue, validate
from ..models import CardTemplate, CardTemplateAssignment, CardWidth, MonitorBoard, MonitorBoardUnit

LAYOUT = {'schema': 1, 'widgets': [{'id': 'w1', 'type': 'tasks', 'x': 0, 'y': 0, 'w': 6, 'h': 2}]}


class Fixture(TestCase):
    def setUp(self):
        self.site = Site.objects.create(name='Bergen', code='BG')
        self.hall = ProductionDepartment.objects.create(site=self.site, name='Hall A', code='HA')
        self.unit = make_unit('T-01', self.hall)
        self.other = make_unit('T-02', self.hall)
        self.system = System.objects.create(site=self.site, production_department=self.hall, name='RAS 1', code='R1')
        self.species = Species.objects.first() or make_species()

    def template(self, name='Hall view', **fields):
        return CardTemplate.objects.create(name=name, layout=fields.pop('layout', LAYOUT), **fields)

    def refused(self, **fields):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.template(**fields)

    def refused_update(self, queryset, **fields):
        with self.assertRaises(IntegrityError), transaction.atomic():
            queryset.update(**fields)


class TemplateConstraintTests(Fixture):
    def test_a_name_is_given_and_unique_among_the_live_templates_in_any_case(self):
        self.refused(name='')
        first = self.template('Hall view')
        self.refused(name='HALL VIEW')
        first.soft_delete(None)
        self.template('hall view')                                        # a deleted template frees its name

    def test_the_layout_version_is_one_the_code_knows_and_the_layout_says_the_same(self):
        self.assertEqual(self.template().schema_version, catalogue.SCHEMA_VERSION)
        self.refused(name='a', schema_version=0)
        self.refused(name='b', schema_version=catalogue.SCHEMA_VERSION + 1,
                     layout={**LAYOUT, 'schema': catalogue.SCHEMA_VERSION + 1})
        self.refused(name='c', layout={**LAYOUT, 'schema': 2})
        self.refused(name='d', layout={**LAYOUT, 'schema': '1'})
        self.refused(name='e', layout={'widgets': []})

    def test_the_layout_is_an_object_with_a_list_of_at_most_forty_widgets_in_32_kilobytes(self):
        self.refused(name='a', layout=[])
        self.refused(name='b', layout='{}')
        self.refused(name='c', layout={'schema': 1, 'widgets': {}})
        self.refused(name='d', layout={'schema': 1, 'widgets': 'none'})
        self.refused(name='e', layout={'schema': 1})
        widget = LAYOUT['widgets'][0]
        self.template('forty', layout={'schema': 1, 'widgets': [widget] * 40})   # the database counts; overlap is the validator's
        self.refused(name='f', layout={'schema': 1, 'widgets': [widget] * 41})
        self.refused(name='g', layout={'schema': 1, 'widgets': [], 'pad': 'x' * 33000})
        self.template('empty', layout={'schema': 1, 'widgets': []})            # a dot tile: the frame alone

    def test_a_template_does_not_expand_into_itself(self):
        template = self.template()
        self.refused_update(CardTemplate.objects.filter(pk=template.pk), expanded=template)
        other = self.template('Other')
        CardTemplate.objects.filter(pk=template.pk).update(expanded=other)

    def test_only_the_four_built_ins_are_built_in(self):
        self.refused(name='Fake', is_builtin=True)
        template = self.template()
        self.refused_update(CardTemplate.objects.filter(pk=template.pk), is_builtin=True)

    def test_a_measure_is_whole_or_absent_and_in_its_range(self):
        """A fitted template's measure (0005): both its width and its height in card units, or neither."""
        self.template('Flows')                                              # neither: a card that flows
        fitted = self.template('Fitted', measure_w=31, measure_h=10)
        self.assertEqual(fitted.measure, (31, 10))
        self.assertIsNone(CardTemplate.objects.get(name='Flows').measure)
        for width, height in ((31, None), (None, 10), (11, 10), (65, 10), (31, 5), (31, 65), (0, 0)):
            with self.subTest(width=width, height=height):
                self.refused(name=f'Odd {width} {height}', measure_w=width, measure_h=height)
        self.refused_update(CardTemplate.objects.filter(pk=fitted.pk), measure_h=None)
        low, high = catalogue.MEASURE_W, catalogue.MEASURE_H
        self.template('Least', measure_w=low[0], measure_h=high[0])
        self.template('Most', measure_w=low[1], measure_h=high[1])


class BuiltinTests(Fixture):
    def test_the_migrations_made_the_four_built_ins_as_builtin_py_says_them(self):
        found = {template.pk: template for template in CardTemplate.objects.filter(is_builtin=True)}
        self.assertEqual(set(found), {builtin.SIMPLE, builtin.DETAILED, builtin.OPERATOR, builtin.SMALL})
        for pk, (name, layout, expanded) in builtin.BUILTINS.items():
            with self.subTest(template=name):
                self.assertEqual((found[pk].name, found[pk].layout, found[pk].expanded_id), (name, layout, expanded))
                self.assertEqual(found[pk].measure, builtin.MEASURES.get(pk))
                self.assertEqual([problem for problem in validate.validate(layout) if problem.severity == 'error'], [])
        self.assertEqual((found[builtin.SIMPLE].expanded_id, found[builtin.DETAILED].expanded_id),
                         (builtin.DETAILED, builtin.SIMPLE))
        self.assertEqual(found[builtin.SMALL].measure, (31, 10))
        self.assertEqual(found[builtin.BIG].measure, (48, 61))
        self.assertEqual(sorted(builtin.MEASURES), [builtin.SMALL, builtin.BIG])   # the others flow, as they always did

    def test_the_migrations_froze_the_same_layouts(self):
        first = import_module('monitoring.migrations.0002_card_templates')
        small = import_module('monitoring.migrations.0005_small_template')
        big = import_module('monitoring.migrations.0006_big_template')
        frozen = {**{pk: [*row, None] for pk, row in first.BUILTINS.items()}, **small.BUILTINS, **big.BUILTINS}
        self.assertEqual(json.loads(json.dumps(frozen)),
                         {str(pk): [name, layout, str(expanded), list(builtin.MEASURES[pk]) if pk in builtin.MEASURES
                                    else None] for pk, (name, layout, expanded) in builtin.BUILTINS.items()})

    def test_every_unit_falls_back_to_simple(self):
        rule = CardTemplateAssignment.objects.get()
        self.assertEqual((rule.template_id, rule.unit, rule.system, rule.system_type, rule.species, rule.kind),
                         (builtin.SIMPLE, None, None, None, None, None))

    def test_a_built_in_is_never_changed_or_deleted_by_any_writer(self):
        simple = CardTemplate.objects.filter(pk=builtin.SIMPLE)
        self.refused_update(simple, name='Mine')
        self.refused_update(simple, layout={'schema': 1, 'widgets': []})
        self.refused_update(simple, description='x')
        self.refused_update(simple, is_deleted=True)
        self.refused_update(simple, is_builtin=False)
        with self.assertRaises(IntegrityError), transaction.atomic():
            simple.delete()

    def test_a_database_emptied_and_loaded_again_gets_its_built_ins_back(self):
        """What a test run's serialized rollback and a restore of a dump do: TRUNCATE (no row trigger) and INSERT the rows
        as they were. A built-in's id is one of the four (the CHECK), so only they can come back."""
        rows = [(pk, name, layout, builtin.MEASURES.get(pk, (None, None)))
                for pk, (name, layout, _expanded) in builtin.BUILTINS.items()]
        with connection.cursor() as cursor:
            cursor.execute('TRUNCATE monitor_card_templates CASCADE')
        for pk, name, layout, (width, height) in rows:
            CardTemplate.objects.create(id=pk, name=name, layout=layout, is_builtin=True, measure_w=width,
                                        measure_h=height)
        self.assertEqual(CardTemplate.objects.filter(is_builtin=True).count(), 4)
        self.assertEqual(CardTemplate.objects.get(pk=builtin.SMALL).measure, builtin.SMALL_MEASURE)

    def test_a_built_in_shows_its_name_in_the_persons_language_a_template_of_ones_own_as_typed(self):
        simple = CardTemplate.objects.get(pk=builtin.SIMPLE)
        with translation.override('nb'):
            self.assertNotEqual(simple.shown_name, 'Simple')
            self.assertEqual(self.template('Simple view').shown_name, 'Simple view')
        self.assertEqual(str(simple), 'Simple')


class AssignmentConstraintTests(Fixture):
    def assign(self, **scope):
        return CardTemplateAssignment.objects.create(template=self.template(f'T {CardTemplate.objects.count()}'), **scope)

    def refused(self, **scope):
        template = self.template(f'R {CardTemplate.objects.count()}')
        with self.assertRaises(IntegrityError), transaction.atomic():
            CardTemplateAssignment.objects.create(template=template, **scope)

    def test_one_scope_per_row(self):
        self.refused(unit=self.unit, kind='tank')
        self.refused(system=self.system, species=self.species)
        self.refused(system_type='ras', kind='pond')

    def test_one_live_row_per_scope_and_one_global(self):
        for scope in ({'unit': self.unit}, {'system': self.system}, {'system_type': 'ras'}, {'species': self.species},
                      {'kind': 'tank'}):
            with self.subTest(scope=scope):
                first = self.assign(**scope)
                self.refused(**scope)
                first.soft_delete(None)
                self.assign(**scope)                                       # a deleted rule frees its scope
        self.refused()                                                     # a second global: the migration made one

    def test_the_system_type_and_the_kind_are_ones_the_farm_knows(self):
        self.assign(system_type='hatchery')                                # reachable here, not through a unit's kind
        self.assign(kind='cage')
        for scope in ({'system_type': 'castle'}, {'system_type': ''}, {'kind': 'reef'}, {'kind': ''}):
            with self.subTest(scope=scope):
                self.refused(**scope)


class DeleteTests(Fixture):
    def test_a_built_in_and_the_global_rules_template_cannot_be_deleted(self):
        self.assertTrue(CardTemplate.objects.get(pk=builtin.DETAILED).delete_blockers())
        mine = self.template()
        self.assertEqual(mine.delete_blockers(), [])
        CardTemplateAssignment.objects.filter(unit=None, system=None, system_type=None, species=None,
                                              kind=None).update(template=mine)
        self.assertTrue(mine.delete_blockers())

    def test_the_global_rule_cannot_be_deleted_a_scoped_one_can(self):
        global_rule = CardTemplateAssignment.objects.get()
        self.assertTrue(global_rule.delete_blockers())
        scoped = CardTemplateAssignment.objects.create(template=self.template(), unit=self.unit)
        self.assertEqual(scoped.delete_blockers(), [])

    def test_deleting_a_template_deletes_its_rules_and_detaches_what_points_at_it(self):
        mine = self.template()
        rule = CardTemplateAssignment.objects.create(template=mine, unit=self.unit)
        other = self.template('Other', expanded=mine)
        board = MonitorBoard.objects.create(name='Wall', default_template=mine)
        row = MonitorBoardUnit.objects.create(board=board, unit=self.unit, template=mine)
        plan = softdelete.plan_delete(mine)
        self.assertTrue(plan.can_delete)
        self.assertEqual(plan.cascade, [rule])
        self.assertEqual(sorted((type(record).__name__, link) for record, link in plan.detach),
                         [('CardTemplate', 'expanded'), ('MonitorBoard', 'default_template')])
        softdelete.execute(plan, None)
        rule.refresh_from_db()
        other.refresh_from_db()
        board.refresh_from_db()
        row.refresh_from_db()
        self.assertEqual((rule.is_deleted, other.expanded, board.default_template), (True, None, None))
        self.assertEqual(row.template, mine)                     # a board's card row is a plain row: it keeps its pointer,
        # and the resolver reads live templates only, so the row counts again if the template is restored

    def test_a_deleted_units_rule_stays_and_counts_again_on_restore(self):
        rule = CardTemplateAssignment.objects.create(template=self.template(), unit=self.unit)
        plan = softdelete.plan_delete(self.unit)
        self.assertNotIn(rule, plan.cascade)
        self.assertIn(CardTemplateAssignment, plan.kept)


class BoardColumnsTests(Fixture):
    def test_a_board_has_a_card_width_and_a_default_template_and_a_row_its_own_template(self):
        board = MonitorBoard.objects.create(name='Wall')
        self.assertEqual(board.card_width, CardWidth.AUTO)
        with self.assertRaises(IntegrityError), transaction.atomic():
            MonitorBoard.objects.filter(pk=board.pk).update(card_width=9)
        board.default_template = CardTemplate.objects.get(pk=builtin.OPERATOR)
        board.save()
        row = MonitorBoardUnit.objects.create(board=board, unit=self.unit, template_id=builtin.DETAILED)
        board.refresh_from_db()
        row.refresh_from_db()
        self.assertEqual((board.default_template_id, row.template_id), (builtin.OPERATOR, builtin.DETAILED))


class BackfillTests(TestCase):
    """0004: a board's default mode and each card's mode become the built-in templates; back, the modes return."""

    def migrate(self, target):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate([('monitoring', target)])
        return executor.loader.project_state([('monitoring', target)]).apps

    def test_forward_and_back(self):
        site = Site.objects.create(name='Bergen', code='BG')
        hall = ProductionDepartment.objects.create(site=site, name='Hall A', code='HA')
        units = [make_unit(f'T-0{number}', hall) for number in range(3)]
        old = self.migrate('0003_template_pointers')
        Board, Row = old.get_model('monitoring', 'MonitorBoard'), old.get_model('monitoring', 'MonitorBoardUnit')
        simple = Board.objects.create(name='Simple wall', default_mode='simple')
        detailed = Board.objects.create(name='Detailed wall', default_mode='detailed')
        for unit, mode in zip(units, ('', 'simple', 'detailed')):
            Row.objects.create(board=simple, unit_id=unit.pk, mode=mode)
        new = self.migrate('0004_backfill_modes')
        Board, Row = new.get_model('monitoring', 'MonitorBoard'), new.get_model('monitoring', 'MonitorBoardUnit')
        self.assertEqual({board.name: board.default_template_id for board in Board.objects.all()},
                         {'Simple wall': builtin.SIMPLE, 'Detailed wall': builtin.DETAILED})
        self.assertEqual(sorted((row.mode, row.template_id) for row in Row.objects.all()),
                         sorted([('', None), ('simple', builtin.SIMPLE), ('detailed', builtin.DETAILED)]))
        # back: a board on a built-in gets its mode again (here moved to Simple before the rollback)
        Board.objects.filter(pk=detailed.pk).update(default_template_id=builtin.SIMPLE, default_mode='detailed')
        back = self.migrate('0003_template_pointers')
        Board = back.get_model('monitoring', 'MonitorBoard')
        self.assertEqual({board.name: board.default_mode for board in Board.objects.all()},
                         {'Simple wall': 'simple', 'Detailed wall': 'simple'})
        self.assertEqual(Board.objects.count(), 2)
        self.migrate('0006_big_template')
        self.assertTrue(global_apps.get_model('monitoring', 'CardTemplate').objects.filter(is_builtin=True).exists())


class SmallTemplateMigrationTests(TestCase):
    """0005: the measure columns and the fourth built-in. Back, the row goes (a built-in is deleted by no writer but
    this migration) with what pointed at it detached; forward again, it is back as it was."""

    def migrate(self, target):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate([('monitoring', target)])
        return executor.loader.project_state([('monitoring', target)]).apps

    def test_back_and_forward(self):
        site = Site.objects.create(name='Bergen', code='BG')
        hall = ProductionDepartment.objects.create(site=site, name='Hall A', code='HA')
        unit = make_unit('T-01', hall)
        board = MonitorBoard.objects.create(name='Overview', default_template_id=builtin.SMALL)
        MonitorBoardUnit.objects.create(board=board, unit=unit, template_id=builtin.SMALL)
        CardTemplateAssignment.objects.create(template_id=builtin.SMALL, unit=unit)
        mine = CardTemplate.objects.create(name='Mine', layout=LAYOUT, expanded_id=builtin.SMALL, measure_w=31,
                                           measure_h=10)
        old = self.migrate('0004_backfill_modes')
        Template, Board = old.get_model('monitoring', 'CardTemplate'), old.get_model('monitoring', 'MonitorBoard')
        Row, Rule = old.get_model('monitoring', 'MonitorBoardUnit'), old.get_model('monitoring', 'CardTemplateAssignment')
        self.assertEqual(sorted(str(pk) for pk in Template.objects.filter(is_builtin=True).values_list('pk', flat=True)),
                         sorted(str(pk) for pk in (builtin.SIMPLE, builtin.DETAILED, builtin.OPERATOR)))
        self.assertFalse(hasattr(Template.objects.get(pk=mine.pk), 'measure_w'))
        self.assertIsNone(Template.objects.get(pk=mine.pk).expanded_id)
        self.assertIsNone(Board.objects.get(pk=board.pk).default_template_id)
        self.assertEqual([row.template_id for row in Row.objects.all()], [None])
        self.assertEqual(Rule.objects.filter(unit_id=unit.pk).count(), 0)          # a rule goes with its template
        with self.assertRaises(IntegrityError), transaction.atomic():              # the CHECK is the three ids again
            Template.objects.create(id=builtin.SMALL, name='Small', layout=LAYOUT, is_builtin=True)
        with self.assertRaises(IntegrityError), transaction.atomic():              # and the trigger is on again
            Template.objects.filter(pk=builtin.SIMPLE).update(name='Mine too')
        self.migrate('0005_small_template')
        small = CardTemplate.objects.get(pk=builtin.SMALL)
        self.assertEqual((small.name, small.layout, small.expanded_id, small.measure, small.is_builtin),
                         ('Small', builtin.SMALL_LAYOUT, builtin.DETAILED, builtin.SMALL_MEASURE, True))
        with self.assertRaises(IntegrityError), transaction.atomic():
            CardTemplate.objects.filter(pk=builtin.SMALL).update(measure_w=40)       # frozen, its measure too
        self.migrate('0006_big_template')


class BigTemplateMigrationTests(TestCase):
    """0006: the fifth built-in. Back, the row goes with what pointed at it detached and the CHECK is the four ids
    again; forward again, it is back as it was."""

    def migrate(self, target):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate([('monitoring', target)])
        return executor.loader.project_state([('monitoring', target)]).apps

    def test_back_and_forward(self):
        site = Site.objects.create(name='Bergen', code='BG')
        hall = ProductionDepartment.objects.create(site=site, name='Hall A', code='HA')
        unit = make_unit('T-01', hall)
        board = MonitorBoard.objects.create(name='Tanks', default_template_id=builtin.BIG)
        MonitorBoardUnit.objects.create(board=board, unit=unit, template_id=builtin.BIG)
        CardTemplateAssignment.objects.create(template_id=builtin.BIG, unit=unit)
        old = self.migrate('0005_small_template')
        Template, Board = old.get_model('monitoring', 'CardTemplate'), old.get_model('monitoring', 'MonitorBoard')
        Row, Rule = old.get_model('monitoring', 'MonitorBoardUnit'), old.get_model('monitoring', 'CardTemplateAssignment')
        self.assertEqual(sorted(str(pk) for pk in Template.objects.filter(is_builtin=True).values_list('pk', flat=True)),
                         sorted(str(pk) for pk in (builtin.SIMPLE, builtin.DETAILED, builtin.OPERATOR, builtin.SMALL)))
        self.assertIsNone(Board.objects.get(pk=board.pk).default_template_id)
        self.assertEqual([row.template_id for row in Row.objects.all()], [None])
        self.assertEqual(Rule.objects.filter(unit_id=unit.pk).count(), 0)          # a rule goes with its template
        with self.assertRaises(IntegrityError), transaction.atomic():              # the CHECK is the four ids again
            Template.objects.create(id=builtin.BIG, name='Big', layout=LAYOUT, is_builtin=True)
        with self.assertRaises(IntegrityError), transaction.atomic():              # and the trigger is on again
            Template.objects.filter(pk=builtin.SMALL).update(name='Mine too')
        self.migrate('0006_big_template')
        big = CardTemplate.objects.get(pk=builtin.BIG)
        self.assertEqual((big.name, big.layout, big.expanded_id, big.measure, big.is_builtin),
                         ('Big', builtin.BIG_LAYOUT, builtin.DETAILED, builtin.BIG_MEASURE, True))
        self.assertEqual([problem for problem in validate.validate(big.layout) if problem.severity == 'error'], [])
        with self.assertRaises(IntegrityError), transaction.atomic():
            CardTemplate.objects.filter(pk=builtin.BIG).update(measure_h=40)         # frozen, its measure too
