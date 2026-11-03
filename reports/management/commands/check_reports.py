from django.core.management.base import BaseCommand, CommandError

from reports import integrity


class Command(BaseCommand):
    help = ('Checks every report from scratch: a filed one has its frozen content and the content its hash, a draft has none, a '
            'correction corrects a filed report of the same key, and a notice is of its event’s or escape’s site.')

    def handle(self, *args, **options):
        found = integrity.problems()
        for problem in found:
            self.stdout.write(problem)
        if found:
            raise CommandError(f'{len(found)} problem(s) in the reports.')
        self.stdout.write(self.style.SUCCESS('The reports add up.'))
