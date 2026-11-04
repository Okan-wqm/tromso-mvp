"""The design of an experiment: `services.save_design` (rows matched by id, levels made from cells, replicates equal to
their count, the log), what is wrong with a design (`design.problems`, one test per finding) and the Design tab's
page against the stored rows."""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.urls import reverse

from core.models import AuditLog
from farm.models import Feed, FeedingProtocol, ProtocolAssignment, ProtocolBand, ProtocolRate

from .. import design, services
from ..models import Experiment, ExperimentGroup, Factor, GroupLevel, Level, Replicate, ReplicateUnit
from . import D, ExperimentTestCase
from .test_pages import RESEARCHER, STUDENT, PageTestCase, person


def diet(name='Diet'):
    return services.FactorRow(name=name, kind='diet')


def density(name='Density', unit='kg/m³'):
    return services.FactorRow(name=name, kind='other', unit=unit)


class DesignTestCase(ExperimentTestCase):
    def setUp(self):
        super().setUp()
        self.trial = self.experiment()
        self.high, self.low = self.protocol('High protein'), self.protocol('Low protein')

    def save(self, factors, groups, trial=None, **kwargs):
        trial = trial or self.trial
        trial.refresh_from_db()
        return services.save_design(self.user, trial, factors, groups, kwargs.pop('version', trial.version))

    def group_row(self, name='A', role='test', replicates=2, cells=(), **fields):
        return services.GroupRow(name=name, role=role, replicates=replicates, cells=list(cells), **fields)

    def refused(self, *args, **kwargs):
        with self.assertRaises(ValidationError) as caught:
            self.save(*args, **kwargs)
        return caught.exception.message_dict[NON_FIELD_ERRORS]

    def two_by_two(self):
        """The owner's example in small: a diet of two protocols and a density of two levels, a group each."""
        factors = [diet(), density()]
        groups = [self.group_row('Control', 'control', 2, [services.Cell(protocol=self.low),
                                                          services.Cell(label='Low', value=D(20))]),
                  self.group_row('High feed', 'test', 3, [services.Cell(protocol=self.high),
                                                         services.Cell(label='Low', value=D(20))])]
        return factors, groups

    def rows(self):
        """The stored design as comparable text: [(factor, kind, unit)], [(group, role, replicates, levels)]."""
        loaded = design.load(self.trial)
        factors = [(factor.name, factor.kind, factor.unit) for factor in loaded.factors]
        groups = [(group.name, group.role, [r.number for r in loaded.replicates.get(group.pk, [])],
                   [services._level_text(loaded.level_of(group, factor)) for factor in loaded.factors])
                  for group in loaded.groups]
        return factors, groups


