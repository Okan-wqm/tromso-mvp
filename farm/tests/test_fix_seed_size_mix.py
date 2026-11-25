"""`manage.py fix_seed_size_mix`: the development seed's two Tromsø cages, each with grow-out salmon (only TG-M01), the
post-smolt, the smolt and the lumpfish, separated through the app's own transfers dated today, in one transaction: the
post-smolt and the smolt get a cage each, made like TG-M02 through the units tab's form; the grow-out salmon and its
lumpfish stay in TG-M01, TG-M02's lumpfish go with the post-smolt into TG-M03 (no cage holds cleaner fish alone, the
owner's decision of 2026-11-09), so TG-M02 is left empty; the history before stays as recorded; check_stock finds nothing new; a second run does nothing; the dry
run writes nothing; every refusal leaves the database as it was."""
import io
from decimal import Decimal
from unittest import mock

from django.core.management import CommandError, call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.urls import reverse

from core.models import AuditLog

from ..management.commands import fix_seed_size_mix
from ..models import (
    Batch, HandlingAcknowledgement, ProductionDepartment, SamplingPoint, Site, StockMovement, StockOperation, Tank,
)
from ..models.feeding import FeedTarget
from ..stock import integrity, read, services
from .helpers import make_species, may_record
from .test_feeding import FeedingTestCase

D = Decimal


def make_cage(code, name, department, diameter='50'):
    unit = Tank.objects.create(name=name, code=code, kind='cage', production_department=department,
                               water_type='saltwater', status='preparing', cage_type='floating', shape='circular',
                               diameter=D(diameter), depth=D('20'), max_density_kg_m3=D('20'))
    unit.refresh_from_db()
    return unit


class SeedCagesTestCase(FeedingTestCase):
    """The seed's Tromsø cages as the dev database has them, in small: 1,000 grow-out salmon of 4,217 g in TG-M01; the
    post-smolt of 594 g in both cages (1,000 and 2,000), the smolt of 78 g in both (500 each) and the lumpfish of 63 g
    in both (300 each); deaths, a weighing and the feedings of each cage since."""

    def setUp(self):
        super().setUp()
        self.tromso = Site.objects.create(name='Tromsø Grow-out', code='TG-02', type='sea_cage', timezone='UTC',
                                          latitude=D('69.6'), longitude=D('18.9'))
        north = ProductionDepartment.objects.create(site=self.tromso, name='Grow-out cages north', code='GRO-N')
        self.m01, self.m02 = make_cage('TG-M01', 'Cage 1', north), make_cage('TG-M02', 'Cage 2', north, '30')
        self.lump = make_species('LUMP', 'Lumpfish', 'Cyclopterus lumpus', local_name='Rognkjeks', freshwater=False,
                                 cleaner_fish_type='lumpfish')
        sea = {'input_stage': 'smolt', 'origin': 'own_hatchery'}

        def stock(lines, days_ago, species=None, **fields):
            operation = services.record_input(self.user, species=species or self.salmon, day=self.day(days_ago),
                                              lines=[(unit, count, D(weight)) for unit, count, weight in lines],
                                              **{**sea, 'notes': f'{fix_seed_size_mix.MARK} [seed]', **fields})
            return operation.movements.first().batch
        self.grow = stock([(self.m01, 1000, '4217')], 20)
        self.post = stock([(self.m01, 1000, '594'), (self.m02, 2000, '594')], 18)
        self.smolt = stock([(self.m01, 500, '78'), (self.m02, 500, '78')], 15)
        self.lumps = stock([(self.m01, 300, '63'), (self.m02, 300, '63')], 15, self.lump, input_stage='juveniles',
                           origin='purchased', provenance='farmed', supplier=self.supplier)
        for unit, batch, days_ago in ((self.m02, self.post, 10), (self.m01, self.smolt, 9), (self.m01, self.grow, 8)):
            services.record_mortality(self.user, unit=unit, batch=batch, day=self.day(days_ago), count=7, cause='unknown')
        services.record_weighing(self.user, unit=self.m01, batch=self.post, day=self.day(6), avg_weight_g=D('610'))
        for unit in (self.m01, self.m02):
            for days_ago in (12, 5, 2):
                self.record(kilos='40', days_ago=days_ago, unit=unit)
            self.record(kilos='1', days_ago=2, unit=unit, target=FeedTarget.CLEANER_FISH)   # 5 % of 18.9 kg
        self.history = list(StockOperation.objects.order_by('pk').values_list('pk', 'kind', 'date'))
        self.assertEqual(integrity.problems(), [])

    def command(self, *extra, **options):
        out = io.StringIO()
        call_command('fix_seed_size_mix', '--force', '--user', self.user.username, '--keep', self.grow.code,
                     '--move', f'{self.post.code}:TG-M03:Cage 3', '--move', f'{self.smolt.code}:TG-M04:Cage 4',
                     *extra, stdout=out, **options)
        return out.getvalue()

    def held(self, unit):
        stock = read.stock_of([unit]).get(unit.pk)
        return {share.batch.code: share.count for share in stock.shares} if stock else {}

    def state(self):
        return (StockOperation.all_objects.count(), StockMovement.objects.count(), Tank.all_objects.count(),
                AuditLog.objects.count(), SamplingPoint.all_objects.count())


