"""A started experiment's design cannot change, for any writer: the triggers of migration 0002, tried by raw SQL and by
the ORM with nothing in between (no form, no service). A draft is free; a running experiment keeps its design and
only lets a placement get shorter or a replacement in; a closed one allows nothing."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection, transaction

from ..models import (
    TRANSITIONS, Experiment, ExperimentGroup, Factor, GroupLevel, Level, Replicate, ReplicateUnit, Status,
)
from . import ExperimentTestCase

STARTED = {'hypothesis': 'More protein, faster growth', 'primary_endpoint': 'bfcr', 'allocation_method': 'manual',
           'allocation_note': 'Tanks 1 to 4 share one drain'}


def sql(statement, params=()):
    with connection.cursor() as cursor:
        cursor.execute(statement, params)
        return cursor.rowcount


class TriggerTestCase(ExperimentTestCase):
    def setUp(self):
        super().setUp()
        self.trial = self.experiment()
        self.diet, self.density = self.factor(self.trial, 'Diet'), self.factor(self.trial, 'Density', 'other')
        self.high, self.low = self.level(self.diet), self.level(self.diet)
        self.dense = self.level(self.density, label='High')
        self.control, self.test = self.group(self.trial, 'Control', 'control'), self.group(self.trial, 'Test')
        self.group_levels = [self.group_level(self.control, self.low), self.group_level(self.test, self.high)]
        self.r1, self.r2 = self.replicate(self.control, 1), self.replicate(self.test, 1)
        self.p1, self.p2 = self.placement(self.r1, self.t1), self.placement(self.r2, self.t2)
        # Parts no other row points at, to delete (a key in use refuses a delete before any trigger does).
        self.spare_factor, self.spare_group = self.factor(self.trial, 'Spare', 'other'), self.group(self.trial, 'Spare')

    def start(self, experiment=None, status='running'):
        """Starts the experiment by the ORM, past the service: day 0 today; closes it too when `status` says so."""
        experiment = experiment or self.trial
        Experiment.objects.filter(pk=experiment.pk).update(status='running', starts_on=self.today, **STARTED)
        if status == 'closed':
            Experiment.objects.filter(pk=experiment.pk).update(status='closed')
        experiment.refresh_from_db()
        return experiment

    def refuses_sql(self, statement, params=()):
        self.refuses(sql, statement, params)

    def accepts_sql(self, statement, params=()):
        """The statement is valid and would change a row (rolled back: the test goes on)."""
        with transaction.atomic():
            self.assertEqual(sql(statement, params), 1, statement)
            transaction.set_rollback(True)

    def flips(self, cases, start):
        """Every statement is accepted while the experiment is a draft and refused once `start()` has run: what
        refuses it is the trigger, not a constraint or a missing row."""
        for statement, params in cases:
            with self.subTest(draft=statement):
                self.accepts_sql(statement, params)
        start()
        for statement, params in cases:
            with self.subTest(started=statement):
                self.refuses_sql(statement, params)


class ExperimentTriggerTests(TriggerTestCase):
    def test_a_draft_changes_freely_and_is_deleted_for_good_when_nothing_holds_it(self):
        sql('UPDATE experiments SET site_id = %s, species_id = %s, duration_days = 10, notes = %s WHERE id = %s',
            [self.tromso.pk, self.trout.pk, 'free', self.trial.pk])
        self.assertEqual(Experiment.objects.get(pk=self.trial.pk).duration_days, 10)
        empty = self.experiment('Empty')
        self.assertEqual(sql('DELETE FROM experiments WHERE id = %s', [empty.pk]), 1)

    def test_once_started_only_the_name_the_notes_the_status_and_the_bookkeeping_change(self):
        self.start()
        sql('UPDATE experiments SET name = %s, notes = %s, version = version + 1, updated_at = now(), '
            'updated_by_id = %s WHERE id = %s', ['Renamed', 'A note', self.user.pk, self.trial.pk])
        trial = Experiment.objects.get(pk=self.trial.pk)
        self.assertEqual((trial.name, trial.notes, trial.version, trial.updated_by), ('Renamed', 'A note', 2, self.user))
        cases = [(f'UPDATE experiments SET {clause} WHERE id = %s', [*params, self.trial.pk]) for clause, params in (
            ('site_id = %s', [self.tromso.pk]), ('species_id = %s', [self.trout.pk]),
            ('hypothesis = %s', ['Another hypothesis']), ("primary_endpoint = 'survival'", []),
            ('starts_on = starts_on + 1', []), ('duration_days = 57', []),
            ("allocation_method = 'sha256_v1', allocation_seed = 5, allocation_note = ''", []),
            ("allocation_note = 'Another reason'", []), ("code = 'E-2026-999'", []),
            ('copied_from_id = %s', [self.experiment('Source').pk]),
            ("entry_key = '8b0e0a6e-6c8f-4f6c-a4a5-8f3c2d6c3a11'", []),
            ('is_deleted = true, deleted_at = now()', []), ("created_at = '2026-01-01'", []))]
        # The same statements are valid on a draft that has the same values (day 0, hypothesis, allocation).
        probe = self.experiment('Probe', starts_on=self.today, **STARTED)
        for statement, params in cases:
            with self.subTest(draft=statement):
                self.accepts_sql(statement.replace('WHERE id = %s', 'WHERE id = %s'), [*params[:-1], probe.pk])
        for statement, params in cases:
            with self.subTest(started=statement):
                self.refuses_sql(statement, params)
        self.assertEqual(Experiment.objects.get(pk=self.trial.pk).duration_days, 56)

    def test_a_started_experiment_is_never_deleted_or_soft_deleted(self):
        self.start()
        self.refuses_sql('DELETE FROM experiments WHERE id = %s', [self.trial.pk])
        self.refuses(self.trial.soft_delete, self.user)
        self.assertEqual(Experiment.objects.filter(pk=self.trial.pk, is_deleted=False).count(), 1)

    def test_the_status_goes_forward_only_as_the_models_transitions_say(self):
        for old in Status.values:
            for new in Status.values:
                with self.subTest(old=old, new=new):
                    trial = self.experiment(f'{old} to {new}')
                    if old != 'draft':
                        self.start(trial, status=old)
                    allowed = old == new or new in TRANSITIONS[old]
                    statement = 'UPDATE experiments SET status = %s, starts_on = %s, hypothesis = %s, ' \
                                'primary_endpoint = %s, allocation_method = %s, allocation_note = %s WHERE id = %s'
                    params = [new, self.today, STARTED['hypothesis'], 'bfcr', 'manual', STARTED['allocation_note'],
                              trial.pk]
                    if allowed:
                        self.assertEqual(sql(statement, params), 1)
                    else:
                        self.refuses_sql(statement, params)
                    self.assertEqual(Experiment.objects.get(pk=trial.pk).status, new if allowed else old)

    def test_a_closed_experiment_keeps_its_design_too_and_its_name_and_notes_can_still_be_edited(self):
        self.start(status='closed')
        self.refuses_sql('UPDATE experiments SET hypothesis = %s WHERE id = %s', ['x', self.trial.pk])
        sql('UPDATE experiments SET notes = %s WHERE id = %s', ['Final remarks', self.trial.pk])

    def test_a_person_removed_from_the_system_does_not_block_a_started_experiment(self):
        creator = get_user_model().objects.create_user('gone', 'gone@example.com', 'x')
        Experiment.objects.filter(pk=self.trial.pk).update(created_by=creator, updated_by=creator)
        Factor.objects.filter(pk=self.diet.pk).update(created_by=creator)
        self.start()
        creator.delete()
        trial = Experiment.objects.get(pk=self.trial.pk)
        self.assertEqual((trial.created_by, trial.updated_by, trial.status), (None, None, 'running'))
        self.assertIsNone(Factor.objects.get(pk=self.diet.pk).created_by)


class DesignTriggerTests(TriggerTestCase):
    def rows(self):
        """One write of each kind against each guarded design table (a started experiment refuses them all)."""
        return {
            'factors': ('INSERT INTO experiment_factors (id, created_at, updated_at, version, is_deleted, experiment_id, '
                        "name, kind, unit, position) VALUES (gen_random_uuid(), now(), now(), 1, false, %s, 'New', "
                        "'other', '', 0)", [self.trial.pk]),
            'groups': ('INSERT INTO experiment_groups (id, created_at, updated_at, version, is_deleted, experiment_id, '
                       "name, role, position) VALUES (gen_random_uuid(), now(), now(), 1, false, %s, 'New', 'test', 0)",
                       [self.trial.pk]),
            'replicates': ('INSERT INTO experiment_replicates (id, created_at, updated_at, version, is_deleted, '
                           'group_id, number) VALUES (gen_random_uuid(), now(), now(), 1, false, %s, 7)',
                           [self.control.pk]),
            'levels': ('INSERT INTO experiment_levels (id, created_at, updated_at, version, is_deleted, factor_id, '
                       "kind, label) VALUES (gen_random_uuid(), now(), now(), 1, false, %s, 'other', 'Low')",
                       [self.density.pk]),
            'group_levels': ('INSERT INTO experiment_group_levels (experiment_id, group_id, factor_id, level_id) '
                             'VALUES (%s, %s, %s, %s)',
                             [self.trial.pk, self.control.pk, self.density.pk, self.dense.pk]),
        }

    def test_every_part_of_a_draft_design_is_free_to_add_change_and_delete(self):
        for table, (statement, params) in self.rows().items():
            with self.subTest(table=table):
                self.assertEqual(sql(statement, params), 1)
        sql('UPDATE experiment_factors SET name = %s WHERE id = %s', ['Feed', self.diet.pk])
        sql('UPDATE experiment_levels SET label = %s WHERE id = %s', ['Dense', self.dense.pk])
        sql('UPDATE experiment_replicates SET number = 5 WHERE id = %s', [self.r1.pk])
        sql('DELETE FROM experiment_group_levels WHERE group_id = %s', [self.test.pk])
        sql('DELETE FROM experiment_replicate_units WHERE replicate_id = %s', [self.r2.pk])
        sql('DELETE FROM experiment_replicates WHERE id = %s', [self.r2.pk])
        sql('DELETE FROM experiment_groups WHERE id = %s', [self.test.pk])
        sql('DELETE FROM experiment_levels WHERE id = %s', [self.high.pk])
        sql('DELETE FROM experiment_factors WHERE id = %s', [self.spare_factor.pk])

    def test_a_started_design_refuses_every_insert_update_and_delete_of_every_part(self):
        cases = [*self.rows().values(),
                 ('UPDATE experiment_factors SET name = %s WHERE id = %s', ['Feed', self.diet.pk]),
                 ('UPDATE experiment_factors SET is_deleted = true WHERE id = %s', [self.diet.pk]),
                 ('UPDATE experiment_levels SET label = %s WHERE id = %s', ['Dense', self.dense.pk]),
                 ('UPDATE experiment_groups SET role = %s WHERE id = %s', ['test', self.control.pk]),
                 ('UPDATE experiment_replicates SET number = 5 WHERE id = %s', [self.r1.pk]),
                 ('UPDATE experiment_replicates SET is_deleted = true WHERE id = %s', [self.r1.pk]),
                 ('UPDATE experiment_group_levels SET level_id = %s WHERE group_id = %s',
                  [self.high.pk, self.control.pk]),
                 ('DELETE FROM experiment_group_levels WHERE group_id = %s', [self.control.pk]),
                 ('DELETE FROM experiment_levels WHERE id = %s', [self.dense.pk]),
                 ('DELETE FROM experiment_replicates WHERE id = %s', [self.r1.pk]),
                 ('DELETE FROM experiment_groups WHERE id = %s', [self.spare_group.pk]),
                 ('DELETE FROM experiment_factors WHERE id = %s', [self.spare_factor.pk])]
        self.flips(cases, self.start)
        self.assertEqual((Factor.objects.count(), Level.objects.count(), ExperimentGroup.objects.count(),
                          Replicate.objects.count(), GroupLevel.objects.count()), (3, 3, 3, 2, 2))

    def test_the_orm_is_refused_as_well_and_a_closed_design_too(self):
        self.start(status='closed')
        self.refuses(self.factor, self.trial, 'Late', 'other')
        self.refuses(self.group, self.trial, 'Late')
        self.refuses(self.replicate, self.control, 4)
        self.refuses(self.level, self.density, label='Late')
        self.refuses(self.group_level, self.control, self.dense)
        self.refuses(self.control.soft_delete, self.user)

    def test_a_part_cannot_be_moved_under_a_started_experiment_from_a_draft(self):
        other = self.experiment('Another')
        group = self.group(other, 'Mine')
        self.start()
        self.refuses_sql('UPDATE experiment_groups SET experiment_id = %s WHERE id = %s', [self.trial.pk, group.pk])

    def test_deleting_a_draft_through_the_plan_soft_deletes_the_whole_design(self):
        """The delete plan's order (children first) passes the guards of a draft."""
        from core import softdelete
        plan = softdelete.plan_delete(self.trial)
        self.assertTrue(plan.can_delete)
        softdelete.execute(plan, self.user)
        self.assertTrue(Experiment.all_objects.get(pk=self.trial.pk).is_deleted)
        self.assertEqual(ReplicateUnit.objects.count(), 0)
        self.assertEqual(Replicate.objects.count() + ExperimentGroup.objects.count() + Factor.objects.count()
                         + Level.objects.count(), 0)

    def test_the_team_is_not_the_design(self):
        self.start()
        kari = get_user_model().objects.create_user('kari', 'kari@example.com', 'x')
        member = self.member(self.trial, kari, 'student')
        member.role = 'advisor'
        member.save()
        member.delete()


