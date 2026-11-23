"""What the seal costs (plan step 12): narrowing a read needs no query of its own, since what the person is granted is
read inside the statement that reads the rows (core.sealing.hidden). A sealed model's read is one statement, and the
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
        with sealing.as_viewer(self.researcher):
            with CaptureQueriesContext(connection) as captured:
                list(Tank.objects.values_list('pk', flat=True))
        self.assertEqual(len(captured), 1)

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
