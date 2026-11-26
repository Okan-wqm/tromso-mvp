"""The commands that are not the product's: a demonstration seeder, a benchmark, a repair of the development seed.
They live beside the product's commands in their apps (their tests, their README sections and the scripts that call
them name them there), and are told apart in one place: the table in README, Management commands, which
core/tests_commands.py holds against the code, and this base class, which every command of those kinds is built on.

A `DevCommand` writes made-up or development-only data into the database it is pointed at, so it refuses to run on a
server unless told twice (`--force`). DEBUG defaults on, so it is not proof enough of a developer's database (the
data-layering audit, L-15): a developer's machine and the scripts' and tests' throwaway databases run with DEBUG on
**and** as a database superuser, and a server runs with neither (its app and owner roles are no superusers: go-live's
database roles). Either fact missing refuses."""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


def superuser():
    """Whether the database role the command runs as is a superuser: a developer's or a test run's database."""
    with connection.cursor() as cursor:
        cursor.execute('SELECT rolsuper FROM pg_roles WHERE rolname = current_user')
        found = cursor.fetchone()
    return bool(found and found[0])


class DevCommand(BaseCommand):
    """A command for a developer's database. `forcible = False`: it never runs with DEBUG off (a seeder that makes
    accounts with a known password)."""
    forcible = True

    def create_parser(self, prog_name, subcommand, **kwargs):
        parser = super().create_parser(prog_name, subcommand, **kwargs)
        if self.forcible:
            parser.add_argument('--force', action='store_true',
                                help='Run although DEBUG is off: this is not a developer\'s database, and the command '
                                     'writes made-up or development-only data into it.')
        return parser

    def execute(self, *args, **options):
        if not (self.forcible and options.get('force')):
            name = type(self).__module__.rsplit('.', 1)[-1]
            way = 'Give --force to run it all the same.' if self.forcible else 'It runs only with DEBUG on.'
            if not settings.DEBUG:
                raise CommandError(
                    f'{name} is a development tool (README, Management commands): it writes made-up or '
                    f'development-only data, and DEBUG is off, so this is not a developer\'s database. ' + way)
            if not superuser():
                raise CommandError(
                    f'{name} is a development tool (README, Management commands): it writes made-up or '
                    f'development-only data, and the database role is not a superuser, so this is not a developer\'s '
                    f'database whatever DEBUG says. ' + ('Give --force to run it all the same.' if self.forcible
                                                         else 'It runs only on a developer\'s database.'))
        return super().execute(*args, **options)
