"""Every `manage.py` command of the project is in the README's table (Layout of the code, Management commands) under
its kind, and the kinds are what the code says: a command of made-up or development-only data (kind dev) is built on
core.management.devtool.DevCommand and refuses to run with DEBUG off unless forced; a product or build command is not
built on it. A new command fails here until it is listed, so a demonstration seeder cannot be added as if it were the
product's."""
import re
from importlib import import_module
from io import StringIO
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management import call_command, get_commands
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from core.management.devtool import DevCommand

ROOT = Path(settings.BASE_DIR)
KINDS = ('product', 'build', 'dev')
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

    def test_with_debug_on_the_guard_lets_the_command_do_its_own_refusing(self):
        with override_settings(DEBUG=True), self.assertRaisesMessage(CommandError, 'Say what to do'):
            call_command('sensors_demo_setup', stdout=StringIO())
