from django.core.management.base import BaseCommand, CommandError

from experiments import integrity


class Command(BaseCommand):
    help = ('Checks every started experiment from scratch and reports every broken rule the database cannot hold: a design '
            'that lost a part (a group without replicates or a level), a tank off the site or booked outside the days, '
            'a tank deleted while in an experiment, and a running placement of a diet group without its live feeding '
            'assignment.')

    def handle(self, *args, **options):
        found = integrity.problems()
        for problem in found:
            self.stdout.write(problem)
        if found:
            raise CommandError(f'{len(found)} problem(s) in the experiments.')
        self.stdout.write(self.style.SUCCESS('The experiments add up.'))
