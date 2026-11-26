"""Drops the revision triggers of every tracked hypertable before a TimescaleDB update (core.rev.drop_hypertable_triggers,
deploy/scripts/timescaledb-move.sh): the update cannot rename a chunk's constraint trigger. `manage.py core_rev_repair`
makes them again after the update and rebuilds every revision; `manage.py check --database default` names them
(core.W005) until then. Refuses, dropping nothing, when another constraint trigger sits on a hypertable."""
from django.core.management.base import BaseCommand, CommandError

from core import rev


class Command(BaseCommand):
    help = ('Before ALTER EXTENSION timescaledb UPDATE: drops the revision triggers of every tracked hypertable '
            '(core_rev_repair makes them again afterwards).')

    def handle(self, *args, **options):
        try:
            dropped = rev.drop_hypertable_triggers()
        except rev.ForeignConstraintTriggers as error:
            raise CommandError(str(error)) from error
        if not dropped:
            self.stdout.write('Dropped: none (no tracked hypertable has a revision trigger now).')
            return
        self.stdout.write('Dropped: ' + ', '.join(f'{table} ({scope})' for table, scope in dropped)
                          + '. After the TimescaleDB update, run manage.py core_rev_repair.')
