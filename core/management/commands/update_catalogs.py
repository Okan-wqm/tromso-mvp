from django.core.management.base import BaseCommand

from core import catalogs


class Command(BaseCommand):
    help = ('Updates locale/<language>/LC_MESSAGES/django.po from the code and templates: what '
            'makemessages does, with Babel instead of GNU gettext.')

    def handle(self, *args, **options):
        for language in catalogs.languages():
            catalogs.update(language)
            if options['verbosity']:
                self.stdout.write(f'Updated {catalogs.po_path(language)}')
