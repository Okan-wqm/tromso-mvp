"""What the browser tests' recorded fixtures were made from (scripts/record_test_world.py): every source the recorder renders
them with, and the hash of each. The recorder writes the hashes beside the fixtures (frontend/test/pages/recorded-from.json);
core/tests_recorded_fixtures.py fails when a source has changed since, so a template, a reader, a form, a word of a catalog
or the test world cannot change without the fixtures being recorded again (scripts/record_test_world.sh).

One list for every fixture the recorder writes: the form oracle, the Overview's props, the list pages' props, the
production panel's props and the pages the server draws. A fixture is not compared with a fresh rendering itself: the
test world's record ids, a page's nonce and the real clock of a few rows differ from run to run; its sources do not."""
import hashlib
from pathlib import Path

from django.conf import settings

BASE = Path(settings.BASE_DIR)
RECORD = BASE / 'frontend' / 'test' / 'pages' / 'recorded-from.json'

# The sources, as globs from the repository's root.
SOURCES = (
    # the recorder and the world it records
    'scripts/record_test_world.py', 'core/test_world.py',
    # the form oracle: every tab's form and the server's own field markup (core/tests_formpayload.drawn)
    'core/formpayload.py', 'core/formprops.py', 'core/tests_formpayload.py', 'core/widgets.py', 'core/crud.py',
    '*/forms.py', '*/forms/*.py', 'templates/django/**/*.html', 'templates/registration/_field.html',
    # the Overview's props
    'config/company.py', 'config/company_props.py', 'core/ui.py', 'alarms/read.py',
    # the list pages' props: the shared words and each tab's rows
    'core/listprops.py', '*/resources.py', '*/resources/*.py',
    # the production panel's pages the server draws, and what they include
    'templates/app_base.html', 'templates/ui/*.html', 'templates/crud/_pager.html', 'templates/tasks/*.html',
    'templates/reports/report_list_next.html', 'templates/reports/_report_tabs.html', 'templates/inventory/*.html',
    'templates/messaging/*.html', 'tasks/views.py', 'inventory/views.py', 'messaging/views.py',
    # the words of every fixture in Norwegian and Turkish
    'locale/*/LC_MESSAGES/django.po',
)


def files():
    """The source files, sorted, as paths from the repository's root."""
    found = {path for pattern in SOURCES for path in BASE.glob(pattern) if path.is_file()}
    return sorted(path.relative_to(BASE).as_posix() for path in found)


def digest():
    """{path: sha256} of every source; line ends counted as LF, so a Windows checkout hashes as the CI's does."""
    return {name: hashlib.sha256((BASE / name).read_bytes().replace(b'\r\n', b'\n')).hexdigest() for name in files()}
