"""The database holds the rules of the design, one test per named constraint, each by a write that checks nothing (the
ORM's create, or raw SQL where the ORM would not say it): what a form or a service would refuse, the database refuses
too, so no writer can leave a wrong row (README, Experiments)."""
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection, transaction

from ..models import (
    Experiment, ExperimentGroup, Factor, GroupLevel, Level, Member, Replicate, ReplicateUnit,
)
from . import D, ExperimentTestCase


class ExperimentConstraintTests(ExperimentTestCase):
    def test_a_number_is_never_given_twice_not_even_after_a_delete_and_has_the_shape_of_a_number(self):
        first = self.experiment()
        self.assertRegex(first.code, r'^E-\d{4}-001$')
        self.refuses(self.experiment, code=first.code)
        first.soft_delete(self.user)
        self.refuses(self.experiment, code=first.code)             # uq_experiments_code is unconditional
        for code in ('X-2026-001', 'E-26-001', 'E-2026-01', 'e-2026-001', 'E-2026-001a', ''):
            with self.subTest(code=code):
                self.refuses(self.experiment, code=code)           # chk_experiments_code
        self.experiment(code='E-2026-1000')                        # four digits once a year passes 999

    def test_status_endpoint_and_duration_are_in_their_lists_and_bounds(self):
        self.refuses(self.experiment, status='paused')
        self.refuses(self.experiment, primary_endpoint='weight')
        for days in (0, 1096):
            with self.subTest(days=days):
                self.refuses(self.experiment, duration_days=days)
        self.assertEqual(Experiment.objects.count(), 0)
        for days in (1, 1095):
            self.experiment(duration_days=days)
        self.assertEqual(Experiment.objects.count(), 2)

    def test_a_template_is_a_draft_without_a_start_day_or_an_allocation(self):
        self.experiment(is_template=True)
        self.refuses(self.experiment, is_template=True, starts_on=self.today)
        self.refuses(self.experiment, is_template=True, allocation_method='manual', allocation_note='by hand')
        template = self.experiment(is_template=True)
        self.refuses(Experiment.objects.filter(pk=template.pk).update, status='running', starts_on=self.today,
                     hypothesis='h', primary_endpoint='bfcr', allocation_method='manual', allocation_note='by hand')

    def test_a_started_experiment_has_its_day_0_hypothesis_endpoint_and_allocation(self):
        """Started by an UPDATE (an experiment is only ever inserted as a draft, the trigger says so): the check refuses it
        without any of them, and lets it through with all."""
        whole = {'starts_on': self.today, 'hypothesis': 'More protein, faster growth', 'primary_endpoint': 'bfcr',
                 'allocation_method': 'manual', 'allocation_note': 'by hand'}

        def start(trial, **fields):
            Experiment.objects.filter(pk=trial.pk).update(status='running', **{**whole, **fields})

        for missing in ('starts_on', 'hypothesis', 'primary_endpoint', 'allocation_method'):
            with self.subTest(missing=missing):
                blank = {missing: None if missing == 'starts_on' else ''}
                if missing == 'allocation_method':
                    blank['allocation_note'] = ''
                self.refuses(start, self.experiment(), **blank)
        start(self.experiment())
        self.experiment(starts_on=None, status='draft')            # a draft needs none of them

    def test_the_allocation_method_its_seed_and_its_reason_belong_together(self):
        self.experiment()
        self.experiment(allocation_method='sha256_v1', allocation_seed=20261103)
        self.experiment(allocation_method='manual', allocation_note='Tanks 1 to 6 share one drain')
        for fields in ({'allocation_seed': 1}, {'allocation_note': 'why'},
                       {'allocation_method': 'sha256_v1'},                                  # a seed is needed
                       {'allocation_method': 'sha256_v1', 'allocation_seed': 1, 'allocation_note': 'why'},
                       {'allocation_method': 'manual'},                                      # a reason is needed
                       {'allocation_method': 'manual', 'allocation_note': 'why', 'allocation_seed': 1},
                       {'allocation_method': 'random', 'allocation_seed': 1}):
            with self.subTest(fields=fields):
                self.refuses(self.experiment, **fields)
        self.assertEqual(Experiment.objects.count(), 3)

    def test_the_key_of_a_form_creates_one_experiment(self):
        key = uuid.uuid4()
        self.experiment(entry_key=key)
        self.refuses(self.experiment, entry_key=key)
        self.experiment(entry_key=None)
        self.experiment(entry_key=None)

    def test_the_site_and_the_species_are_protected(self):
        trial = self.experiment()
        self.refuses(self.bergen.delete)
        self.refuses(self.salmon.delete)
        self.assertTrue(Experiment.objects.filter(pk=trial.pk).exists())

    def test_a_copy_keeps_pointing_at_a_source_that_is_gone(self):
        source = self.experiment(is_template=True)
        copy = self.experiment(copied_from=source)
        source.soft_delete(self.user)
        copy.refresh_from_db()
        self.assertEqual(copy.copied_from_id, source.pk)

        def hard_delete():
            Experiment.all_objects.filter(pk=source.pk).delete()
            connection.check_constraints()                                         # the key is checked at once
        self.refuses(hard_delete)


