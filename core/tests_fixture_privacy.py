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
