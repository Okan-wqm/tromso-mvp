"""Background jobs (core.jobs): Django's task API (`django.tasks`) on a queue in the database, run by `manage.py
run_worker`. A job is written in the caller's transaction (it exists iff the work that asked for it was committed),
a waiting job of the same kind and arguments is not queued twice, one job of a key runs at a time (the database
refuses a second), a failure is tried again later up to a limit and then stays visible as dead, a worker that dies
leaves a lease that runs out and the job is taken again, and /healthz says whether the worker is alive."""
import json
from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.tasks import TaskResultStatus, task
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import jobs
from .models import Job, WorkerBeat

CALLS = []


@task
def add(a, b):
    CALLS.append((a, b))
    return a + b


@task
def boom():
    raise RuntimeError('the disk is full')


@task
def tick(period):
    CALLS.append(period)


class JobCase(TestCase):
    def setUp(self):
        CALLS.clear()


class EnqueueTests(JobCase):
    def test_a_task_is_queued_as_a_row_with_its_arguments(self):
        result = add.enqueue(2, b=3)
        job = Job.objects.get()
        self.assertEqual((str(job.id), job.kind, job.status, job.payload, job.attempts),
                         (result.id, 'core.tests_jobs.add', 'queued', {'args': [2], 'kwargs': {'b': 3}}, 0))
        self.assertEqual(result.status, TaskResultStatus.READY)
        self.assertEqual(CALLS, [])                          # nothing runs in the request

    def test_a_job_exists_only_if_the_transaction_that_asked_for_it_commits(self):
        with self.assertRaises(ZeroDivisionError), transaction.atomic():
            add.enqueue(1, 1)
            1 / 0
        self.assertFalse(Job.objects.exists())

    def test_the_same_waiting_job_is_not_queued_twice(self):
        first, second = add.enqueue(1, 2), add.enqueue(1, 2)
        add.enqueue(1, 3)
        self.assertEqual(first.id, second.id)
        self.assertEqual(Job.objects.count(), 2)

    def test_a_deferred_job_waits_for_its_time(self):
        later = timezone.now() + timedelta(hours=1)
        add.using(run_after=later).enqueue(1, 2)
        self.assertEqual(Job.objects.get().run_after, later)
        self.assertIsNone(jobs.run_one('w1'))

    def test_the_result_is_read_back_by_id(self):
        result = add.enqueue(4, 5)
        jobs.run_one('w1')
        found = add.get_result(result.id)
        self.assertEqual((found.status, found.return_value, found.attempts), (TaskResultStatus.SUCCESSFUL, 9, 1))


