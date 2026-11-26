"""The go-live package's files hold together (deploy/, docker/testrunner.Dockerfile stage `web`, docs/ops/): the
production image holds every application, every image a server runs is pinned by digest, and no secret is in the
repository. What the files do is proved by the production stack's workflow (.github/workflows/go-live-stack.yml)."""
import re
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.test import SimpleTestCase

BASE = Path(settings.BASE_DIR)
DOCKERFILES = [BASE / 'docker' / 'testrunner.Dockerfile', BASE / 'deploy' / 'db' / 'Dockerfile']
COMPOSE = BASE / 'deploy' / 'compose.yml'


def web_stage():
    text = (BASE / 'docker' / 'testrunner.Dockerfile').read_text(encoding='utf-8')
    start = text.index('FROM runner AS web')
    end = text.index('\nFROM ', start + 1)
    return text[start:end]


class WebImageTests(SimpleTestCase):
    def test_the_web_image_holds_every_application_of_the_project(self):
        own = sorted({Path(config.path).relative_to(BASE).parts[0] for config in apps.get_app_configs()
                      if Path(config.path).is_relative_to(BASE)} - {'.venv'})
        self.assertIn('core', own)
        stage = web_stage()
        ignore = (BASE / '.dockerignore').read_text(encoding='utf-8').splitlines()
        for folder in [*own, 'config', 'templates', 'static', 'locale']:
            with self.subTest(folder=folder):
                self.assertIn(f'COPY {folder}/ ./{folder}/', stage)
                self.assertIn(f'!{folder}/', ignore)
        # what runs at start: the chemistry core's expected build (core.E001), the server's files, the grants
        for path in ('chemcore/EXPECTED', 'deploy/web/', 'deploy/db/sql/grants.sql', 'manage.py'):
            self.assertIn(f'COPY {path} ./{path}', stage)

    def test_the_web_image_runs_as_an_unprivileged_user_and_checks_itself(self):
        stage = web_stage()
        self.assertRegex(stage, r'\nUSER balik\n')
        self.assertIn('HEALTHCHECK', stage)
        self.assertIn('collectstatic', stage)
        self.assertIn('"/app/deploy/web/gunicorn.conf.py"', stage)

    def test_a_build_without_a_target_is_still_the_test_runner(self):
        text = (BASE / 'docker' / 'testrunner.Dockerfile').read_text(encoding='utf-8')
        self.assertEqual(re.findall(r'^FROM .* AS (\S+)$', text, re.M)[-1], 'tests')


class PinnedImagesTests(SimpleTestCase):
    def test_every_base_image_is_pinned_by_digest(self):
        for dockerfile in DOCKERFILES:
            text = dockerfile.read_text(encoding='utf-8')
            stages = set(re.findall(r'^FROM .* AS (\S+)$', text, re.M))
            for line in re.findall(r'^FROM (\S+)', text, re.M):
                with self.subTest(dockerfile=dockerfile.name, image=line):
                    self.assertTrue(line in stages or re.search(r'@sha256:[0-9a-f]{64}$', line), line)

    def test_every_image_the_stack_pulls_is_pinned_by_digest(self):
        images = re.findall(r'^\s+image:\s*(\S+)', COMPOSE.read_text(encoding='utf-8'), re.M)
        self.assertTrue(images)
        for image in images:
            with self.subTest(image=image):
                # the farm's own images are built from the pinned Dockerfiles above (their tag names the release)
                own = re.fullmatch(r'\$\{[A-Z_]+_IMAGE:-balik-[a-z]+:[a-z0-9.-]+\}', image)
                self.assertTrue(own or re.search(r'@sha256:[0-9a-f]{64}$', image), image)


class SecretsTests(SimpleTestCase):
    def test_the_secrets_and_the_farms_settings_stay_out_of_the_repository(self):
        ignored = (BASE / '.gitignore').read_text(encoding='utf-8').splitlines()
        for path in ('/deploy/secrets/', '/deploy/farm.env'):
            self.assertIn(path, ignored)

    def test_no_key_or_certificate_is_in_the_package(self):
        for path in [*BASE.joinpath('deploy').rglob('*'), *BASE.joinpath('docs', 'ops').rglob('*')]:
            if path.is_file() and 'secrets' not in path.relative_to(BASE).parts:
                with self.subTest(path=str(path.relative_to(BASE))):
                    text = path.read_text(encoding='utf-8', errors='replace')
                    self.assertNotRegex(text, r'-----BEGIN [A-Z ]*(PRIVATE KEY|CERTIFICATE)-----')
                    self.assertNotRegex(text, r'eyJhIjoi[A-Za-z0-9_-]{20,}')      # a Cloudflare tunnel token

    def test_the_example_settings_hold_placeholders_only(self):
        values = [line.split('=', 1)[1] for line in
                  (BASE / 'deploy' / 'farm.env.example').read_text(encoding='utf-8').splitlines()
                  if '=' in line and not line.lstrip().startswith('#')]
        hosts = {host for value in values for host in re.findall(r'\b(?:[a-z0-9-]+\.)+[a-z]{2,}\b', value)}
        self.assertTrue(hosts)
        for host in hosts:
            with self.subTest(host=host):
                self.assertTrue(host.endswith('.invalid'), host)
