"""The recorded fixtures of the browser tests are as fresh as their sources (core/recorded.py): every source the recorder
renders them with has the hash it had when they were recorded. A changed template, reader, form, catalog or test world
fails here until scripts/record_test_world.sh records them again (it writes frontend/test/pages/recorded-from.json)."""
import json

from django.test import SimpleTestCase

from core import recorded


class RecordedFixturesTests(SimpleTestCase):
    def test_the_fixtures_were_recorded_from_the_sources_as_they_are(self):
        self.assertTrue(recorded.RECORD.is_file(), 'no recorded-from.json: run scripts/record_test_world.sh')
        then, now = json.loads(recorded.RECORD.read_text(encoding='utf-8')), recorded.digest()
        changed = sorted(name for name in then.keys() | now.keys() if then.get(name) != now.get(name))
        self.assertEqual(changed, [], 'these sources changed since the fixtures were recorded: run '
                                      'scripts/record_test_world.sh and commit what it writes')

    def test_the_sources_are_found(self):
        names = recorded.files()
        for wanted in ('scripts/record_test_world.py', 'core/listprops.py', 'templates/tasks/task_list_next.html',
                       'locale/nb/LC_MESSAGES/django.po', 'hr/resources/leave.py'):
            self.assertIn(wanted, names)
