"""Writes the real templates' parts the browser layout test reads (core/layout_pages.py); --check fails when they are
not what the templates print now."""
from django.core.management.base import BaseCommand, CommandError

from core import layout_pages


class Command(BaseCommand):
    help = 'Write frontend/test/pages from the real templates (--check: fail when they are out of date).'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--check', action='store_true')

    def handle(self, *args, check=False, **options):
        if check:
            if stale := layout_pages.stale():
                raise CommandError(f'{", ".join(stale)} out of date: run `manage.py layout_pages` and commit the result.')
            self.stdout.write('The layout pages are up to date.')
            return
        layout_pages.write()
        self.stdout.write(f'Wrote {len(layout_pages.PAGES)} pages to {layout_pages.FOLDER}')
