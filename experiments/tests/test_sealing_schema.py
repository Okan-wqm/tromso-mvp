"""The confidentiality schema, against stored rows: who may read an experiment (its audience, its team's windows, its
shares), the whole-system bookings, the sealed cells, and what the database refuses whatever writes."""
from datetime import timedelta

from django.contrib.auth.models import Group
from django.db import connection
from django.utils import timezone

from farm.models import System, Tank

from ..models import Experiment, ExperimentShare, Member, ReplicateSystem, ReplicateUnit, SealedCell
from . import ExperimentTestCase


class SchemaCase(ExperimentTestCase):
    audience = None              # the database's default: sealed

    def setUp(self):
        super().setUp()
        self.loop = System.objects.create(site=self.bergen, production_department=self.hall, name='Loop', code='L1')
        Tank.objects.filter(pk__in=[self.tanks[2].pk, self.tanks[3].pk]).update(system=self.loop)
        self.trial = self.experiment(starts_on=self.today)
        self.group_a = self.group(self.trial)
        self.rep = self.replicate(self.group_a)

    def booking(self, replicate=None, system=None, first=0, last=56, **fields):
        return ReplicateSystem.objects.create(replicate=replicate or self.rep, system=system or self.loop,
                                              from_on=self.today + timedelta(days=first),
                                              until_on=self.today + timedelta(days=last), **fields)

    def start(self, trial=None):
        trial = trial or self.trial
        Experiment.objects.filter(pk=trial.pk).update(
            status='running', hypothesis='h', primary_endpoint='bfcr', allocation_method='manual',
            allocation_note='by hand')

    def share(self, **fields):
        values = {'experiment': self.trial, 'user': self.user, 'part': 'water', 'reason': 'Audit of the water',
                  'valid_until': timezone.now() + timedelta(days=30), **fields}
        return ExperimentShare.objects.create(**values)


class ExperimentColumnTests(SchemaCase):
    def test_a_new_experiment_is_sealed_with_no_approval(self):
        self.trial.refresh_from_db()
        self.assertEqual((self.trial.audience, self.trial.approval_ref, self.trial.approval_valid_until),
                         ('sealed', '', None))

    def test_the_checks(self):
        self.refuses(Experiment.objects.filter(pk=self.trial.pk).update, audience='public')
        self.refuses(Experiment.objects.filter(pk=self.trial.pk).update, approval_valid_until=self.today)
        Experiment.objects.filter(pk=self.trial.pk).update(approval_ref='FOTS 12345', approval_valid_until=self.today)

    def test_a_started_experiment_still_changes_its_audience_and_approval_never_its_design(self):
        self.start()
        Experiment.objects.filter(pk=self.trial.pk).update(audience='open', approval_ref='FOTS 1',
                                                           approval_valid_until=self.today)
        self.trial.refresh_from_db()
        self.assertEqual((self.trial.audience, self.trial.approval_ref), ('open', 'FOTS 1'))
        self.refuses(Experiment.objects.filter(pk=self.trial.pk).update, hypothesis='another')


class MemberTests(SchemaCase):
    def test_a_member_has_a_window_and_a_guest_role(self):
        now = timezone.now()
        member = Member.objects.create(experiment=self.trial, user=self.user, role='guest', valid_from=now,
                                       valid_until=now + timedelta(days=3))
        member.refresh_from_db()
        self.assertEqual((member.role, member.valid_from, member.valid_until), ('guest', now, now + timedelta(days=3)))

    def test_the_window_ends_after_it_begins(self):
        now = timezone.now()
        self.refuses(Member.objects.create, experiment=self.trial, user=self.user, valid_from=now, valid_until=now)
        self.refuses(Member.objects.create, experiment=self.trial, user=self.user, role='visitor')


class ShareTests(SchemaCase):
    def test_a_share_is_stored_with_every_column(self):
        share = self.share(created_by=self.user)
        share.refresh_from_db()
        self.assertEqual((share.experiment, share.user, share.group, share.part, share.reason, share.revoked_at,
                          share.created_by), (self.trial, self.user, None, 'water', 'Audit of the water', None, self.user))
        self.assertTrue(share.is_live())

    def test_the_checks(self):
        role = Group.objects.create(name='Auditors')
        later = timezone.now() + timedelta(days=1)
        self.refuses(self.share, group=role)                                     # a person and a role
        self.refuses(self.share, user=None)                                      # nobody
        self.refuses(self.share, part='all')
        self.refuses(self.share, valid_from=later, valid_until=later)            # ends as it begins
        self.refuses(self.share, valid_until=timezone.now() + timedelta(days=731))
        self.refuses(self.share, reason='')
        self.refuses(self.share, revoked_at=timezone.now())                      # revoked by nobody
        self.share(valid_until=timezone.now() + timedelta(days=730))

    def test_one_live_share_a_part_a_grantee_and_a_revoked_one_frees_it(self):
        first = self.share()
        self.refuses(self.share)
        ExperimentShare.objects.filter(pk=first.pk).update(revoked_at=timezone.now(), revoked_by=self.user)
        self.share()
        role = Group.objects.create(name='Auditors')
        self.share(user=None, group=role)
        self.refuses(self.share, user=None, group=role)


