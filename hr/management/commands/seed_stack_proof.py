from django.contrib.auth import get_user_model
from django.core.management.base import CommandError

from core.management.stackproof import StackProofCommand

from . import _demo_company as demo_company


class Command(StackProofCommand):
    help = ('The go-live stack\'s synthetic data (deploy/ci/stack.sh, step data): the HR demonstration company without '
            'any sign-in, every record written through the services by the account named with --by (the stack\'s first '
            'admin). Idempotent. It runs only on a database that carries the stack\'s mark (core/management/'
            'stackproof.py), never on a farm\'s or a developer\'s.')

    def add_arguments(self, parser):
        parser.add_argument('--by', required=True, help='The username of the active account that writes the records.')

    def handle(self, *args, **options):
        by = get_user_model().objects.filter(username=options['by'], is_active=True).first()
        if by is None:
            raise CommandError(f'No active account is named {options["by"]!r}.')
        people = demo_company.build(by)
        self.stdout.write(f'Stack data ready: {len(people)} people of the HR demonstration company, written by '
                          f'{by.username}; no sign-in made.')
