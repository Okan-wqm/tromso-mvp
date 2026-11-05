from django.core.management.base import BaseCommand, CommandError

from ... import checks


class Command(BaseCommand):
    help = ('Reports what disagrees in the HR records, the rules a database constraint cannot hold (a last day with a placement '
            'after it, leave after it, a person placed in no department). Nothing is changed.')

    def handle(self, *args, **options):
        found = checks.problems()
        for code, text in found:
            self.stdout.write(f'{code}: {text}')
        if found:
            raise CommandError(f'{len(found)} problem(s) found in the HR records.')
        self.stdout.write('The HR records agree.')
