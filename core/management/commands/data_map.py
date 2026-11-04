from django.core.management.base import BaseCommand, CommandError

from core import datamap


class Command(BaseCommand):
    help = ('Writes docs/data-map.md and docs/data-map.json: for every table, which screen fills, changes, deletes '
            'and shows it, read from the models, the tabs, the routes and each app\'s screens.py (core.datamap). '
            '--check writes nothing and fails when the committed files are stale or a table has no screen.')
    # The map is read from the code: no database is needed (some system checks ask it for its version).
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--check', action='store_true', help='Fail when the committed files are not up to date.')

    def handle(self, *args, **options):
        # The routes and the tabs are declared when the URL configuration is imported.
        from importlib import import_module
        from django.conf import settings
        import_module(settings.ROOT_URLCONF)
        built, markdown, document = datamap.build()
        if built.problems:
            raise CommandError('The data map is incomplete:\n- ' + '\n- '.join(built.problems))
        files = {datamap.MARKDOWN: markdown, datamap.JSON: document}
        if options['check']:
            stale = [path.name for path, text in files.items()
                     if not path.exists() or path.read_bytes() != text.encode('utf-8')]
            if stale:
                raise CommandError(f'{", ".join(stale)} out of date: run `manage.py data_map` and commit the result.')
            self.stdout.write('The data map is up to date.')
            return
        for path, text in files.items():
            path.write_bytes(text.encode('utf-8'))
            self.stdout.write(f'Wrote {path}')
