from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from monitoring.cards import render


class Command(BaseCommand):
    help = ('Writes static/css/card-grid.css, the classes that place a card\'s widgets on its grid, from the widget '
            'catalogue (monitoring.cards.render.grid_css). --check writes nothing and fails when the file is stale.')
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--check', action='store_true', help='Fail when the committed file is not up to date.')

    def handle(self, *args, **options):
        path = Path(settings.BASE_DIR) / 'static' / 'css' / 'card-grid.css'
        text = render.grid_css()
        if options['check']:
            if not path.exists() or path.read_bytes() != text.encode('utf-8'):
                raise CommandError(f'{path.name} out of date: run `manage.py card_grid_css` and commit the result.')
            self.stdout.write(f'{path.name} is up to date.')
            return
        path.write_bytes(text.encode('utf-8'))
        self.stdout.write(f'Wrote {path}')
