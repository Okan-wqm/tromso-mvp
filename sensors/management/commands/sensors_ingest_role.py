"""Opens the ingest service's database role (made NOLOGIN by migration sensors 0001) with the password in a secret file,
or closes it again (`--disable`). The password is never an argument (it would show in the process list and the shell's
history) and never goes through Django's query log: it is sent on the database driver's own connection, as a quoted
literal. Needs a database user that may alter roles."""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from psycopg import sql

ROLE = 'sensors_ingest'


class Command(BaseCommand):
    help = 'Lets the ingest service\'s database role sign in with the password in a file, or stops it.'

    def add_arguments(self, parser):
        parser.add_argument('--password-file', help='A file holding the password (its first line).')
        parser.add_argument('--disable', action='store_true', help='Make the role unable to sign in.')
        parser.add_argument('--role', default=ROLE, help=f'The role (default {ROLE}).')

    def handle(self, *args, **options):
        role = sql.Identifier(options['role'])
        connection.ensure_connection()
        raw = connection.connection
        if options['disable']:
            raw.execute(sql.SQL('ALTER ROLE {} NOLOGIN').format(role))
            self.stdout.write(f'{options["role"]} can no longer sign in.')
            return
        if not options['password_file']:
            raise CommandError('Give --password-file, or --disable.')
        lines = Path(options['password_file']).read_text(encoding='utf-8').splitlines()
        password = lines[0] if lines else ''
        if not password.strip():
            raise CommandError(f'{options["password_file"]} holds no password.')
        raw.execute(sql.SQL('ALTER ROLE {} LOGIN PASSWORD {}').format(role, sql.Literal(password)))
        self.stdout.write(f'{options["role"]} can sign in with the password of {options["password_file"]}.')