class FactorConstraintTests(ExperimentTestCase):
    def setUp(self):
        super().setUp()
        self.trial = self.experiment()

    def test_a_factor_name_is_one_among_live_factors_whatever_its_case(self):
        factor = self.factor(self.trial, 'Temperature', 'other', unit='°C')
        self.refuses(self.factor, self.trial, 'temperature', 'other')
        self.factor(self.experiment('Another'), 'Temperature', 'other')             # another experiment: its own
        factor.soft_delete(self.user)
        self.factor(self.trial, 'temperature', 'other')                              # a removed one frees its name

    def test_an_experiment_has_one_diet_factor_and_another_can_be_made_when_it_is_removed(self):
        diet = self.factor(self.trial, 'Diet')
        self.refuses(self.factor, self.trial, 'Feed', 'diet')
        self.factor(self.trial, 'Temperature', 'other')                              # another kind is fine
        diet.soft_delete(self.user)
        self.factor(self.trial, 'Feed', 'diet')

    def test_the_diet_has_no_unit_and_the_kind_is_one_of_the_two(self):
        self.refuses(self.factor, self.trial, 'Diet', 'diet', unit='g/kg')
        self.refuses(self.factor, self.trial, 'Odd', 'mixed')
        self.factor(self.trial, 'Density', 'other', unit='kg/m³')


class LevelConstraintTests(ExperimentTestCase):
    def setUp(self):
        super().setUp()
        self.trial = self.experiment()
        self.diet = self.factor(self.trial, 'Diet')
        self.temperature = self.factor(self.trial, 'Temperature', 'other', unit='°C')

    def test_a_level_takes_the_kind_of_its_factor_when_it_is_saved(self):
        self.assertEqual(self.level(self.diet).kind, 'diet')
        self.assertEqual(self.level(self.temperature, label='12', value=D(12)).kind, 'other')

    def test_a_diet_level_has_a_protocol_and_no_label_or_value_and_another_has_a_label_and_no_protocol(self):
        protocol = self.protocol()
        self.refuses(Level.objects.create, factor=self.diet)                                   # no protocol
        self.refuses(Level.objects.create, factor=self.diet, protocol=protocol, label='High protein')
        self.refuses(Level.objects.create, factor=self.diet, protocol=protocol, value=D(12))
        self.refuses(Level.objects.create, factor=self.temperature, label='12', protocol=protocol)
        self.refuses(Level.objects.create, factor=self.temperature, label='')                  # no label
        Level.objects.create(factor=self.diet, protocol=protocol)
        Level.objects.create(factor=self.temperature, label='12', value=D(12))
        Level.objects.create(factor=self.temperature, label='Ambient')                         # a label is enough

    def test_a_level_of_the_wrong_kind_is_refused_by_the_composite_key_when_written_past_save(self):
        """The kind a level carries is the factor's: a row written by bulk or SQL with another is refused."""
        protocol = self.protocol()
        wrong = Level(factor=self.temperature, kind='diet', protocol=protocol)
        self.refuses(Level.objects.bulk_create, [wrong])
        wrong = Level(factor=self.diet, kind='other', label='x')
        self.refuses(Level.objects.bulk_create, [wrong])
        self.assertEqual(Level.objects.count(), 0)

    def test_a_label_and_a_protocol_are_one_level_of_a_factor_among_live_levels(self):
        protocol = self.protocol()
        level = self.level(self.diet, protocol)
        self.refuses(self.level, self.diet, protocol)
        self.level(self.temperature, label='Ambient')
        self.refuses(self.level, self.temperature, label='ambient')
        self.level(self.temperature, label='AMBIENT 2')
        level.soft_delete(self.user)
        self.level(self.diet, protocol)                                       # a removed level frees its protocol

    def test_a_protocol_a_level_names_cannot_be_deleted(self):
        protocol = self.protocol()
        self.level(self.diet, protocol)
        self.refuses(protocol.delete)