class SaveDesignTests(DesignTestCase):
    def test_a_design_is_stored_as_factors_levels_groups_replicates_and_each_groups_levels(self):
        saved = self.save(*self.two_by_two())
        factors, groups = self.rows()
        self.assertEqual(factors, [('Diet', 'diet', ''), ('Density', 'other', 'kg/m³')])
        self.assertEqual(groups, [('Control', 'control', [1, 2], ['Low protein', 'Low (20)']),
                                  ('High feed', 'test', [1, 2, 3], ['High protein', 'Low (20)'])])
        self.assertEqual((saved.version, saved.updated_by), (2, self.user))
        levels = sorted(Level.objects.values_list('factor__name', 'kind', 'label', 'protocol__name', 'value'),
                        key=str)
        self.assertEqual(levels, [('Density', 'other', 'Low', None, D(20)), ('Diet', 'diet', '', 'High protein', None),
                                  ('Diet', 'diet', '', 'Low protein', None)])      # two groups, one level of density
        self.assertEqual(GroupLevel.objects.count(), 4)
        self.assertEqual(Replicate.objects.count(), 5)
        entry = AuditLog.objects.get(action='update')
        self.assertEqual((entry.entity_type, entry.entity_id), ('experiment', str(self.trial.pk)))
        self.assertEqual(entry.changes, {'Design': [None, (
            'Factors: Diet (diet); Density (other factor, kg/m³)\n'
            'Control (control group): Diet = Low protein, Density = Low (20); 2 replicates\n'
            'High feed (test group): Diet = High protein, Density = Low (20); 3 replicates')]})

    def test_saving_the_same_design_again_changes_and_logs_nothing(self):
        factors, groups = self.two_by_two()
        self.save(factors, groups)
        stored = design.load(self.trial)
        factors = [services.FactorRow(f.name, f.kind, f.unit, f.pk) for f in stored.factors]
        groups = [self.group_row(g.name, g.role, len(stored.replicates[g.pk]), [
            services.Cell(protocol=stored.level_of(g, stored.factors[0]).protocol),
            services.Cell(label='Low', value=D(20))], id=g.pk) for g in stored.groups]
        before = (AuditLog.objects.count(), Level.objects.count(), GroupLevel.objects.count())
        again = self.save(factors, groups)
        self.assertEqual((again.version, AuditLog.objects.count(), Level.objects.count(), GroupLevel.objects.count()),
                         (2, *before))
        self.assertEqual(design.load(self.trial).groups, stored.groups)

    def test_a_rename_keeps_the_group_its_replicates_and_the_tanks_placed_in_them(self):
        self.save(*self.two_by_two())
        stored = design.load(self.trial)
        control = stored.groups[0]
        placement = self.placement(stored.replicates[control.pk][0], self.t1)
        factors = [services.FactorRow('Feed', 'diet', '', stored.factors[0].pk),
                   services.FactorRow('Stocking density', 'other', 'kg/m³', stored.factors[1].pk)]
        groups = [self.group_row('Reference', 'control', 2, [services.Cell(protocol=self.low),
                                                            services.Cell(label='Low', value=D(20))], id=control.pk)]
        groups.append(self.group_row('High feed', 'test', 3, [services.Cell(protocol=self.high),
                                                             services.Cell(label='Low', value=D(20))],
                                     id=stored.groups[1].pk))
        self.save(factors, groups)
        renamed = ExperimentGroup.objects.get(pk=control.pk)
        self.assertEqual((renamed.name, Factor.objects.get(pk=stored.factors[0].pk).name), ('Reference', 'Feed'))
        self.assertEqual(ReplicateUnit.objects.get(pk=placement.pk).replicate.group_id, control.pk)
        self.assertFalse(AuditLog.objects.filter(action='delete').exists())

    def test_two_groups_or_two_factors_can_swap_names(self):
        self.save(*self.two_by_two())
        stored = design.load(self.trial)
        factors = [services.FactorRow('Density', 'other', 'kg/m³', stored.factors[1].pk),
                   services.FactorRow('Diet', 'diet', '', stored.factors[0].pk)]
        first, second = stored.groups
        groups = [self.group_row('High feed', 'control', 2, [services.Cell(label='Low', value=D(20)),
                                                            services.Cell(protocol=self.low)], id=first.pk),
                  self.group_row('Control', 'test', 3, [services.Cell(label='Low', value=D(20)),
                                                       services.Cell(protocol=self.high)], id=second.pk)]
        self.save(factors, groups)
        self.assertEqual({group.pk: group.name for group in ExperimentGroup.objects.all()},
                         {first.pk: 'High feed', second.pk: 'Control'})
        self.assertEqual([factor.name for factor in design.load(self.trial).factors], ['Density', 'Diet'])

    def test_the_replicates_of_a_group_are_made_equal_to_its_count_and_one_with_a_tank_stays(self):
        factors, groups = self.two_by_two()
        self.save(factors, groups)
        stored = design.load(self.trial)
        groups = [self.group_row(g.name, g.role, 2, [services.Cell(protocol=stored.level_of(g, stored.factors[0]).protocol),
                                                    services.Cell(label='Low', value=D(20))], id=g.pk)
                  for g in stored.groups]
        factors = [services.FactorRow(f.name, f.kind, f.unit, f.pk) for f in stored.factors]
        self.save(factors, groups)
        self.assertEqual({g.name: [r.number for r in design.load(self.trial).replicates[g.pk]]
                          for g in stored.groups}, {'Control': [1, 2], 'High feed': [1, 2]})
        self.assertEqual(Replicate.all_objects.filter(is_deleted=True).count(), 1)               # R3 of High feed
        groups[1].replicates = 5
        self.save(factors, groups)
        self.assertEqual(len(design.load(self.trial).replicates[stored.groups[1].pk]), 5)
        replicate_4 = Replicate.objects.get(group=stored.groups[1], number=4)
        self.placement(replicate_4, self.t1)
        groups[1].replicates = 3
        before = self.rows()
        self.assertEqual(self.refused(factors, groups),
                         ['Replicate High feed R4 holds tanks: take them out on the Places tab before removing it.'])
        self.assertEqual(self.rows(), before)                    # nothing was written: R5 stays too
        self.assertTrue(Replicate.objects.filter(group=stored.groups[1], number=5).exists())

    def test_a_group_with_tanks_is_not_removed_and_one_without_goes_with_its_replicates(self):
        factors, groups = self.two_by_two()
        self.save(factors, groups)
        stored = design.load(self.trial)
        kept = [services.FactorRow(f.name, f.kind, f.unit, f.pk) for f in stored.factors]
        only = [self.group_row(g.name, g.role, 2, [services.Cell(protocol=stored.level_of(g, stored.factors[0]).protocol),
                                                  services.Cell(label='Low', value=D(20))], id=g.pk)
                for g in stored.groups[:1]]
        self.placement(stored.replicates[stored.groups[1].pk][0], self.t1)
        self.assertEqual(self.refused(kept, only),
                         ['Group High feed has tanks placed: take them out on the Places tab before removing it.'])
        ReplicateUnit.objects.all().delete()
        self.save(kept, only)
        self.assertEqual([g.name for g in design.load(self.trial).groups], ['Control'])
        deleted = sorted(AuditLog.objects.filter(action='delete').values_list('entity_type', flat=True))
        self.assertEqual(deleted, ['experiment group', 'factor level', 'replicate', 'replicate', 'replicate'])

    def test_a_level_nobody_asks_for_any_more_is_removed_and_asked_for_again_it_is_made_again(self):
        factors, groups = self.two_by_two()
        self.save(factors, groups)
        stored = design.load(self.trial)
        kept = [services.FactorRow(f.name, f.kind, f.unit, f.pk) for f in stored.factors]

        def rows(density_label, protocol):
            return [self.group_row(g.name, g.role, 1, [services.Cell(protocol=protocol),
                                                      services.Cell(label=density_label, value=D(35))], id=g.pk)
                    for g in stored.groups]
        self.save(kept, rows('High', self.low))
        self.assertEqual(sorted(Level.objects.values_list('label', 'protocol__name')),
                         [('', 'Low protein'), ('High', None)])
        self.assertEqual(Level.all_objects.filter(is_deleted=True).count(), 2)       # Low (20) and High protein
        self.save(kept, rows('Low', self.high))
        self.assertEqual(sorted(Level.objects.values_list('label', 'protocol__name'), key=str),
                         [('', 'High protein'), ('Low', None)])

    def test_a_labels_case_and_number_are_updated_in_place(self):
        self.save([density()], [self.group_row('A', replicates=1, cells=[services.Cell(label='low', value=D(10))])])
        stored = design.load(self.trial)
        level = stored.level_of(stored.groups[0], stored.factors[0])
        self.save([services.FactorRow('Density', 'other', 'kg/m³', stored.factors[0].pk)],
                  [self.group_row('A', replicates=1, id=stored.groups[0].pk,
                                  cells=[services.Cell(label='Low', value=D(12))])])
        updated = Level.objects.get(pk=level.pk)
        self.assertEqual((updated.label, updated.value), ('Low', D(12)))

    def test_a_factor_whose_kind_changed_is_a_new_factor(self):
        self.save([density('Feed', '')], [self.group_row('A', replicates=1, cells=[services.Cell(label='Soy')])])
        stored = design.load(self.trial)
        self.save([services.FactorRow('Feed', 'diet', '', stored.factors[0].pk)],
                  [self.group_row('A', replicates=1, id=stored.groups[0].pk,
                                  cells=[services.Cell(protocol=self.high)])])
        now = design.load(self.trial)
        self.assertNotEqual(now.factors[0].pk, stored.factors[0].pk)
        self.assertEqual((now.factors[0].kind, self.rows()[1]), ('diet', [('A', 'test', [1], ['High protein'])]))
        self.assertTrue(Factor.all_objects.get(pk=stored.factors[0].pk).is_deleted)

    def test_a_label_two_groups_share_is_one_level_and_two_numbers_for_it_are_refused(self):
        groups = [self.group_row(name, replicates=1, cells=[services.Cell(label='Warm', value=value)])
                  for name, value in (('A', D(18)), ('B', D(18)))]
        self.save([density('Temperature', '°C')], groups)
        self.assertEqual(Level.objects.count(), 1)
        self.assertEqual(GroupLevel.objects.count(), 2)
        groups[1].cells[0].value = D(19)
        stored = design.load(self.trial)
        self.assertEqual(self.refused([services.FactorRow('Temperature', 'other', '°C', stored.factors[0].pk)],
                                      [self.group_row('A', replicates=1, id=stored.groups[0].pk,
                                                      cells=[services.Cell(label='Warm', value=D(18))]),
                                       self.group_row('B', replicates=1, id=stored.groups[1].pk,
                                                      cells=[services.Cell(label='warm', value=D(19))])]),
                         ['The level warm of Temperature has two different values.'])

    def test_a_cell_left_empty_is_no_level_and_the_design_says_so(self):
        self.save([diet()], [self.group_row('A', replicates=2, cells=[services.Cell()])])
        self.assertEqual((Level.objects.count(), GroupLevel.objects.count()), (0, 0))
        self.assertIn('missing_level', {finding.code for finding in design.problems(self.trial)})

    def test_the_refusals_say_every_fault_at_once_and_write_nothing(self):
        other = self.protocol('Trout feed', species=self.trout)
        retired = self.protocol('Old feed', status='retired')
        cases = [
            ([diet(''), diet('Feed'), density('Feed')], [], ['Every factor has a name.', 'Two factors are called Feed.',
                                                             'An experiment has one diet factor.']),
            ([services.FactorRow('Diet', 'diet', 'kg')], [], ['The diet has no unit: its levels are protocols.']),
            ([services.FactorRow('Odd', 'mixed')], [], ['The kind of factor Odd is not one of the two.']),
            ([], [self.group_row(''), self.group_row('A'), self.group_row('a')],
             ['Every group has a name.', 'Two groups are called a.']),
            ([], [self.group_row('A', replicates=0), self.group_row('B', replicates=100)],
             ['Group A has between 1 and 99 replicates.', 'Group B has between 1 and 99 replicates.']),
            ([], [self.group_row('A', role='boss')], ['The role of group A is not one of the four.']),
            ([diet()], [self.group_row('A', cells=[])], ['Group A has a cell for each factor.']),
            ([diet()], [self.group_row('A', cells=[services.Cell(protocol=other)])],
             ['Group A: the protocol Trout feed cannot be used, only an active feeding protocol of Atlantic salmon '
              '(SAL) can.']),
            ([diet()], [self.group_row('A', cells=[services.Cell(protocol=retired)])],
             ['Group A: the protocol Old feed cannot be used, only an active feeding protocol of Atlantic salmon '
              '(SAL) can.']),
            ([diet()], [self.group_row('A', cells=[services.Cell(label='Soy')])],
             ['Group A: the diet is a protocol, not a label.']),
            ([density()], [self.group_row('A', cells=[services.Cell(protocol=self.high)])],
             ['Group A: Density takes a label, not a protocol.']),
            ([density()], [self.group_row('A', cells=[services.Cell(value=D(5))])],
             ['Group A: a level of Density with a value needs a label.']),
            ([density()], [self.group_row('A', cells=[services.Cell(label='x' * 61)])],
             [f'Group A: the label {"x" * 61} is too long.']),
            ([services.FactorRow('Gone', 'other', '', id=self.trial.pk)], [],
             ['Factor Gone was removed meanwhile: reload the page.']),
            ([], [self.group_row('Gone', id=self.trial.pk)], ['Group Gone was removed meanwhile: reload the page.']),
        ]
        for factors, groups, messages in cases:
            with self.subTest(messages=messages):
                self.assertEqual(self.refused(factors, groups), messages)
        self.assertEqual((Factor.objects.count(), ExperimentGroup.objects.count(), AuditLog.objects.count()), (0, 0, 0))

    def test_a_protocol_retired_since_stays_in_the_design_and_the_design_says_so(self):
        self.save([diet()], [self.group_row('A', cells=[services.Cell(protocol=self.high)])])
        FeedingProtocol.objects.filter(pk=self.high.pk).update(status='retired')
        stored = design.load(self.trial)
        self.save([services.FactorRow('Diet', 'diet', '', stored.factors[0].pk)],
                  [self.group_row('A', replicates=3, id=stored.groups[0].pk, cells=[services.Cell(protocol=self.high)])])
        self.assertIn('protocol_not_active', {finding.code for finding in design.problems(self.trial)})

    def test_a_started_experiment_a_stale_version_and_a_deleted_one_are_refused(self):
        factors, groups = self.two_by_two()
        stale = self.trial.version
        self.save(factors, groups)
        self.assertEqual(self.refused(factors, groups, version=stale),
                         ['Someone else changed this experiment while you were editing it. The page now shows their '
                          'version; make your changes again.'])
        Experiment.objects.filter(pk=self.trial.pk).update(
            status='running', starts_on=self.today, hypothesis='h', primary_endpoint='bfcr',
            allocation_method='manual', allocation_note='by hand')
        self.assertEqual(self.refused(factors, groups),
                         ['The experiment has started: its design is fixed. Copy it to change the design.'])
        self.assertEqual(self.rows()[0][0][0], 'Diet')
        other = self.experiment('Gone')
        other.soft_delete(self.user)
        self.assertEqual(self.refused(factors, groups, trial=other), ['This experiment was deleted meanwhile.'])

    def test_a_template_is_designed_like_any_draft(self):
        template = self.experiment('Template', is_template=True)
        self.save(*self.two_by_two(), trial=template)
        self.assertEqual(Factor.objects.filter(experiment=template).count(), 2)


