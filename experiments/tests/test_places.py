"""The places of an experiment: the seeded deal (fixed vectors), `services.save_places` and `randomise` (the sites, the
span, the bookings by other experiments, the allocation and its reason, the log), the span that moves its placements, the
Places tab's page, and two experiments enrolling one tank at once."""
import threading
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import IntegrityError, connection
from django.test import SimpleTestCase, TransactionTestCase
from django.urls import reverse

from core.models import AuditLog
from farm.models import System
from farm.stock.dates import site_today
from farm.tests.helpers import role
from farm.tests.test_stock import make_unit

from .. import allocation, read, services
from ..models import Experiment, ReplicateUnit
from . import ExperimentTestCase
from .test_pages import RESEARCHER, PageTestCase, person


class AllocationTests(SimpleTestCase):
    """The deal never changes: its vectors are written here, so a different Python, machine or edit that changed one is
    caught (the keys are SHA-256 of "<seed>:<code>", checked with an independent `sha256sum`)."""

    def test_the_sort_key_is_the_sha256_of_the_seed_and_the_code(self):
        self.assertEqual(allocation.sort_key(7, 'T-01'),
                         '905d442ed69b07314a6bbc714904328fe9f793c4b74d838213d6993feeea713d')

    def test_fixed_vectors(self):
        self.assertEqual(allocation.deal(['T-01', 'T-02', 'T-03', 'T-04'], [(0, 1), (0, 2), (1, 1), (1, 2)], 20261103),
                         [((0, 1), 'T-04'), ((0, 2), 'T-03'), ((1, 1), 'T-02'), ((1, 2), 'T-01')])
        self.assertEqual(allocation.deal(['T-01', 'T-02', 'T-03', 'T-04', 'T-05', 'T-06'], list(range(6)), 1),
                         [(0, 'T-01'), (1, 'T-02'), (2, 'T-06'), (3, 'T-03'), (4, 'T-05'), (5, 'T-04')])
        self.assertEqual(allocation.deal(['R1', 'T-09', 'T-10'], list(range(3)), 0),
                         [(0, 'T-10'), (1, 'T-09'), (2, 'R1')])

    def test_the_deal_depends_on_the_pool_and_the_seed_and_not_on_the_order_the_pool_is_given_in(self):
        codes = ['T-01', 'T-02', 'T-03', 'T-04', 'T-05', 'T-06']
        slots = list(range(6))
        dealt = allocation.deal(codes, slots, 1)
        self.assertEqual(allocation.deal(list(reversed(codes)), slots, 1), dealt)
        self.assertEqual(allocation.deal(codes[3:] + codes[:3], slots, 1), dealt)
        self.assertNotEqual(allocation.deal(codes, slots, 2), dealt)
        self.assertEqual(sorted(code for _slot, code in allocation.deal(codes, slots, 99)), sorted(codes))
        self.assertEqual(allocation.METHOD, 'sha256_v1')


class PlacesTestCase(ExperimentTestCase):
    def setUp(self):
        super().setUp()
        self.trial = self.experiment(starts_on=self.today)
        self.control, self.test = self.group(self.trial, 'Control', 'control'), self.group(self.trial, 'Test')
        self.slots = [self.replicate(self.control, 1), self.replicate(self.control, 2), self.replicate(self.test, 1),
                      self.replicate(self.test, 2)]
        self.end = self.today + timedelta(days=56)

    def place(self, tanks=None, note='Tanks 1 to 4 stand in one row', trial=None, **kwargs):
        trial = trial or self.trial
        trial.refresh_from_db()
        tanks = tanks if tanks is not None else self.tanks[:4]
        places = [services.Place(replicate, [tank]) for replicate, tank in zip(self.slots, tanks)]
        return services.save_places(self.user, trial, kwargs.pop('places', places), trial.version, note)

    def refused(self, call, *args, **kwargs):
        with self.assertRaises(ValidationError) as caught:
            call(*args, **kwargs)
        return caught.exception.message_dict[NON_FIELD_ERRORS]

    def stored(self, trial=None):
        return [(f'{cell.group.name} R{cell.replicate.number}', cell.unit.code, cell.first, cell.last)
                for cell in read.cells(trial or self.trial)]