class SeparationTests(SeedCagesTestCase):
    def test_the_cages_keep_the_grow_out_salmon_and_the_lumpfish_and_each_other_size_gets_a_cage(self):
        out = self.command()
        m03, m04 = Tank.objects.get(code='TG-M03'), Tank.objects.get(code='TG-M04')
        self.assertEqual(self.held(self.m01), {self.grow.code: 993, self.lumps.code: 300})
        self.assertEqual(self.held(self.m02), {})
        self.assertEqual(Tank.objects.get(pk=self.m02.pk).status, 'fallow')
        self.assertEqual(self.held(m03), {self.post.code: 2993, self.lumps.code: 300})
        self.assertEqual(self.held(m04), {self.smolt.code: 993})
        for unit, name in ((m03, 'Cage 3'), (m04, 'Cage 4')):
            self.assertEqual((unit.name, unit.kind, unit.production_department.site, unit.status, unit.cage_type,
                              unit.diameter, unit.max_density_kg_m3),
                             (name, 'cage', self.tromso, 'active', 'floating', D('30.00'), D('20.00')))
            self.assertTrue(SamplingPoint.objects.filter(unit=unit).exists())       # as a person's new unit gets
            self.assertTrue(AuditLog.objects.filter(entity_type='unit', entity_id=str(unit.pk), action='create')
                            .exists())
        transfers = list(StockOperation.objects.filter(kind='transfer').order_by('created_at'))
        self.assertEqual(len(transfers), 5)
        for operation in transfers:
            out_line = operation.movements.get(kind='transfer_out')
            cleaner = out_line.batch == self.lumps
            self.assertEqual((operation.date, out_line.reason, operation.created_by),
                             (self.today, 'other' if cleaner else 'growth_stage', self.user))
            self.assertIn('seed-history-2026-11', operation.notes)
            if cleaner:
                self.assertEqual((out_line.unit, operation.movements.get(kind='transfer_in').unit), (self.m02, m03))
                self.assertIn('with the post-smolt they clean', operation.notes)
        last = transfers[-1].movements.get(kind='transfer_out')                 # the salmon arrive first
        self.assertEqual(last.batch, self.lumps)
        self.assertEqual(list(StockOperation.objects.filter(pk__in=[pk for pk, _kind, _date in self.history])
                              .order_by('pk').values_list('pk', 'kind', 'date')), self.history)   # history as it was
        self.assertEqual(integrity.problems(), [])
        self.assertIn(f'Moved 1000 fish of {self.post.code} from TG-M01 to TG-M03.', out)
        self.assertIn('Done', out)

    def test_a_second_run_does_nothing(self):
        self.command()
        state = self.state()
        out = self.command()
        self.assertIn('Nothing to move', out)
        self.assertEqual(self.state(), state)

    def test_the_dry_run_prints_the_plan_and_writes_nothing(self):
        state = self.state()
        out = self.command('--dry-run')
        self.assertEqual(self.state(), state)
        self.assertIn('Dry run', out)
        self.assertIn('Make TG-M03 "Cage 3" like TG-M02', out)
        self.assertIn(f'Transfer 1993 fish of {self.post.code} (594.0 g) from TG-M02 to TG-M03 on '
                      f'{self.today.isoformat()}.', out)
        self.assertIn(f'Transfer 1000 fish of {self.post.code} (610.0 g) from TG-M01 to TG-M03', out)
        self.assertIn(f'Transfer 300 fish of {self.lumps.code} (63.0 g) from TG-M02 to TG-M03, cleaner fish with the '
                      'production fish they clean', out)
        self.assertIn(f'Leave the cleaner fish {self.lumps.code} in TG-M01.', out)
        self.assertNotIn(f'Leave the cleaner fish {self.lumps.code} in TG-M02', out)
        self.assertFalse(Tank.all_objects.filter(code='TG-M03').exists())
        self.command()                                                     # the database is writable again after it
        self.assertTrue(Tank.objects.filter(code='TG-M03').exists())

    def test_the_default_plan_is_the_dev_databases(self):
        self.assertEqual((fix_seed_size_mix.SOURCES, fix_seed_size_mix.KEEP, fix_seed_size_mix.MOVES,
                          fix_seed_size_mix.LIKE, fix_seed_size_mix.CLEANER_MOVES),
                         (('TG-M01', 'TG-M02'), 'B-2026-004',
                          (('B-2026-005', 'TG-M03', 'Cage 3'), ('B-2026-007', 'TG-M04', 'Cage 4')), 'TG-M02',
                          (('TG-M02', 'TG-M03'),)))

    def test_the_pages_after_it(self):
        self.command()
        board = self.client.get(reverse('farm:meal_board'))
        self.assertEqual(board.status_code, 200)
        rows = {row['unit'].code: [line['batch'].code for line in row['lines']] for row in board.context['rows']}
        self.assertEqual(sorted(rows['TG-M01']), sorted([self.grow.code, self.lumps.code]))
        self.assertEqual(rows['TG-M03'], [self.post.code, self.lumps.code])
        self.assertNotIn('TG-M02', rows)