class ProblemsTests(DesignTestCase):
    def good(self):
        """A design with nothing to say: two groups of two replicates, a control, one diet each, a lead and the rest."""
        self.trial.hypothesis, self.trial.primary_endpoint = 'More protein, faster growth', 'bfcr'
        self.trial.starts_on, self.trial.version = self.today, 1
        self.trial.save()
        self.member(self.trial, self.user, 'lead')
        factors = [diet()]
        groups = [self.group_row('Control', 'control', 2, [services.Cell(protocol=self.low)]),
                  self.group_row('High feed', 'test', 2, [services.Cell(protocol=self.high)])]
        self.save(factors, groups)
        self.trial.refresh_from_db()
        slots = design.load(self.trial).slots()
        services.save_places(self.user, self.trial, [services.Place(replicate, [tank])
                                                     for tank, (_group, replicate) in zip(self.tanks, slots)],
                             self.trial.version, 'Tanks 1 to 4 stand in one row')
        for tank in self.tanks[:4]:
            self.stock(tank, count=1000, weight='50', days_ago=0)                 # stocked, so weighed, on day 0
        for protocol, unit in ((self.low, self.tanks[6]), (self.high, self.tanks[7])):
            ProtocolAssignment.objects.create(protocol=protocol, unit=unit, valid_from=self.day(1),
                                              valid_until=self.day(1))        # assigned: its table is fixed

    def found(self):
        self.trial.refresh_from_db()                       # a write by queryset leaves the loaded one as it was
        return design.problems(self.trial)

    def codes(self, level=None):
        return [finding.code for finding in self.found() if level in (None, finding.level)]

    def test_a_design_with_nothing_to_say(self):
        self.good()
        self.assertEqual(self.found(), [])
        self.assertEqual(design.assess(self.trial).fingerprint, '')

    def test_what_the_experiment_says_of_itself(self):
        self.assertEqual(self.codes(), ['no_hypothesis', 'no_endpoint', 'no_start_day', 'no_lead', 'no_group',
                                        'no_allocation'])
        self.good()
        Experiment.objects.filter(pk=self.trial.pk).update(starts_on=self.day(32))
        ReplicateUnit.objects.update(from_on=self.day(32), until_on=self.day(32) + timedelta(days=56))   # the days move too
        self.assertEqual(self.codes('error'), ['day_0_too_old'])
        self.assertEqual(self.found()[0].text, 'Day 0 is further back than records can be dated: an '
                                                              'experiment is registered at most 31 days after it begins.')
        Experiment.objects.filter(pk=self.trial.pk).update(starts_on=self.day(31))
        ReplicateUnit.objects.update(from_on=self.day(31), until_on=self.day(31) + timedelta(days=56))
        self.assertEqual(self.codes('error'), [])

    def test_the_groups_have_replicates_and_a_level_of_every_factor_and_none_repeats_another(self):
        self.good()
        stored = design.load(self.trial)
        Replicate.objects.filter(group=stored.groups[0]).delete()
        GroupLevel.objects.filter(group=stored.groups[1]).delete()
        self.assertEqual(self.codes('error'), ['no_replicate', 'missing_level'])
        self.assertEqual([finding.text for finding in design.problems(self.trial) if finding.level == 'error'],
                         ['Group Control has no replicate.', 'Group High feed has no level of Diet.'])

    def test_two_groups_with_one_set_of_levels_are_one_group(self):
        self.good()
        stored = design.load(self.trial)
        level = stored.level_of(stored.groups[0], stored.factors[0])
        GroupLevel.objects.filter(group=stored.groups[1]).update(level=level)
        self.assertEqual(self.codes('error'), ['same_levels'])
        self.assertEqual(design.problems(self.trial)[0].text, 'Groups Control and High feed have the same levels: they '
                                                              'are one group.')

    def test_the_diets_protocols_are_active_and_of_the_species_and_say_what_can_still_change(self):
        self.good()
        FeedingProtocol.objects.filter(pk=self.high.pk).update(status='retired')
        FeedingProtocol.objects.filter(pk=self.low.pk).update(species=self.trout)
        self.assertEqual(sorted(self.codes('error')), ['protocol_not_active', 'protocol_species'])
        FeedingProtocol.objects.filter(pk=self.high.pk).update(status='active')
        FeedingProtocol.objects.filter(pk=self.low.pk).update(species=self.salmon)
        self.assertEqual(self.codes(), [])
        ProtocolAssignment.objects.all().delete()
        self.assertEqual(self.codes('warning'), ['protocol_unassigned', 'protocol_unassigned'])
        self.assertEqual(self.found()[0].text, 'The feeding protocol Low protein is not assigned yet: '
                                                              'its table can still change until the experiment starts.')

    def test_feeding_tables_that_differ_in_more_than_the_feed_are_a_warning(self):
        self.good()
        self.assertNotIn('tables_differ', self.codes())
        band = ProtocolBand.objects.get(protocol=self.high)
        ProtocolRate.objects.filter(band=band).update(sfr_pct=D('1.60'))
        self.assertEqual(self.codes('warning'), ['tables_differ'])
        ProtocolRate.objects.filter(band=band).update(sfr_pct=D('1.10'))
        other_feed = Feed.objects.create(name='Grower 6', code='GR-6', feed_type='grower', pellet_size_mm=D(6))
        ProtocolBand.objects.filter(pk=band.pk).update(feed=other_feed)          # the feed alone: nothing to say
        self.assertEqual(self.codes(), [])

    def test_the_balance_of_the_design_one_group_few_replicates_no_control_unequal_groups(self):
        self.good()
        stored = design.load(self.trial)
        Replicate.objects.filter(group=stored.groups[1], number=2).delete()
        self.assertEqual(self.codes('warning'), ['few_replicates', 'unequal_replicates'])
        ExperimentGroup.objects.filter(pk=stored.groups[0].pk).update(role='test')
        self.assertEqual(self.codes('warning'), ['few_replicates', 'no_control', 'unequal_replicates'])
        ExperimentGroup.objects.filter(pk=stored.groups[1].pk).update(is_deleted=True)
        self.assertEqual(self.codes('warning'), ['one_group', 'no_control'])

    def test_errors_come_first_and_the_warnings_fingerprint_follows_the_warnings_not_the_language(self):
        self.good()
        first = design.assess(self.trial)
        self.assertEqual(first.fingerprint, '')
        stored = design.load(self.trial)
        Replicate.objects.filter(group=stored.groups[1], number=2).delete()
        Experiment.objects.filter(pk=self.trial.pk).update(hypothesis='')
        self.assertEqual([finding.level for finding in self.found()], ['error', 'warning', 'warning'])
        one = design.assess(self.trial).fingerprint
        self.assertEqual(len(one), 20)
        from django.utils import translation
        with translation.override('tr'):
            self.assertEqual(design.assess(self.trial).fingerprint, one)
        Replicate.objects.filter(group=stored.groups[0], number=2).delete()
        self.assertNotEqual(design.assess(self.trial).fingerprint, one)

    def test_the_tanks_are_allocated_in_every_replicate_on_the_site_and_inside_the_days(self):
        self.good()
        stored = design.load(self.trial)
        first, second = stored.replicates[stored.groups[0].pk]
        placement = stored.placements[first.pk][0]
        ReplicateUnit.objects.filter(pk=placement.pk).update(from_on=self.day(1), until_on=self.today + timedelta(days=57))
        self.assertEqual(self.codes('error'), ['window_outside_span'])
        ReplicateUnit.objects.filter(pk=placement.pk).update(from_on=self.today, until_on=self.today + timedelta(days=56))
        ReplicateUnit.objects.filter(replicate=second).delete()
        self.assertEqual(self.codes('error'), ['slot_without_tank'])
        self.assertEqual(self.found()[0].text, 'Control R2 has no tank.')
        ReplicateUnit.objects.create(replicate=second, unit=self.p1, from_on=self.today,
                                     until_on=self.today + timedelta(days=56))
        self.assertEqual(self.codes('error'), ['tank_off_site'])
        ReplicateUnit.objects.filter(replicate=second).delete()
        ReplicateUnit.objects.create(replicate=second, unit=self.tanks[5], from_on=self.today,
                                     until_on=self.today + timedelta(days=56))
        Experiment.objects.filter(pk=self.trial.pk).update(allocation_method='', allocation_note='')
        self.assertEqual(self.codes('error'), ['no_allocation'])

    def test_the_water_the_tanks_share_is_a_warning_by_replicate_and_by_group(self):
        from farm.models import System
        self.good()
        stored = design.load(self.trial)
        first, second = stored.replicates[stored.groups[0].pk]
        other = stored.replicates[stored.groups[1].pk][0]
        ras = System.objects.create(site=self.bergen, name='RAS 1', code='R1')
        Tank = type(self.t1)
        Tank.objects.filter(pk__in=[stored.placements[first.pk][0].unit_id,
                                    stored.placements[other.pk][0].unit_id]).update(system=ras)
        self.assertEqual(self.codes('warning'), ['system_confounding'])
        self.assertEqual(self.found()[0].text, 'System RAS 1 holds tanks of different groups (Control, High feed): its '
                                               'water, and a treatment in it, is shared between them.')
        second_system = System.objects.create(site=self.bergen, name='RAS 2', code='R2')
        ReplicateUnit.objects.create(replicate=first, unit=self.tanks[5], from_on=self.today,
                                     until_on=self.today + timedelta(days=56))
        Tank.objects.filter(pk=self.tanks[5].pk).update(system=second_system)
        self.assertEqual(sorted(self.codes('warning')), ['no_fish', 'replicate_in_systems', 'system_confounding'])

    def test_the_checks_are_a_list_other_areas_can_add_to(self):
        self.good()

        def permit(loaded):
            yield design.Finding(design.ERROR, 'no_permit', 'No permit for an animal trial.')
        design.CHECKS.append(permit)
        try:
            self.assertEqual(self.codes('error'), ['no_permit'])
        finally:
            design.CHECKS.remove(permit)
        self.assertEqual(self.codes(), [])


