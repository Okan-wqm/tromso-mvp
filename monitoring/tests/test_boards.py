"""Monitoring boards, checked against the stored rows: create, read, edit, delete and restore of a board, its cards saved as a
whole list, every constraint the database holds (each refused with IntegrityError), the migration, the role matrix, the menu,
the database viewer and the board on the page."""
import itertools
from decimal import Decimal

from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from core import access, database, navigation, softdelete
from core.models import AuditLog
from core.softdelete import plan_delete
from farm.models import Tank
from farm.tests.helpers import rows_data

from .. import read
from ..forms import BoardUnitForm, MonitorBoardForm
from ..models import MonitorBoard, MonitorBoardUnit
from . import MonitoringCase
from ..cards.builtin import DETAILED, SIMPLE
from core.testing import delete_confirmed

KEEPER = ('view_monitorboard', 'add_monitorboard', 'change_monitorboard', 'delete_monitorboard', 'view_tank',
          'view_stockoperation')
LIST, CREATE = reverse('monitoring:monitorboard_list'), reverse('monitoring:monitorboard_create')
NUMBER = itertools.count(1)


class BoardCase(MonitoringCase):
    def setUp(self):
        super().setUp()
        self.keeper = self.as_person('keeper', *KEEPER)

    def board(self, name=None, **fields):
        return MonitorBoard.objects.create(name=name or f'Board {next(NUMBER)}', **fields)

    def edit(self, board):
        return reverse('monitoring:monitorboard_edit', args=[board.pk])

    def units_url(self, board):
        return reverse('monitoring:monitorboard_units', args=[board.pk])

    def posted(self, board, **changes):
        form = self.client.get(self.edit(board)).context['form']
        data = {name: ('' if form[name].value() is None else form[name].value()) for name in form.fields}
        return {**data, **changes}

    def save_units(self, board, rows, initial=0):
        return self.client.post(self.units_url(board), rows_data('units', rows, initial=initial, record=board))


class ColumnsTests(BoardCase):
    def test_every_form_field_has_a_column(self):
        for form, model in ((MonitorBoardForm, MonitorBoard), (BoardUnitForm, MonitorBoardUnit)):
            columns = {field.name for field in model._meta.concrete_fields}
            for name in form.base_fields:
                with self.subTest(form=form.__name__, field=name):
                    self.assertIn(name, columns)
        self.assertEqual(set(MonitorBoardForm.base_fields) - {'version'},
                         {'name', 'description', 'default_template', 'card_width', 'refresh_seconds', 'screen',
                          'screen_inches', 'distance_m'})
        self.assertEqual(set(BoardUnitForm.base_fields), {'unit', 'template'})


