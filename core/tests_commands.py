"""Every `manage.py` command of the project is in the README's table (Layout of the code, Management commands) under
its kind, and the kinds are what the code says: a command of made-up or development-only data (kind dev) is built on
core.management.devtool.DevCommand and refuses to run with DEBUG off unless forced; a product or build command is not
built on it; a command of the go-live stack's synthetic data (kind stack) is built on
core.management.stackproof.StackProofCommand and runs only on the database the stack marked. A new command fails here
until it is listed, so a demonstration seeder cannot be added as if it were the product's."""
import re
from importlib import import_module
from io import StringIO
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management import call_command, get_commands
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings

from core.management.devtool import DevCommand
from core.management.stackproof import MARK, StackProofCommand

ROOT = Path(settings.BASE_DIR)
KINDS = ('product', 'build', 'dev', 'stack')
ROW = re.compile(r'^\| `([a-z_]+)` \| ([a-z]+) \| ([a-z]+) \|')


def listed():
    """{command: (app, kind)} as the README's table says."""
    text = (ROOT / 'README.md').read_text(encoding='utf-8')
    section = text.split('\n### Management commands\n', 1)[1].split('\n## ', 1)[0]
    return {found[1]: (found[2], found[3]) for found in map(ROW.match, section.splitlines()) if found}


def ours():
    """{command: app} of the commands this project's own apps hold."""
    own = {config.name for config in apps.get_app_configs() if (ROOT / config.name).is_dir()}
    return {name: app for name, app in get_commands().items() if app in own}


def command(name, app):
    return import_module(f'{app}.management.commands.{name}').Command


class CommandTableTests(SimpleTestCase):
    def test_every_command_is_listed_under_its_app_and_a_kind_and_nothing_else_is(self):
        table, found = listed(), ours()
        self.assertEqual({name: app for name, (app, _kind) in table.items()}, found)
        self.assertEqual({kind for _app, kind in table.values()} - set(KINDS), set())
        self.assertGreaterEqual(len(found), 24)

    def test_a_dev_command_is_built_on_the_guard_and_no_other_command_is(self):
        for name, (app, kind) in listed().items():
            with self.subTest(command=name):
                self.assertEqual(issubclass(command(name, app), DevCommand), kind == 'dev')
                self.assertEqual(issubclass(command(name, app), StackProofCommand), kind == 'stack')


class DevCommandTests(SimpleTestCase):
    """The guard itself, on each dev command: with DEBUG off it stops before the command's own work (its own arguments
    are not even looked at), and says what it is and how to run it all the same."""

    def dev(self):
        return {name: command(name, app) for name, (app, kind) in listed().items() if kind == 'dev'}

    def test_with_debug_off_each_refuses_and_names_the_way_on(self):
        self.assertFalse(settings.DEBUG)                     # a test run is not a developer's database either
        for name, made in self.dev().items():
            with self.subTest(command=name), self.assertRaises(CommandError) as refused:
                made().execute(force=False, stdout=StringIO(), stderr=StringIO(), no_color=True, force_color=False,
                               skip_checks=True)
            said = str(refused.exception)
            self.assertIn(f'{name} is a development tool', said)
            self.assertIn('Give --force' if made.forcible else 'runs only with DEBUG on', said)

    def test_force_is_an_argument_of_those_that_can_be_forced_only(self):
        for name, made in self.dev().items():
            with self.subTest(command=name):
                options = {action.dest for action in made().create_parser('manage.py', name)._actions}
                self.assertEqual('force' in options, made.forcible)
        self.assertEqual([name for name, made in self.dev().items() if not made.forcible], ['seed_hr_demo'])

    def test_a_seeder_of_known_passwords_is_not_forced(self):
        with self.assertRaisesMessage(CommandError, 'runs only with DEBUG on'):
            command('seed_hr_demo', 'hr')().execute(force=True, stdout=StringIO(), stderr=StringIO(), no_color=True,
                                                    force_color=False, skip_checks=True)

    databases = {'default'}           # the guard's second fact is the database role's (L-15)

    def test_with_debug_on_a_role_that_is_no_superuser_is_refused_too(self):
        """The data-layering audit, L-15: DEBUG defaults on, so it is not proof enough of a developer's database. A
        developer's and a test run's database role is a superuser; the server's roles are not (the app and the owner
        role of the go-live roles), so a dev tool on a server whose DEBUG was left on is still refused, unless forced."""
        from unittest import mock

        from core.management import devtool
        self.assertTrue(devtool.superuser())                   # the test database's role, as a developer's
        with override_settings(DEBUG=True), mock.patch.object(devtool, 'superuser', return_value=False):
            with self.assertRaisesMessage(CommandError, 'is not a superuser'):
                command('sensors_demo_setup', 'sensors')().execute(force=False, stdout=StringIO(), stderr=StringIO(),
                                                                   no_color=True, force_color=False, skip_checks=True)

    def test_with_debug_on_the_guard_lets_the_command_do_its_own_refusing(self):
        with override_settings(DEBUG=True), self.assertRaisesMessage(CommandError, 'Say what to do'):
            call_command('sensors_demo_setup', stdout=StringIO())

    def test_seed_hr_demo_is_refused_on_a_servers_role_with_debug_on(self):
        """The production stack's case, on a real role and no stand-in: DEBUG left on, the role no superuser (as a
        farm's app and owner roles are), the seeder of known passwords is refused before it writes (deploy/ci/stack.sh,
        step data, proves the same on the production stack's own app role)."""
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute('SET ROLE pg_monitor')            # a role that is no superuser, for this session only
        try:
            with override_settings(DEBUG=True), self.assertRaisesMessage(CommandError, 'is not a superuser'):
                command('seed_hr_demo', 'hr')().execute(force=True, stdout=StringIO(), stderr=StringIO(), no_color=True,
                                                        force_color=False, skip_checks=True)
        finally:
            with connection.cursor() as cursor:
                cursor.execute('RESET ROLE')


