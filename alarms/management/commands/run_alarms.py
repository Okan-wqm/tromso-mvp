"""One pass of the alarms (alarms/engine.py), now, then one round through the outbox (alarms/outbox.py): it checks the
sensor rules and the water limits, queues the notifications, escalates, and hands what is due to the connected
transports; with none connected nothing is sent, and it says so. The alarms are kept checked by the alarm worker
(manage.py run_alarm_worker), which does the same for as long as it runs; this command is for an operator."""
from django.conf import settings
from django.core.management.base import BaseCommand

from alarms import engine, outbox


class Command(BaseCommand):
    help = 'Checks the alarms once and sends what is due: opens, clears, notifies, escalates, sends.'

    def handle(self, *args, **options):
        summary = engine.run_once()
        delivery = outbox.send_due(timeout=settings.ALARM_WORKER['send_timeout'])
        self.stdout.write(f'{summary}; {delivery}')
