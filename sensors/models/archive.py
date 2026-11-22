"""The cold tier's record of each chunk of readings moved out of the database (sensors/tiers.py)."""
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _


class ArchiveState(models.TextChoices):
    EXPORTED = 'exported', _('Exported')
    VERIFIED = 'verified', _('Verified')
    DROPPED = 'dropped', _('In the archive only')
    FAILED = 'failed', _('Failed')


class ArchivedChunk(models.Model):
    """One chunk of `sensors_reading` (a week of every channel) written to a Parquet file of the cold archive: its
    range, the file, its rows and checksums, and how far it went (exported, verified against the database, dropped
    from the database). The proof a chunk may be dropped and the index of what the archive holds. Written by the
    system (the tier jobs), never by a person."""

    State = ArchiveState

    table = models.CharField(max_length=63, default='sensors_reading')
    chunk = models.CharField(max_length=200)                 # the chunk's name when it was exported
    range_start = models.DateTimeField()
    range_end = models.DateTimeField()
    path = models.CharField(max_length=300)                   # inside the archive directory
    rows = models.BigIntegerField()
    sha256 = models.CharField(max_length=64)                  # of the file
    digest = models.CharField(max_length=80)                  # of the rows, worked out by the database at the export
    state = models.CharField(max_length=10, choices=State.choices, default=State.EXPORTED)
    error = models.TextField(blank=True)
    exported_at = models.DateTimeField()
    verified_at = models.DateTimeField(null=True, blank=True)
    dropped_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'sensors_archived_chunk'
        ordering = ['-range_start']
        verbose_name = _('archived chunk')
        verbose_name_plural = _('archived chunks')
        constraints = [
            models.CheckConstraint(condition=Q(state__in=ArchiveState.values), name='chk_sensors_archived_chunk_state'),
            models.CheckConstraint(condition=Q(range_end__gt=models.F('range_start')),
                                   name='chk_sensors_archived_chunk_range'),
            models.CheckConstraint(condition=Q(rows__gte=0), name='chk_sensors_archived_chunk_rows'),
            # A dropped chunk was verified first, and it is in the archive only.
            models.CheckConstraint(condition=~Q(state=ArchiveState.DROPPED)
                                   | Q(verified_at__isnull=False, dropped_at__isnull=False),
                                   name='chk_sensors_archived_chunk_dropped'),
            # One live record per range: a failed one may be tried again.
            models.UniqueConstraint(fields=['table', 'range_start'], condition=~Q(state=ArchiveState.FAILED),
                                    name='uq_sensors_archived_chunk_range'),
        ]

    def __str__(self):
        return f'{self.table} {self.range_start:%Y-%m-%d}–{self.range_end:%Y-%m-%d} {self.state}'
