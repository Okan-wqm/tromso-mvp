from django.core.management.base import BaseCommand, CommandError

from farm.stock import integrity


class Command(BaseCommand):
    help = ('Folds every batch of the stock ledger from its first line and reports every broken rule: counts '
            'below zero, operations not made of their lines, stocking dates, unit statuses and species, and '
            'feedings, treatments and sea-lice counts in a unit without fish that day.')

    def handle(self, *args, **options):
        found = integrity.problems()
        for problem in found:
            self.stdout.write(problem)
        if found:
            raise CommandError(f'{len(found)} problem(s) in the stock.')
        self.stdout.write(self.style.SUCCESS('The stock adds up.'))