def mark_database(text=MARK):
    """The test database's comment set to `text` for the running test's transaction (a TestCase rolls it back), as
    deploy/ci/stack.sh marks the stack's database."""
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute('SELECT current_database()')
        name = cursor.fetchone()[0]
        cursor.execute(f'COMMENT ON DATABASE {connection.ops.quote_name(name)} IS %s', [text])


class StackProofCommandTests(TestCase):
    """The go-live stack's commands (core/management/stackproof.py): refused on every database without the stack's mark,
    a developer's (DEBUG on, a superuser) and a farm's alike; run on the marked one. What seed_stack_proof writes is
    hr/tests/test_hardening.py's (StackSeedTests)."""

    def stack(self):
        return {name: command(name, app) for name, (app, kind) in listed().items() if kind == 'stack'}

    def test_there_is_one_and_it_is_not_a_dev_tool(self):
        self.assertEqual(list(self.stack()), ['seed_stack_proof'])
        self.assertFalse(issubclass(command('seed_stack_proof', 'hr'), DevCommand))
        self.assertNotIn('force', {action.dest for action in command('seed_stack_proof', 'hr')().create_parser(
            'manage.py', 'seed_stack_proof')._actions})

    @override_settings(DEBUG=True)
    def test_unmarked_or_marked_otherwise_each_refuses_before_its_own_work(self):
        from core.management import devtool, stackproof
        self.assertTrue(devtool.superuser())                   # a developer's database: refused all the same
        for text in (None, '', MARK + ' ', MARK.upper(), 'balik go-live stack proof'):
            if text is not None:
                mark_database(text)
            self.assertFalse(stackproof.marked(), text)
            for name, made in self.stack().items():
                with self.subTest(command=name, mark=text), self.assertRaises(CommandError) as refused:
                    made().execute(by='nobody', stdout=StringIO(), stderr=StringIO(), no_color=True, force_color=False,
                                   skip_checks=True)
                said = str(refused.exception)
                self.assertIn(f"{name} is a command of the go-live stack's proof", said)
                self.assertIn("does not carry the stack's mark", said)

    def test_marked_it_runs(self):
        from core.management import stackproof
        mark_database()
        self.assertTrue(stackproof.marked())
        with self.assertRaisesMessage(CommandError, "No active account is named 'nobody'"):   # its own work began
            call_command('seed_stack_proof', by='nobody', stdout=StringIO())
