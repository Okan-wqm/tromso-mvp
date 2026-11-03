from django.core.management.base import BaseCommand, CommandError

from inventory import integrity


class Command(BaseCommand):
    help = ('Checks every rule of the store from scratch: operations made of their lines, transfer pairs, suppliers '
            'of the categories they delivered, lots of the categories that need a number and an expiry, no '
            'departure below 0 in the book of the lines, no deleted location holding stock.')

    def handle(self, *args, **options):
        found = integrity.problems()
        for problem in found:
            self.stdout.write(problem)
        if found:
            raise CommandError(f'{len(found)} problem(s) in the store.')
        self.stdout.write(self.style.SUCCESS('The store adds up.'))