class DesignPageTests(PageTestCase):
    def setUp(self):
        super().setUp()
        self.create()
        self.trial = Experiment.objects.get()
        self.url = reverse('experiments:experiment_design', args=[self.trial.pk])
        self.edit = reverse('experiments:experiment_edit', args=[self.trial.pk])
        self.high, self.low = self.protocol('High protein'), self.protocol('Low protein')

    def grid(self, factors, groups, version=None, **extra):
        """What the design grids post: a row per factor and per group, the cells numbered by the factor's row."""
        data = {'version': str(version or Experiment.objects.get(pk=self.trial.pk).version),
                'factors-TOTAL_FORMS': str(len(factors)), 'factors-INITIAL_FORMS': '0',
                'factors-MIN_NUM_FORMS': '0', 'factors-MAX_NUM_FORMS': '1000',
                'groups-TOTAL_FORMS': str(len(groups)), 'groups-INITIAL_FORMS': '0',
                'groups-MIN_NUM_FORMS': '0', 'groups-MAX_NUM_FORMS': '1000', **extra}
        for index, row in enumerate(factors):
            data.update({f'factors-{index}-{key}': value for key, value in row.items()})
        for index, row in enumerate(groups):
            data.update({f'groups-{index}-{key}': value for key, value in row.items()})
        return data

    def post(self, factors, groups, **extra):
        return self.client.post(self.url, self.grid(factors, groups, **extra))

    def owners_example(self):
        factors = [{'name': 'Diet', 'kind': 'diet', 'unit': ''}]
        groups = [{'name': 'Control', 'role': 'control', 'replicates': '2', 'diet_0': str(self.low.pk)},
                  {'name': 'High protein', 'role': 'test', 'replicates': '2', 'diet_0': str(self.high.pk)}]
        return factors, groups

    def test_the_tab_starts_with_the_diet_factor_and_offers_the_active_protocols_of_the_species(self):
        retired = self.protocol('Old feed', status='retired')
        trout = self.protocol('Trout feed', species=self.trout)
        page = self.client.get(self.edit)
        self.assertContains(page, 'data-tab="design"')
        factors = page.context['factors']
        self.assertEqual([(form['name'].value(), form['kind'].value()) for form in factors], [('Diet', 'diet')])
        self.assertEqual(list(page.context['groups'].empty_form.fields),
                         ['id', 'name', 'role', 'replicates', 'diet_0', 'DELETE'])
        offered = page.context['groups'].empty_form.fields['diet_0'].queryset
        self.assertEqual([protocol.name for protocol in offered], ['High protein', 'Low protein'])
        self.assertNotIn(retired, offered)
        self.assertNotIn(trout, offered)
        self.assertContains(page, 'The design has no group.')                      # what is wrong, shown
        self.assertContains(page, 'To fix before it can start')

    def test_a_posted_design_is_stored_logged_and_shown_again(self):
        response = self.post(*self.owners_example())
        self.assertRedirects(response, self.edit, fetch_redirect_response=False)
        factors, groups = DesignTestCase.rows(self)
        self.assertEqual(factors, [('Diet', 'diet', '')])
        self.assertEqual(groups, [('Control', 'control', [1, 2], ['Low protein']),
                                  ('High protein', 'test', [1, 2], ['High protein'])])
        self.assertContains(self.client.get(self.edit), 'Design of “')
        entry = AuditLog.objects.filter(action='update').latest('created_at')
        self.assertEqual(list(entry.changes), ['Design'])
        page = self.client.get(self.edit)
        self.assertEqual([(form['name'].value(), form['replicates'].value(), form['diet_0'].value())
                          for form in page.context['groups']],
                         [('Control', 2, self.low.pk), ('High protein', 2, self.high.pk)])
        self.assertEqual(str(page.context['groups'].forms[0]['id'].value()), str(design_group(self.trial, 'Control').pk))

    def test_a_second_factor_a_column_a_cell_with_a_number_and_a_removed_group(self):
        factors, groups = self.owners_example()
        factors.append({'name': 'Density', 'kind': 'other', 'unit': 'kg/m³'})
        for group, label, value in zip(groups, ('Low', 'High'), ('20', '40.5')):
            group.update({'label_1': label, 'value_1': value})
        self.assertEqual(self.post(factors, groups).status_code, 302)
        self.assertEqual(DesignTestCase.rows(self)[1], [
            ('Control', 'control', [1, 2], ['Low protein', 'Low (20)']),
            ('High protein', 'test', [1, 2], ['High protein', 'High (40.5)'])])
        self.assertEqual(sorted(Level.objects.exclude(label='').values_list('label', 'value')),
                         [('High', Decimal('40.5')), ('Low', Decimal('20'))])
        page = self.client.get(self.edit)
        self.assertEqual(list(page.context['groups'].empty_form.fields),
                         ['id', 'name', 'role', 'replicates', 'diet_0', 'label_1', 'value_1', 'DELETE'])
        self.assertContains(page, 'Density (kg/m³)')

    def test_changing_a_factors_kind_or_adding_a_factor_renders_the_grid_again_and_saves_nothing(self):
        factors, groups = self.owners_example()
        data = self.grid(factors, groups, _draft='factors-0-kind')
        data['factors-0-kind'] = 'other'
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        empty = response.context['groups'].empty_form
        self.assertEqual(list(empty.fields), ['id', 'name', 'role', 'replicates', 'label_0', 'value_0', 'DELETE'])
        self.assertEqual([form['name'].value() for form in response.context['groups']], ['Control', 'High protein'])
        self.assertContains(response, 'data-has-errors', count=0)
        added = self.client.post(self.url, self.grid(factors, groups, _draft='add_factor'))
        self.assertEqual([(form['name'].value(), form['kind'].value()) for form in added.context['factors']],
                         [('Diet', 'diet'), (None, 'other')])
        self.assertEqual(added.context['groups'].columns, [{'index': 0, 'name': 'Diet', 'kind': 'diet', 'unit': ''}])
        self.assertFalse(Factor.objects.exists())

    def test_removing_a_factor_in_the_draft_renumbers_the_cells_of_those_after_it(self):
        factors = [{'name': 'Density', 'kind': 'other', 'unit': 'kg/m³', 'DELETE': 'on'},
                   {'name': 'Diet', 'kind': 'diet', 'unit': ''}]
        groups = [{'name': 'Control', 'role': 'control', 'replicates': '2', 'label_0': 'Low', 'diet_1': str(self.low.pk)}]
        page = self.client.post(self.url, self.grid(factors, groups, _draft='factors-0-DELETE'))
        self.assertEqual([form['name'].value() for form in page.context['factors']], ['Diet'])
        self.assertEqual(page.context['groups'].forms[0]['diet_0'].value(), str(self.low.pk))

    def test_what_is_wrong_is_said_on_the_rows_and_nothing_is_stored(self):
        factors, groups = self.owners_example()
        groups[0]['replicates'] = '0'
        groups[1]['name'] = ''
        response = self.post(factors, groups)
        self.assertEqual(response.status_code, 422)
        self.assertIn('replicates', response.context['groups'].forms[0].errors)
        self.assertIn('name', response.context['groups'].forms[1].errors)
        self.assertContains(response, 'data-has-errors', status_code=422)
        factors.append({'name': 'Feed', 'kind': 'diet', 'unit': ''})
        groups = [{'name': 'A', 'role': 'test', 'replicates': '1'}]
        response = self.post(factors, groups)
        self.assertEqual(response.status_code, 422)
        self.assertIn('An experiment has one diet factor.', str(response.context['factors'].non_form_errors()))
        self.assertFalse(Factor.objects.exists())

    def test_a_stale_version_and_a_protocol_the_form_does_not_offer_are_refused(self):
        factors, groups = self.owners_example()
        self.assertEqual(self.post(factors, groups, version=99).status_code, 422)
        self.assertContains(self.post(factors, groups, version=99),
                            'Someone else changed this experiment while you were editing it.', status_code=422)
        trout = self.protocol('Trout feed', species=self.trout)
        groups[0]['diet_0'] = str(trout.pk)
        response = self.post(factors, groups)             # the form never offers it: a choice that is not one
        self.assertEqual(response.status_code, 422)
        self.assertIn('diet_0', response.context['groups'].forms[0].errors)
        self.assertFalse(Factor.objects.exists())

    def test_a_started_experiment_shows_its_design_as_it_is_and_refuses_a_save(self):
        self.post(*self.owners_example())
        self.started(self.trial)
        page = self.client.get(self.edit)
        self.assertContains(page, 'The experiment has started, so its design is fixed')
        self.assertContains(page, 'High protein')
        self.assertNotContains(page, f'action="{self.url}"')
        response = self.post(*self.owners_example(), version=Experiment.objects.get().version)
        self.assertContains(response, 'The experiment has started, so its design is fixed', status_code=422)
        self.assertEqual(Experiment.objects.get().version, self.trial.version)

    def test_who_may_save_a_design(self):
        factors, groups = self.owners_example()
        self.client.force_login(person('reader', 'view_experiment'))
        self.assertEqual(self.post(factors, groups).status_code, 403)
        self.client.force_login(person('student', *STUDENT))
        self.assertEqual(self.post(factors, groups).status_code, 302)
        self.assertEqual(self.client.get(self.url).status_code, 302)                 # a GET goes back to the form
        self.client.logout()
        self.assertEqual(self.post(factors, groups).status_code, 302)
        self.assertIn('login', self.post(factors, groups)['Location'])

    def protocol(self, name='Salmon grow-out', species=None, status='active'):
        return ExperimentTestCase.protocol(self, name, species, status)


def design_group(trial, name):
    return ExperimentGroup.objects.get(experiment=trial, name=name)

