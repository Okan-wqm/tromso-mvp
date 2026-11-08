"""The tables the ingest service writes (sensors/CONTRACT.md): plain rows, no version and no soft delete, one writer per
row. Django makes them (migrations) and reads them; a person changes only a dead letter's resolution. Defaults the
writer relies on are database defaults (`db_default`), so a row it inserts without them gets them."""
from django.conf import settings
from django.db import models
from django.db.models import F, Func, IntegerField, Q
from django.db.models.lookups import GreaterThanOrEqual, LessThanOrEqual
from django.utils.translation import gettext_lazy as _


MAX_PAYLOAD = 4096


class Contract(models.Model):
    """The one row both sides of the contract read: its version, the configuration's epoch (a trigger moves it and
    notifies channel `sensors_config` on every change of a table the ingest reads), how far in the future a device's
    time may be before it is replaced by the receive time, how long raw readings are kept (a test keeps it equal to
    the retention policy) and how old a message may be before it is refused as too old (two days inside the
    retention, so every message taken in also reaches the rollups)."""

    id = models.SmallIntegerField(primary_key=True, db_default=1)
    schema_version = models.IntegerField(_('Contract version'))
    config_epoch = models.BigIntegerField(_('Configuration epoch'), db_default=0)
    future_skew_s = models.IntegerField(_('Allowed future skew (seconds)'), db_default=60)
    retention_days = models.IntegerField(_('Raw retention (days)'), db_default=730)
    late_limit_days = models.IntegerField(_('Late limit (days)'), db_default=728)

    class Meta:
        db_table = 'sensors_contract'
        verbose_name = _('ingest contract')
        verbose_name_plural = _('ingest contract')
        constraints = [
            models.CheckConstraint(condition=Q(id=1), name='chk_sensors_contract_singleton'),
            models.CheckConstraint(condition=Q(future_skew_s__gte=0, future_skew_s__lte=3600),
                                   name='chk_sensors_contract_skew'),
            models.CheckConstraint(condition=Q(retention_days__gte=3), name='chk_sensors_contract_retention'),
            # Two days inside the retention: the daily late refresh looks one day past the limit and must never reach a
            # region whose raw chunks are dropped (a refresh there would empty the rollups; migration 0003).
            models.CheckConstraint(condition=Q(late_limit_days__gte=1, late_limit_days__lte=F('retention_days') - 2),
                                   name='chk_sensors_contract_late_limit'),
        ]

    def __str__(self):
        return f'v{self.schema_version} epoch {self.config_epoch}'


class QualityFlag(models.Model):
    """One bit of a reading's quality (sensors/quality.py, the one definition; seeded by migration 0001)."""

    bit = models.SmallIntegerField(_('Bit'), primary_key=True)
    name = models.CharField(_('Name'), max_length=30, unique=True)
    is_bad = models.BooleanField(_('Bad'))

    class Meta:
        db_table = 'sensors_quality_flag'
        ordering = ['bit']
        verbose_name = _('quality flag')
        verbose_name_plural = _('quality flags')
        constraints = [models.CheckConstraint(condition=Q(bit__in=[1, 2, 4, 8, 16, 32, 64, 128]),
                                              name='chk_sensors_quality_flag_bit')]

    def __str__(self):
        return self.name


class ChannelState(models.Model):
    """The ingest's memory of a channel, one row per channel number, updated in the same transaction as the readings it
    writes: the last value seen and the last good one (what `latest` reads, never the readings), the anchor the
    deadband is measured from (the last STORED value), the run of values not stored since it, and the newest stored
    time (an older value takes the late path)."""

    channel_no = models.IntegerField(_('Channel number'), primary_key=True)
    last_seen_at = models.DateTimeField(_('Last seen at'), null=True)
    last_good_at = models.DateTimeField(_('Last good value at'), null=True)
    last_value = models.FloatField(_('Last good value'), null=True)
    last_value_ts = models.DateTimeField(_('Time of the last good value'), null=True)
    last_quality = models.SmallIntegerField(_('Quality of the last value'), null=True)
    anchor_ts = models.DateTimeField(_('Anchor time'), null=True)
    anchor_value = models.FloatField(_('Anchor value'), null=True)
    anchor_quality = models.SmallIntegerField(_('Anchor quality'), null=True)
    run_n = models.IntegerField(_('Values in the open run'), db_default=0)
    run_sum = models.FloatField(_('Sum of the open run'), null=True)
    run_min = models.FloatField(_('Lowest of the open run'), null=True)
    run_max = models.FloatField(_('Highest of the open run'), null=True)
    # The newest time processed, stored or not: a sample at an older or equal time is late or a duplicate.
    high_ts = models.DateTimeField(_('Newest time processed'), null=True)

    class Meta:
        db_table = 'sensors_channel_state'
        verbose_name = _('channel state')
        verbose_name_plural = _('channel states')
        constraints = [models.CheckConstraint(condition=Q(run_n__gte=0), name='chk_sensors_channel_state_run_n')]

    def __str__(self):
        return f'#{self.channel_no}'


