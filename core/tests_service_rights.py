"""The data-layering audit, L-6: the farm's services (stock, feeding, water, health), the store's and the tasks' ask who may
themselves (core.access.require), as messaging's and HR's do, so a caller that is not the page (a command, a worker, a
future API or app) cannot skip the right the page asks for. Every public function of these modules that takes the person
first is called by an active person with no right at all, with placeholders for the rest: each must refuse
(PermissionDenied) before it reads its arguments, so nothing is written. A function that is no write for a person is
named in NOT_A_WRITER with why."""
import inspect

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TestCase

from farm.feeding import services as feeding
from farm.health import services as health
from farm.stock import services as stock
from farm.water import services as water
from inventory import services as inventory
from tasks import services as tasks

MODULES = (stock, feeding, water, health, inventory, tasks)
NOT_A_WRITER = {
    'farm.stock.services.voided': "the one void's shared step, called by the area's void inside its own checked call",
    'tasks.services.is_for': 'a question (is the task for this person), no write',
    'tasks.services.may_work_on': 'a question (may this person work on the task), no write',
    'tasks.services.withdraw': "replan's step, inside replan's checked call",
}


def writers():
    for module in MODULES:
        for name, function in inspect.getmembers(module, inspect.isfunction):
            if function.__module__ != module.__name__ or name.startswith('_'):
                continue
            parameters = list(inspect.signature(function).parameters.values())
            if not parameters or parameters[0].name != 'user':
                continue
            yield f'{module.__name__}.{name}', function, parameters[1:]


class ServiceRightsTests(TestCase):
    def test_every_writer_refuses_who_holds_no_right(self):
        nobody = get_user_model().objects.create_user('nobody', 'nobody@example.com', 'x')
        found = set()
        for dotted, function, rest in writers():
            found.add(dotted)
            if dotted in NOT_A_WRITER:
                continue
            placeholders = {parameter.name: None for parameter in rest
                            if parameter.default is inspect.Parameter.empty
                            and parameter.kind in (parameter.POSITIONAL_OR_KEYWORD, parameter.KEYWORD_ONLY)}
            with self.subTest(service=dotted), self.assertRaises(PermissionDenied):
                function(nobody, **placeholders)
        self.assertEqual(set(NOT_A_WRITER) - found, set(), 'a named exception is gone: take it off NOT_A_WRITER')

    def test_an_inactive_account_is_refused_whatever_it_holds(self):
        retired = get_user_model().objects.create_superuser('retired', 'retired@example.com', 'x', is_active=False)
        with self.assertRaises(PermissionDenied):
            stock.void(retired, None, 'reason')
