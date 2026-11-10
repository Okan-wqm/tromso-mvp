from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from core.migrations import _private


class Command(BaseCommand):
    help = ('Makes the plain values in the activity log that were decided private into private values: the conversion '
            'of migration core/0011 (core/migrations/_private.py), callable again. One-way. With --dry-run nothing is '
            'written: it says how many values would be converted and names the entries whose contact list cannot be '
            'taken apart (by id, record type and record, never by their words). Run the dry run on a copy of the '
            'database before the migration runs on it; run it without --dry-run when the check core.W004 '
            '(`manage.py check --database default`) reports plain values left by a server that still ran old code.')

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Say what would be converted; write nothing.')

    def handle(self, *args, dry_run=False, **options):
        if dry_run:
            with connection.cursor() as cursor:
                found, counts = _private.plan(cursor)
            self.stdout.write('Dry run: nothing is written.')
            if counts['rows']:
                self.stdout.write(f'{counts["rows"]} activity-log row(s) hold plain values that were decided private:')
            self.stdout.write('\n'.join(_private.report(found, counts)))
            if counts['rows'] and _private.key_refusal():
                self.stdout.write(f'The conversion would be refused here: {_private.key_refusal()}')
            return
        try:
            with transaction.atomic(), connection.cursor() as cursor:
                found, _counts = _private.plan(cursor)            # for the entries' names; convert plans again itself
                with connection.schema_editor() as editor:
                    counts = _private.convert(editor)
        except RuntimeError as refusal:
            raise CommandError(str(refusal)) from refusal
        if counts['rows']:
            self.stdout.write(f'{counts["rows"]} activity-log row(s) converted:')
        self.stdout.write('\n'.join(_private.report(found, counts)))
