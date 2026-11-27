from django.core.management.base import BaseCommand

from experiments import preflight


class Command(BaseCommand):
    help = ('Before confidentiality goes live: how many experiments are open, sealed and private, those without a live '
            'lead, the replicates that hold a whole system without booking it, approvals ended while their experiment '
            'runs, live shares to inactive accounts and bookings with no live tank; then the announcement to send. '
            'Changes nothing.')

    def add_arguments(self, parser):
        parser.add_argument('--announcement', action='store_true', help='Print the announcement to the people too.')

    def handle(self, *args, **options):
        for line in preflight.report():
            self.stdout.write(line)
        if options['announcement']:
            self.stdout.write('')
            self.stdout.write(preflight.ANNOUNCEMENT)
