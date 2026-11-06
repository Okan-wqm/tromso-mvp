"""After a restore, or a load run with the revision triggers off: moves every revision of core_rev past every stored
figure's stamp (core.rev.rebuild), so each stored figure is built again from the data. Safe to run at any time: it
never changes a business row, it only makes stored figures miss once."""
from django.core.management.base import BaseCommand
from django.db import transaction

from core import rev


class Command(BaseCommand):
    help = 'Moves every core_rev revision past every stored figure (after a restore or a bulk load).'

    def handle(self, *args, **options):
        with transaction.atomic():
            target = rev.rebuild()
        missing = rev.missing()
        self.stdout.write(f'Every revision is now {target}; stored figures are built again on their next use.')
        if missing:
            self.stderr.write('Revision triggers missing or disabled: ' + ', '.join(missing))