class GroupConstraintTests(ExperimentTestCase):
    def test_a_group_name_is_one_in_the_experiment_whatever_its_case_and_both_controls_may_exist(self):
        trial = self.experiment()
        self.group(trial, 'Control', 'negative_control')
        self.group(trial, 'Reference', 'positive_control')                    # no uniqueness among the roles
        self.group(trial, 'Plain', 'control')
        self.group(trial, 'Plain 2', 'control')
        self.refuses(self.group, trial, 'CONTROL', 'test')
        self.refuses(self.group, trial, 'Odd', 'treatment')
        self.group(self.experiment('Another'), 'Control')

    def test_a_group_level_is_one_per_group_and_factor_and_of_that_factor_and_experiment(self):
        trial, other = self.experiment(), self.experiment('Another')
        diet, temperature = self.factor(trial, 'Diet'), self.factor(trial, 'Temperature', 'other')
        other_diet = self.factor(other, 'Diet')
        group, other_group = self.group(trial), self.group(other)
        high, low = self.level(diet), self.level(diet)
        warm = self.level(temperature, label='Warm')
        foreign = self.level(other_diet)
        self.group_level(group, high)
        self.group_level(group, warm)
        # one level per factor per group
        self.refuses(self.group_level, group, low)
        group_b = self.group(trial, 'B')
        # a group of another experiment than the row's, the rest in order
        self.refuses(GroupLevel.objects.create, experiment=trial, group=other_group, factor=diet, level=low)
        # a factor of another experiment than the row's, the rest in order
        self.refuses(GroupLevel.objects.create, experiment=trial, group=group_b, factor=other_diet, level=foreign)
        # a level that is not of the factor, the rest in order
        self.refuses(GroupLevel.objects.create, experiment=trial, group=group_b, factor=diet, level=warm)
        # a row of another experiment, the group and the factor of this one
        self.refuses(GroupLevel.objects.create, experiment=other, group=group, factor=diet, level=low)
        self.group_level(other_group, foreign)
        self.assertEqual(GroupLevel.objects.count(), 3)

    def test_the_composite_keys_hold_for_raw_sql_too(self):
        trial = self.experiment()
        diet = self.factor(trial, 'Diet')
        other_level = self.level(self.factor(self.experiment('Another'), 'Diet'))
        group = self.group(trial)
        with self.assertRaises(Exception), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute('INSERT INTO experiment_group_levels (experiment_id, group_id, factor_id, level_id) '
                           'VALUES (%s, %s, %s, %s)', [trial.pk, group.pk, diet.pk, other_level.pk])
        self.assertEqual(GroupLevel.objects.count(), 0)


class ReplicateConstraintTests(ExperimentTestCase):
    def test_a_replicate_number_is_one_in_its_group_among_live_replicates_from_1_to_99(self):
        trial = self.experiment()
        group = self.group(trial)
        replicate = self.replicate(group, 1)
        self.refuses(self.replicate, group, 1)
        self.replicate(self.group(trial, 'B'), 1)
        for number in (0, 100):
            with self.subTest(number=number):
                self.refuses(self.replicate, group, number)
        self.replicate(group, 99)
        replicate.soft_delete(self.user)
        self.replicate(group, 1)


