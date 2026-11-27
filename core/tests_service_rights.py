"""The data-layering audit, L-6: every service that writes for a person asks who may itself (core.access.require, or the
area's own row rule as HR's and messaging's), so a caller that is not the page (a command, a worker, a future API or app)
cannot skip the right the page asks for.

The services are found, not listed: every `services.py` of the scanned packages and every module the layering guard
lets write (core/tests_data_access.py WRITE_PATHS and WRITES_ALLOWED), each public function that takes a parameter named
`user`. Each is called by an
active person with no right at all, with placeholders for the rest, and must refuse (PermissionDenied) before it reads its
arguments, so nothing is written. A function that is no write for a person (a question, a step inside a checked call, an
operator's command) is named in NOT_A_WRITER with why; a write whose rule rests on the row itself (one's own leave
request) in ROW_RULED; a module whose `user` is not the person acting in EXCLUDED."""
import importlib
import inspect

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import SimpleTestCase, TestCase

from farm.stock import services as stock

from . import tests_data_access as layering

# {module: why}: its functions' `user` is not the person who acts.
EXCLUDED = {
    'core.audit': "the activity log's writer: `user` is the person a checked write names",
    'core.accountmail': '`user` is the account mailed; the users tab and the sign-in pages check who acts',
}
# {dotted function: why}: no write for a person.
NOT_A_WRITER = {
    'farm.stock.services.voided': "the one void's shared step, called by the area's void inside its own checked call",
    'experiments.services.is_lead': 'a question (is this person the experiment\u2019s lead), no write',
    'tasks.services.is_for': 'a question (is the task for this person), no write',
    'tasks.services.may_work_on': 'a question (may this person work on the task), no write',
    'tasks.services.withdraw': "replan's step, inside replan's checked call",
    'hr.services.can_plan': 'a question (may this person plan shifts), no write',
    'hr.services.own_record': "a question (is it this person's own record), no write",
    'hr.services.can_decide': 'a question (may this person decide the request), no write',
    'hr.services.can_correct': 'a question (may this person correct the request), no write',
    'hr.services.can_cancel': 'a question (may this person cancel the request), no write',
    'hr.services.own_employee': "a question (this person's own employee record), no write",
    'messaging.services.contacts': 'a question (whom this person may write to), no write',
    'farm.handling.check.second_person_must_approve': 'a question (must a second person approve), no write',
    'farm.handling.check.require_acknowledged': "a check of the warnings the caller's form acknowledged, inside its "
                                                'checked write',
    'farm.handling.check.needs_second_person': 'a question (does this acknowledgement need a second person), no write',
    'core.softdelete.execute': "the delete plan's step, inside crud's checked delete (the tab's Delete right)",
    'core.softdelete.restore': "the delete plan's restore, inside the admin's checked restore",
    'farm.health.withdrawal.guarded': "the withdrawal guard around a checked write (the caller's right asked first)",
    'farm.health.withdrawal.guarded_ceiling': "the withdrawal guard around a checked write (the caller's right asked "
                                              'first)',
    'farm.health.withdrawal.guarded_units': "the withdrawal guard around a checked write (the caller's right asked "
                                            'first)',
    'farm.feeding.assignments.write': "the rows' write, inside a checked call: the assignment page's save, an "
                                      "experiment's start, release or replacement",
    'farm.feeding.assignments.end': "an experiment's release step, inside its checked call",
    'inventory.services.item_for': "a feed's store item made the first time it is needed, inside a checked receipt, "
                                   'count or reorder-level save',
    'core.language.account_language': "a question (the person's own language), no write",
    'core.language.save_account_language': "a person's own language on their own profile: everyone may set theirs",
    'farm.water.rederive.apply': "the operator's one-off repair (manage.py rederive_ph), logged as the person named or "
                                 'the system',
}
# {dotted function: why}: a write whose rule rests on the row.
ROW_RULED = {
    'hr.services.cancel_leave': 'a person cancels their own pending request with no right at all, a decider any they '
                                'may decide (hr.services.can_cancel, held by the HR leave tests)',
}


def modules():
    """The dotted names of every services.py of the scanned packages and of every module the guard lets write."""
    found = {path for path, _tree in layering.production_modules() if path.endswith('/services.py')}
    found |= set(layering.WRITE_PATHS) | set(layering.WRITES_ALLOWED)
    return sorted(name for name in (path[:-3].replace('/', '.') for path in found) if name not in EXCLUDED)


def writers():
    for name in modules():
        module = importlib.import_module(name)
        for attribute, function in inspect.getmembers(module, inspect.isfunction):
            if function.__module__ != module.__name__ or attribute.startswith('_'):
                continue
            parameters = inspect.signature(function).parameters
            if 'user' in parameters:
                yield f'{name}.{attribute}', function, parameters


class ServiceRightsTests(TestCase):
    def test_every_writer_refuses_who_holds_no_right(self):
        nobody = get_user_model().objects.create_user('nobody', 'nobody@example.com', 'x')
        found = set()
        for dotted, function, parameters in writers():
            found.add(dotted)
            if dotted in NOT_A_WRITER or dotted in ROW_RULED:
                continue
            arguments = {name: None for name, parameter in parameters.items()
                         if parameter.default is inspect.Parameter.empty
                         and parameter.kind in (parameter.POSITIONAL_OR_KEYWORD, parameter.KEYWORD_ONLY)}
            arguments['user'] = nobody
            with self.subTest(service=dotted), self.assertRaises(PermissionDenied):
                function(**arguments)
        gone = (set(NOT_A_WRITER) | set(ROW_RULED)) - found
        self.assertEqual(gone, set(), 'a named exception is gone: take it off its list')

    def test_an_inactive_account_is_refused_whatever_it_holds(self):
        retired = get_user_model().objects.create_superuser('retired', 'retired@example.com', 'x', is_active=False)
        with self.assertRaises(PermissionDenied):
            stock.void(retired, None, 'reason')


class DiscoveryTests(SimpleTestCase):
    def test_every_area_and_write_path_is_found(self):
        found = modules()
        for name in ('reports.services', 'experiments.services', 'farm.feeding.protocols', 'farm.feeding.assignments',
                     'farm.water.points', 'sensors.bindings', 'farm.stock.services', 'hr.services',
                     'messaging.services', 'alarms.services', 'knowledge.services', 'monitoring.services',
                     'farm.health.withdrawal', 'farm.water.rederive', 'sensors.alarms'):
            with self.subTest(module=name):
                self.assertIn(name, found)
        self.assertFalse(set(EXCLUDED) & set(found))

    def test_every_listed_exception_has_its_reason(self):
        for dotted, why in {**NOT_A_WRITER, **ROW_RULED, **EXCLUDED}.items():
            with self.subTest(name=dotted):
                self.assertTrue(why.strip())
