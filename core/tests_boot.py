"""The server starts as a server, not as a management command (review F1). A command reads as the system
(core.sealing.enter_process_system), so the test suite and every other command never met what a server meets: the
project imported and its URLconf loaded with nobody looking, then a request read as its person. A queryset a module or
a class builds when it is imported (a form's choices) must not need anyone looking: the seal reads the person when the
SQL is compiled. These start the project in a process of its own, as a server does."""
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.test import SimpleTestCase
from django.urls import reverse

ROOT = Path(settings.BASE_DIR)
SETUP = ('import django, os; os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings"); django.setup(); '
         'from django.urls import get_resolver; get_resolver().url_patterns; '
         'import config.wsgi; print("ready")')


def environment():
    """The server's environment: this run's database (each parallel worker has its own copy), no command."""
    env = dict(os.environ)
    env['DB_NAME'] = connection.settings_dict['NAME']
    return env


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


class BootTests(SimpleTestCase):
    databases = {'default'}

    def test_the_project_sets_up_and_loads_its_urls_with_nobody_looking(self):
        done = subprocess.run([sys.executable, '-c', SETUP], cwd=ROOT, env=environment(), capture_output=True,
                              text=True, timeout=300)
        self.assertEqual(done.returncode, 0, done.stderr[-3000:])
        self.assertIn('ready', done.stdout)

    def test_runserver_starts_and_answers_a_request(self):
        port = free_port()
        server = subprocess.Popen([sys.executable, 'manage.py', 'runserver', f'127.0.0.1:{port}', '--noreload'],
                                  cwd=ROOT, env=environment(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True)
        try:
            answer, deadline = None, time.monotonic() + 240
            while answer is None and time.monotonic() < deadline:
                if server.poll() is not None:
                    self.fail(f'runserver stopped: {server.stdout.read()[-3000:]}')
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{port}{reverse("login")}', timeout=10) as response:
                        answer = (response.status, response.read())
                except OSError:
                    time.sleep(1)
            self.assertIsNotNone(answer, 'runserver did not answer in four minutes')
            self.assertEqual(answer[0], 200)
        finally:
            server.terminate()
            try:
                server.wait(timeout=30)
            except subprocess.TimeoutExpired:
                server.kill()
            server.stdout.close()
