"""Starting an experiment: what blocks it, the warnings acknowledged by their fingerprint, the farm's own assignments it
writes (the rows the dialog would write, so the ration follows the diet), the log, a second start, and the Start dialog."""
import threading
from datetime import timedelta

from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import connection
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog
from farm.feeding import read as feeding_read
from farm.models import ProtocolAssignment, Tank
from farm.stock import integrity, services as stock_services

from .. import design, integrity as experiments_integrity, services
from ..models import Experiment, Member, Replicate, ReplicateUnit
from . import D
from .test_design import DesignTestCase, diet
from .test_pages import PageTestCase, person


class StartTestCase(DesignTestCase):
    """A design that can start: two groups of two replicates on four stocked tanks, by hand, a lead, the endpoint and the
    hypothesis; neither protocol is assigned yet (starting assigns it)."""

    days_ago = 0            # day 0: today, or some days back (the overview's tests read a trial that has run)

    def setUp(self):
        super().setUp()
        self.first = self.day(self.days_ago)
        self.trial.hypothesis, self.trial.primary_endpoint = 'More protein, faster growth', 'bfcr'
        self.trial.starts_on = self.first
        self.trial.save()
        self.member(self.trial, self.user, 'lead')
        groups = [self.group_row('Control', 'control', 2, [services.Cell(protocol=self.low)]),
                  self.group_row('High feed', 'test', 2, [services.Cell(protocol=self.high)])]
        self.save([diet()], groups)
        self.trial.refresh_from_db()
        self.stored = design.load(self.trial)
        slots = self.stored.slots()
        services.save_places(self.user, self.trial, [services.Place(replicate, [tank])
                                                     for tank, (_group, replicate) in zip(self.tanks, slots)],
                             self.trial.version, 'Tanks 1 to 4 stand in one row')
        self.batches = [self.stock(tank, count=1000, weight='50', days_ago=self.days_ago) for tank in self.tanks[:4]]
        self.end = self.first + timedelta(days=56)

    def assess(self):
        self.trial.refresh_from_db()
        return design.assess(self.trial)

    def start(self, seen=None, trial=None, **kwargs):
        trial = trial or self.trial
        trial.refresh_from_db()
        if seen is None:
            seen = design.assess(trial).fingerprint
        return services.start(self.user, trial, seen, kwargs.pop('version', trial.version))

    def refused(self, call, *args, **kwargs):
        with self.assertRaises(ValidationError) as caught:
            call(*args, **kwargs)
        return caught.exception.message_dict