class PlacementConstraintTests(ExperimentTestCase):
    def setUp(self):
        super().setUp()
        self.trial = self.experiment()
        self.group_a = self.group(self.trial, 'A')
        self.r1, self.r2 = self.replicate(self.group_a, 1), self.replicate(self.group_a, 2)

    def test_a_window_ends_on_or_after_the_day_it_starts_and_is_never_open(self):
        self.placement(self.r1, self.t1, 3, 3)                                  # a one-day window
        self.refuses(self.placement, self.r1, self.t2, 5, 4)
        self.refuses(ReplicateUnit.objects.create, replicate=self.r1, unit=self.t2, from_on=self.today)  # no end
        self.refuses(ReplicateUnit.objects.create, replicate=self.r1, unit=self.t2, until_on=self.today)
        self.refuses(ReplicateUnit.objects.create, replicate=self.r1, from_on=self.today, until_on=self.today)  # no tank

    def test_a_tank_is_in_one_experiment_at_a_time_drafts_included_and_the_days_are_inclusive(self):
        self.placement(self.r1, self.t1, 0, 10)
        self.refuses(self.placement, self.r2, self.t1, 10, 20)                  # day 10 is booked
        self.refuses(self.placement, self.r2, self.t1, -5, 0)
        self.refuses(self.placement, self.r2, self.t1, 3, 4)                    # inside
        self.refuses(self.placement, self.r2, self.t1, -5, 30)                  # around
        self.placement(self.r2, self.t1, 11, 20)                                # the day after
        self.placement(self.r2, self.t1, -9, -1)                                # the day before
        self.placement(self.r2, self.t2, 0, 10)                                 # another tank
        # another experiment's replicate, a draft too: the same tank, the same days
        other = self.experiment('Another')
        replicate = self.replicate(self.group(other, 'X'), 1)
        self.refuses(self.placement, replicate, self.t1, 0, 56)
        self.refuses(self.placement, replicate, self.t2, 5, 6)

    def test_a_deleted_placement_frees_its_tank_and_a_running_experiment_books_as_a_draft_does(self):
        booked = self.placement(self.r1, self.t1, 0, 56)
        self.refuses(self.placement, self.r2, self.t1, 0, 56)
        booked.soft_delete(self.user)
        self.placement(self.r2, self.t1, 0, 56)
        running = self.experiment('Running')
        replicate = self.replicate(self.group(running, 'R'), 1)
        Experiment.objects.filter(pk=running.pk).update(
            status='running', starts_on=self.today, hypothesis='h', primary_endpoint='bfcr',
            allocation_method='manual', allocation_note='by hand')                # started: its design is fixed
        self.refuses(self.placement, replicate, self.t1, 56, 60)

    def test_a_tank_that_was_in_a_trial_cannot_be_deleted_from_the_database(self):
        self.placement(self.r1, self.t1)
        self.refuses(self.t1.delete)


class MemberConstraintTests(ExperimentTestCase):
    def test_a_person_is_once_in_the_team_and_the_team_has_one_lead(self):
        trial = self.experiment()
        kari = get_user_model().objects.create_user('kari', 'kari@example.com', 'x')
        olav = get_user_model().objects.create_user('olav', 'olav@example.com', 'x')
        self.member(trial, self.user, 'lead')
        self.refuses(self.member, trial, self.user, 'student')                 # once
        self.refuses(self.member, trial, kari, 'lead')                         # one lead
        self.member(trial, kari, 'researcher')
        self.member(trial, olav, 'student')
        self.refuses(self.member, trial, get_user_model().objects.create_user('x', 'x@example.com', 'x'), 'chief')
        other = self.experiment('Another')
        self.member(other, kari, 'lead')                                       # the lead of another experiment
        self.assertEqual(Member.objects.filter(experiment=trial).count(), 3)

    def test_a_person_of_a_team_cannot_be_deleted(self):
        trial = self.experiment()
        kari = get_user_model().objects.create_user('kari', 'kari@example.com', 'x')
        self.member(trial, kari, 'lead')
        self.refuses(kari.delete)


class ModelTextTests(ExperimentTestCase):
    def test_the_models_say_what_they_are(self):
        trial = self.experiment()
        diet = self.factor(trial)
        level = self.level(diet)
        group = self.group(trial, 'A')
        replicate = self.replicate(group, 2)
        placement = self.placement(replicate, self.t1, 0, 56)
        self.assertEqual(str(trial), f'{trial.code} · Diet trial')
        self.assertEqual((str(group), str(replicate), str(level)), ('A', 'A R2', 'Protocol 1'))
        self.assertEqual(str(placement), f'A R2 · T-01 · {self.today.isoformat()}')
        self.assertEqual(placement.until_on - placement.from_on, timedelta(days=56))
