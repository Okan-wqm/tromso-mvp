"""Every route of the project, swept: a page that forgot its permission check fails here the day it is added.

A signed-in person with no role must be refused (403) by every page, or told the record is not there (404) by a page
that takes a record, unless the page is in one of the two short lists below, each with its reason: the pages open to
everyone (signing in, resetting a password) and the pages open to every signed-in person (their own account, the
overviews that show only the tiles a person's roles allow). Someone not signed in is sent to sign in everywhere else.
The admin has its own gate (staff only)."""
import uuid
from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import URLResolver, get_resolver
from django.urls.converters import IntConverter, SlugConverter, UUIDConverter

# Open to everyone, signed in or not.
PUBLIC = {
    'login': 'signing in',
    'password_reset': 'asking for a reset link',
    'password_reset_done': 'the "link sent" page',
    'password_reset_confirm': 'the link itself: its token is the check',
    'password_reset_complete': 'the "password set" page',
    'logout': 'signing out',
    'core:set_language': 'the language of the sign-in page too',
}

# Open to every signed-in person. Each shows only what the person's roles allow, or is the person's own account.
SIGNED_IN = {
    'home': 'the company overview: a tile for each area the roles allow (config/views.py)',
    'production_home': 'the production overview: a tile for each area the roles allow (config/views.py)',
    'sensors:home': 'the Sensors overview: a tile for each part the roles allow (sensors/views.py home, state_tiles)',
    'password_change': "the person's own password",
    'password_change_done': "the person's own password",
}

# An argument no record has: a page that looks a record up answers 404 for it, one that asks for a permission first
# answers 403.
SAMPLE = {IntConverter: '987654321', UUIDConverter: str(uuid.UUID(int=0xFEED)), SlugConverter: 'x'}


@dataclass(frozen=True)
class Route:
    name: str                   # 'farm:stock_mortality' ('' when the route has no name)
    pattern: str                # 'operations/units/<uuid:pk>/mortality/'
    path: str                   # the pattern with a sample for every argument
    takes_record: bool

    def __str__(self):
        return f'{self.name or "(no name)"} {self.pattern}'


def _sample(pattern, converters):
    path, rest = '', pattern
    while '<' in rest:
        before, _, rest = rest.partition('<')
        inner, _, rest = rest.partition('>')
        path += before + SAMPLE.get(type(converters[inner.split(':')[-1]]), 'x')
    return '/' + path + rest


def routes(patterns=None, prefix='', namespace=''):
    """Every route of the project but the admin's, in the order Django tries them."""
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
        name = f'{namespace}:{item.name}' if namespace and item.name else (item.name or '')
        found.append(Route(name, pattern, _sample(pattern, converters), bool(converters)))
    return found


def reach(client, route):
    """The answer to a GET, or to a POST where the page takes only POST."""
    response = client.get(route.path)
    if response.status_code == 405:
        response = client.post(route.path)
    return response


class RouteSweepTests(TestCase):
    def test_the_sweep_sees_the_project(self):
        names = {route.name for route in routes()}
        self.assertGreater(len(names), 300)
        for name in ('farm:site_list', 'hr:punch', 'core:database_export', 'messaging:post', 'sensors:live'):
            self.assertIn(name, names)

    def test_the_lists_name_real_routes(self):
        names = {route.name for route in routes()}
        self.assertEqual(set(PUBLIC) - names, set())
        self.assertEqual(set(SIGNED_IN) - names, set())

    def test_every_route_has_a_name(self):
        self.assertEqual([str(route) for route in routes() if not route.name], [])

    def test_someone_not_signed_in_is_sent_to_sign_in(self):
        open_ = []
        for route in routes():
            if route.name in PUBLIC:
                continue
            response = reach(self.client, route)
            if response.status_code != 302 or not response['Location'].startswith('/accounts/login/'):
                open_.append(f'{route} -> {response.status_code}')
        self.assertEqual(open_, [])

    def test_a_signed_in_person_with_no_role_is_refused_everywhere_else(self):
        person = get_user_model().objects.create_user('norole', 'norole@example.com', 'x')
        self.client.force_login(person)
        open_ = []
        for route in routes():
            if route.name in PUBLIC or route.name in SIGNED_IN:
                continue
            status = reach(self.client, route).status_code
            refused = status == 403 or (status == 404 and route.takes_record)
            if not refused:
                open_.append(f'{route} -> {status}')
        self.assertEqual(open_, [], 'a page without a permission check: give it one, or name it in SIGNED_IN with why')

    def test_the_admin_is_for_staff_only(self):
        person = get_user_model().objects.create_user('norole', 'norole@example.com', 'x')
        self.client.force_login(person)
        response = self.client.get('/admin/')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response['Location'].startswith('/admin/login/'))