class SavePlacesTests(PlacesTestCase):
    def test_tanks_are_placed_for_the_whole_span_logged_and_the_allocation_is_by_hand_with_its_reason(self):
        saved = self.place()
        self.assertEqual(self.stored(), [('Control R1', 'T-01', self.today, self.end),
                                         ('Control R2', 'T-02', self.today, self.end),
                                         ('Test R1', 'T-03', self.today, self.end),
                                         ('Test R2', 'T-04', self.today, self.end)])
        self.assertEqual((saved.allocation_method, saved.allocation_seed, saved.allocation_note, saved.version),
                         ('manual', None, 'Tanks 1 to 4 stand in one row', 2))
        self.assertEqual(self.trial.pk, saved.pk)
        entry = AuditLog.objects.get(action='update')
        self.assertEqual(entry.changes, {
            'Places': [None, f'Control R1: T-01 ({self.today.isoformat()} to {self.end.isoformat()})\n'
                             f'Control R2: T-02 ({self.today.isoformat()} to {self.end.isoformat()})\n'
                             f'Test R1: T-03 ({self.today.isoformat()} to {self.end.isoformat()})\n'
                             f'Test R2: T-04 ({self.today.isoformat()} to {self.end.isoformat()})'],
            'Allocation': [None, 'Placed by hand: Tanks 1 to 4 stand in one row']})

    def test_a_row_may_give_days_of_its_own_and_several_tanks(self):
        places = [services.Place(self.slots[0], [self.tanks[0], self.tanks[1]], self.today + timedelta(days=7),
                                 self.today + timedelta(days=49))]
        self.place(places=places)
        self.assertEqual(self.stored(), [('Control R1', 'T-01', self.today + timedelta(days=7),
                                          self.today + timedelta(days=49)),
                                         ('Control R1', 'T-02', self.today + timedelta(days=7),
                                          self.today + timedelta(days=49))])

    def test_saving_the_same_places_again_changes_and_logs_nothing_and_a_new_reason_is_kept(self):
        self.place()
        before = (AuditLog.objects.count(), Experiment.objects.get(pk=self.trial.pk).version)
        again = self.place(note='')
        self.assertEqual((AuditLog.objects.count(), again.version), before)
        self.place(note='Tanks 1 to 4 share a drain')
        self.trial.refresh_from_db()
        self.assertEqual((self.trial.allocation_note, self.trial.version), ('Tanks 1 to 4 share a drain', 3))
        self.assertEqual(AuditLog.objects.filter(action='update').count(), 2)
        self.assertEqual(AuditLog.objects.latest('created_at').changes,
                         {'Allocation': ['Placed by hand: Tanks 1 to 4 stand in one row',
                                         'Placed by hand: Tanks 1 to 4 share a drain']})

    def test_a_placement_that_is_not_randomised_needs_its_reason(self):
        self.assertEqual(self.refused(self.place, note=' '),
                         ['Say why the tanks are placed by hand: a placement that is not randomised is registered with '
                          'its reason.'])
        self.assertEqual(self.stored(), [])

    def test_changing_one_replicate_keeps_the_others_and_taking_every_tank_out_clears_the_allocation(self):
        self.place()
        kept = list(ReplicateUnit.objects.filter(replicate=self.slots[0]).values_list('pk', flat=True))
        self.place(tanks=[self.tanks[0], self.tanks[1], self.tanks[2], self.tanks[5]], note='Tank 4 is leaking')
        self.assertEqual([cell.unit.code for cell in read.cells(self.trial)], ['T-01', 'T-02', 'T-03', 'T-06'])
        self.assertEqual(list(ReplicateUnit.objects.filter(replicate=self.slots[0]).values_list('pk', flat=True)), kept)
        self.place(places=[], note='')
        self.trial.refresh_from_db()
        self.assertEqual((self.trial.allocation_method, self.trial.allocation_seed, self.trial.allocation_note), ('', None, ''))
        self.assertEqual(ReplicateUnit.all_objects.count(), 0)           # a draft's placements are removed for good
        self.assertEqual(AuditLog.objects.latest('created_at').changes['Allocation'][1], None)

    def test_a_tank_must_be_on_the_site_and_the_days_inside_the_experiment_and_in_order(self):
        cases = [
            ([services.Place(self.slots[0], [self.p1])], ['P-01 is not on the site of the experiment (Bergen).']),
            ([services.Place(self.slots[0], [self.tanks[0]], self.today - timedelta(days=1), self.end)],
             [f'Control R1: the days are outside the experiment ({self.today.isoformat()} to {self.end.isoformat()}).']),
            ([services.Place(self.slots[0], [self.tanks[0]], self.today, self.end + timedelta(days=1))],
             [f'Control R1: the days are outside the experiment ({self.today.isoformat()} to {self.end.isoformat()}).']),
            ([services.Place(self.slots[0], [self.tanks[0]], self.end, self.today)],
             ['Control R1: the last day comes on or after the first day.']),
            ([services.Place(self.slots[0], [self.tanks[0]]), services.Place(self.slots[1], [self.tanks[0]])],
             ['T-01 is placed twice on some of the same days (Control R1, Control R2).']),
        ]
        for places, messages in cases:
            with self.subTest(messages=messages):
                self.assertEqual(self.refused(self.place, places=places), messages)
        self.assertEqual(self.stored(), [])

    def test_a_tank_may_be_in_two_replicates_on_days_that_do_not_meet(self):
        middle = self.today + timedelta(days=28)
        places = [services.Place(self.slots[0], [self.tanks[0]], self.today, middle),
                  services.Place(self.slots[1], [self.tanks[0]], middle + timedelta(days=1), self.end)]
        self.place(places=places)
        self.assertEqual(len(self.stored()), 2)

    def test_a_replicate_of_another_experiment_or_one_removed_meanwhile_is_refused(self):
        other = self.experiment('Other', starts_on=self.today)
        foreign = self.replicate(self.group(other, 'X'), 1)
        self.assertEqual(self.refused(self.place, places=[services.Place(foreign, [self.tanks[0]])]),
                         ['A replicate was removed meanwhile: reload the page.'])

    def test_a_tank_booked_to_another_experiment_is_refused_with_its_days_never_the_experiment(self):
        other = self.experiment('Other', starts_on=self.today)
        mine = self.replicate(self.group(other, 'X'), 1)
        services.save_places(self.user, other, [services.Place(mine, [self.tanks[0]], self.today + timedelta(days=50),
                                                               self.end)], other.version, 'one tank')
        held = f'T-01 is booked by another experiment from {(self.today + timedelta(days=50)).isoformat()} to {self.end.isoformat()}.'
        self.assertEqual(self.refused(self.place), [held])
        self.assertEqual(self.stored(), [])
        Experiment.objects.filter(pk=other.pk).update(
            status='running', hypothesis='h', primary_endpoint='bfcr', allocation_method='manual',
            allocation_note='by hand')
        self.assertEqual(self.refused(self.place), [held])
        self.place(tanks=[self.tanks[1], self.tanks[2], self.tanks[3], self.tanks[4]])        # other tanks: free
        self.assertEqual(len(self.stored()), 4)

    def test_a_booking_made_between_the_check_and_the_write_is_told_the_same_way(self):
        other = self.experiment('Other', starts_on=self.today)
        mine = self.replicate(self.group(other, 'X'), 1)
        services.save_places(self.user, other, [services.Place(mine, [self.tanks[0]])], other.version, 'one tank')
        with mock.patch.object(services, '_check_booked'):
            self.assertEqual(self.refused(self.place),
                             ['A tank or a system was booked by another experiment meanwhile: look at the places and '
                              'try again.'])
        self.assertEqual(self.stored(), [])

    def test_a_system_is_the_tanks_of_it_and_of_the_systems_nested_in_it_and_is_never_stored(self):
        ras = System.objects.create(site=self.bergen, name='RAS 1', code='R1')
        loop = System.objects.create(site=self.bergen, name='Loop', code='R1-A', parent=ras)
        type(self.t1).objects.filter(pk__in=[self.tanks[0].pk, self.tanks[1].pk]).update(system=ras)
        type(self.t1).objects.filter(pk=self.tanks[2].pk).update(system=loop)
        self.assertEqual([tank.code for tank in services.tanks_of(ras)], ['T-01', 'T-02', 'T-03'])
        self.assertEqual([tank.code for tank in services.tanks_of(loop)], ['T-03'])
        self.assertEqual(services.tanks_of(self.tanks[3]), [self.tanks[3]])
        self.place(places=[services.Place(self.slots[0], services.tanks_of(ras))])
        self.assertEqual([row[1] for row in self.stored()], ['T-01', 'T-02', 'T-03'])
        self.assertFalse(any('system' in field.name for field in ReplicateUnit._meta.get_fields()))

    def test_a_whole_system_is_booked_with_each_nested_system_and_its_tanks_are_tagged(self):
        from ..models import ReplicateSystem
        ras = System.objects.create(site=self.bergen, name='RAS 1', code='R1')
        loop = System.objects.create(site=self.bergen, name='Loop', code='R1-A', parent=ras)
        type(self.t1).objects.filter(pk__in=[self.tanks[0].pk, self.tanks[1].pk]).update(system=ras)
        type(self.t1).objects.filter(pk=self.tanks[2].pk).update(system=loop)
        self.place(places=[services.Place(self.slots[0], services.tanks_of(ras), systems=services.whole(ras)),
                           services.Place(self.slots[1], [self.tanks[3]])])
        bookings = {row.system.code: row for row in ReplicateSystem.objects.select_related('system')}
        self.assertEqual(sorted((code, row.replicate, row.from_on, row.until_on) for code, row in bookings.items()),
                         [('R1', self.slots[0], self.today, self.end), ('R1-A', self.slots[0], self.today, self.end)])
        tags = {row.unit.code: row.booking.system.code if row.booking else None
                for row in ReplicateUnit.objects.select_related('unit', 'booking__system')}
        self.assertEqual(tags, {'T-01': 'R1', 'T-02': 'R1', 'T-03': 'R1-A', 'T-04': None})
        entry = AuditLog.objects.filter(entity_id=str(self.trial.pk)).latest('created_at')
        self.assertIn('Control R1: T-01, T-02, T-03', entry.changes['Places'][1])
        self.assertIn('(whole: R1, R1-A)', entry.changes['Places'][1])
        self.place(places=[services.Place(self.slots[1], [self.tanks[3]])])           # the system taken out again
        self.assertFalse(ReplicateSystem.objects.exists())

    def test_a_system_booked_by_another_experiment_is_refused_with_its_days(self):
        ras = System.objects.create(site=self.bergen, name='RAS 1', code='R1')
        type(self.t1).objects.filter(pk=self.tanks[5].pk).update(system=ras)
        other = self.experiment('Other', starts_on=self.today)
        services.save_places(self.user, other, [services.Place(self.replicate(self.group(other, 'X'), 1), [],
                                                               systems=[ras])], other.version, 'the loop')
        refused = self.refused(self.place, places=[services.Place(self.slots[0], [self.tanks[0]], systems=[ras])])
        self.assertEqual(refused, [f'R1 is booked by another experiment from {self.today.isoformat()} to '
                                   f'{self.end.isoformat()}.'])
        self.assertNotIn(other.code, ' '.join(refused))

    def test_the_booking_check_reads_bookings_the_person_may_not_read_and_answers_days_only(self):
        other = self.experiment('Other', starts_on=self.today)
        services.save_places(self.user, other, [services.Place(self.replicate(self.group(other, 'X'), 1),
                                                               [self.tanks[0]])], other.version, 'one tank')
        stranger = get_user_model().objects.create_user('stranger', 'stranger@example.com', 'x')
        from core import sealing
        with sealing.as_viewer(stranger):
            self.assertEqual(read.booked([self.tanks[0].pk], self.today, self.end), {
                self.tanks[0].pk: (self.today, self.end)})

    def test_the_form_offers_a_tank_booked_elsewhere_disabled_with_its_days_never_the_experiment(self):
        from ..forms import places_forms
        other = self.experiment('Other', starts_on=self.today)
        services.save_places(self.user, other, [services.Place(self.replicate(self.group(other, 'X'), 1),
                                                               [self.tanks[0]])], other.version, 'one tank')
        form, rows = places_forms(self.trial)
        rendered = str(form['pool']) + str(rows.forms[0]['tanks'])
        self.assertIn(f'booked {self.today.isoformat()} to {self.end.isoformat()}', rendered)
        self.assertNotIn(other.code, rendered)

    def test_a_moved_span_moves_the_bookings_with_their_tanks(self):
        from ..models import ReplicateSystem
        ras = System.objects.create(site=self.bergen, name='RAS 1', code='R1')
        type(self.t1).objects.filter(pk=self.tanks[0].pk).update(system=ras)
        self.place(places=[services.Place(self.slots[0], [self.tanks[0]], systems=[ras])])
        old = services.span(self.trial)
        Experiment.objects.filter(pk=self.trial.pk).update(starts_on=self.today + timedelta(days=7))
        self.trial.refresh_from_db()
        services.move_span(self.user, self.trial, old)
        booking = ReplicateSystem.objects.get()
        self.assertEqual((booking.from_on, booking.until_on), (self.today + timedelta(days=7), self.end + timedelta(days=7)))
        self.assertEqual(ReplicateUnit.objects.get().booking, booking)

    def test_a_template_a_started_experiment_a_stale_version_and_no_day_0_are_refused(self):
        stale = self.trial.version
        self.place()
        self.assertEqual(self.refused(services.save_places, self.user, self.trial, [], stale, 'x'),
                         ['Someone else changed this experiment while you were editing it. The page now shows their '
                          'version; make your changes again.'])
        template = self.experiment('Template', is_template=True)
        self.assertEqual(self.refused(services.save_places, self.user, template, [], template.version, 'x'),
                         ['A template has no tanks: it is a design to copy.'])
        undated = self.experiment('Undated')
        self.assertEqual(self.refused(services.save_places, self.user, undated, [], undated.version, 'x'),
                         ['Set day 0 on the Details tab first: a tank is booked for days.'])
        Experiment.objects.filter(pk=self.trial.pk).update(
            status='running', hypothesis='h', primary_endpoint='bfcr')
        self.trial.refresh_from_db()
        self.assertEqual(self.refused(services.save_places, self.user, self.trial, [], self.trial.version, 'x'),
                         ['The experiment has started: its design is fixed. Copy it to change the design.'])