class CleanerMoveTests(SeedCagesTestCase):
    def test_cleaner_fish_go_only_into_a_cage_of_the_plan(self):
        state = self.state()
        with self.assertRaisesMessage(CommandError, '--move-cleaner TG-M02:TG-M01: TG-M01 is not a cage the plan moves '
                                                    'salmon into'):
            self.command('--move-cleaner', 'TG-M02:TG-M01')
        self.assertEqual(self.state(), state)

    def test_without_a_cleaner_move_the_lumpfish_stay(self):
        self.command('--move-cleaner', '')
        self.assertEqual(self.held(self.m02), {self.lumps.code: 300})


class RefusalTests(SeedCagesTestCase):
    def refused(self, *extra):
        state = self.state()
        with self.assertRaises(CommandError) as caught:
            self.command(*extra)
        self.assertEqual(self.state(), state)                              # nothing written, no cage made
        self.assertFalse(Tank.all_objects.filter(code__in=['TG-M03', 'TG-M04']).exists())
        return str(caught.exception)

    def test_a_batch_neither_kept_nor_moved_stops_it(self):
        other = services.record_input(self.user, species=self.salmon, day=self.day(3), input_stage='smolt',
                                      origin='own_hatchery', lines=[(self.m02, 100, D('600'))]).movements.get().batch
        self.assertIn(f'{other.code} in TG-M02 is neither kept, moved nor cleaner fish', self.refused())

    def test_a_handling_warning_stops_it_unless_accepted_and_is_then_stored(self):
        self.record(kilos='30', days_ago=0, unit=self.m01)                # fed today: the 24 h fast is not kept
        self.assertIn('--accept-handling-warnings', self.refused())
        self.command('--accept-handling-warnings')
        self.assertEqual(self.held(self.m01), {self.grow.code: 993, self.lumps.code: 300})
        self.assertTrue(HandlingAcknowledgement.objects.exists())

    def test_an_unmigrated_database_is_refused_but_the_dry_run_still_reads(self):
        with mock.patch.object(fix_seed_size_mix.Command, 'pending_migrations', return_value=['farm.0035_x']):
            self.assertIn('Migrate first: farm.0035_x', self.refused())
            out = self.command('--dry-run')
        self.assertIn('lacks farm.0035_x', out)
        self.assertIn(f'Transfer 1993 fish of {self.post.code}', out)

    def test_a_cage_of_the_plan_holding_other_fish_or_an_unknown_user_stops_it(self):
        cage = make_cage('TG-M03', 'Cage 3', self.m01.production_department)
        services.record_input(self.user, species=self.salmon, day=self.day(3), input_stage='smolt',
                              origin='own_hatchery', lines=[(cage, 100, D('600'))])
        state = self.state()
        with self.assertRaisesMessage(CommandError, 'TG-M03 exists and is not an empty cage'):
            self.command()
        self.assertEqual(self.state(), state)
        with self.assertRaisesMessage(CommandError, "No active user 'nobody'"):
            call_command('fix_seed_size_mix', '--force', '--user', 'nobody', stdout=io.StringIO())

    def test_a_refusal_of_the_stock_rolls_back_the_cages_made_before_it(self):
        with mock.patch.object(services, 'record_transfer', side_effect=services.ValidationError('Refused here.')):
            self.assertIn('Refused, nothing written: Refused here.', self.refused())