class StartTests(StartTestCase):
    def test_a_design_with_only_the_unassigned_protocols_to_read_starts_and_applies_the_diet(self):
        found = self.assess()
        self.assertEqual([(finding.level, finding.code) for finding in found.findings],
                         [('warning', 'protocol_unassigned'), ('warning', 'protocol_unassigned')])
        started = self.start()
        self.assertEqual((started.status, started.version, started.updated_by), ('running', 4, self.user))
        rows = ProtocolAssignment.objects.order_by('unit__code')
        self.assertEqual([(row.unit.code, row.batch, row.protocol.name, row.valid_from, row.valid_until, row.notes,
                           row.created_by, row.scope) for row in rows],
                         [(f'T-0{n}', None, name, self.today, self.end, f'{self.trial.code} · {group}', self.user, 'unit')
                          for n, name, group in ((1, 'Low protein', 'Control'), (2, 'Low protein', 'Control'),
                                                 (3, 'High protein', 'High feed'), (4, 'High protein', 'High feed'))])
        # Each row is logged as the assignment dialog logs it, and the experiment's own row says what changed.
        created = AuditLog.objects.filter(entity_type='protocol assignment', action='create')
        self.assertEqual(created.count(), 4)
        entry = AuditLog.objects.get(entity_id=str(self.trial.pk), changes__has_key='Status')
        self.assertEqual(entry.changes['Status'], [{'msgid': 'Draft'}, {'msgid': 'Running'}])
        self.assertEqual(entry.changes['Warnings acknowledged'][1].count('is not assigned yet'), 2)
        self.assertEqual((entry.severity, entry.user), ('normal', self.user))
        self.assertTrue(all(protocol.is_assigned() for protocol in (self.low, self.high)))
        self.assertEqual(experiments_integrity.problems(), [])             # every placement has its row, to its last day

    def test_the_ration_follows_the_level_on_every_day_of_the_window(self):
        self.start()
        units = Tank.all_objects.in_bulk([tank.pk for tank in self.tanks[:4]])
        policy = feeding_read.policy(units, {batch.pk for batch in self.batches}, self.today, timezone.now())
        wanted = {self.tanks[0]: self.low, self.tanks[1]: self.low, self.tanks[2]: self.high, self.tanks[3]: self.high}
        for tank, batch in zip(self.tanks[:4], self.batches):
            for offset in range(0, 57, 7):
                row, skipped = policy.resolve(tank.pk, batch.pk, self.today + timedelta(days=offset))
                self.assertEqual((row.protocol, skipped), (wanted[tank], None), (tank.code, offset))
        self.assertIsNone(policy.resolve(self.tanks[0].pk, self.batches[0].pk, self.end + timedelta(days=1))[0])
        self.assertEqual(integrity.problems(), [])

    def test_a_start_that_is_clean_needs_no_acknowledgement_and_logs_no_warnings(self):
        for protocol, unit in ((self.low, self.tanks[6]), (self.high, self.tanks[7])):
            ProtocolAssignment.objects.create(protocol=protocol, unit=unit, valid_from=self.day(1),
                                              valid_until=self.day(1))
        self.assertEqual(self.assess().findings, [])
        started = self.start(seen='')
        self.assertEqual(started.status, 'running')
        entry = AuditLog.objects.get(entity_id=str(self.trial.pk), changes__has_key='Status')
        self.assertNotIn('Warnings acknowledged', entry.changes)

    def test_a_group_without_a_diet_level_or_an_experiment_without_a_diet_factor_writes_no_assignments(self):
        other = self.experiment('No diet', starts_on=self.today)
        self.member(other, self.user, 'lead')
        other.hypothesis, other.primary_endpoint = 'Temperature', 'survival'
        other.save()
        self.save([services.FactorRow('Temperature', 'other', '°C')],
                  [self.group_row('Cold', 'control', 2, [services.Cell(label='12')]),
                   self.group_row('Warm', 'test', 2, [services.Cell(label='16')])], trial=other)
        other.refresh_from_db()
        slots = design.load(other).slots()
        for tank in self.tanks[4:8]:
            self.stock(tank, count=1000, weight='50', days_ago=0)
        services.save_places(self.user, other, [services.Place(replicate, [tank])
                                                for tank, (_g, replicate) in zip(self.tanks[4:8], slots)],
                             other.version, 'by hand')
        before = ProtocolAssignment.objects.count()
        started = self.start(trial=other)
        self.assertEqual((started.status, ProtocolAssignment.objects.count()), ('running', before))


