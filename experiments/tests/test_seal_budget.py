"""What the seal costs (plan step 12): what the person may not read is read once per request (their Reach, one
statement), and written into each sealed read when it is compiled (core.sealing.Sealed): nothing at all for a person
from whom nothing is hidden or, for a farm fact, who holds Oversee. A sealed model's read is one statement, and the
farm's pages never load the viewer (the query that reads a person's teams and shares), which only an experiment's own
pages and the read log ask for. (A figure read as the system, a withdrawal or a stock fold, counts every unit, so its
queries follow the farm's records, sealed or not: they are not the seal's cost.)"""
from unittest import mock

from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext

from core import sealing
from farm.models import Tank

from .. import sealing as provider
from . import world
from .test_confidential import routes

PAGES = ('farm:production_units', 'farm:productionplan_list', 'monitoring:cards', 'monitoring:monitor',
         'sensors:binding_list', 'tasks:task_list')


class SealBudgetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        world.build_open(cls)
        world.build_sealed(cls)

    def test_a_sealed_read_costs_no_query_of_its_own(self):
        """What the person may not read is read once (their Reach, one statement); every sealed read after it is one.
        (Their rights, which Oversee is read from, Django loads once a request for any page: loaded first here.)"""
        self.researcher.has_perm('experiments.oversee_experiment')
        with sealing.as_viewer(self.researcher):
            with CaptureQueriesContext(connection) as captured:
                for _read in range(3):
                    list(Tank.objects.values_list('pk', flat=True))
        self.assertEqual(len(captured), 1 + 3)

    def test_the_seal_is_built_only_for_a_read_that_needs_it(self):
        """The seal's condition (its parents' and children's managers, each with theirs) is built when a statement is
        compiled for a person from whom something is hidden, never when a manager is touched (core.sealing.HiddenRows):
        not for the system, not for the lead of the only sealed experiment."""
        with mock.patch.object(sealing, 'hidden', wraps=sealing.hidden) as built:
            list(Tank.objects.values_list('pk', flat=True))
            with sealing.as_viewer(self.lead):
                list(Tank.objects.values_list('pk', flat=True))
            self.assertEqual(built.call_count, 0)
            with sealing.as_viewer(self.researcher):
                list(Tank.objects.values_list('pk', flat=True))
            self.assertGreater(built.call_count, 0)

    def test_a_person_from_whom_nothing_is_hidden_reads_without_the_seal(self):
        """The lead reads X (its team): no work is hidden from them, so the seal adds nothing to their statement; an
        outsider's carries X's id written in, never the grant subqueries."""
        with sealing.as_viewer(self.lead):
            lead = str(Tank.objects.values_list('pk', flat=True).query)
        with sealing.as_viewer(self.researcher):
            outsider = str(Tank.objects.values_list('pk', flat=True).query)
        self.assertNotIn('experiment_cells', lead)
        self.assertNotIn('experiment_members', lead)
        self.assertIn('experiment_cells', outsider)
        self.assertIn(str(self.experiment.pk).replace('-', ''), outsider.replace('-', ''))
        self.assertNotIn('experiment_members', outsider)
        self.assertNotIn('experiment_shares', outsider)

    def test_an_overseer_reads_the_farm_facts_without_the_seal(self):
        keeper = world.person('keeper', 'farm.view_tank', 'experiments.oversee_experiment')
        with sealing.as_viewer(keeper):
            facts = str(Tank.objects.values_list('pk', flat=True).query)
            tanks = set(Tank.objects.values_list('pk', flat=True))
        self.assertNotIn('experiment_cells', facts)
        self.assertTrue({tank.pk for tank in self.sealed_tanks} <= tanks)

    def test_a_grant_made_or_ended_inside_one_request_narrows_the_next_read(self):
        """The Reach is kept for the request, and read again after a write that changes what the person reads: a share
        given (a save), a share ended (a queryset update), a team place (a bulk create, which sends no signal)."""
        from datetime import timedelta
        from django.utils import timezone
        from ..models import ExperimentShare, Member
        tank = self.sealed_tanks[0].pk
        with sealing.as_viewer(self.researcher):
            self.assertFalse(Tank.objects.filter(pk=tank).exists())
            share = ExperimentShare.objects.create(experiment=self.experiment, user=self.researcher, part='systems',
                                                   reason='Audit', valid_until=timezone.now() + timedelta(days=5))
            self.assertTrue(Tank.objects.filter(pk=tank).exists())
            ExperimentShare.objects.filter(pk=share.pk).update(revoked_at=timezone.now(), revoked_by=self.lead)
            self.assertFalse(Tank.objects.filter(pk=tank).exists())
            Member.objects.bulk_create([Member(experiment=self.experiment, user=self.researcher)])
            self.assertTrue(Tank.objects.filter(pk=tank).exists())

    def test_the_farms_pages_never_load_the_viewer(self):
        paths = {route.name: route.path(()) for route in routes() if route.name in PAGES}
        self.assertEqual(set(paths), set(PAGES))
        client = Client()
        client.force_login(self.researcher)
        with mock.patch.object(provider.Provider, 'load', wraps=provider.load) as load:
            for name, path in paths.items():
                with self.subTest(page=name):
                    self.assertEqual(client.get(path).status_code, 200)
        self.assertEqual(load.call_count, 0)
