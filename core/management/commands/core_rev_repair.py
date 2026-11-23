"""Makes the revision triggers core.rev.missing() names (core.W005) again, exactly as their migrations made them, then
rebuilds every revision (core.rev.repair): a change may have passed unseen while a trigger was gone, so every stored
figure is built again. Does nothing when none is missing."""
from django.core.management.base import BaseCommand

from core import rev


class Command(BaseCommand):
    help = 'Makes the missing or disabled core_rev triggers again and rebuilds every revision.'

    def handle(self, *args, **options):
        made = rev.repair()
        if not made:
            self.stdout.write('Every revision trigger is there; nothing was changed.')
            return
        self.stdout.write('Made again: ' + ', '.join(f'{table} ({scope})' for table, scope in made)
                          + '. Every revision was rebuilt.')
        left = rev.missing()
        if left:
            self.stderr.write('Still missing: ' + ', '.join(left))
