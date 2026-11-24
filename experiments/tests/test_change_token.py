"""The change token of a person from whom confidential work is hidden (core.audit.revision, monitoring's change_token):
it costs what it cost before confidentiality, whatever the number of experiments or of people, and it never reads the
seal (the works each activity-log entry was stamped with when it was written stand in for it); a change to a record of
work hidden from the person never moves it, and a grant, a share's end or an audience change that opens or closes
work to them does, even with no entry written."""
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from core import audit, sealing
from core.codes import next_code
from core.models import AuditLog
from farm.models import Batch, StockMovement, Tank
from farm.tests.helpers import point_of, stock_fish
from farm.tests.test_stock import make_unit
from farm.water import services as water_services
from monitoring import read
from tasks.models import Task, TaskNote

from ..models import Experiment, ExperimentGroup, ExperimentShare, Member, Replicate, ReplicateUnit
from . import world

CARDS = 'monitoring:cards'


def add_sealed(cls, number):
    """One more sealed experiment, led by the lead, on a tank of its own with fish in it."""
    tank = make_unit(f'EXTRA-{number}', cls.hall)
    began = cls.today - timedelta(days=world.BEGAN)
    experiment = Experiment.objects.create(code=next_code(Experiment, f'E-{cls.today.year}-'), name=f'Extra {number}',
                                           site=cls.site, species=cls.salmon, duration_days=world.DURATION,
                                           starts_on=began, hypothesis='h', primary_endpoint='bfcr', notes='n')
    group = ExperimentGroup.objects.create(experiment=experiment, name=f'G{number}')
    replicate = Replicate.objects.create(group=group, number=1)
    ReplicateUnit.objects.create(replicate=replicate, unit=tank, from_on=began,
                                 until_on=began + timedelta(days=world.DURATION))
    Experiment.objects.filter(pk=experiment.pk).update(status='running', allocation_method='manual', allocation_note='by hand')
    Member.objects.create(experiment=experiment, user=cls.lead, role='lead')
    stock_fish(cls.boss, tank, 300, '40', days_ago=world.BEGAN - 1, species=cls.salmon)
    return experiment


class TokenCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        world.build_open(cls)
        world.build_sealed(cls)
        cls.keeper = world.person('keeper', *world.area_perms(exclude_apps=('reports',)),
                                  'experiments.oversee_experiment')

    def token(self, user):
        """The token a person's screen would poll with (the grid of every unit), read as them."""
        with sealing.as_viewer(user), mock.patch.object(read, 'TOKEN_BUCKET', 10 ** 9):
            return read.change_token(user, '')

    def hidden_write(self):
        """A water sample on X's tank, written through the service as anyone writes one (logged)."""
        water_services.record(self.lead, point=self.sealed_point, measured_at=timezone.now() - timedelta(minutes=5),
                              source='manual', values={'ph': Decimal('7.0')})

    def poll(self, user, *more):
        """The queries of the grid's first fill and of its unchanged poll for `user`."""
        self.client.force_login(user)
        with mock.patch.object(read, 'TOKEN_BUCKET', 10 ** 9):
            self.client.get(reverse(CARDS))                                             # warm what loads once
            with CaptureQueriesContext(connection) as fill:
                first = self.client.get(reverse(CARDS))
            with CaptureQueriesContext(connection) as unchanged:
                second = self.client.get(first['X-Poll-Next'])
        self.assertEqual((first.status_code, second.status_code), (200, 204))
        return list(fill), list(unchanged)


class CostTests(TokenCase):
    def test_the_poll_costs_the_same_whatever_the_experiments_and_the_people(self):
        people = {'outsider': self.researcher, 'lead': self.lead, 'overseer': self.keeper, 'admin': self.boss}
        before = {name: [len(each) for each in self.poll(user)] for name, user in people.items()}
        for number in range(3):
            add_sealed(type(self), number)
        after = {name: [len(each) for each in self.poll(user)] for name, user in people.items()}
        self.assertEqual(after, before)
        # Against the token as it was before confidentiality (nothing hidden, nothing read of the person): one query
        # more, what the person reads (one statement), for the fill and the unchanged poll alike, for everyone.
        with mock.patch.object(sealing, 'reach', return_value=sealing.SEES_ALL):
            plain = {name: [len(each) for each in self.poll(user)] for name, user in people.items()}
        self.assertEqual(after, {name: [fill + 1, unchanged + 1] for name, (fill, unchanged) in plain.items()})

    def test_the_token_never_reads_the_seal(self):
        for user in (self.researcher, self.lead, self.keeper, self.boss):
            with self.subTest(user=user.username):
                _fill, unchanged = self.poll(user)
                for query in unchanged:
                    self.assertNotIn('experiment_cells', query['sql'])
                    if '"audit_log"' in query['sql']:
                        # the log is read plainly: no subquery of any seal, as before confidentiality
                        self.assertEqual(query['sql'].count('SELECT'), 1, query['sql'][:300])

    def test_a_system_read_compiles_to_plain_sql(self):
        with sealing.system('test: the plain statement'):
            for model in (Tank, StockMovement, Batch, Task, TaskNote, Experiment):
                with self.subTest(model=model.__name__):
                    text = str(model.objects.all().query)
                    self.assertNotIn('experiment_cells', text)
                    self.assertNotIn('EXISTS', text)
                    self.assertNotIn('experiment_members', text)


