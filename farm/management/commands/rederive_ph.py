"""Puts the stored samples' pH measured on another scale than NBS on the NBS scale again by the application's formula
(farm/water/rederive.py: formula 4's step; what was measured is never touched, each rewrite is logged in the activity
log with the old value). Run once after the formula changed, on a database backed up first; again whenever the check
farm.W001 (`manage.py check --database default`) reports samples left on an older formula. Running it again changes
nothing.

    python manage.py rederive_ph --dry-run          # reads only: every sample, its pH before and after
    python manage.py rederive_ph [--user NAME]      # writes, one transaction, logged as NAME (default: the system)"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from farm.water import chemistry, rederive


class Command(BaseCommand):
    help = ('Puts the pH of the stored water samples measured on the total, seawater or free scale on the NBS scale '
            'again by the application’s formula, from what was measured; each change logged with its old value. '
            '--dry-run writes nothing.')

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Say what would change; write nothing.')
        parser.add_argument('--user', help='The username the activity log names (default: the system).')

    def handle(self, *args, dry_run=False, user=None, **options):
        person = None
        if user:
            try:
                person = get_user_model().objects.get(username=user)
            except get_user_model().DoesNotExist as missing:
                raise CommandError(f'No user {user!r}.') from missing
        found = rederive.plan() if dry_run else rederive.apply(person)
        moved = sum(item.moved for item in found)
        refused = [item for item in found if item.new is None]
        self.stdout.write(f'{"Dry run: nothing is written. " if dry_run else ""}Formula {chemistry.FORMULA_VERSION}: '
                          f'{len(found)} sample(s) on an older formula; {moved} NBS pH(s) '
                          f'{"would change" if dry_run else "changed"}, {len(found) - moved - len(refused)} the same, '
                          f'{len(refused)} not converted again.')
        for item in found:
            self.stdout.write(item.line())
        if refused and not dry_run:
            self.stderr.write(f'{len(refused)} sample(s) were left as they were (see above): the check farm.W001 keeps '
                              'naming them.')