class RandomiseTests(PlacesTestCase):
    def pool(self, count=4):
        return list(self.tanks[:count])

    def randomise(self, pool=None, seed=20261103, trial=None):
        trial = trial or self.trial
        trial.refresh_from_db()
        return services.randomise(self.user, trial, self.pool() if pool is None else pool, seed, trial.version)

    def test_the_deal_is_stored_with_its_method_and_seed_and_is_the_fixed_vector(self):
        saved = self.randomise()
        self.assertEqual([(row[0], row[1]) for row in self.stored()],
                         [('Control R1', 'T-04'), ('Control R2', 'T-03'), ('Test R1', 'T-02'), ('Test R2', 'T-01')])
        self.assertEqual((saved.allocation_method, saved.allocation_seed, saved.allocation_note, saved.version),
                         ('sha256_v1', 20261103, '', 2))
        self.assertEqual({(row[2], row[3]) for row in self.stored()}, {(self.today, self.end)})
        entry = AuditLog.objects.get(action='update')
        self.assertEqual(entry.changes['Allocation'], [None, 'Randomised, seed 20261103'])
        self.assertEqual(entry.changes['Places'][0], None)

    def test_the_same_pool_and_seed_give_the_same_placements_and_a_new_seed_replaces_them(self):
        self.randomise()
        first = self.stored()
        self.randomise(pool=list(reversed(self.pool())))
        self.assertEqual(self.stored(), first)                      # the order of the pool does not matter
        self.assertEqual(AuditLog.objects.filter(action='update').count(), 1)       # and nothing changed
        self.randomise(seed=5)
        self.assertNotEqual(self.stored(), first)
        self.assertEqual(Experiment.objects.get(pk=self.trial.pk).allocation_seed, 5)
        self.assertEqual(ReplicateUnit.all_objects.count(), 4)

    def test_a_pool_item_that_is_a_system_gives_all_its_tanks_to_one_replicate(self):
        ras = System.objects.create(site=self.bergen, name='RAS 1', code='R1')
        type(self.t1).objects.filter(pk__in=[self.tanks[4].pk, self.tanks[5].pk]).update(system=ras)
        self.randomise(pool=[self.tanks[0], self.tanks[1], self.tanks[2], ras], seed=3)
        by_replicate = {}
        for label, code, *_days in self.stored():
            by_replicate.setdefault(label, []).append(code)
        self.assertEqual(sorted(len(codes) for codes in by_replicate.values()), [1, 1, 1, 2])
        self.assertIn(['T-05', 'T-06'], by_replicate.values())

    def test_the_pool_must_match_the_replicates_and_its_items_be_distinct_and_have_tanks(self):
        ras = System.objects.create(site=self.bergen, name='RAS 1', code='R1')
        empty = System.objects.create(site=self.bergen, name='Empty', code='R2')
        type(self.t1).objects.filter(pk=self.tanks[0].pk).update(system=ras)
        clash = System.objects.create(site=self.bergen, name='Same code', code='T-02')
        cases = [
            (self.pool(3), ['The pool has 3 items for 4 replicates: choose as many tanks or systems as there are '
                            'replicates.']),
            (self.pool(5), ['The pool has 5 items for 4 replicates: choose as many tanks or systems as there are '
                            'replicates.']),
            ([self.tanks[1], self.tanks[2], self.tanks[3], empty], ['R2 has no tank.']),
            ([self.tanks[0], ras, self.tanks[2], self.tanks[3]],
             ['T-01 is in the pool twice (alone and through a system).']),
            ([self.tanks[1], clash, self.tanks[2], self.tanks[3]], ['Two items of the pool have the code T-02.']),
        ]
        for pool, messages in cases:
            with self.subTest(messages=messages):
                self.assertEqual(self.refused(self.randomise, pool=pool), messages)
        self.assertEqual(self.refused(self.randomise, seed=-1), ['The seed is a whole number from 0 to 9223372036854775807.'])
        self.assertEqual(self.refused(self.randomise, seed='7'), ['The seed is a whole number from 0 to 9223372036854775807.'])
        self.assertEqual(self.stored(), [])

    def test_a_pool_tank_off_the_site_or_booked_elsewhere_is_refused_and_so_is_a_design_without_replicates(self):
        self.assertEqual(self.refused(self.randomise, pool=[self.tanks[0], self.tanks[1], self.tanks[2], self.p1]),
                         ['P-01 is not on the site of the experiment (Bergen).'])
        other = self.experiment('Other', starts_on=self.today)
        services.save_places(self.user, other, [services.Place(self.replicate(self.group(other, 'X'), 1),
                                                               [self.tanks[3]])], other.version, 'one tank')
        self.assertEqual(self.refused(self.randomise), [
            f'T-04 is booked by another experiment from {self.today.isoformat()} to {self.end.isoformat()}.'])
        empty = self.experiment('Empty', starts_on=self.today)
        self.assertEqual(self.refused(self.randomise, pool=[], trial=empty),
                         ['The design has no replicate to place tanks in.'])

    def test_a_template_and_a_started_experiment_are_not_dealt_to(self):
        template = self.experiment('Template', is_template=True)
        self.assertEqual(self.refused(self.randomise, pool=[], trial=template),
                         ['A template has no tanks: it is a design to copy.'])


