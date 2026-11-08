"""The readings: the hypertable the ingest service writes (sensors/CONTRACT.md) and Django only reads."""
from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _

from .. import quality
from .channel import finite


class Reading(models.Model):
    """One stored value of a channel at the device's time: the hypertable `sensors_reading` (7-day chunks, compressed
    after 14 days, kept 730 days). Written only by the ingest service; a row stands for `n` messages, and for n > 1 it
    carries the run's sum, lowest and highest (the messages not stored since the previous row, and this one), so
    averages are exact. Only clean readings (sensors/quality.py) reach the rollups, the latest value and the charts."""

    pk = models.CompositePrimaryKey('channel_no', 'ts')
    channel_no = models.IntegerField(_('Channel number'))
    ts = models.DateTimeField(_('Time'))
    value = models.FloatField(_('Value'))
    n = models.IntegerField(_('Messages'), db_default=1)
    quality = models.SmallIntegerField(_('Quality'), db_default=0)
    run_sum = models.FloatField(_('Sum of the run'), null=True)
    run_min = models.FloatField(_('Lowest of the run'), null=True)
    run_max = models.FloatField(_('Highest of the run'), null=True)

    class Meta:
        db_table = 'sensors_reading'
        verbose_name = _('sensor reading')
        verbose_name_plural = _('sensor readings')
        constraints = [
            models.CheckConstraint(condition=finite('value'), name='chk_sensors_reading_value'),
            models.CheckConstraint(condition=Q(quality__gte=0, quality__lte=quality.ALL_BITS), name='chk_sensors_reading_quality'),
            models.CheckConstraint(
                condition=Q(n=1, run_sum__isnull=True, run_min__isnull=True, run_max__isnull=True)
                # NOT NULL spelled out: a CHECK whose condition is NULL passes.
                | (Q(n__gt=1, run_sum__isnull=False, run_min__isnull=False, run_max__isnull=False,
                     run_min__lte=F('value'), run_max__gte=F('value'))
                   & finite('run_sum') & finite('run_min') & finite('run_max')),
                name='chk_sensors_reading_run'),
        ]

    def __str__(self):
        return f'#{self.channel_no} {self.ts:%Y-%m-%d %H:%M:%S}: {self.value}'