class RefusalTests(StartTestCase):
    def codes(self):
        return [(finding.level, finding.code) for finding in self.assess().findings]

    def test_every_error_blocks_the_start_and_nothing_is_written(self):
        Experiment.objects.filter(pk=self.trial.pk).update(hypothesis='')
        Member.objects.all().delete()
        messages = self.refused(self.start)[NON_FIELD_ERRORS]
        self.assertEqual(messages, ['The hypothesis is not written.', 'The team has no lead.'])
        self.assertEqual(Experiment.objects.get(pk=self.trial.pk).status, 'draft')
        self.assertFalse(ProtocolAssignment.objects.exists())
        self.assertFalse(AuditLog.objects.filter(entity_id=str(self.trial.pk), changes__has_key='Status').exists())

    def test_a_tank_with_a_standing_assignment_of_its_own_blocks_it_and_is_listed_and_never_ended(self):
        standing = ProtocolAssignment.objects.create(protocol=self.low, unit=self.tanks[0], valid_from=self.day(3))
        self.assertEqual(self.codes(), [('error', 'standing_assignment'), ('warning', 'protocol_unassigned')])
        text = self.assess().errors[0].text
        self.assertEqual(text, 'T-01 already has the feeding protocol Low protein assigned (from '
                               f'{self.day(3).isoformat()}, with no last day): end it first, for starting an '
                               'experiment never ends another record.')
        self.assertEqual(self.refused(self.start)[NON_FIELD_ERRORS], [text])
        self.assertIsNone(ProtocolAssignment.objects.get(pk=standing.pk).valid_until)        # not ended for the person
        ProtocolAssignment.objects.filter(pk=standing.pk).update(valid_until=self.day(1))      # the person ends it
        self.assertEqual([code for _level, code in self.codes()], ['protocol_unassigned'])      # Low is assigned now
        self.start()
        self.assertEqual(ProtocolAssignment.objects.filter(unit=self.tanks[0]).count(), 2)

    def test_a_protocol_assigned_to_a_batch_in_the_tank_would_beat_the_diet_and_blocks_it(self):
        ProtocolAssignment.objects.create(protocol=self.high, unit=self.tanks[1], batch=self.batches[1],
                                          valid_from=self.day(1), valid_until=self.today + timedelta(days=10))
        errors = self.assess().errors
        self.assertEqual([finding.code for finding in errors], ['batch_assignment'])
        self.assertIn(f'T-02 feeds batch {self.batches[1].code} by High protein (', errors[0].text)
        self.assertIn('it would override the diet of Control.', errors[0].text)
        self.refused(self.start)
        self.assertFalse(ProtocolAssignment.objects.filter(notes__startswith=self.trial.code).exists())

    def test_an_assignment_to_a_whole_batch_or_outside_the_days_does_not_block(self):
        ProtocolAssignment.objects.create(protocol=self.high, batch=self.batches[0], valid_from=self.day(1))
        ProtocolAssignment.objects.create(protocol=self.high, unit=self.tanks[1], valid_from=self.day(20),
                                          valid_until=self.day(10))
        ProtocolAssignment.objects.create(protocol=self.low, unit=self.tanks[2], valid_from=self.end + timedelta(days=1))
        self.assertEqual([code for level, code in self.codes() if level == 'error'], [])

    def test_the_warnings_must_be_acknowledged_as_they_are_now_and_the_fingerprint_follows_them(self):
        self.assertEqual(self.refused(self.start, seen=''), {'start_ack': ['Tick the box to go on despite these '
                                                                           'warnings.']})
        shown = self.assess().fingerprint
        self.assertEqual(len(shown), 20)
        self.assertEqual(self.refused(self.start, seen='stale'),
                         {'start_ack': ['The warnings changed since the form was shown: read them again, and tick the '
                                        'box to go on.']})
        replicate = design.load(self.trial).replicates[self.stored.groups[1].pk][1]
        ReplicateUnit.objects.filter(replicate=replicate).delete()
        Replicate.objects.filter(pk=replicate.pk).delete()                       # unequal groups: a new warning
        self.assertNotEqual(self.assess().fingerprint, shown)
        errors = self.refused(self.start, seen=shown)
        self.assertEqual(list(errors), ['start_ack'])                              # asked again for what changed
        self.assertEqual(Experiment.objects.get(pk=self.trial.pk).status, 'draft')

    def test_a_stale_version_a_second_start_a_template_and_a_deleted_experiment_are_refused(self):
        self.assertEqual(self.refused(self.start, version=0)[NON_FIELD_ERRORS],
                         ['Someone else changed this experiment while you were editing it. The page now shows their '
                          'version; make your changes again.'])
        self.start()
        self.assertEqual(self.refused(self.start)[NON_FIELD_ERRORS],
                         ['The experiment has started: its design is fixed. Copy it to change the design.'])
        template = self.experiment('Template', is_template=True)
        self.assertEqual(self.refused(self.start, trial=template)[NON_FIELD_ERRORS],
                         ['A template is not started: copy it into an experiment.'])
        gone = self.experiment('Gone')
        gone.soft_delete(self.user)
        self.assertEqual(self.refused(self.start, trial=gone)[NON_FIELD_ERRORS],
                         ['This experiment was deleted meanwhile.'])
        self.assertEqual(ProtocolAssignment.objects.count(), 4)

    def test_a_row_the_assignments_refuse_leaves_nothing_started_and_names_the_tank(self):
        from unittest import mock
        from farm.feeding import assignments as farm_assignments
        clash = farm_assignments.RowError(self.tanks[2], NON_FIELD_ERRORS,
                                          'Another protocol is assigned to this unit on some of these days.')
        real = farm_assignments.rows

        def rows(protocol, units, batch, first, last, notes=''):
            made, errors = real(protocol, units, batch, first, last, notes)
            return made, [*errors, clash] if protocol == self.high else errors
        with mock.patch.object(farm_assignments, 'rows', rows):
            errors = self.refused(self.start)[NON_FIELD_ERRORS]
        self.assertEqual(errors, ['T-03: Another protocol is assigned to this unit on some of these days.'])
        self.assertEqual((Experiment.objects.get(pk=self.trial.pk).status, ProtocolAssignment.objects.count()),
                         ('draft', 0))


