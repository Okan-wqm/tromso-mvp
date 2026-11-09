"""The alarm loop (alarms/engine.py): one pass, or one every `--loop` seconds until stopped. It checks the sensor rules and
the water limits, queues the notifications, escalates and hands what is queued to the connected transports; with none
connected nothing is sent, and it says so."""
import logging
import time

from django.core.management.base import BaseCommand

from alarms import engine

logger = logging.getLogger('alarms.loop')


class Command(BaseCommand):
    help = 'Checks the alarms once (or every --loop seconds): opens, clears, notifies, escalates, sends.'

    def add_arguments(self, parser):
        parser.add_argument('--loop', type=int, default=0, help='Seconds between two passes; 0 runs one pass.')

    def handle(self, *args, **options):
        while True:
            try:
                self.stdout.write(str(engine.run_once()))
            except Exception as error:                   # a pass that failed whole: said, logged, and the loop goes on
                logger.exception('An alarm pass failed; the loop goes on.')
                self.stderr.write(f'The pass failed: {error}')
                if options['loop'] <= 0:
                    raise
            if options['loop'] <= 0:
                return
            time.sleep(options['loop'])