class SeedMarkerTests(SeedCagesTestCase):
    """F7: only the seed's own fish and cages: the batches kept and moved carry its marker, a cage of the plan that is
    there already was made by this command."""

    def test_a_batch_without_the_marker_stops_it(self):
        Batch.objects.filter(pk=self.post.pk).update(notes='Bought in August')
        state = self.state()
        with self.assertRaisesMessage(CommandError, f'{self.post.code} does not carry the seed’s marker'):
            self.command()
        self.assertEqual(self.state(), state)

    def test_a_cage_of_the_plan_not_made_by_it_stops_it(self):
        make_cage('TG-M03', 'Cage 3', self.m01.production_department)
        with self.assertRaisesMessage(CommandError, 'TG-M03 was not made by fix_seed_size_mix'):
            self.command()


class LockOrderTests(SeedCagesTestCase):
    """F8: a cage of the plan that is there already is locked with the fish, before a new cage locks its department
    and its site (core/softdelete.py, LOCK ORDER)."""

    def test_the_existing_cage_is_locked_before_the_new_one_is_made(self):
        cage = make_cage('TG-M04', 'Cage 4', self.m01.production_department)
        Tank.objects.filter(pk=cage.pk).update(notes=f'{fix_seed_size_mix.MARK}: made by fix_seed_size_mix')
        calls = []
        lock = services.lock_fish
        make = fix_seed_size_mix.Command.make_unit
        with mock.patch.object(services, 'lock_fish', side_effect=lambda ids, *a, **k: calls.append(('lock', set(ids)))
                               or lock(ids, *a, **k)), \
                mock.patch.object(fix_seed_size_mix.Command, 'make_unit', autospec=True,
                                  side_effect=lambda self_, *a: calls.append(('make', a[2])) or make(self_, *a)):
            self.command()
        self.assertEqual(calls[0], ('lock', {self.m01.pk, self.m02.pk, cage.pk}))
        self.assertEqual(calls[1], ('make', 'TG-M03'))
        self.assertEqual(self.held(cage), {self.smolt.code: 993})


class UnmigratedDryRunTests(TransactionTestCase):
    """F10: the dry run on a database at farm 0033 (before the size columns): it reads, and says the run would refuse."""
    serialized_rollback = True

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)

    def test_the_dry_run_reads_an_old_schema(self):
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.create_user('seed', 'seed@example.com', 'x')
        site = Site.objects.create(name='Tromsø', code='TG-02', type='sea_cage', timezone='UTC',
                                   latitude=D('69.6'), longitude=D('18.9'))
        north = ProductionDepartment.objects.create(site=site, name='North', code='N')
        m01, _m02 = make_cage('TG-M01', 'Cage 1', north), make_cage('TG-M02', 'Cage 2', north)
        salmon = make_species()
        today = services.local_today(m01)

        def stock(unit, weight):
            may_record(user, 'add_stockoperation')  # the stock service asks (L-6)
            return services.record_input(user, species=salmon, day=today, input_stage='smolt', origin='own_hatchery',
                                         lines=[(unit, 100, D(weight))], notes=f'{fix_seed_size_mix.MARK} [seed]',
                                         size_mix_ack=True).movements.get().batch
        keep, post = stock(m01, '4000'), stock(m01, '500')
        self.addCleanup(lambda: self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes()))
        self.migrate([('farm', '0033_oxygen_basis')])
        out = io.StringIO()
        call_command('fix_seed_size_mix', '--force', '--user', 'seed', '--keep', keep.code, '--move', f'{post.code}:TG-M03:Cage 3',
                     '--move-cleaner', '', '--dry-run', stdout=out)
        self.assertIn('lacks farm.0034_species_max_weight_ratio, farm.0035_stock_operation_size_mix_ack', out.getvalue())
        self.assertIn(f'Transfer 100 fish of {post.code} (500.0 g) from TG-M01 to TG-M03', out.getvalue())
        with self.assertRaisesMessage(CommandError, 'Migrate first'):
            call_command('fix_seed_size_mix', '--force', '--user', 'seed', '--keep', keep.code, '--move',
                         f'{post.code}:TG-M03:Cage 3', '--move-cleaner', '', stdout=io.StringIO())