class BookingTests(SchemaCase):
    def test_a_booking_is_stored_and_a_system_is_in_one_experiment_at_a_time(self):
        booking = self.booking()
        booking.refresh_from_db()
        self.assertEqual((booking.replicate, booking.system, booking.from_on, booking.until_on),
                         (self.rep, self.loop, self.today, self.today + timedelta(days=56)))
        other = self.experiment(name='Other', starts_on=self.today)
        other_rep = self.replicate(self.group(other))
        self.refuses(self.booking, replicate=other_rep, first=50, last=60)
        self.refuses(self.booking, first=3, last=2)
        self.booking(replicate=other_rep, first=57, last=60)

    def test_its_placements_are_its_tanks_in_its_replicate_on_its_days(self):
        booking = self.booking(last=20)
        tank = self.tanks[2]
        self.placement(self.rep, tank, 0, 20, booking=booking)
        other_rep = self.replicate(self.group_a, 2)
        self.refuses(self.placement, other_rep, self.tanks[3], 0, 20, booking=booking)       # another replicate
        self.refuses(self.placement, self.rep, self.tanks[3], 0, 21, booking=booking)        # past its days
        self.refuses(self.placement, self.rep, self.tanks[4], 0, 20, booking=booking)        # not its system's

    def test_a_booking_is_not_shortened_past_its_placements(self):
        booking = self.booking(last=20)
        self.placement(self.rep, self.tanks[2], 0, 20, booking=booking)
        self.refuses(ReplicateSystem.objects.filter(pk=booking.pk).update, until_on=self.today + timedelta(days=10))

    def test_a_started_experiment_only_shortens_a_booking_and_never_deletes_it(self):
        booking = self.booking(last=20)
        self.start()
        ReplicateSystem.objects.filter(pk=booking.pk).update(until_on=self.today + timedelta(days=15))
        self.refuses(ReplicateSystem.objects.filter(pk=booking.pk).update, until_on=self.today + timedelta(days=30))
        self.refuses(ReplicateSystem.objects.filter(pk=booking.pk).delete)

    def test_no_tank_joins_or_leaves_a_booked_system_and_the_system_is_not_moved(self):
        self.booking()
        self.refuses(Tank.objects.filter(pk=self.tanks[2].pk).update, system=None)
        self.refuses(Tank.objects.filter(pk=self.tanks[4].pk).update, system=self.loop)
        outer = System.objects.create(site=self.bergen, name='Hall loop', code='HL')
        self.refuses(System.objects.filter(pk=self.loop.pk).update, parent=outer)
        free = System.objects.create(site=self.bergen, name='Free', code='FR')
        Tank.objects.filter(pk=self.tanks[4].pk).update(system=free)

    def test_a_past_booking_frees_the_system(self):
        self.booking(first=-30, last=-1)
        Tank.objects.filter(pk=self.tanks[2].pk).update(system=None)


class CellTests(SchemaCase):
    def test_the_cells_are_the_live_placements_and_bookings_of_sealed_experiments(self):
        booking = self.booking(last=20)
        placement = self.placement(self.rep, self.tanks[2], 0, 20, booking=booking)
        open_trial = self.experiment(name='Open', starts_on=self.today, audience='open')
        self.placement(self.replicate(self.group(open_trial)), self.tanks[5], 0, 10)
        deleted = self.placement(self.rep, self.tanks[6], 0, 10)
        ReplicateUnit.objects.filter(pk=deleted.pk).update(is_deleted=True)
        cells = sorted((str(cell.unit_id), str(cell.system_id), cell.from_on, cell.until_on, str(cell.work))
                       for cell in SealedCell.objects.all())
        end = self.today + timedelta(days=20)
        self.assertEqual(cells, sorted([
            (str(placement.unit_id), 'None', self.today, end, str(self.trial.pk)),
            ('None', str(self.loop.pk), self.today, end, str(self.trial.pk))]))

    def test_it_is_a_view(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT table_type FROM information_schema.tables WHERE table_name = 'experiment_cells'")
            self.assertEqual(cursor.fetchone(), ('VIEW',))