class WorkerTests(JobCase):
    def test_a_job_runs_once_and_is_done(self):
        add.enqueue(2, 3)
        self.assertIsNotNone(jobs.run_one('w1'))
        self.assertIsNone(jobs.run_one('w1'))
        job = Job.objects.get()
        self.assertEqual((job.status, job.attempts, job.worker, job.lease_until), ('done', 1, 'w1', None))
        self.assertIsNotNone(job.finished_at)
        self.assertEqual(CALLS, [(2, 3)])

    def test_a_failure_is_tried_again_later_and_then_stays_dead(self):
        boom.enqueue()
        Job.objects.update(max_attempts=2)
        jobs.run_one('w1')
        job = Job.objects.get()
        self.assertEqual((job.status, job.attempts), ('queued', 1))
        self.assertIn('the disk is full', job.last_error)
        self.assertGreater(job.run_after, timezone.now())
        self.assertIsNone(jobs.run_one('w1'))                # not before its time
        Job.objects.update(run_after=timezone.now())
        jobs.run_one('w1')
        job.refresh_from_db()
        self.assertEqual((job.status, job.attempts), ('dead', 2))
        self.assertIsNotNone(job.finished_at)

    def test_a_job_of_an_unknown_kind_fails_without_retries(self):
        Job.objects.create(kind='core.tests_jobs.gone', key='x', payload={'args': [], 'kwargs': {}},
                           run_after=timezone.now())
        jobs.run_one('w1')
        job = Job.objects.get()
        self.assertEqual((job.status, job.attempts), ('failed', 1))
        self.assertIn('core.tests_jobs.gone', job.last_error)

    def test_a_lease_that_ran_out_puts_the_job_back_or_kills_it_when_its_tries_are_spent(self):
        add.enqueue(1, 1)
        boom.enqueue()
        past = timezone.now() - timedelta(seconds=1)
        Job.objects.filter(kind__endswith='add').update(status='running', attempts=1, lease_until=past, worker='gone')
        Job.objects.filter(kind__endswith='boom').update(status='running', attempts=5, lease_until=past, worker='gone')
        self.assertEqual(jobs.reap(), 2)
        self.assertEqual(dict(Job.objects.values_list('kind', 'status')),
                         {'core.tests_jobs.add': 'queued', 'core.tests_jobs.boom': 'dead'})
        self.assertIn('lease', Job.objects.get(kind__endswith='boom').last_error)

    def test_one_job_of_a_key_runs_at_a_time(self):
        add.enqueue(1, 1)
        Job.objects.update(status='running', attempts=1, lease_until=timezone.now() + timedelta(minutes=5))
        add.enqueue(1, 1)                                   # the same work asked again while it runs: queued
        self.assertEqual(Job.objects.filter(status='queued').count(), 1)
        self.assertIsNone(jobs.run_one('w2'))               # waits for the running one
        with self.assertRaises(IntegrityError), transaction.atomic():
            Job.objects.filter(status='queued').update(status='running')

    def test_a_status_outside_the_list_is_refused(self):
        add.enqueue(1, 1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Job.objects.update(status='paused')

    def test_a_periodic_kind_is_queued_once_per_period(self):
        every = [(tick, timedelta(hours=1))]
        now = timezone.now().replace(minute=10)
        self.assertEqual(jobs.enqueue_periodic(every, now), 1)
        self.assertEqual(jobs.enqueue_periodic(every, now + timedelta(minutes=20)), 0)
        jobs.run_one('w1')
        self.assertEqual(jobs.enqueue_periodic(every, now + timedelta(minutes=30)), 0)    # done in this period
        self.assertEqual(jobs.enqueue_periodic(every, now + timedelta(hours=1)), 1)

    def test_the_worker_command_beats_and_runs_what_is_due(self):
        add.enqueue(1, 2)
        out = StringIO()
        call_command('run_worker', '--once', '--name', 'w9', stdout=out)
        self.assertEqual(Job.objects.get().status, 'done')
        self.assertTrue(WorkerBeat.objects.filter(name='w9').exists())
        self.assertIn('1 job', out.getvalue())


class HealthTests(JobCase):
    def health(self):
        response = self.client.get(reverse('healthz'))
        return response.status_code, json.loads(response.content)

    def test_without_a_worker_beat_the_health_is_not_ok(self):
        status, body = self.health()
        self.assertEqual((status, body['database'], body['worker_beat_age_s']), (503, 'ok', None))

    def test_a_fresh_beat_is_ok_and_dead_and_waiting_jobs_are_counted(self):
        WorkerBeat.objects.create(name='w1', beat_at=timezone.now())
        boom.enqueue()
        Job.objects.update(status='dead')
        add.enqueue(1, 1)
        Job.objects.filter(status='queued').update(run_after=timezone.now() - timedelta(minutes=3))
        status, body = self.health()
        self.assertEqual((status, body['dead_jobs']), (200, 1))
        self.assertGreaterEqual(body['oldest_queued_s'], 179)

    def test_a_stale_beat_is_not_ok(self):
        WorkerBeat.objects.create(name='w1', beat_at=timezone.now() - timedelta(minutes=10))
        self.assertEqual(self.health()[0], 503)

    @override_settings(WORKER_STALE_SECONDS=3600)
    def test_the_stale_limit_is_a_setting(self):
        WorkerBeat.objects.create(name='w1', beat_at=timezone.now() - timedelta(minutes=10))
        self.assertEqual(self.health()[0], 200)