class DayZeroTests(StartTestCase):
    def codes(self):
        return [finding.code for finding in self.assess().findings if finding.code in (
            'no_fish', 'two_batches', 'no_weighing')]

    def place_in_first_replicate(self, *tanks, first=None, last=None):
        replicate = design.load(self.trial).slots()[0][1]
        for tank in tanks:
            ReplicateUnit.objects.create(replicate=replicate, unit=tank, from_on=first or self.today,
                                         until_on=last or self.end)

    def test_fish_of_the_species_one_batch_and_a_weighing_on_day_0_say_nothing(self):
        self.assertEqual(self.codes(), [])

    def test_a_tank_without_fish_of_the_species_or_with_only_cleaner_fish_says_so(self):
        self.stock(self.tanks[4], count=100, weight='5', days_ago=0, species=self.trout)
        self.place_in_first_replicate(self.tanks[4], self.tanks[5])
        found = [finding for finding in self.assess().findings if finding.code == 'no_fish']
        self.assertEqual([finding.text for finding in found],
                         ['T-05 holds no fish of Atlantic salmon (SAL) on day 0.',
                          'T-06 holds no fish of Atlantic salmon (SAL) on day 0.'])

    def test_two_batches_of_the_species_in_a_tank_on_day_0_are_a_warning(self):
        self.stock(self.tanks[0], count=500, weight='60', days_ago=0)
        self.assertEqual(self.codes(), ['two_batches'])
        self.assertEqual([finding.text for finding in self.assess().findings if finding.code == 'two_batches'],
                         ['T-01 holds more than one batch of Atlantic salmon (SAL) on day 0: its figures are the '
                          'batches’ together.'])

    def test_fish_there_on_day_0_without_a_weighing_that_day_have_no_baseline_until_they_are_weighed(self):
        batch = self.stock(self.tanks[4], count=500, weight='60', days_ago=5)                 # came before day 0
        self.place_in_first_replicate(self.tanks[4])
        found = [finding for finding in self.assess().findings if finding.code == 'no_weighing']
        self.assertEqual([finding.text for finding in found],
                         ['The fish of T-05 are not weighed on day 0: the baseline of their feed conversion is '
                          'missing.'])
        stock_services.record_weighing(self.user, unit=self.tanks[4], batch=batch, day=self.today,
                                       avg_weight_g=D(70))
        self.assertEqual(self.codes(), [])

    def test_a_day_0_to_come_is_not_asked_yet(self):
        Experiment.objects.filter(pk=self.trial.pk).update(starts_on=self.today + timedelta(days=5))
        ReplicateUnit.objects.update(from_on=self.today + timedelta(days=5), until_on=self.today + timedelta(days=61))
        self.assertEqual(self.codes(), [])


