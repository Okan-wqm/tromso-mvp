"""The commands of the go-live stack's proof (deploy/ci/stack.sh, .github/workflows/go-live-stack.yml): synthetic data
for the production stack built on a throwaway CI runner, written as a farm's server writes (the app role, DEBUG off,
through the services), so that the backup, the restore and the point-in-time restore are proven on rows of the
product's own making. They are no development tools (core/management/devtool.py): those run on a developer's database
(DEBUG on and a superuser role), and the stack is no developer's database, it is the production stack.

A `StackProofCommand` runs on one database only: the one the stack marked. The mark is the database's comment, `MARK`
word for word, which the stack writes as the database's owner role before it seeds (`COMMENT ON DATABASE`). It is a
fact of the database, not of the process: no setting, environment variable or argument stands for it, and the app role
a command runs as on a server cannot write it (a comment on a database is its owner's or a superuser's to set: go-live's
database roles). A farm's database never carries it: no step of the installation, the upgrade or the restore writes it,
and a dump does not carry it to another database (pg_dump writes a database's comment only with --create, which the
backup does not use). Nothing forces past it: there is no `--force`."""
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

MARK = 'balik go-live stack proof: a throwaway database of deploy/ci/stack.sh, synthetic data only'


def marked():
    """Whether the database the command is connected to carries the stack's mark as its comment."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT shobj_description(oid, 'pg_database') FROM pg_database "
                       "WHERE datname = current_database()")
        found = cursor.fetchone()
    return bool(found and found[0] == MARK)


class StackProofCommand(BaseCommand):
    """A command of the go-live stack's proof: refused on every database the stack did not mark."""

    def execute(self, *args, **options):
        if not marked():
            name = type(self).__module__.rsplit('.', 1)[-1]
            raise CommandError(
                f'{name} is a command of the go-live stack\'s proof (README, Management commands): it writes synthetic '
                f'data, and this database does not carry the stack\'s mark (its comment), so it is not the stack\'s '
                f'throwaway database. It runs nowhere else.')
        return super().execute(*args, **options)
