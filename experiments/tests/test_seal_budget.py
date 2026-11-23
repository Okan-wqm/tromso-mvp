"""What the seal costs (plan step 12): narrowing a read needs no query of its own, since what the person is granted is
read inside the statement that reads the rows (core.sealing.hidden). So an outsider reads every list in as many queries
with a sealed experiment on the farm as without it."""
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext

from core import sealing
from farm.models import Tank

from . import world
from .test_confidential import routes


def queries(user, path):
    client = Client()
    client.force_login(user)
    client.get(path)                                     # the first visit fills what a session keeps
    with CaptureQueriesContext(connection) as captured:
        try:
            client.get(path)
        except Exception as error:                       # the route walk reports a crash; here it costs nothing
            return repr(error)
    return len(captured)


class SealBudgetTests(TestCase):
    def test_an_outsider_reads_every_list_in_as_many_queries_with_x_as_without(self):
        world.build_open(self)
        paths = {route.name: route.path(()) for route in routes() if not route.converters}
        without = {name: queries(self.researcher, path) for name, path in paths.items()}
        world.build_sealed(self)
        with_x = {name: queries(self.researcher, path) for name, path in paths.items()}
        differ = {name: (without[name], with_x[name]) for name in paths if without[name] != with_x[name]}
        self.assertEqual(differ, {})

    def test_a_sealed_read_costs_no_query_of_its_own(self):
        world.build_open(self)
        world.build_sealed(self)
        with sealing.as_viewer(self.researcher):
            with CaptureQueriesContext(connection) as captured:
                list(Tank.objects.values_list('pk', flat=True))
        self.assertEqual(len(captured), 1)
