"""Whether the alarms are being checked (alarms/watch.py): exit 0 and the last pass's age, or exit 1 and why not. The
compose service's healthcheck (docker-compose.yml `alarms`) and anyone on the server run it."""
import sys

from django.core.management.base import BaseCommand

from alarms import watch
from alarms.worker import DEFAULT_NAME

WHY = {
    watch.NEVER: 'no alarm worker has ever run on this database: no alarm is raised and nobody is told',
    watch.STOPPED: 'the alarm worker stopped: no alarm is raised and nobody is told',
    watch.STALE: 'no alarm pass has finished for {age}: no alarm is raised and nobody is told',
    watch.FAILING: 'alarm passes finish, but these steps fail: {steps}',
    watch.SENDER: 'the alarm notifications have not been gone through since {since}: nobody is told',
    watch.UNDELIVERABLE: '{count} critical notification(s) cannot be delivered, the oldest queued {since}',
}


class Command(BaseCommand):
    help = 'Exit 0 when the alarms are being checked and sent, 1 (and why) when they are not.'

    def add_arguments(self, parser):
        parser.add_argument('--name', default=DEFAULT_NAME)

    def handle(self, *args, **options):
        found = watch.state(options['name'])
        if found.checked:
            self.stdout.write(f'ok: the last alarm pass finished {found.age.total_seconds():.0f} s ago')
            return
        age = f'{found.age.total_seconds():.0f} s' if found.age is not None else 'ever'
        since = f'{found.since:%Y-%m-%d %H:%M:%S} UTC' if found.since else '?'
        self.stderr.write(WHY[found.reason].format(age=age, steps=found.failed_steps or '?', since=since,
                                                   count=found.row.undeliverable if found.row else 0))
        sys.exit(1)
