"""Deletes the dead letters last seen more than 90 days ago (sensors/CONTRACT.md): they are evidence for a while, not
history. Readings are never touched here (their retention is the hypertable's policy). Run it daily."""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from sensors.models import DeadLetter

KEEP_DAYS = 90


class Command(BaseCommand):
    help = 'Deletes the dead letters last seen more than 90 days ago.'

    def handle(self, *args, **options):
        deleted, _detail = DeadLetter.objects.filter(last_at__lt=timezone.now() - timedelta(days=KEEP_DAYS)).delete()
        self.stdout.write(f'{deleted} dead letters older than {KEEP_DAYS} days deleted.')