class RoundTripTests(BoardCase):
    def test_a_board_is_created_read_edited_and_deleted(self):
        response = self.client.post(CREATE, {'name': 'Hall A wall', 'description': 'North screen',
                                             'default_template': str(DETAILED), 'card_width': '3',
                                             'refresh_seconds': '30'})
        self.assertEqual(response.status_code, 302)
        board = MonitorBoard.objects.get()
        self.assertEqual((board.name, board.description, board.default_template_id, board.card_width,
                          board.refresh_seconds, board.created_by, board.version),
                         ('Hall A wall', 'North screen', DETAILED, 3, 30, self.keeper, 1))
        self.assertEqual(AuditLog.objects.filter(entity_type='monitoring board', action='create').count(), 1)
        # read: the list, the edit form filled from the row
        listing = self.client.get(LIST)
        self.assertEqual([each.pk for each in listing.context['objects']], [board.pk])
        self.assertContains(listing, 'Hall A wall')
        self.assertContains(listing, f'{reverse("monitoring:monitor")}?board={board.pk}')
        form = self.client.get(self.edit(board)).context['form']
        self.assertEqual((form['name'].value(), str(form['default_template'].value()), form['card_width'].value(),
                          form['refresh_seconds'].value()), ('Hall A wall', str(DETAILED), 3, 30))
        # edit: every optional field cleared, the version moves, the change is logged
        response = self.client.post(self.edit(board), self.posted(board, name='Hall B wall', description='',
                                                                  default_template='', card_width='1',
                                                                  refresh_seconds=''))
        self.assertEqual(response.status_code, 302)
        board.refresh_from_db()
        self.assertEqual((board.name, board.description, board.default_template, board.card_width,
                          board.refresh_seconds, board.version, board.updated_by),
                         ('Hall B wall', '', None, 1, None, 2, self.keeper))           # empty: the rules decide
        self.assertEqual(AuditLog.objects.filter(entity_type='monitoring board', action='update').count(), 1)
        self.assertEqual(board.seconds, 15)                         # empty: the system's interval
        # delete: a soft delete with a clean plan, logged
        self.assertEqual(plan_delete(board).blockers, [])
        delete_confirmed(self.client, reverse('monitoring:monitorboard_delete', args=[board.pk]))
        self.assertFalse(MonitorBoard.objects.filter(pk=board.pk).exists())
        self.assertTrue(MonitorBoard.all_objects.get(pk=board.pk).is_deleted)
        self.assertTrue(AuditLog.objects.filter(entity_id=str(board.pk), action='delete').exists())

    def test_a_stale_version_is_refused(self):
        board = self.board('Wall')
        stale = self.posted(board, name='Mine')
        self.client.post(self.edit(board), self.posted(board, name='Theirs'))
        response = self.client.post(self.edit(board), stale, follow=True)
        self.assertEqual(MonitorBoard.objects.get(pk=board.pk).name, 'Theirs')
        self.assertContains(response, 'Someone else changed this monitoring board')

    def test_the_names_rules_reach_the_person_as_messages(self):
        self.board('Hall A wall')
        for data, text in (({'name': 'hall a WALL'}, 'Another monitoring board already has this name.'),
                           ({'name': ''}, 'This field is required.'),
                           ({'name': 'x', 'refresh_seconds': '5'}, 'greater than or equal to 10'),
                           ({'name': 'x', 'refresh_seconds': '601'}, 'less than or equal to 600')):
            with self.subTest(data=data):
                response = self.client.post(CREATE, {'description': '', 'card_width': '2', **data})
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, text)
        self.assertEqual(MonitorBoard.objects.count(), 1)