class MoveSpanTests(PageTestCase):
    """A draft's day 0 or duration moves the placements that equalled the old span, through the Details form."""

    def setUp(self):
        super().setUp()
        self.create()
        self.trial = Experiment.objects.get()
        self.control, self.test = self.group(self.trial, 'Control', 'control'), self.group(self.trial, 'Test')
        self.slots = [self.replicate(self.control, 1), self.replicate(self.test, 1)]
        self.url = reverse('experiments:experiment_edit', args=[self.trial.pk])

    def post(self, **fields):
        self.trial.refresh_from_db()
        data = {**self.data(), 'version': str(self.trial.version), **fields}
        data.pop('entry_key')
        return self.client.post(self.url, data)

    def cells(self):
        return [(cell.unit.code, cell.first, cell.last) for cell in read.cells(self.trial)]

    def start_places(self):
        self.trial.refresh_from_db()
        services.save_places(self.user, self.trial, [services.Place(self.slots[0], [self.tanks[0]]),
                                                     services.Place(self.slots[1], [self.tanks[1]],
                                                                    self.day(7) + timedelta(days=7),
                                                                    self.day(7) + timedelta(days=40))],
                             self.trial.version, 'two tanks')

    def test_the_windows_that_equalled_the_span_follow_it_and_a_window_of_its_own_stays(self):
        self.start_places()
        start = self.day(7)
        self.assertEqual(self.cells(), [('T-01', start, start + timedelta(days=56)),
                                        ('T-02', start + timedelta(days=7), start + timedelta(days=40))])
        self.assertEqual(self.post(starts_on=self.today.isoformat(), duration_days='60').status_code, 302)
        self.assertEqual(self.cells(), [('T-01', self.today, self.today + timedelta(days=60)),
                                        ('T-02', start + timedelta(days=7), start + timedelta(days=40))])
        entry = AuditLog.objects.filter(entity_id=str(self.trial.pk), changes__has_key='Places').latest('created_at')
        self.assertEqual(list(entry.changes), ['Places'])
        self.assertIn(f'Control R1: T-01 ({self.today.isoformat()} to {(self.today + timedelta(days=60)).isoformat()})',
                      entry.changes['Places'][1])
        self.assertTrue(AuditLog.objects.filter(entity_id=str(self.trial.pk), changes__has_key='Starts on').exists())

    def test_a_change_of_something_else_moves_nothing(self):
        self.start_places()
        before = self.cells()
        self.post(name='Renamed', notes='x')
        self.assertEqual(self.cells(), before)

    def test_a_move_onto_days_another_experiment_holds_a_tank_is_refused_on_the_field(self):
        self.start_places()
        other = self.experiment('Other', starts_on=self.today)
        late = services.Place(self.replicate(self.group(other, 'X'), 1), [self.tanks[0]],
                              self.today + timedelta(days=50), self.today + timedelta(days=56))
        services.save_places(self.user, other, [late], other.version, 'one tank')      # after this one ends: free now
        response = self.post(starts_on=self.today.isoformat())         # T-01 would meet Other's days
        self.assertEqual(response.status_code, 200)
        held = [f'T-01 is booked by another experiment from {(self.today + timedelta(days=50)).isoformat()} to '
                f'{(self.today + timedelta(days=56)).isoformat()}.']
        self.assertEqual(response.context['form'].errors['starts_on'], held)
        response = self.post(duration_days='80')
        self.assertEqual(response.context['form'].errors['duration_days'], held)
        self.assertEqual(Experiment.objects.get(pk=self.trial.pk).starts_on, self.day(7))


