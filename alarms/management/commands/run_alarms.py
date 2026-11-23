"""One pass of the alarms (alarms/engine.py), now: it checks the sensor rules and the water limits, queues the notifications,
escalates and hands what is queued to the connected transports; with none connected nothing is sent, and it says so. The
alarms are kept checked by the alarm worker (manage.py run_alarm_worker), which runs this same pass for as long as it
runs; this command is for an operator."""
from django.core.management.base import BaseCommand

from alarms import engine


class Command(BaseCommand):
    help = 'Checks the alarms once: opens, clears, notifies, escalates, sends. The worker is run_alarm_worker.'

    def handle(self, *args, **options):
        self.stdout.write(str(engine.run_once()))
