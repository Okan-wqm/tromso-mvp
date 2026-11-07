"""Background jobs on Django's task API (`django.tasks`), queued in the database (`core_job`), run by
`manage.py run_worker` (a second process from the same code: a Docker service, or a Windows process in development).

Why our own backend: Django 6.1 ships only the immediate and dummy backends, and the third-party database backend
(django-tasks-db 0.13, BSD-3) has no retries, no lease for a worker that dies and no unique job (the spike of the
performance plan, perf/MEASURED.md). The rules held here:
- enqueue writes the row in the caller's transaction (an outbox: a job exists iff the work that asked for it
  committed; never `on_commit`, which loses the job if the process dies between);
- a job's key is a hash of its kind and arguments; the database keeps one WAITING and one RUNNING job per key
  (two partial unique indexes), so the same work asked twice waits once, and work asked again while it runs is
  queued once behind it (never folded into the running one, which may have read the old data);
- a claim takes the oldest due job with FOR UPDATE SKIP LOCKED, gives it a lease the worker extends while it runs; a
  lease that runs out (the worker died) puts the job back, or kills it when its tries are spent;
- a failure is tried again with a growing delay up to `max_attempts`, then the job is `dead` and stays visible;
  a job whose code cannot be found fails at once.
Handlers are idempotent and re-read the state they work on. Nothing a person needs for a safety figure waits on one."""
import hashlib
import json
import logging
import threading
import traceback
from datetime import timedelta

from django.db import IntegrityError, connection, transaction
from django.db.models import Exists, OuterRef
from django.tasks import TaskResult, TaskResultStatus
from django.tasks.backends.base import BaseTaskBackend
from django.tasks.base import TaskError
from django.tasks.exceptions import TaskResultDoesNotExist
from django.utils import timezone
from django.utils.json import normalize_json
from django.utils.module_loading import import_string

from .models import Job, JobStatus, WorkerBeat

logger = logging.getLogger(__name__)

LEASE = timedelta(minutes=5)
# The delay before try n+1: 30 s, 1 min, 2 min ... at most an hour.
FIRST_DELAY, LONGEST_DELAY = timedelta(seconds=30), timedelta(hours=1)
STATUS = {JobStatus.QUEUED: TaskResultStatus.READY, JobStatus.RUNNING: TaskResultStatus.RUNNING,
          JobStatus.DONE: TaskResultStatus.SUCCESSFUL, JobStatus.FAILED: TaskResultStatus.FAILED,
          JobStatus.DEAD: TaskResultStatus.FAILED}