class PlacesPageTests(PageTestCase):
    def setUp(self):
        super().setUp()
        self.create(starts_on=self.today.isoformat())
        self.trial = Experiment.objects.get()
        self.control, self.test = self.group(self.trial, 'Control', 'control'), self.group(self.trial, 'Test')
        self.slots = [self.replicate(self.control, 1), self.replicate(self.control, 2), self.replicate(self.test, 1),
                      self.replicate(self.test, 2)]
        self.url = reverse('experiments:experiment_places', args=[self.trial.pk])
        self.edit = reverse('experiments:experiment_edit', args=[self.trial.pk])

    def grid(self, rows, action='save', **extra):
        self.trial.refresh_from_db()
        data = {'version': str(self.trial.version), 'places-TOTAL_FORMS': str(len(rows)),
                'places-INITIAL_FORMS': '0', 'places-MIN_NUM_FORMS': '0', 'places-MAX_NUM_FORMS': '1000',
                'action': action, 'seed': '20261103', 'note': 'Tanks 1 to 4 stand in one row', **extra}
        for index, row in enumerate(rows):
            data.update({f'places-{index}-{key}': value for key, value in row.items()})
        return data

    def rows(self, tanks):
        return [{'replicate': str(replicate.pk), 'tanks': [str(tank.pk)]} for replicate, tank in zip(self.slots, tanks)]

    def test_the_tab_has_a_row_a_replicate_the_pool_a_seed_and_marks_the_tanks_booked_elsewhere(self):
        other = self.experiment('Other', starts_on=self.today)
        services.save_places(self.user, other, [services.Place(self.replicate(self.group(other, 'X'), 1),
                                                               [self.tanks[2]])], other.version, 'one tank')
        page = self.client.get(self.edit)
        self.assertContains(page, 'data-tab="places"')
        rows = page.context['places']
        self.assertEqual([row.label for row in rows], ['Control R1', 'Control R2', 'Test R1', 'Test R2'])
        self.assertContains(page, f'T-03 · Unit T-03 — booked {self.today.isoformat()} to '
                                  f'{(self.today + timedelta(days=56)).isoformat()}')
        self.assertNotContains(page, other.code)
        self.assertContains(page, 'disabled')
        self.assertTrue(page.context['places_form'].initial['seed'] in range(10 ** 9))
        self.assertEqual(page.context['places_form'].fields['pool'].widget.booked, {
            f'tank:{self.tanks[2].pk}': f'booked {self.today.isoformat()} to {(self.today + timedelta(days=56)).isoformat()}'})
        pool = [value for _group, options in page.context['places_form'].fields['pool'].choices
                for value, _label in options]
        self.assertEqual(pool[:3], [f'tank:{tank.pk}' for tank in self.tanks[:3]])

    def test_a_row_placed_by_hand_is_stored_and_the_banner_says_so(self):
        response = self.client.post(self.url, self.grid(self.rows(self.tanks[:4])))
        self.assertRedirects(response, self.edit, fetch_redirect_response=False)
        self.assertEqual([cell.unit.code for cell in read.cells(self.trial)], ['T-01', 'T-02', 'T-03', 'T-04'])
        page = self.client.get(self.edit)
        self.assertContains(page, 'Placed by hand: Tanks 1 to 4 stand in one row')
        self.assertEqual([row['tanks'].value() for row in page.context['places']],
                         [[self.tanks[0].pk], [self.tanks[1].pk], [self.tanks[2].pk], [self.tanks[3].pk]])

    def test_adding_a_system_places_its_tanks_and_a_row_may_give_its_own_days(self):
        ras = System.objects.create(site=self.bergen, name='RAS 1', code='R1')
        type(self.t1).objects.filter(pk__in=[self.tanks[4].pk, self.tanks[5].pk]).update(system=ras)
        rows = self.rows(self.tanks[:1])
        rows[0].update({'system': str(ras.pk), 'first': (self.today + timedelta(days=7)).isoformat(),
                        'last': (self.today + timedelta(days=21)).isoformat()})
        rows += [{'replicate': str(replicate.pk)} for replicate in self.slots[1:]]
        self.client.post(self.url, self.grid(rows))
        self.assertEqual([(cell.unit.code, cell.first, cell.last) for cell in read.cells(self.trial)],
                         [('T-01', self.today + timedelta(days=7), self.today + timedelta(days=21)),
                          ('T-05', self.today + timedelta(days=7), self.today + timedelta(days=21)),
                          ('T-06', self.today + timedelta(days=7), self.today + timedelta(days=21))])
        page = self.client.get(self.edit)
        self.assertEqual((page.context['places'].forms[0]['first'].value(), page.context['places'].forms[0]['last'].value()),
                         (self.today + timedelta(days=7), self.today + timedelta(days=21)))

    def test_randomise_deals_the_pool_and_the_banner_gives_the_seed(self):
        pool = [f'tank:{tank.pk}' for tank in self.tanks[:4]]
        response = self.client.post(self.url, self.grid([{'replicate': str(r.pk)} for r in self.slots],
                                                        action='randomise', pool=pool))
        self.assertRedirects(response, self.edit, fetch_redirect_response=False)
        self.assertEqual([cell.unit.code for cell in read.cells(self.trial)], ['T-04', 'T-03', 'T-02', 'T-01'])
        self.assertContains(self.client.get(self.edit), 'Randomised, seed 20261103.')

    def test_what_is_wrong_is_said_and_nothing_is_stored(self):
        pool = [f'tank:{tank.pk}' for tank in self.tanks[:3]]
        blank = [{'replicate': str(replicate.pk)} for replicate in self.slots]
        response = self.client.post(self.url, self.grid(blank, action='randomise', pool=pool))
        self.assertContains(response, 'The pool has 3 items for 4 replicates', status_code=422)
        response = self.client.post(self.url, self.grid(blank, action='randomise', pool=pool, seed=''))
        self.assertContains(response, 'Give the seed', status_code=422)
        response = self.client.post(self.url, self.grid(self.rows(self.tanks[:4]), note=''))
        self.assertContains(response, 'Say why the tanks are placed by hand', status_code=422)
        response = self.client.post(self.url, self.grid(self.rows(self.tanks[:4]), version='99'))
        self.assertContains(response, 'Someone else changed this experiment', status_code=422)
        rows = self.rows(self.tanks[:4])
        rows[0]['tanks'] = ['not-a-tank']
        response = self.client.post(self.url, self.grid(rows))
        self.assertEqual(response.status_code, 422)
        self.assertIn('tanks', response.context['places'].forms[0].errors)
        self.assertContains(response, 'data-has-errors', status_code=422)
        self.assertFalse(ReplicateUnit.objects.exists())

    def test_a_tank_booked_elsewhere_cannot_be_posted_either(self):
        other = self.experiment('Other', starts_on=self.today)
        services.save_places(self.user, other, [services.Place(self.replicate(self.group(other, 'X'), 1),
                                                               [self.tanks[0]])], other.version, 'one tank')
        response = self.client.post(self.url, self.grid(self.rows(self.tanks[:4])))
        self.assertContains(response, 'T-01 is booked by another experiment from', status_code=422)
        self.assertNotContains(response, other.code, status_code=422)

    def test_no_day_0_a_template_and_a_started_experiment_have_their_own_page(self):
        Experiment.objects.filter(pk=self.trial.pk).update(starts_on=None)
        self.assertContains(self.client.get(self.edit), 'Set day 0 on the Details tab first')
        Experiment.objects.filter(pk=self.trial.pk).update(starts_on=self.today)
        self.client.post(self.url, self.grid(self.rows(self.tanks[:4])))
        self.started(self.trial)
        page = self.client.get(self.edit)
        self.assertContains(page, 'The experiment has started: its tanks and days are fixed.')
        self.assertContains(page, 'T-04 · Unit T-04')
        self.assertNotContains(page, f'action="{self.url}"')
        template = self.experiment('Template', is_template=True)
        self.assertNotContains(self.client.get(reverse('experiments:experiment_edit', args=[template.pk])),
                               'data-tab="places"')

    def test_who_may_place_tanks(self):
        self.client.force_login(person('reader', 'view_experiment'))
        self.assertEqual(self.client.post(self.url, self.grid(self.rows(self.tanks[:4]))).status_code, 403)
        self.client.logout()
        self.assertIn('login', self.client.post(self.url, self.grid(self.rows(self.tanks[:4])))['Location'])
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.url).status_code, 302)


