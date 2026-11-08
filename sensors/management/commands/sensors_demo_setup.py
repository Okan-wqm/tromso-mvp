"""Makes (or, with --remove, deletes) the live demo's sensor configuration for the tanks and systems the database already
has (sensors/demo.py). It writes configuration rows into the database it is pointed at, so it runs only when told:
`--confirm` to make, `--remove` to delete. The simulator credential's secret is printed once, when it is made (and
written to `--secret-file` when given, for the simulator's compose secret); run `manage.py sensor_broker_sync` after."""
import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from sensors import demo


class Command(BaseCommand):
    help = 'Makes, or removes, the demo sensors for the existing tanks and systems.'

    def add_arguments(self, parser):
        parser.add_argument('--confirm', action='store_true', help='Make the demo configuration.')
        parser.add_argument('--remove', action='store_true', help='Delete the demo configuration.')
        parser.add_argument('--secret-file', help='Also write the simulator secret here when it is made (mode 600).')

    def handle(self, *args, **options):
        if options['confirm'] == options['remove']:
            raise CommandError('Say what to do: --confirm to make the demo sensors, or --remove to delete them.')
        if options['remove']:
            self.stdout.write(f'{demo.remove()} demo devices removed with their channels and bindings.')
            return
        report = demo.setup()
        self.stdout.write(f'{len(report.devices)} demo devices made, {len(report.kept)} already there.')
        for place, why in report.skipped:
            self.stdout.write(f'Skipped {place}: {why}.')
        if report.secret:
            self.stdout.write(f'Simulator credential {demo.USERNAME}, secret: {report.secret} (shown once).')
            if options['secret_file']:
                path = Path(options['secret_file'])
                # One line feed on every platform: Windows' text mode would write CRLF, and a reader taking the
                # first line would keep the carriage return as part of the password.
                path.write_text(report.secret + '\n', encoding='utf-8', newline='\n')
                os.chmod(path, 0o600)
        self.stdout.write('Write the broker files next: manage.py sensor_broker_sync.')
