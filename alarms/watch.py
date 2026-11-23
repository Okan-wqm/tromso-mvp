"""Whether the alarms are being checked and their notifications sent now, read from the alarm worker's row
(alarms.AlarmWorkerStatus) on the database's clock: the one verdict the health check (manage.py alarm_worker_health), the
pages' notice ({% alarm_watch %}), the dead man (alarms/worker.py) and the worker's own restart read. One query.

- `never`: no worker has ever run on this database: no alarm has been raised and nobody has been told of anything;
- `stopped`: the worker stopped (it says so when it ends);
- `stale`: no pass has finished for longer than the worker's own `stale_after` (it was killed, hangs, or cannot reach the
  database): nothing is being checked;
- `failing`: passes finish, but a step of each has failed for that long (the steps that failed are said): part of the
  alarms is not checked;
- `sender`: the alarms are checked, but the outbox's sender has not gone through the outbox for that long (its thread
  died or hangs): nobody is told;
- `undeliverable`: critical notifications of open, unacknowledged alarms have failed longer than the escalation time
  (alarms/outbox.py): their people are not reached;
- otherwise the alarms are checked and sent, the last pass `age` seconds ago."""
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db.models.functions import Now

from .models import AlarmWorkerStatus, WorkerState

NEVER, STOPPED, STALE, FAILING, SENDER, UNDELIVERABLE = (
    'never', 'stopped', 'stale', 'failing', 'sender', 'undeliverable')


@dataclass(frozen=True)
class Watch:
    reason: str                     # '' when checked, else one of the reasons above
    last_pass_at: datetime | None   # when a pass last finished
    last_ok_pass_at: datetime | None
    since: datetime | None          # since when it is so: the last good pass, the last round, the oldest undelivered
    age: timedelta | None           # how long ago the last pass finished, on the database's clock
    failed_steps: str = ''
    row: AlarmWorkerStatus | None = None

    @property
    def checked(self):
        return not self.reason


def state(name='alarms'):
    """The verdict on worker `name` now."""
    row = AlarmWorkerStatus.objects.filter(name=name).annotate(db_now=Now()).first()
    if row is None:
        return Watch(NEVER, None, None, None, None)
    limit = timedelta(seconds=row.stale_after_seconds)
    age = row.db_now - row.last_pass_at if row.last_pass_at else None
    since = row.last_ok_pass_at or row.started_at
    sent = max(row.last_send_at or row.started_at, row.started_at)
    if row.state == WorkerState.STOPPED:
        reason = STOPPED
    elif age is None or age > limit:
        reason = STALE
    elif row.last_ok_pass_at is None or row.db_now - row.last_ok_pass_at > limit:
        reason = FAILING
    elif row.db_now - sent > limit:
        reason, since = SENDER, sent
    elif row.undeliverable:
        reason, since = UNDELIVERABLE, row.undeliverable_since
    else:
        reason, since = '', None
    return Watch(reason, row.last_pass_at, row.last_ok_pass_at, since, age, row.failed_steps, row)