class PlacementTriggerTests(TriggerTestCase):
    def test_a_draft_places_moves_and_deletes_freely(self):
        sql('UPDATE experiment_replicate_units SET unit_id = %s, until_on = until_on + 5 WHERE id = %s',
            [self.tanks[3].pk, self.p1.pk])
        sql('UPDATE experiment_replicate_units SET is_deleted = true WHERE id = %s', [self.p2.pk])
        sql('DELETE FROM experiment_replicate_units WHERE id = %s', [self.p1.pk])

    def test_a_running_placement_only_gets_shorter_and_says_why(self):
        pk = self.p1.pk
        cases = [(f'UPDATE experiment_replicate_units SET {clause} WHERE id = %s', [*params, pk]) for clause, params in (
            ('until_on = until_on + 1', []), ('from_on = from_on + 1', []), ('unit_id = %s', [self.tanks[3].pk]),
            ('replicate_id = %s', [self.r2.pk]), ('is_deleted = true, deleted_at = now()', []),
            ("created_at = '2026-01-01'", []))]
        cases.append(('DELETE FROM experiment_replicate_units WHERE id = %s', [pk]))
        self.flips(cases, self.start)
        self.refuses(self.p1.soft_delete, self.user)
        sql('UPDATE experiment_replicate_units SET until_on = %s, left_reason = %s, version = version + 1, '
            'updated_by_id = %s WHERE id = %s', [self.today + timedelta(days=20), 'Pump failed', self.user.pk, pk])
        placement = ReplicateUnit.objects.get(pk=pk)
        self.assertEqual((placement.until_on, placement.left_reason, placement.version),
                         (self.today + timedelta(days=20), 'Pump failed', 2))
        sql('UPDATE experiment_replicate_units SET until_on = %s WHERE id = %s',
            [self.today + timedelta(days=20), pk])                                # the same day: not longer
        self.refuses_sql('UPDATE experiment_replicate_units SET until_on = %s WHERE id = %s',
                         [self.today + timedelta(days=21), pk])

    def test_a_running_experiment_may_get_a_replacement_placement_and_a_closed_one_may_not(self):
        self.start()
        sql('UPDATE experiment_replicate_units SET until_on = %s WHERE id = %s', [self.today + timedelta(days=9), self.p1.pk])
        self.placement(self.r1, self.tanks[3], 10, 56)
        self.assertEqual(ReplicateUnit.objects.filter(replicate=self.r1).count(), 2)
        Experiment.objects.filter(pk=self.trial.pk).update(status='closed')
        self.refuses(self.placement, self.r1, self.tanks[4], 10, 56)
        self.refuses_sql('UPDATE experiment_replicate_units SET until_on = %s WHERE id = %s',
                         [self.today + timedelta(days=5), self.p2.pk])
        self.refuses_sql('UPDATE experiment_replicate_units SET left_reason = %s WHERE id = %s', ['x', self.p2.pk])
        self.refuses_sql('DELETE FROM experiment_replicate_units WHERE id = %s', [self.p2.pk])

    def test_a_placement_cannot_be_moved_into_a_started_experiment_nor_one_into_a_template(self):
        running = self.experiment('Running')
        group = self.group(running, 'R')
        replicate = self.replicate(group, 1)
        self.start(running)
        self.refuses_sql('UPDATE experiment_replicate_units SET replicate_id = %s WHERE id = %s',
                         [replicate.pk, self.p1.pk])
        template = self.experiment('Template', is_template=True)
        slot = self.replicate(self.group(template, 'T'), 1)
        self.refuses(self.placement, slot, self.tanks[5])
        self.refuses_sql('UPDATE experiment_replicate_units SET replicate_id = %s WHERE id = %s', [slot.pk, self.p1.pk])

    def test_a_person_removed_from_the_system_does_not_block_a_started_placement(self):
        creator = get_user_model().objects.create_user('gone', 'gone@example.com', 'x')
        ReplicateUnit.objects.filter(pk=self.p1.pk).update(created_by=creator)
        self.start()
        creator.delete()
        self.assertIsNone(ReplicateUnit.objects.get(pk=self.p1.pk).created_by)


