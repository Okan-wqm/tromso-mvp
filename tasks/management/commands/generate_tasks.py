from django.core.management.base import BaseCommand

from tasks import services


class Command(BaseCommand):
    help = ("Makes the planned tasks of every active recurring task up to TASK_HORIZON_DAYS ahead (and missed ones "
            "back to TASK_BACKFILL_DAYS): the task job, run every hour by the server's jobs. The pages only read; "
            "they say when recurring tasks are not planned up to today.")

    def handle(self, *args, **options):
        made = services.materialise_due()
        self.stdout.write(f'{len(made)} task(s) made.')
