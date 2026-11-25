"""The browser tests' recorded fixtures (frontend/test/pages) are what the code renders today: the test world is built in
the test run's database with the clock pinned to its MOMENT, every fixture is rendered by the one function its recorder
uses (core.recorded_fixtures.render_all), and each committed file must say the same once what varies from run to run is
put in a fixed form (record ids, a page's nonce and token, the assets' versions). Every database sequence is pushed far
ahead first (AHEAD), as the whole suite's earlier tests push it, so a number the database counts (a row id, a channel
number) that a fixture still writes as a figure fails here in every run, not only in the whole suite. A changed template, reader, model,
form or word that a fixture shows fails here, naming the file and its first differing line: run
scripts/record_test_world.sh and commit what it writes. A change no fixture shows does not."""
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.utils import translation

from core import recorded_fixtures

PAGES = Path(settings.BASE_DIR) / 'frontend' / 'test' / 'pages'
AHEAD = 7919     # how far every sequence is pushed before the world is built: never the recorder's numbers


def push_sequences_ahead(by=AHEAD):
    """Moves every sequence of the public schema `by` numbers on (sequences are not rolled back with the test)."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT sequence_name FROM information_schema.sequences WHERE sequence_schema = 'public'")
        for (name,) in cursor.fetchall():
            cursor.execute('SELECT setval(%s, nextval(%s) + %s)', [f'public."{name}"', f'public."{name}"', by])


# the islands' build in the test run is the committed manifest the list pages' tests use; its file names are put in a
# fixed form anyway (normalised)
@override_settings(ALLOWED_HOSTS=['localhost', 'testserver'],
                   ISLANDS_MANIFEST=str(Path(settings.BASE_DIR) / 'core' / 'testdata' / 'islands-company-manifest.json'))
class FixturesAreFreshTests(TestCase):
    def test_every_recorded_fixture_is_what_the_code_renders_today(self):
        from core.test_world import MOMENT, ticking, world
        push_sequences_ahead()
        with translation.override('en'):
            with mock.patch('django.utils.timezone.now', side_effect=ticking()):     # as the recorder builds it
                admin = get_user_model().objects.create_superuser('test.admin', 'test.admin@example.com', 'x')
                world(admin)
            with mock.patch('django.utils.timezone.now', return_value=MOMENT):
                texts, _missing = recorded_fixtures.render_all(admin)
        self.assertGreaterEqual(len(texts), 25, 'the oracle, 3 x 3 props files, 15 pages')
        recorded = {path.relative_to(PAGES).as_posix() for path in PAGES.rglob('*')
                    if path.relative_to(PAGES).as_posix() in texts or path.parent.name == 'panel'}
        self.assertEqual(recorded - texts.keys(), set(), 'a recorded page the recorder no longer renders')
        stale = [recorded_fixtures.first_difference(name, (PAGES / name).read_text(encoding='utf-8')
                                                    if (PAGES / name).is_file() else '', text)
                 for name, text in sorted(texts.items())]
        stale = [each for each in stale if each]
        self.assertEqual(stale, [], 'run scripts/record_test_world.sh and commit what it writes')

    def test_what_varies_is_put_in_a_fixed_form_and_nothing_else(self):
        one = ('<script nonce="abc">x</script><a href="/tasks/3f1e2d4c-1111-4222-8333-944455556666/check/12/?v=99">'
               '<li id="m40"><span>23.11.2026 13:41</span>')
        two = ('<script nonce="zzz">x</script><a href="/tasks/0a0b0c0d-1111-4222-8333-944455556666/check/97/?v=17">'
               '<li id="m3"><span>23.11.2026 13:41</span>')
        self.assertEqual(recorded_fixtures.normalised(one), recorded_fixtures.normalised(two))
        self.assertIsNone(recorded_fixtures.first_difference('panel/x.html', one, two))
        changed = two.replace('13:41', '13:42')
        self.assertIn('panel/x.html, line 1', recorded_fixtures.first_difference('panel/x.html', one, changed))
        # a person in a list by their user name, never a number that only looks like an id
        people = {'7': [('role', {'Test role'}, 'Test role'), ('user', {'test.admin', 'Test Admin'}, 'test.admin')]}
        self.assertEqual(recorded_fixtures._stable_people('<option value="7">Test Admin</option><option value="7">7 kg</option>'
                                                          '{"value": "7", "label": "test.admin"}', people),
                         '<option value="user:test.admin">Test Admin</option><option value="7">7 kg</option>'
                         '{"value": "user:test.admin", "label": "test.admin"}')
        # JSON written on one line (the form oracle) is compared a value a line
        self.assertTrue(recorded_fixtures.first_difference('form-oracle.json', '{"cases": [1]}', '{"cases": [2]}')
                        .startswith("form-oracle.json, line 3: recorded '  1'"))