class WallScreenTests(BoardCase):
    """The board's wall screen and how far it is read from (CONSENSUS §9), through the form, against the stored row."""

    def test_a_preset_is_its_own_diagonal_another_screen_is_typed_and_none_clears_both(self):
        response = self.client.post(CREATE, {'name': 'Hall A wall', 'card_width': '2', 'screen': '55', 'screen_inches': '',
                                             'distance_m': '3'})
        self.assertEqual(response.status_code, 302)
        board = MonitorBoard.objects.get()
        self.assertEqual((board.screen, board.screen_inches, board.distance_m, board.legible),
                         ('55', Decimal('55.0'), Decimal('3.0'), True))
        # a preset wins over a diagonal typed beside it: the preset is a known screen
        self.client.post(self.edit(board), self.posted(board, screen='24', screen_inches='40', distance_m='1'))
        board.refresh_from_db()
        self.assertEqual((board.screen, board.screen_inches), ('24', Decimal('24.0')))
        self.client.post(self.edit(board), self.posted(board, screen='other', screen_inches='43'))
        board.refresh_from_db()
        self.assertEqual((board.screen, board.screen_inches), ('other', Decimal('43.0')))
        self.client.post(self.edit(board), self.posted(board, screen='', screen_inches='43', distance_m=''))
        board.refresh_from_db()
        self.assertEqual((board.screen, board.screen_inches, board.distance_m, board.legible), ('', None, None, False))
        self.assertEqual(AuditLog.objects.filter(entity_type='monitoring board', action='update').count(), 3)
        listing = self.client.get(LIST)
        self.assertContains(listing, 'Wall screen')

    def test_what_the_form_refuses_reaches_the_person_as_messages(self):
        for data, text in (({'screen': 'other', 'screen_inches': ''}, 'Type the diagonal of the screen, in inches.'),
                           ({'screen': 'other', 'screen_inches': '9'}, 'greater than or equal to 10'),
                           ({'screen': '55', 'distance_m': '0.4'}, 'greater than or equal to 0.5'),
                           ({'screen': '55', 'distance_m': '21'}, 'less than or equal to 20')):
            with self.subTest(data=data):
                response = self.client.post(CREATE, {'name': 'x', 'card_width': '2', 'screen_inches': '',
                                                     'distance_m': '', **data})
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, text)
        self.assertFalse(MonitorBoard.objects.exists())

    def test_a_screen_and_distance_no_card_can_be_read_at_are_refused_with_the_farthest_that_works(self):
        """Review round 2, B3: a 24 inch monitor read from 3 m was accepted, and its wall drew 4 px type."""
        for screen, inches, metres, farthest in (('24', '', '3', '1.9'), ('24', '', '5', '1.9'), ('55', '', '5', '4.4'),
                                                 ('other', '24', '3', '1.9')):
            # (the distance said as a number of the person's language, to one decimal, as the form shows it)
            with self.subTest(screen=screen, metres=metres):
                response = self.client.post(CREATE, {'name': 'x', 'card_width': '2', 'screen': screen,
                                                     'screen_inches': inches, 'distance_m': metres})
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, f'Not one card a page can be read from {metres}.0 m on this screen: '
                                              f'read it from {farthest} m or nearer, or choose a larger screen.')
        self.assertFalse(MonitorBoard.objects.exists())
        # met, but one card a page: saved, and the person is told what the wall will do
        response = self.client.post(CREATE, {'name': 'Hall A wall', 'card_width': '2', 'screen': '55',
                                             'screen_inches': '', 'distance_m': '3'}, follow=True)
        self.assertContains(response, 'From 3.0 m this screen shows 1 card a page: the wall turns its pages. '
                                      'A nearer distance or a larger screen shows more.')
        board = MonitorBoard.objects.get()
        # many a page: nothing to warn of
        response = self.client.post(self.edit(board), self.posted(board, distance_m='1'), follow=True)
        self.assertNotContains(response, 'the wall turns its pages')
        self.assertEqual(MonitorBoard.objects.get().distance_m, Decimal('1.0'))

    def test_the_database_holds_the_screens_rules(self):
        def refused(**fields):
            with self.assertRaises(IntegrityError), transaction.atomic():
                MonitorBoard.objects.bulk_create([MonitorBoard(name=f'Board {next(NUMBER)}', **fields)])
        refused(screen='55', screen_inches=Decimal('40'))          # a preset is its own diagonal
        refused(screen='55')                                       # ... and has it
        refused(screen='', screen_inches=Decimal('55'))            # no screen, no diagonal
        refused(screen='other')
        for inches in ('9.9', '150.1'):
            refused(screen='other', screen_inches=Decimal(inches))
        for metres in ('0.4', '20.1'):
            refused(distance_m=Decimal(metres))
        refused(screen='99', screen_inches=Decimal('99'))          # not a screen the list offers
        for fields in ({'screen': 'other', 'screen_inches': Decimal('10')}, {'screen': 'other', 'screen_inches': Decimal('150')},
                       {'screen': '65', 'screen_inches': Decimal('65')}, {'distance_m': Decimal('0.5')},
                       {'distance_m': Decimal('20')}):
            MonitorBoard.objects.bulk_create([MonitorBoard(name=f'Board {next(NUMBER)}', **fields)])

    def test_the_wall_is_told_its_screen_and_distance_only_when_the_board_says_both(self):
        board = self.board('Wall', screen='55', screen_inches=Decimal('55'), distance_m=Decimal('3'))
        html = self.client.get(reverse('monitoring:monitor'), {'board': str(board.pk), 'wall': '1'}).content.decode()
        self.assertIn('data-screen-inches="55.0" data-distance-m="3.0"', html)       # a dot in every language: a number
        self.client.cookies['django_language'] = 'nb'
        self.assertIn('data-screen-inches="55.0" data-distance-m="3.0"',
                      self.client.get(reverse('monitoring:monitor'), {'board': str(board.pk)}).content.decode())
        MonitorBoard.objects.filter(pk=board.pk).update(distance_m=None)
        html = self.client.get(reverse('monitoring:monitor'), {'board': str(board.pk), 'wall': '1'}).content.decode()
        self.assertNotIn('data-screen-inches', html)
        self.assertNotIn('data-distance-m', html)