def key_of(kind, args, kwargs):
    text = json.dumps([kind, args, kwargs], sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(text.encode()).hexdigest()[:64]


class DatabaseBackend(BaseTaskBackend):
    supports_defer = True
    supports_get_result = True

    def enqueue(self, task, args, kwargs):
        self.validate_task(task)
        args, kwargs = normalize_json(list(args)), normalize_json(dict(kwargs))
        kind = task.module_path
        key = key_of(kind, args, kwargs)
        run_after = task.run_after or timezone.now()
        with transaction.atomic():           # a savepoint inside the caller's transaction, which it commits with
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO core_job (id, kind, key, payload, status, attempts, max_attempts, run_after, worker, "
                    "last_error, created_at) VALUES (gen_random_uuid(), %s, %s, %s, 'queued', 0, 5, %s, '', '', now()) "
                    "ON CONFLICT (kind, key) WHERE status = 'queued' DO NOTHING RETURNING id",
                    [kind, key, json.dumps({'args': args, 'kwargs': kwargs}), run_after])
                found = cursor.fetchone()
        job = Job.objects.get(pk=found[0]) if found else Job.objects.get(kind=kind, key=key, status=JobStatus.QUEUED)
        return self.result_of(job, task)

    def get_result(self, result_id):
        try:
            job = Job.objects.get(pk=result_id)
        except (Job.DoesNotExist, ValueError, TypeError):
            raise TaskResultDoesNotExist(result_id) from None
        return self.result_of(job)

    def result_of(self, job, task=None):
        task = task or import_string(job.kind)
        errors = [TaskError(exception_class_path='builtins.Exception', traceback=job.last_error)] if job.last_error else []
        result = TaskResult(task=task, id=str(job.pk), status=STATUS[job.status], enqueued_at=job.created_at,
                            started_at=job.started_at, last_attempted_at=job.started_at, finished_at=job.finished_at,
                            args=job.payload.get('args', []), kwargs=job.payload.get('kwargs', {}), backend=self.alias,
                            errors=errors, worker_ids=[job.worker] if job.worker else [])
        object.__setattr__(result, '_return_value', job.result)
        return result


def claim(worker):
    """Takes the oldest due job whose key is not running; None when there is none."""
    while True:
        try:
            with transaction.atomic():
                running = Job.objects.filter(kind=OuterRef('kind'), key=OuterRef('key'), status=JobStatus.RUNNING)
                job = (Job.objects.select_for_update(skip_locked=True)
                       .filter(~Exists(running), status=JobStatus.QUEUED, run_after__lte=timezone.now())
                       .order_by('run_after').first())
                if job is None:
                    return None
                now = timezone.now()
                job.status, job.attempts, job.worker = JobStatus.RUNNING, job.attempts + 1, worker
                job.lease_until, job.started_at = now + LEASE, now
                job.save(update_fields=['status', 'attempts', 'worker', 'lease_until', 'started_at'])
                return job
        except IntegrityError:
            continue                          # another worker started the same key at the same moment


def _keep_lease(job, stop):
    """Extends the lease while the job runs, from its own connection."""
    try:
        while not stop.wait(LEASE.total_seconds() / 3):
            Job.objects.filter(pk=job.pk, status=JobStatus.RUNNING).update(lease_until=timezone.now() + LEASE)
    finally:
        connection.close()


def run_one(worker, lease_thread=False):
    """Claims and runs one due job; returns it, or None when nothing was due."""
    job = claim(worker)
    if job is None:
        return None
    stop = threading.Event()
    keeper = None
    if lease_thread:
        keeper = threading.Thread(target=_keep_lease, args=(job, stop), daemon=True)
        keeper.start()
    try:
        try:
            task = import_string(job.kind)
        except ImportError:
            _finish(job, JobStatus.FAILED, error=f'No task {job.kind}: the code that ran it is gone.')
            return job
        try:
            value = task.call(*job.payload.get('args', []), **job.payload.get('kwargs', {}))
        except Exception:
            logger.exception('Job %s (%s) failed', job.pk, job.kind)
            _failed(job, traceback.format_exc())
        else:
            _finish(job, JobStatus.DONE, result=normalize_json(value))
    finally:
        stop.set()
        if keeper is not None:
            keeper.join()
    return job


def _finish(job, status, error='', result=None):
    job.status, job.last_error, job.result = status, error or job.last_error, result
    job.lease_until, job.finished_at = None, timezone.now()
    job.save(update_fields=['status', 'last_error', 'result', 'lease_until', 'finished_at'])


def _failed(job, error):
    if job.attempts >= job.max_attempts:
        _finish(job, JobStatus.DEAD, error=error)
        return
    delay = min(FIRST_DELAY * 2 ** (job.attempts - 1), LONGEST_DELAY)
    _again(job, error, timezone.now() + delay)


def _again(job, error, run_after):
    """Back to waiting, unless the same work already waits (then this one is over: the waiting one does it)."""
    try:
        with transaction.atomic():
            Job.objects.filter(pk=job.pk).update(status=JobStatus.QUEUED, lease_until=None, last_error=error,
                                                 run_after=run_after)
    except IntegrityError:
        Job.objects.filter(pk=job.pk).update(status=JobStatus.FAILED, lease_until=None, finished_at=timezone.now(),
                                             last_error=error + '\nThe same work was asked for again and waits.')
    job.refresh_from_db()


def reap():
    """Running jobs whose lease ran out (their worker died): back to waiting, or dead when their tries are spent.
    Returns how many."""
    count = 0
    for job in Job.objects.filter(status=JobStatus.RUNNING, lease_until__lt=timezone.now()):
        error = f'The worker {job.worker} stopped while it ran (its lease ran out).'
        if job.attempts >= job.max_attempts:
            _finish(job, JobStatus.DEAD, error=error)
        else:
            _again(job, error, timezone.now())
        count += 1
    return count


def period_start(now, every):
    seconds = int(every.total_seconds())
    epoch = int(now.timestamp())
    return epoch - epoch % seconds


def enqueue_periodic(every, now=None):
    """Queues each periodic task once per period: its argument is the period's start, so its key is the same within
    the period, and a job of that key that ran (whatever its outcome) is not queued again. Returns how many."""
    now = now or timezone.now()
    count = 0
    for task, period in every:
        start = period_start(now, period)
        key = key_of(task.module_path, [start], {})
        if not Job.objects.filter(kind=task.module_path, key=key).exists():
            task.enqueue(start)
            count += 1
    return count


def beat(name):
    WorkerBeat.objects.update_or_create(name=name, defaults={'beat_at': timezone.now()})