class BornDraftAndTemplateTests(TriggerTestCase):
    def insert(self, status, code):
        return sql("INSERT INTO experiments (id, code, name, status, is_template, species_id, site_id, duration_days, version, "
                   "created_at, updated_at, is_deleted, hypothesis, primary_endpoint, allocation_method, allocation_note, "
                   "notes, starts_on, entry_key) SELECT gen_random_uuid(), %s, 'Raw', %s, false, species_id, site_id, 56, 1, now(), "
                   "now(), false, 'h', 'bfcr', 'manual', 'x', '', current_date, gen_random_uuid() FROM experiments WHERE id = %s",
                   [code, status, self.trial.pk])

    def test_an_experiment_is_only_ever_made_a_draft(self):
        self.assertEqual(self.insert('draft', 'E-2026-901'), 1)
        for status, code in (('running', 'E-2026-902'), ('closed', 'E-2026-903')):
            with self.subTest(status=status):
                self.refuses(self.insert, status, code)

    def test_a_draft_with_placements_is_not_made_a_template_and_one_without_is(self):
        self.refuses_sql("UPDATE experiments SET is_template = true, starts_on = NULL, allocation_method = '', "
                         "allocation_note = '', allocation_seed = NULL WHERE id = %s", [self.trial.pk])
        empty = self.experiment('Empty')
        self.accepts_sql("UPDATE experiments SET is_template = true WHERE id = %s", [empty.pk])


class TriggersInTheCatalogueTests(TriggerTestCase):
    def test_each_guarded_table_has_its_trigger_and_the_team_has_none(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT c.relname, t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                           "WHERE NOT t.tgisinternal AND c.relname ~ '^experiment' ORDER BY 1")
            found = sorted(cursor.fetchall())
        self.assertEqual(found, sorted([
            ('experiments', 'trg_experiments_frozen'), ('experiment_factors', 'trg_experiment_factors_frozen'),
            ('experiment_groups', 'trg_experiment_groups_frozen'), ('experiment_levels', 'trg_experiment_levels_frozen'),
            ('experiment_group_levels', 'trg_experiment_group_levels_frozen'),
            ('experiment_replicates', 'trg_experiment_replicates_frozen'),
            ('experiment_replicate_units', 'trg_experiment_replicate_units_frozen'),
            # Whole-system bookings (migration 0003): a placement's tag, a booking's days, its frozen rule.
            ('experiment_replicate_units', 'trg_experiment_replicate_units_booking'),
            ('experiment_replicate_systems', 'trg_experiment_replicate_systems_frozen'),
            ('experiment_replicate_systems', 'trg_experiment_replicate_systems_holds')]))
