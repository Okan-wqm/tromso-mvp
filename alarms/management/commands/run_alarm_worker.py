"""The alarm worker (alarms/worker.py): checks the alarms until stopped, a pass at a time. The compose service `alarms`
runs it (docker-compose.yml), and Docker starts it again when it exits. SIGTERM or SIGINT: the pass under way finishes,
the worker's row says stopped, exit 0. Exit 1: it must be started again (the database unreachable too long, passes
failing whole, a pass that hangs)."""
import signal
import sys

from django.core.management.base import BaseCommand

from alarms.worker import DEFAULT_NAME, Worker


class Command(BaseCommand):
    help = 'Checks the alarms until stopped: the alarm worker (one active per database, others stand by).'

    def add_arguments(self, parser):
        parser.add_argument('--name', default=DEFAULT_NAME, help='The worker\'s name, its row in alarm_worker_status.')

    def handle(self, *args, **options):
        worker = Worker(options['name'])
        for number in (signal.SIGTERM, signal.SIGINT):
            signal.signal(number, lambda *_: worker.stop.set())
        code = worker.run()
        if code:
            sys.exit(code)
