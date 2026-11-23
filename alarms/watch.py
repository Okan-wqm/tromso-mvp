"""Whether the alarms are being checked now, read from the alarm worker's row (alarms.AlarmWorkerStatus) on the database's
clock: the one verdict the health check (manage.py alarm_worker_health), the pages' notice and the alarm worker's own
restart (alarms/worker.py) read. One query.

- `never`: no worker has ever run on this database: no alarm has been raised and nobody has been told of anything;
- `stopped`: the worker stopped (it says so when it ends);
- `stale`: no pass has finished for longer than the worker's own `stale_after` (it was killed, hangs, or cannot reach the
  database): nothing is being checked;
- `failing`: passes finish, but a step of each has failed for that long (the steps that failed are said): part of the
  alarms is not checked;
- otherwise the alarms are checked, the last pass `age` seconds ago."""
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db.models.functions import Now

from .models import AlarmWorkerStatus, WorkerState

NEVER, STOPPED, STALE, FAILING = 'never', 'stopped', 'stale', 'failing'


@dataclass(frozen=True)
class Watch:
    reason: str                     # '' when checked, else NEVER, STOPPED, STALE or FAILING
    last_pass_at: datetime | None   # when a pass last finished
    last_ok_pass_at: datetime | None
    since: datetime | None          # since when the alarms are not (all) checked: the last good pass, or the start
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
    if row.state == WorkerState.STOPPED:
        reason = STOPPED
    elif age is None or age > limit:
        reason = STALE
    elif row.last_ok_pass_at is None or row.db_now - row.last_ok_pass_at > limit:
        reason = FAILING
    else:
        reason, since = '', None
    return Watch(reason, row.last_pass_at, row.last_ok_pass_at, since, age, row.failed_steps, row)