class CardsListTests(BoardCase):
    def test_the_list_is_saved_whole_with_one_log_entry_and_its_author(self):
        board = self.board('Wall')
        response = self.save_units(board, [{'unit': str(self.t1.pk), 'template': str(DETAILED)},
                                           {'unit': str(self.t2.pk), 'template': ''}])
        self.assertEqual(response.status_code, 302)
        rows = {row.unit.code: (row.template_id, row.created_by) for row in board.rows.select_related('unit')}
        self.assertEqual(rows, {'T-01': (DETAILED, self.keeper), 'T-02': (None, self.keeper)})
        entry = AuditLog.objects.get(entity_id=str(board.pk), action='update')
        self.assertEqual(entry.changes['Units'], [None, 'T-01: Detailed; T-02: as the board'])
        board.refresh_from_db()
        self.assertEqual(board.version, 2)
        # saved whole: a second list replaces the first
        self.save_units(board, [{'unit': str(self.p1.pk), 'template': str(SIMPLE)}])
        self.assertEqual([row.unit.code for row in board.rows.all()], ['P-01'])
        self.assertEqual(AuditLog.objects.filter(entity_id=str(board.pk), action='update').count(), 2)

    def test_one_card_per_unit_a_stale_list_and_a_template_that_is_not_one_are_refused(self):
        board = self.board('Wall')
        twice = self.save_units(board, [{'unit': str(self.t1.pk), 'template': ''}, {'unit': str(self.t1.pk), 'template': ''}])
        self.assertContains(twice, 'One card per unit.')
        self.assertEqual(board.rows.count(), 0)
        bad = self.save_units(board, [{'unit': str(self.t1.pk), 'template': 'huge'}])
        self.assertEqual(bad.status_code, 200)
        self.assertEqual(board.rows.count(), 0)
        stale = rows_data('units', [{'unit': str(self.t1.pk), 'template': ''}], record=board)
        self.save_units(board, [{'unit': str(self.t2.pk), 'template': ''}])
        self.client.post(self.units_url(board), stale)                    # based on the version before the save
        self.assertEqual([row.unit.code for row in board.rows.all()], ['T-02'])

    def test_a_deleted_unit_keeps_its_row_hidden_back_on_restore_and_dropped_by_a_save(self):
        board = self.board('Wall')
        # (the pond is empty: a unit with fish cannot be deleted)
        self.save_units(board, [{'unit': str(self.t1.pk), 'template': ''}, {'unit': str(self.p1.pk), 'template': str(DETAILED)}])
        shown = lambda: [unit.code for unit in read.units_for(read.Params(), MonitorBoard.objects
                                                              .prefetch_related('rows').get(pk=board.pk))]
        self.assertEqual(shown(), ['T-01', 'P-01'])
        Tank.objects.get(pk=self.p1.pk).soft_delete(self.keeper)
        self.assertEqual(board.rows.count(), 2)                          # the row stays: configuration, not history
        self.assertEqual(shown(), ['T-01'])                              # the live join hides the card
        form = self.client.get(self.edit(board)).context['units']
        self.assertEqual([row.instance.unit.code for row in form.forms], ['T-01'])    # the form offers live units only
        softdelete.restore(Tank.all_objects.get(pk=self.p1.pk), self.keeper)
        self.assertEqual(shown(), ['T-01', 'P-01'])                      # back on restore
        Tank.objects.get(pk=self.p1.pk).soft_delete(self.keeper)
        self.save_units(board, [{'unit': str(self.t1.pk), 'template': ''}])
        self.assertEqual([row.unit.code for row in board.rows.all()], ['T-01'])        # a save drops it

    def test_a_deleted_board_comes_back_with_its_cards(self):
        board = self.board('Wall')
        self.save_units(board, [{'unit': str(self.t1.pk), 'template': ''}])
        delete_confirmed(self.client, reverse('monitoring:monitorboard_delete', args=[board.pk]))
        self.assertEqual(MonitorBoardUnit.objects.filter(board=board).count(), 1)      # a soft delete never cascades
        softdelete.restore(MonitorBoard.all_objects.get(pk=board.pk), self.keeper)
        restored = MonitorBoard.objects.prefetch_related('rows').get(pk=board.pk)
        self.assertEqual([unit.code for unit in read.units_for(read.Params(), restored)], ['T-01'])
        self.assertTrue(AuditLog.objects.filter(entity_id=str(board.pk), action='restore').exists())