class ConcurrencyTests(TransactionTestCase):
    """Two experiments enrolling one tank at once: the tank's lock makes them take turns, so the second finds it booked
    and says to whom; exactly one wins."""

    serialized_rollback = True      # the rows migrations write (the equipment types) come back for later tests

    def setUp(self):
        from farm.models import ProductionDepartment, Site
        from farm.tests.helpers import make_species
        self.user = get_user_model().objects.create_user('ali', 'ali@example.com', 'x')
        self.user.groups.add(role('Researcher', *RESEARCHER))
        self.site = Site.objects.create(name='Bergen', code='BG')
        hall = ProductionDepartment.objects.create(site=self.site, name='Hall A', code='HA')
        self.tank = make_unit('T-01', hall)
        self.species = make_species()
        self.today = site_today(self.site)
        self.experiments = []
        for name in ('One', 'Two'):
            trial = Experiment.objects.create(code=f'E-2026-00{len(self.experiments) + 1}', name=name, site=self.site,
                                              species=self.species, duration_days=56, starts_on=self.today)
            group = trial.groups.create(name='A')
            self.experiments.append((trial, group.replicates.create(number=1)))

    def test_two_experiments_enrolling_one_tank_at_once_one_wins(self):
        results, gate = [], threading.Barrier(2)

        def enrol(trial, replicate):
            gate.wait()
            try:
                services.save_places(self.user, trial, [services.Place(replicate, [self.tank])], trial.version, 'by hand')
                results.append('ok')
            except ValidationError as error:
                results.append(error.messages[0])
            except IntegrityError:
                results.append('IntegrityError')
            finally:
                connection.close()

        threads = [threading.Thread(target=enrol, args=pair) for pair in self.experiments]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(result == 'ok' for result in results), [False, True])
        loser = next(result for result in results if result != 'ok')
        self.assertRegex(loser, r'^T-01 is booked by another experiment from \S+ to \S+\.$')
        self.assertEqual(ReplicateUnit.objects.count(), 1)
