"""A sealed experiment does not exist for the people who may not see it: the route walk.

Every route of the project (its URL patterns, the admin's aside), every method a page answers, as people who are not in
X's team and hold no share of it: HR, an unrelated researcher, a student, staff who may read every farm page. Each route
that takes a record is tried with the id of every record of X and on its cells (world.sealed_ids) and with an id no
record has: the two answers are the same, and neither carries the canary. Each list is read plain and with every filter
set to a sealed record and a search for the canary. A POST to a sealed record changes nothing and writes no log row.

The non-interference test reads every list as an outsider before X exists (world B) and after (world A): the pages are
the same, so nothing on them (a count, a total, a choice, a tile) tells that X is there."""
import re
import uuid
from dataclasses import dataclass
from functools import cache
from itertools import product

from django.test import Client, TestCase
from django.urls import URLResolver, get_resolver
from django.urls.converters import IntConverter, UUIDConverter

from core.crud import Resource
from core.models import AuditLog

from . import world

RANDOM_UUID = str(uuid.UUID(int=0xFEED))
RANDOM_INT = '987654321'
# Query parameters the lists filter by: each is set to a sealed record of the kind it names.
FILTERS = {'unit': 'farm.Tank', 'tank': 'farm.Tank', 'units': 'farm.Tank', 'system': 'farm.System',
           'point': 'farm.SamplingPoint', 'batch': 'farm.Batch', 'channel': 'sensors.Channel',
           'experiment': 'experiments.Experiment', 'task': 'tasks.Task', 'event': 'farm.HealthEvent',
           'treatment': 'farm.Treatment', 'loaded': 'farm.Tank'}
# Arguments that name a record of another kind than the route's tab (an experiment's placement).
ARGUMENTS = {'placement': 'experiments.ReplicateUnit'}
# The record the `pk` of a route outside a tab names. A route in neither list is tried with every sealed record.
ROUTE_RECORDS = {
    **{f'farm:stock_{kind}': 'farm.Tank' for kind in ('mortality', 'weighing', 'transfer', 'grading', 'cull', 'harvest',
                                                      'delivery', 'escape')},
    'farm:stock_void': 'farm.StockOperation', 'farm:stock_batch': 'farm.Batch', 'farm:feeding_record': 'farm.Tank',
    'farm:feeding_void': 'farm.FeedingRecord', 'farm:water_unit_chart': 'farm.Tank',
    'farm:water_system_chart': 'farm.System', 'farm:water_void': 'farm.WaterMeasurement',
    'farm:treatment_last_day': 'farm.Treatment', 'farm:treatment_void': 'farm.Treatment',
    'farm:healthevent_void': 'farm.HealthEvent', 'farm:lice_void': 'farm.LiceCount',
    **{f'tasks:task_{verb}': 'tasks.Task' for verb in ('start', 'complete', 'cancel', 'reopen', 'tick', 'note')},
    # Records X has none of: a document, a conversation, the store, a report, a person's leave and punch, a credential,
    # an alarm event, a dead letter, a table of the database viewer (the platform admin's only).
    **{name: None for name in (
        'password_reset_confirm', 'knowledge:document_file', 'knowledge:document_text', 'knowledge:entry_review',
        'messaging:conversation', 'messaging:post', 'messaging:poll', 'messaging:members', 'messaging:add_members',
        'messaging:remove_member', 'messaging:set_role', 'messaging:leave', 'messaging:delete_message', 'inventory:void',
        'inventory:item', 'inventory:lot', 'reports:report_submit', 'reports:report_correct', 'reports:report_export',
        'reports:report_print', 'reports:duty_undo', 'reports:due_reopen', 'hr:punch', 'hr:leaverequest_approve',
        'hr:leaverequest_reject', 'hr:leaverequest_cancel', 'hr:production_punch',
        'hr:production_leaverequest_approve', 'hr:production_leaverequest_reject', 'hr:production_leaverequest_cancel',
        'sensors:credential_rotate', 'sensors:alarm_event_acknowledge', 'sensors:dead_letter_resolve',
        'core:database_table', 'core:database_export')},
}
# The search typed into every list: the canary in lower case, so the box echoing it is not a finding while a record
# found by it (searches ignore case) is.
SEARCH = world.CANARY.lower()
CSRF = re.compile(rb'(csrfmiddlewaretoken" value="|csrftoken=|"csrfToken": ")[^"; ]+')


@dataclass(frozen=True)
class Route:
    name: str
    pattern: str
    converters: tuple      # (argument name, converter) in the order the pattern has them

    def path(self, values):
        path, rest, index = '', self.pattern, 0
        while '<' in rest:
            before, _, rest = rest.partition('<')
            _inner, _, rest = rest.partition('>')
            path += before + str(values[index])
            index += 1
        return '/' + path + rest


def routes(patterns=None, prefix='', namespace=''):
    """Every route of the project but the admin's."""
    found = []
    for item in get_resolver().url_patterns if patterns is None else patterns:
        if isinstance(item, URLResolver):
            if item.namespace == 'admin':
                continue
            inner = f'{namespace}:{item.namespace}' if namespace and item.namespace else item.namespace or namespace
            found += routes(item.url_patterns, prefix + str(item.pattern), inner)
            continue
        pattern = prefix + str(item.pattern)
        converters = getattr(item.pattern, 'converters', {})
        names = re.findall(r'<(?:[^:>]+:)?([^>]+)>', pattern)
        name = f'{namespace}:{item.name}' if namespace and item.name else (item.name or '')
        found.append(Route(name, pattern, tuple((arg, converters[arg]) for arg in names)))
    return found