class ConstraintTests(BoardCase):
    def refused(self, **fields):
        with self.assertRaises(IntegrityError), transaction.atomic():
            MonitorBoard.objects.create(**{'name': f'Board {next(NUMBER)}', **fields})

    def test_the_database_holds_every_rule_a_row_can_state(self):
        first = self.board('Hall A wall')
        self.refused(name='hall a wall')                                  # unique among the live, in any case
        self.refused(name='')
        self.refused(default_mode='x')
        for seconds in (9, 601):
            self.refused(refresh_seconds=seconds)
        for seconds in (None, 10, 600):                                   # the edges are allowed
            self.board(refresh_seconds=seconds)
        first.delete()
        self.board('HALL A WALL')                                         # the name is free once the first is deleted

    def test_a_card_is_one_per_unit_and_its_mode_is_in_range(self):
        board = self.board('Wall')
        MonitorBoardUnit.objects.create(board=board, unit=self.t1, mode='')
        with self.assertRaises(IntegrityError), transaction.atomic():
            MonitorBoardUnit.objects.create(board=board, unit=self.t1, mode='simple')
        with self.assertRaises(IntegrityError), transaction.atomic():
            MonitorBoardUnit.objects.create(board=board, unit=self.t2, mode='x')
        for mode in ('', 'simple', 'detailed'):
            MonitorBoardUnit.objects.create(board=self.board(), unit=self.t2, mode=mode)
        MonitorBoardUnit.objects.create(board=self.board(), unit=self.t1)        # the same unit on another board


class RulesTests(BoardCase):
    def test_the_matrix_the_menu_and_the_viewer_know_the_boards(self):
        areas = [str(area.label) for area in access.areas()]
        self.assertEqual(areas[areas.index('Tanks, ponds & cages') + 1], 'Monitoring boards')
        area = next(each for each in access.areas() if each.model == 'monitoring.MonitorBoard')
        self.assertEqual(area.actions, ('view', 'add', 'change', 'delete'))
        place = navigation.place('monitoring.view_monitorboard')
        self.assertEqual((str(place.entry.label), str(place.section.label), str(place.group.label)),
                         ('Monitoring boards', 'Setup', 'Facility structure'))
        self.assertContains(self.client.get(LIST), 'aria-current="page"')
        tables = {table.name: table for _section, found in database.sections() for table in found}
        for name in ('monitor_boards', 'monitor_board_units'):
            self.assertTrue(tables[name].description, name)
        self.assertTrue(tables['monitor_boards'].description.startswith('The named wall screens'))
        names = {constraint.name for constraint in tables['monitor_boards'].structure().constraints}
        self.assertTrue({'chk_monitor_boards_name', 'chk_monitor_boards_mode', 'chk_monitor_boards_refresh'} <= names)

    def test_the_boards_are_for_those_who_may_make_them_and_open_for_those_who_may_read_the_page(self):
        board = self.board('Wall')
        self.as_person('reader-only', 'view_stockoperation')
        self.assertEqual(self.client.get(LIST).status_code, 403)
        self.assertEqual(self.client.post(CREATE, {'name': 'x'}).status_code, 403)
        self.assertEqual(self.client.get(self.edit(board)).status_code, 403)
        self.assertEqual(delete_confirmed(self.client,
                                          reverse('monitoring:monitorboard_delete', args=[board.pk])).status_code, 403)
        page = self.client.get(reverse('monitoring:monitor'), {'board': board.pk})
        self.assertEqual(page.status_code, 200)                           # any reader may choose a board
        self.assertContains(page, 'Wall')


class MigrationTests(TransactionTestCase):
    serialized_rollback = True

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)

    def tables(self):
        with connection.cursor() as cursor:
            return {name for name in connection.introspection.table_names(cursor)}

    def test_it_applies_reverses_and_applies_again(self):
        self.addCleanup(lambda: self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes()))
        self.assertTrue({'monitor_boards', 'monitor_board_units'} <= self.tables())
        self.migrate([('monitoring', None)])
        self.assertFalse({'monitor_boards', 'monitor_board_units'} & self.tables())
        self.migrate([('monitoring', '0001_boards')])
        self.assertTrue({'monitor_boards', 'monitor_board_units'} <= self.tables())

    def test_the_migration_starts_from_the_tanks_not_the_latest_farm_migration(self):
        migration = MigrationExecutor(connection).loader.get_migration('monitoring', '0001_boards')
        self.assertIn(('farm', '0008_tanks'), migration.dependencies)

    def test_the_models_and_the_migration_agree(self):
        call_command('makemigrations', 'monitoring', check=True, dry_run=True, verbosity=0)


