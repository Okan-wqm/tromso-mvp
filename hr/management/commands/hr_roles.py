from django.core.management.base import BaseCommand

from ... import roles


class Command(BaseCommand):
    help = ('Creates the Production manager and Production worker roles (hr.roles) when they do not exist. A role that exists '
            'is kept as it is, whatever an administrator changed in it.')

    def handle(self, *args, **options):
        for name, created in roles.create():
            self.stdout.write(f'{name}: created.' if created else f'{name}: exists, kept as it is.')
