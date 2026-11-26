"""Opens the ingest service's database role (made NOLOGIN by migration sensors 0001) with the password in a secret file,
or closes it again (`--disable`). The password is never an argument (it would show in the process list and the shell's
history), never goes through Django's query log, and never reaches the server as text: libpq makes its SCRAM-SHA-256
verifier here (PQencryptPasswordConn) and only that is sent, so a server that logs DDL logs no secret (the data-layering
audit, L-15). It opens only a least-privilege role: a superuser, a role that may create roles or databases, or one that
owns tables of the schema is refused. Needs a database user that may alter roles."""
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
        found = raw.execute(
            "SELECT rolsuper OR rolcreaterole OR rolcreatedb OR EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = "
            "'public' AND tableowner = rolname) FROM pg_roles WHERE rolname = %s", [options['role']]).fetchone()
        if found is None:
            raise CommandError(f'There is no role {options["role"]}.')
        if found[0]:
            raise CommandError(f'{options["role"]} is not a least-privilege role (a superuser, a role that may create '
                               f'roles or databases, or the owner of tables): this command opens the ingest\'s role only.')
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
        verifier = raw.pgconn.encrypt_password(password.encode(), options['role'].encode(), b'scram-sha-256')
        raw.execute(sql.SQL('ALTER ROLE {} LOGIN PASSWORD {}').format(role, sql.Literal(verifier.decode('ascii'))))
        self.stdout.write(f'{options["role"]} can sign in with the password of {options["password_file"]}.')