class ScreenMigrationTests(TestCase):
    """0008: a board that existed at 0007 says no screen and no distance (its wall is as it was), which the new
    constraints accept; back, the row stays and its columns go."""

    def migrate(self, target):
        # (the rows this test made have their deferred checks still pending in its transaction: run them now)
        with connection.cursor() as cursor:
            cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate([('monitoring', target)])
        return executor.loader.project_state([('monitoring', target)]).apps

    def test_a_board_of_0007_reads_no_screen_and_no_distance(self):
        leaf = MigrationExecutor(connection).loader.graph.leaf_nodes('monitoring')
        old = self.migrate('0007_ph_window_scales')
        Board = old.get_model('monitoring', 'MonitorBoard')
        board = Board.objects.create(name='Hall A wall', default_mode='simple', card_width=3, refresh_seconds=30)
        Board = self.migrate('0008_board_screen').get_model('monitoring', 'MonitorBoard')
        self.assertEqual(list(Board.objects.filter(pk=board.pk).values_list('name', 'card_width', 'refresh_seconds',
                                                                             'screen', 'screen_inches', 'distance_m')),
                         [('Hall A wall', 3, 30, '', None, None)])
        Board = self.migrate('0007_ph_window_scales').get_model('monitoring', 'MonitorBoard')
        self.assertEqual(list(Board.objects.values_list('name', 'card_width', 'refresh_seconds')), [('Hall A wall', 3, 30)])
        self.migrate(leaf[0][1])
        self.assertFalse(MonitorBoard.objects.get(pk=board.pk).legible)


class OnThePageTests(BoardCase):
    def test_a_board_picks_its_units_draws_each_as_its_row_says_and_sets_the_interval(self):
        board = self.board('Wall', default_template_id=SIMPLE, refresh_seconds=45)
        self.save_units(board, [{'unit': str(self.t1.pk), 'template': str(DETAILED)}, {'unit': str(self.t2.pk), 'template': ''}])
        page = self.client.get(reverse('monitoring:monitor'), {'board': str(board.pk), 'full': '1'})
        html = page.content.decode()
        self.assertEqual(page.context['shown'], 2)
        self.assertIn('data-poll-every="45"', html)
        self.assertEqual(html.count(f'data-template="{DETAILED}"'), 1)                    # T-01 by its row, T-02 by the board's default
        self.assertIn(f'<option value="{board.pk}" selected>Wall</option>', html)
        self.assertIn(f'data-storage-key="monitoring:{board.pk}"', html)
        # the board's default template applies to every card without a template of its own
        MonitorBoard.objects.filter(pk=board.pk).update(default_template_id=DETAILED)
        self.assertEqual(self.client.get(reverse('monitoring:monitor'), {'board': str(board.pk), 'full': '1'}).content.decode()
                         .count(f'data-template="{DETAILED}"'), 2)

    def test_a_board_that_does_not_exist_shows_the_page_without_it(self):
        page = self.client.get(reverse('monitoring:monitor'), {'full': '1', 'board': '6f7f1b3a-6c9e-4f43-8f0e-6a7d0d0b0a11'})
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context['shown'], 0)                       # never the whole farm for a wall that lost its board

    def test_a_board_with_no_cards_or_deleted_under_a_running_wall_shows_no_unit(self):
        board = self.board('Wall')
        url = reverse('monitoring:cards')
        empty = self.client.get(reverse('monitoring:monitor'), {'board': str(board.pk), 'full': '1'})
        self.assertEqual(empty.context['shown'], 0)
        self.save_units(board, [{'unit': str(self.t1.pk), 'template': ''}])
        self.assertEqual(self.client.get(reverse('monitoring:monitor'), {'board': str(board.pk), 'full': '1'}).context['shown'], 1)
        delete_confirmed(self.client, reverse('monitoring:monitorboard_delete', args=[board.pk]))
        gone = self.client.get(url, {'board': str(board.pk)}).content.decode()
        self.assertNotIn('data-key="card:', gone)                          # the poll of a deleted board draws no card

    def test_the_token_moves_when_a_board_is_saved(self):
        board = self.board('Wall')
        before = read.change_token(self.reader, f'board={board.pk}', board=str(board.pk))
        self.client.post(self.edit(board), self.posted(board, name='Wall 2'))
        self.assertNotEqual(read.change_token(self.reader, f'board={board.pk}', board=str(board.pk)), before)
        before = read.change_token(self.reader, f'board={board.pk}', board=str(board.pk))
        self.save_units(board, [{'unit': str(self.t1.pk), 'template': ''}], initial=0)
        self.assertNotEqual(read.change_token(self.reader, f'board={board.pk}', board=str(board.pk)), before)
