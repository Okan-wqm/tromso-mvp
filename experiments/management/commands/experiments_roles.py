from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ... import roles


class Command(BaseCommand):
    help = ('Creates the Research collaborator role (Experiments: read, nothing else; experiments.roles) when no role has '
            'its name. A role that exists is kept as it is, whatever an administrator changed in it.')

    def add_arguments(self, parser):
        parser.add_argument('--language', default='en', help='The language of the role\'s name (en, nb or tr).')

    def handle(self, *args, **options):
        if options['language'] not in dict(settings.LANGUAGES):
            raise CommandError(f'No such language: {options["language"]}.')
        name, created = roles.create(options['language'])
        self.stdout.write(f'{name}: created.' if created else f'{name}: exists, kept as it is.')