class MovesTests(TokenCase):
    def test_a_hidden_write_does_not_move_the_token_of_who_may_not_see_it(self):
        before = {user.username: self.token(user) for user in (self.researcher, self.staff, self.lead, self.keeper,
                                                                self.boss)}
        self.hidden_write()
        after = {user.username: self.token(user) for user in (self.researcher, self.staff, self.lead, self.keeper,
                                                               self.boss)}
        self.assertEqual(after['researcher'], before['researcher'])
        self.assertEqual(after['staff'], before['staff'])
        for name in ('lead', 'keeper', 'root'):                     # the team, Oversee (a farm fact), the admin (sealed)
            self.assertNotEqual(after[name], before[name], name)

    def test_the_poll_of_who_may_not_see_it_stays_204(self):
        self.client.force_login(self.researcher)
        with mock.patch.object(read, 'TOKEN_BUCKET', 10 ** 9):
            following = self.client.get(reverse(CARDS))['X-Poll-Next']
            self.hidden_write()
            self.assertEqual(self.client.get(following).status_code, 204)
            self.client.force_login(self.lead)
            following = self.client.get(reverse(CARDS))['X-Poll-Next']
            water_services.record(self.lead, point=self.sealed_point, measured_at=timezone.now() - timedelta(minutes=4),
                                  source='manual', values={'ph': Decimal('7.1')})
            self.assertEqual(self.client.get(following).status_code, 200)

    def test_a_grant_moves_the_grantees_token_and_no_one_elses(self):
        before = (self.token(self.researcher), self.token(self.staff))
        ExperimentShare.objects.create(experiment=self.experiment, user=self.researcher, part='water',
                                       valid_until=timezone.now() + timedelta(days=30), reason='test')
        self.assertNotEqual(self.token(self.researcher), before[0])
        self.assertEqual(self.token(self.staff), before[1])

    def test_a_shares_end_moves_the_token_with_no_entry_written(self):
        share = ExperimentShare.objects.create(experiment=self.experiment, user=self.researcher, part='water',
                                               valid_until=timezone.now() + timedelta(days=30), reason='test')
        granted = self.token(self.researcher)
        rows = AuditLog.objects.count()
        ExperimentShare.objects.filter(pk=share.pk).update(valid_until=timezone.now() - timedelta(seconds=1))
        self.assertEqual(AuditLog.objects.count(), rows)
        self.assertNotEqual(self.token(self.researcher), granted)

    def test_an_audience_change_moves_the_token_of_whom_it_opens_or_closes_to(self):
        before = {user.username: self.token(user) for user in (self.researcher, self.lead, self.boss)}
        Experiment._base_manager.filter(pk=self.experiment.pk).update(audience=Experiment.Audience.PRIVATE)
        private = {user.username: self.token(user) for user in (self.researcher, self.lead, self.boss)}
        self.assertNotEqual(private['root'], before['root'])            # closed to the platform admin
        self.assertEqual(private['researcher'], before['researcher'])   # hidden from them before and after
        self.assertEqual(private['lead'], before['lead'])               # theirs before and after
        Experiment._base_manager.filter(pk=self.experiment.pk).update(audience=Experiment.Audience.OPEN)
        self.assertNotEqual(self.token(self.researcher), private['researcher'])   # opened to everyone

    def test_a_new_sealed_experiment_elsewhere_moves_no_outsiders_token(self):
        before = self.token(self.staff)
        add_sealed(type(self), 7)
        self.assertEqual(self.token(self.staff), before)


class StampTests(TokenCase):
    def test_an_entry_is_stamped_with_every_work_whose_seal_hides_its_record(self):
        """works_of read the other way round is never less than the seal: every record of X and on its cells that the
        outsider may not see is stamped with X (a TaskNote through its task, a batch through its movements)."""
        experiment = str(self.experiment.pk)
        for label, pks in world.sealed_ids(type(self)).items():
            from django.apps import apps
            model = apps.get_model(label)
            seal = sealing.seal_of(model)
            if seal is None or not seal.filters:
                continue
            with sealing.as_viewer(self.researcher):
                shown = {str(pk) for pk in model.objects.filter(pk__in=pks).values_list('pk', flat=True)}
            works = sealing.works_of(model, pks)
            for pk in pks:
                with self.subTest(model=label, pk=pk):
                    if str(pk) not in shown:
                        self.assertIn(experiment, works[str(pk)])

    def test_the_log_stamps_what_it_writes_and_nothing_else(self):
        entry = audit.record(self.lead, AuditLog.Action.UPDATE, self.task_note)
        self.assertEqual(entry.works, [str(self.experiment.pk)])
        entry.refresh_from_db()
        self.assertEqual(entry.works, [str(self.experiment.pk)])
        self.assertEqual(audit.record(self.lead, AuditLog.Action.UPDATE, self.open_tank).works, [])
        self.assertEqual(audit.record(self.lead, AuditLog.Action.UPDATE, self.site).works, [])
        many = [audit.entry(None, AuditLog.Action.CREATE, self.alarm), audit.entry(None, AuditLog.Action.CREATE,
                                                                                 self.open_tank)]
        AuditLog.objects.bulk_create(many)
        self.assertEqual([row.works for row in many], [[str(self.experiment.pk)], []])

    def test_a_record_that_is_gone_is_stamped_unknown_and_an_open_one_with_nothing(self):
        gone = str(uuid.uuid4())
        self.assertEqual(sealing.works_of(Tank, [str(self.open_tank.pk), gone]),
                         {str(self.open_tank.pk): set(), gone: {sealing.UNKNOWN}})
        open_point = point_of(self.open_tank)
        self.assertEqual(sealing.works_of(type(open_point), [self.sealed_point.pk, open_point.pk]),
                         {str(self.sealed_point.pk): {str(self.experiment.pk)}, str(open_point.pk): set()})