@cache
def route_models():
    """{route name: model label} for the routes of a tab (core.crud.Resource), whose argument is one of its records."""
    found = {}
    for tab in Resource.registry:
        for route in tab.urls():
            if route.name:
                namespace = tab.namespace or tab.model._meta.app_label
                found[f'{namespace}:{route.name}'] = tab.model._meta.label
    return found


def content(response):
    """Everything the person receives: the body (a streamed one read out), the headers, a redirect's address."""
    body = b''.join(response.streaming_content) if response.streaming else response.content
    headers = '\n'.join(f'{key}: {value}' for key, value in response.headers.items()).encode()
    return body + b'\n' + headers


def normal(data, ids=()):
    """An answer with what differs between two renders of the same page taken out: the CSRF tokens, and the ids tried."""
    data = CSRF.sub(rb'\1-', data)
    for value in ids:
        data = data.replace(str(value).encode(), b'<id>')
    return data


class WalkCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        world.build_open(cls)
        world.build_sealed(cls)
        cls.sealed = world.sealed_ids(cls)

    def candidates(self, route, argument, converter):
        """The sealed ids a route's argument is tried with: the records of the kind it names (the route's own tab's for
        its `pk`), or any sealed record."""
        if argument in ARGUMENTS:
            model = ARGUMENTS[argument]
        elif route.name in ROUTE_RECORDS:
            model = ROUTE_RECORDS[route.name]
        else:
            model = route_models().get(route.name, '*')
        pools = list(self.sealed.values()) if model == '*' else [self.sealed.get(model, [])]
        wanted = int if isinstance(converter, IntConverter) else uuid.UUID if isinstance(converter, UUIDConverter) \
            else None
        if wanted is None:
            return []
        return [pk for pool in pools for pk in pool if isinstance(pk, wanted)]

    @staticmethod
    def random(converter):
        return RANDOM_INT if isinstance(converter, IntConverter) else RANDOM_UUID if isinstance(
            converter, UUIDConverter) else 'x'

    def answer(self, client, method, path, data=None):
        try:
            return getattr(client, method)(path, data or {})
        except Exception as error:    # a crash is a finding of its own: reported with the leaks
            return error

    def walk(self, user):
        """Every route as `user`: [finding]."""
        client = Client()
        client.force_login(user)
        findings = []
        logged = AuditLog.objects.count()
        for route in routes():
            if not route.converters:
                queries = ['', '?q=' + SEARCH + '&' + '&'.join(
                    f'{key}={self.sealed[label][0]}' for key, label in FILTERS.items() if label in self.sealed)]
                for query in queries:
                    response = self.answer(client, 'get', route.path(()) + query)
                    findings += self.check(route, 'GET' + query[:1], response)
                continue
            pools = [self.candidates(route, arg, converter) for arg, converter in route.converters]
            randoms = [self.random(converter) for _arg, converter in route.converters]
            if not any(pools):
                continue
            unknown = {method: self.answer(client, method, route.path(randoms)) for method in ('get', 'post')}
            for values in product(*[pool or [randoms[index]] for index, pool in enumerate(pools)]):
                for method in ('get', 'post'):
                    response = self.answer(client, method, route.path(values))
                    findings += self.check(route, method.upper(), response, unknown[method], values, randoms)
        if AuditLog.objects.count() != logged:
            findings.append(f'{user}: {AuditLog.objects.count() - logged} log rows written by the walk')
        return findings

    def check(self, route, method, response, unknown=None, values=(), randoms=()):
        if isinstance(response, Exception):
            return [f'{route.name} {method} {values}: crashed {type(response).__name__}: {response}'[:300]]
        found = []
        data = content(response)
        if world.CANARY.encode() in data:
            at = data.find(world.CANARY.encode())
            found.append(f'{route.name} {method} {response.status_code}: canary in '
                         f'…{data[max(0, at - 80):at + 40].decode(errors="replace")}…')
        if unknown is not None and not isinstance(unknown, Exception):
            same = (response.status_code == unknown.status_code
                    and normal(data, values) == normal(content(unknown), randoms))
            if not same:
                found.append(f'{route.name} {method}: a sealed id answers {response.status_code}, an unknown one '
                             f'{unknown.status_code} (or another page)')
        return found

    def assertWalkClean(self, user):
        findings = self.walk(user)
        self.assertEqual(findings[:60], [], f'{len(findings)} findings as {user}')


class RouteWalkTests(WalkCase):
    def test_hr(self):
        self.assertWalkClean(self.hr)

    def test_an_unrelated_researcher(self):
        self.assertWalkClean(self.researcher)

    def test_a_student(self):
        self.assertWalkClean(self.student)

    def test_staff_who_read_every_farm_page(self):
        self.assertWalkClean(self.staff)


class NonInterferenceTests(TestCase):
    """What an outsider reads on every list is the same before X exists and after."""

    def lists(self, user):
        client = Client()
        client.force_login(user)
        pages = {}
        for route in routes():
            if route.converters:
                continue
            try:
                response = client.get(route.path(()))
            except Exception as error:
                pages[route.name] = repr(error).encode()
                continue
            pages[route.name] = (response.status_code, normal(content(response)))
        return pages

    def test_every_list_reads_the_same_with_and_without_x(self):
        world.build_open(self)
        without = self.lists(self.researcher)
        world.build_sealed(self)
        with_x = self.lists(self.researcher)
        differ = sorted(name for name in without if without[name] != with_x.get(name))
        self.assertEqual(differ, [])