class StartPageTests(PageTestCase):
    def setUp(self):
        super().setUp()
        self.create(starts_on=self.today.isoformat())
        self.trial = Experiment.objects.get()
        Experiment.objects.filter(pk=self.trial.pk).update(audience='open')   # the roles here; sealed: test_access
        self.url = reverse('experiments:experiment_start', args=[self.trial.pk])
        self.edit = reverse('experiments:experiment_edit', args=[self.trial.pk])

    def ready(self):
        """A design that can start, by the services."""
        low, high = self.protocol('Low protein'), self.protocol('High protein')
        trial = Experiment.objects.get(pk=self.trial.pk)
        groups = [services.GroupRow('Control', 'control', 2, [services.Cell(protocol=low)]),
                  services.GroupRow('High feed', 'test', 2, [services.Cell(protocol=high)])]
        services.save_design(self.user, trial, [services.FactorRow('Diet', 'diet')], groups, trial.version)
        trial.refresh_from_db()
        slots = design.load(trial).slots()
        tanks = self.tanks[:4]
        services.save_places(self.user, trial, [services.Place(r, [t]) for t, (_g, r) in zip(tanks, slots)],
                             trial.version, 'by hand')
        for tank in tanks:
            self.stock(tank, count=1000, weight='50', days_ago=0)
        return low, high

    def test_the_dialog_lists_what_blocks_and_disables_start(self):
        page = self.client.get(self.url, headers={'X-Modal': '1'})
        self.assertContains(page, 'To fix before it can start')
        self.assertContains(page, 'The design has no group.')
        self.assertContains(page, 'disabled')
        self.assertNotContains(page, 'name="start_ack"')

    def test_the_dialog_shows_the_warnings_with_their_box_and_a_start_is_taken_with_it(self):
        self.ready()
        page = self.client.get(self.url, headers={'X-Modal': '1'})
        self.assertContains(page, 'To read before it starts')
        self.assertContains(page, 'is not assigned yet')
        fingerprint = page.context['findings'].fingerprint
        self.assertContains(page, f'name="start_ack" value="{fingerprint}"')
        version = page.context['form']['version'].value()
        refused = self.client.post(self.url, {'version': version}, headers={'X-Modal': '1'})
        self.assertContains(refused, 'Tick the box to go on despite these warnings.', status_code=422)
        self.assertEqual(Experiment.objects.get().status, 'draft')
        done = self.client.post(self.url, {'version': version, 'start_ack': fingerprint}, headers={'X-Modal': '1'})
        self.assertEqual(done.status_code, 204)
        self.assertEqual(done['X-Modal-Load'], self.edit)
        self.assertEqual((Experiment.objects.get().status, ProtocolAssignment.objects.count()), ('running', 4))
        again = self.client.get(self.url, headers={'X-Modal': '1'})
        self.assertContains(again, 'This experiment has started.')

    def test_a_stale_page_a_page_for_a_template_and_who_may_start(self):
        self.ready()
        page = self.client.get(self.url)
        version = page.context['form']['version'].value()
        fingerprint = page.context['findings'].fingerprint
        self.assertContains(self.client.post(self.url, {'version': '99', 'start_ack': fingerprint}),
                            'Someone else changed this experiment', status_code=422)
        template = self.experiment('Template', is_template=True)
        self.assertContains(self.client.get(reverse('experiments:experiment_start', args=[template.pk])),
                            'A template is not started')
        self.client.force_login(person('reader', 'view_experiment'))
        self.assertEqual(self.client.post(self.url, {'version': version, 'start_ack': fingerprint}).status_code, 403)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_the_start_button_is_on_the_design_tab_and_the_read_page_for_those_who_may_and_not_for_a_template(self):
        self.assertContains(self.client.get(self.edit), f'href="{self.url}"')
        detail = reverse('experiments:experiment_detail', args=[self.trial.pk])
        self.assertContains(self.client.get(detail), f'href="{self.url}"')
        self.client.force_login(person('reader', 'view_experiment'))
        self.assertNotContains(self.client.get(detail), f'href="{self.url}"')
        self.client.force_login(self.user)
        self.started(self.trial)
        self.assertNotContains(self.client.get(detail), f'href="{self.url}"')
        template = self.experiment('Template', is_template=True)
        self.assertNotContains(self.client.get(reverse('experiments:experiment_edit', args=[template.pk])),
                               reverse('experiments:experiment_start', args=[template.pk]))


