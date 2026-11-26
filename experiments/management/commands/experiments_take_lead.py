from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError

from ... import services
from ...models import Experiment


class Command(BaseCommand):
    help = ('The platform admin takes over an experiment that has no live lead (its lead left, or their window ended): '
            'the account named becomes its lead, with the reason given, logged on the experiment. Refused while the '
            'experiment has a lead, and for an account that is not the platform admin.')

    def add_arguments(self, parser):
        parser.add_argument('code', help='The experiment\'s number, e.g. E-2026-001.')
        parser.add_argument('--as', dest='username', required=True, help='The platform admin\'s username.')
        parser.add_argument('--reason', required=True, help='Why it is taken over.')

    def handle(self, *args, code, username, reason, **options):
        experiment = Experiment.all_objects.filter(code=code).first()
        user = get_user_model().objects.filter(username=username, is_active=True).first()
        if experiment is None or user is None:
            raise CommandError('No such experiment or active account.')
        try:
            services.take_lead(user, experiment, reason)
        except ValidationError as error:
            raise CommandError(' '.join(error.messages))
        except PermissionDenied:
            raise CommandError('Only the platform admin takes an experiment over.')
        self.stdout.write(f'{experiment.code}: {username} leads it now.')
