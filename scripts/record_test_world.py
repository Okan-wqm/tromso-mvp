"""Records the browser tests' fixtures from the TEST WORLD, never from the development database: every file
core/recorded_fixtures.py renders (render_all: the form oracle, the Overview's props, the list pages' and the production
panel's props, the pages the server draws), under frontend/test/pages. core/tests_fixtures_fresh.py renders them again in
the test run and fails when a committed one is not what the code renders today: run this, and commit what it writes.

    --check     write nothing: compare the committed files with a fresh rendering and say the first difference of each

Every person, address and name in them is a fixture value (names "Test …", addresses @example.com); the guard
core/tests_fixture_privacy.py fails on any other e-mail domain under frontend/test and core/testdata.

Run it in the test runner's image against a THROWAWAY database (scripts/record_test_world.sh starts one, migrates it, runs
this and removes it); it refuses any database not named `test_world`. Everything is made in one transaction that is
rolled back, with the clock pinned to the test world's MOMENT."""
import os
import sys
from importlib import import_module
from pathlib import Path
from unittest import mock

sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django  # noqa: E402

django.setup()
from django.conf import settings  # noqa: E402
from django.db import connection, transaction  # noqa: E402

if connection.settings_dict['NAME'] != 'test_world':
    sys.exit('refused: this records fixtures only from the throwaway database test_world (scripts/record_test_world.sh)')

from django.contrib.auth import get_user_model  # noqa: E402
from django.utils import translation  # noqa: E402

import_module(settings.ROOT_URLCONF)
from core.recorded_fixtures import first_difference, render_all  # noqa: E402
from core.test_world import MOMENT, world  # noqa: E402

OUT = Path('/app/frontend/test/pages')
CHECK = '--check' in sys.argv[1:]


class Rollback(Exception):
    pass


try:
    with transaction.atomic(), mock.patch('django.utils.timezone.now', return_value=MOMENT), translation.override('en'):
        admin = get_user_model().objects.create_superuser('test.admin', 'test.admin@example.com', 'x')
        made = world(admin)
        texts, missing = render_all(admin)
        raise Rollback
except Rollback:
    pass
print('made:', '; '.join(made))
print(f'no record to edit for: {", ".join(missing)}')
if CHECK:
    found = [first_difference(name, (OUT / name).read_text(encoding='utf-8') if (OUT / name).is_file() else '', text)
             for name, text in sorted(texts.items())]
    found = [each for each in found if each]
    print('\n'.join(found) if found else f'all {len(texts)} fixtures are what the code renders')
    sys.exit(1 if found else 0)
for name, text in texts.items():
    (OUT / name).parent.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(text, encoding='utf-8', newline='\n')
print(f'wrote {len(texts)} fixtures')
