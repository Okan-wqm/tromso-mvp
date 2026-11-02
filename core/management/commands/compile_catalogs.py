from django.core.management.base import BaseCommand

from core import catalogs


class Command(BaseCommand):
    help = ('Builds the .mo files Django loads from the .po files: what compilemessages does, '
            'with Babel instead of GNU gettext.')

    def handle(self, *args, **options):
        for language in catalogs.languages():
            catalogs.compile(language)
            if options['verbosity']:
                self.stdout.write(f'Built {catalogs.mo_path(language)}')
