"""No real person's address in the repository's test fixtures (owner rule: users' e-mail addresses are private, and no data
of the development database goes to GitHub). Every e-mail address in the browser tests' sources and fixtures
(frontend/test, frontend/islands) and in core/testdata must be a fixture address: example.com or a .example domain
(RFC 2606). A file recorded from the development database (form-oracle.json was, once) fails here; fixtures are recorded
from the test world (scripts/record_test_world.sh)."""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ROOT = Path(settings.BASE_DIR)
SCANNED = ('frontend/test', 'frontend/islands', 'core/testdata')
TEXT = {'.json', '.ts', '.tsx', '.js', '.html', '.txt', '.md', '.py', '.css', '.csv'}
ADDRESS = re.compile(r'[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)')
ALLOWED = re.compile(r'(?:^|\.)example\.com$|\.example$|^example$', re.I)


def addresses(text):
    """[(address, domain)] of the e-mail addresses in `text`."""
    return [(found.group(0), found.group(1)) for found in ADDRESS.finditer(text)]


class FixturePrivacyTests(SimpleTestCase):
    def test_every_address_in_the_fixtures_is_a_fixture_address(self):
        found = []
        for folder in SCANNED:
            for path in (ROOT / folder).rglob('*'):
                if path.suffix not in TEXT or not path.is_file() or 'node_modules' in path.parts:
                    continue
                for address, domain in addresses(path.read_text(encoding='utf-8', errors='replace')):
                    if not ALLOWED.search(domain):
                        found.append(f'{path.relative_to(ROOT)}: {address}')
        self.assertEqual(found, [])

    def test_the_guard_sees_a_real_address_and_lets_a_fixture_one_pass(self):
        self.assertEqual([domain for _address, domain in addresses('a b@company.no c')], ['company.no'])
        for fixture in ('kari@example.com', 'bergen@nordhav.example', 'x@sub.example.com'):
            self.assertTrue(ALLOWED.search(addresses(fixture)[0][1]), fixture)
        for real in ('owner@company.no', 'x@example.com.evil.org', 'y@gmail.com'):
            self.assertFalse(ALLOWED.search(addresses(real)[0][1]), real)


# The recorded fixtures (scripts/record_test_world.py) and the fields in them that name a person: every such name is one of
# the test world's people ("Test …", an account test.…), or "system", the activity log's name for a write no person made
# (core.audit: a record the test world makes in the models); never anyone else's.
RECORDED = ROOT / 'frontend' / 'test' / 'pages'
PERSON_FIELDS = {'employee', 'user', 'manager', 'assignees', 'site_manager', 'examined_by', 'asked_by'}
TEST_PERSON = re.compile(r'^(?:Test |test\.|system$)')


def people_in(value, found=None, person=False):
    """Every person's name in a recorded payload: the options of a field that chooses a person, a `by` (an activity entry's
    author), a `manager`, and the first cell of a people list."""
    found = [] if found is None else found
    if isinstance(value, dict):
        widget = value.get('widget')
        if isinstance(widget, dict) and value.get('name') in PERSON_FIELDS:
            for group in widget.get('groups') or ():
                found += [option['label'] for option in group['options'] if option.get('value') not in ('', None)]
        for key, item in value.items():
            if key in ('by', 'manager') and isinstance(item, dict) and isinstance(item.get('name'), str):
                found.append(item['name'])
            elif key == 'employee' and isinstance(item, dict) and isinstance(item.get('text'), str):
                found.append(item['text'])
            else:
                people_in(item, found)
    elif isinstance(value, list):
        for item in value:
            people_in(item, found)
    return found


class RecordedPeopleTests(SimpleTestCase):
    def test_every_person_in_the_recorded_fixtures_is_one_of_the_test_worlds(self):
        import json
        files = sorted(RECORDED.glob('*.json'))
        self.assertTrue(any(path.name == 'form-oracle.json' for path in files))
        strangers, seen = [], 0
        for path in files:
            names = people_in(json.loads(path.read_text(encoding='utf-8')))
            seen += len(names)
            strangers += [f'{path.name}: {name}' for name in names if not TEST_PERSON.match(name)]
        self.assertGreater(seen, 0, 'the recorded fixtures name the test world\'s people')
        self.assertEqual(strangers, [])

    def test_the_name_rule_sees_a_stranger(self):
        payload = {'fields': [{'name': 'employee', 'widget': {'groups': [{'options': [
            {'value': '1', 'label': 'Test Person'}, {'value': '2', 'label': 'Kari Nordmann'}]}]}}],
            'entries': [{'by': {'name': 'test.admin'}}], 'rows': [{'cells': {'employee': {'text': 'Ola Hansen'}}}]}
        self.assertEqual([name for name in people_in(payload) if not TEST_PERSON.match(name)], ['Kari Nordmann', 'Ola Hansen'])
