from django.core.management.base import BaseCommand

from tasks import services


class Command(BaseCommand):
    help = ("Makes the planned tasks of every active recurring task up to TASK_HORIZON_DAYS ahead (and missed ones "
            "back to TASK_BACKFILL_DAYS); for a cron job. The Tasks pages do the same before they read.")

    def handle(self, *args, **options):
        made = services.materialise_due()
        self.stdout.write(f'{len(made)} task(s) made.')
