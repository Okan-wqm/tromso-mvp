"""The background worker (core.jobs): beats, puts back the jobs of a worker that died, queues the periodic tasks
(core.tasks.PERIODIC; no cron or Task Scheduler needed) and runs the due jobs one at a time. Stops after the job it is
running on Ctrl+C or SIGTERM. In Docker it is the `worker` service; in development run it beside runserver."""
import signal
import socket
import threading

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from core import jobs, tasks


class Command(BaseCommand):
    help = 'Runs the background jobs (core.jobs) until stopped.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Run what is due now, then exit.')
        parser.add_argument('--name', default='', help='The worker\'s name on /healthz (default: host and process).')
        parser.add_argument('--interval', type=float, default=5.0, help='Seconds between two looks when idle.')

    def handle(self, *args, once=False, name='', interval=5.0, **options):
        import os
        name = name or f'{socket.gethostname()}:{os.getpid()}'
        stop = threading.Event()
        if not once:
            for sig in (signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, lambda *_: stop.set())
        ran = 0
        while not stop.is_set():
            if not once:
                close_old_connections()          # a long-lived process: drop a broken or old connection
            jobs.beat(name)
            jobs.reap()
            jobs.enqueue_periodic(tasks.PERIODIC)
            while not stop.is_set() and jobs.run_one(name, lease_thread=not once) is not None:
                ran += 1
                jobs.beat(name)
            if once:
                break
            stop.wait(interval)
        self.stdout.write(f'{ran} job(s) run by {name}.')