class DeviceState(models.Model):
    """What the ingest has seen of a device: when its last message came, its last sequence number (for monitoring only,
    never a key or a reason to refuse) and how many messages it accepted, took late, dead-lettered or ignored."""

    device_id = models.UUIDField(_('Device'), primary_key=True)
    last_message_at = models.DateTimeField(_('Last message at'), null=True)
    last_seq = models.BigIntegerField(_('Last sequence number'), null=True)
    accepted_total = models.BigIntegerField(_('Accepted'), db_default=0)
    late_total = models.BigIntegerField(_('Late'), db_default=0)
    dead_total = models.BigIntegerField(_('Dead-lettered'), db_default=0)
    ignored_total = models.BigIntegerField(_('Ignored'), db_default=0)

    class Meta:
        db_table = 'sensors_device_state'
        verbose_name = _('device state')
        verbose_name_plural = _('device states')

    def __str__(self):
        return str(self.device_id)


class IngestStatus(models.Model):
    """The ingest service's heartbeat per connection: whether it is connected to the broker, how many messages wait,
    when it last committed. The Sensors overview says from it whether the ingest is alive."""

    connection_id = models.UUIDField(_('Connection'), primary_key=True)
    heartbeat_at = models.DateTimeField(_('Heartbeat at'))
    version = models.CharField(_('Service version'), max_length=50, blank=True, db_default='')
    connected = models.BooleanField(_('Connected'), db_default=False)
    queue_depth = models.IntegerField(_('Messages waiting'), db_default=0)
    last_commit_at = models.DateTimeField(_('Last commit at'), null=True)
    qos0_dropped = models.BigIntegerField(_('QoS 0 messages dropped on a full queue'), db_default=0)
    poison_total = models.BigIntegerField(_('Messages the database refused'), db_default=0)

    class Meta:
        db_table = 'sensors_ingest_status'
        verbose_name = _('ingest status')
        verbose_name_plural = _('ingest statuses')
        constraints = [models.CheckConstraint(condition=Q(queue_depth__gte=0), name='chk_sensors_ingest_status_queue')]

    def __str__(self):
        return str(self.connection_id)


class DeadReason(models.TextChoices):
    NOT_JSON = 'not_json', _('Not JSON')
    NO_ROUTE = 'no_route', _('No device publishes on this topic')
    NO_CHANNEL_MATCH = 'no_channel_match', _('No channel of the device matches')
    MISSING_TIME = 'missing_time', _('The time is missing')
    BAD_TIME = 'bad_time', _('The time cannot be read')
    TOO_OLD = 'too_old', _('Older than the raw data is kept')
    MISSING_VALUE = 'missing_value', _('The value is missing')
    BAD_VALUE = 'bad_value', _('The value is not a number')
    OVERSIZE = 'oversize', _('The message is too large')


OVERFLOW = 'overflow'


def _octets():
    return Func(F('payload'), function='octet_length', output_field=IntegerField())


class DeadLetter(models.Model):
    """A message the ingest could not store, kept as evidence: its topic, why, its first 4096 bytes and how often the
    same message came (one row per connection, topic, reason and payload hash, counted). Beyond 1000 new rows per
    connection and hour the rest are counted on one row whose hash is 'overflow'. Readings are never capped. A person
    marks one resolved; pruned after 90 days (`manage.py sensors_housekeeping`)."""

    id = models.BigAutoField(primary_key=True)
    connection_id = models.UUIDField(_('Connection'))
    device_id = models.UUIDField(_('Device'), null=True)
    topic = models.CharField(_('Topic'), max_length=255)
    reason = models.CharField(_('Reason'), max_length=20, choices=DeadReason.choices)
    payload_sha256 = models.CharField(_('Payload hash (SHA-256)'), max_length=64)
    payload = models.BinaryField(_('Payload'))
    payload_len = models.IntegerField(_('Payload size (bytes)'))
    count = models.IntegerField(_('Times'), db_default=1)
    first_at = models.DateTimeField(_('First at'))
    last_at = models.DateTimeField(_('Last at'))
    resolved_at = models.DateTimeField(_('Resolved at'), null=True)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+',
                                    verbose_name=_('Resolved by'))

    class Meta:
        db_table = 'sensors_dead_letter'
        ordering = ['-last_at']
        verbose_name = _('dead letter')
        verbose_name_plural = _('dead letters')
        constraints = [
            models.UniqueConstraint(fields=['connection_id', 'topic', 'reason', 'payload_sha256'],
                                    name='uq_sensors_dead_letter_message'),
            models.CheckConstraint(condition=Q(reason__in=DeadReason.values), name='chk_sensors_dead_letter_reason'),
            models.CheckConstraint(condition=Q(payload_sha256__regex=r'^[0-9a-f]{64}$') | Q(payload_sha256=OVERFLOW),
                                   name='chk_sensors_dead_letter_hash'),
            # The first 4096 bytes are kept; the size is the whole message's.
            models.CheckConstraint(condition=LessThanOrEqual(_octets(), MAX_PAYLOAD), name='chk_sensors_dead_letter_payload'),
            models.CheckConstraint(condition=GreaterThanOrEqual(F('payload_len'), _octets()), name='chk_sensors_dead_letter_len'),
            models.CheckConstraint(condition=Q(count__gte=1), name='chk_sensors_dead_letter_count'),
            models.CheckConstraint(condition=Q(last_at__gte=F('first_at')), name='chk_sensors_dead_letter_times'),
            models.CheckConstraint(condition=Q(resolved_at__isnull=True) | Q(resolved_at__gte=F('first_at')),
                                   name='chk_sensors_dead_letter_resolved'),
        ]
        indexes = [models.Index(fields=['-last_at'], name='sensors_dead_letter_last_idx')]

    def __str__(self):
        return f'{self.topic}: {self.reason}'