class ConcurrencyTests(TransactionTestCase):
    """Two starts at once: the tanks' and the experiment's locks make them take turns, so the second finds it started and
    only one writes the assignments."""

    serialized_rollback = True

    def setUp(self):
        from django.contrib.auth import get_user_model
        from farm.models import FeedingProtocol, ProductionDepartment, ProtocolBand, ProtocolRate, Site, Feed
        from farm.tests.helpers import make_species, may_record, role
        from farm.tests.test_stock import make_unit
        from .test_pages import RESEARCHER
        from decimal import Decimal
        self.user = get_user_model().objects.create_user('ali', 'ali@example.com', 'x')
        self.user.groups.add(role('Researcher', *RESEARCHER))
        may_record(self.user)                     # the fixture's stocking: the stock service asks (L-6)
        site = Site.objects.create(name='Bergen', code='BG')
        hall = ProductionDepartment.objects.create(site=site, name='Hall A', code='HA')
        self.tank = make_unit('T-01', hall)
        species = make_species()
        feed = Feed.objects.create(name='Grower 4', code='GR-4', feed_type='grower', pellet_size_mm=Decimal(4))
        protocol = FeedingProtocol.objects.create(name='Grow-out', species=species, expected_fcr=Decimal('1.0'),
                                                  status='active')
        band = ProtocolBand.objects.create(protocol=protocol, min_weight_g=0, feed=feed, meals_per_day=4)
        ProtocolRate.objects.create(band=band, temperature_c=Decimal(12), sfr_pct=Decimal('1.1'))
        today = stock_services.local_today(self.tank)
        stock_services.record_input(self.user, species=species, input_stage='fry', origin='own_hatchery', day=today,
                                   lines=[(self.tank, 1000, Decimal(50))])
        self.trial = Experiment.objects.create(code='E-2026-001', name='One', site=site, species=species,
                                               duration_days=56, starts_on=today, hypothesis='h',
                                               primary_endpoint='bfcr', allocation_method='manual',
                                               allocation_note='by hand')
        Member.objects.create(experiment=self.trial, user=self.user, role='lead')
        group = self.trial.groups.create(name='A', role='control')
        factor = self.trial.factors.create(name='Diet', kind='diet')
        level = factor.levels.create(protocol=protocol)
        replicate = group.replicates.create(number=1)
        self.trial.group_levels.create(group=group, factor=factor, level=level)
        replicate.placements.create(unit=self.tank, from_on=today, until_on=today + timedelta(days=56))
        self.today = today

    def test_two_starts_at_once_one_wins_and_the_assignment_is_written_once(self):
        results, gate = [], threading.Barrier(2)

        def start():
            gate.wait()
            try:
                fingerprint = design.assess(self.trial).fingerprint
                services.start(self.user, self.trial, fingerprint, self.trial.version)
                results.append('ok')
            except ValidationError as error:
                results.append(error.messages[0])
            finally:
                connection.close()

        threads = [threading.Thread(target=start) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(result == 'ok' for result in results), [False, True])
        self.assertEqual(ProtocolAssignment.objects.count(), 1)
        self.assertEqual(Experiment.objects.get().status, 'running')

    def test_a_feeding_recorded_while_it_starts_waits_for_the_tank_and_both_are_whole(self):
        from farm.feeding import services as feeding_services
        from farm.models import Feed
        from decimal import Decimal
        results, gate = [], threading.Barrier(2)
        feed = Feed.objects.get()

        def start():
            gate.wait()
            try:
                services.start(self.user, self.trial, design.assess(self.trial).fingerprint, self.trial.version)
                results.append('started')
            except ValidationError as error:
                results.append(error.messages[0])
            finally:
                connection.close()

        def feed_them():
            gate.wait()
            try:
                feeding_services.record_feeding(self.user, unit=self.tank, day=self.today, feed=feed,
                                                amount_kg=Decimal('5'))
                results.append('fed')
            except ValidationError as error:
                results.append(error.messages[0])
            finally:
                connection.close()

        threads = [threading.Thread(target=start), threading.Thread(target=feed_them)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(results), ['fed', 'started'])
        self.assertEqual(ProtocolAssignment.objects.count(), 1)
        self.assertEqual(integrity.problems(), [])
