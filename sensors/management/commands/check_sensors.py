"""Checks the sensor alarm rules (sensors/alarms.py) once, or every `--loop` seconds until stopped. Shown, not sent: the
events appear on the Sensors overview and the Alarm events page; nobody is notified."""
import time

from django.core.management.base import BaseCommand

from sensors import alarms


class Command(BaseCommand):
    help = 'Checks the sensor alarm rules once, or every --loop seconds.'

    def add_arguments(self, parser):
        parser.add_argument('--loop', type=int, default=0, help='Seconds between two checks; 0 checks once.')

    def handle(self, *args, **options):
        while True:
            opened, closed = alarms.evaluate()
            self.stdout.write(f'{opened} alarm events opened, {closed} closed.')
            if options['loop'] <= 0:
                return
            time.sleep(options['loop'])
