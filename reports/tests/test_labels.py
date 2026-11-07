"""One label registry (reports/labels.py) names every key a report's content can hold, as the report pages name it: the
key of every dict the computation writes (reports/compute, read from its code, so a new key cannot slip by), the lice stages
and a notice's narrative. Nothing falls back to the raw key."""
import ast
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from .. import labels
from ..compute import lice, notices


def keys_written():
    """Every string key of a dict literal in reports/compute, and the keys it writes from a list of names."""
    found = set(lice.STAGES) | set(notices.NARRATIVE)
    for path in Path(settings.BASE_DIR, 'reports', 'compute').glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.Dict):
                found |= {key.value for key in node.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)}
    return found - labels.NOT_CONTENT


class LabelRegistryTests(SimpleTestCase):
    def test_every_key_the_computation_writes_has_its_label(self):
        self.assertEqual(sorted(keys_written() - set(labels.FIELDS) - set(labels.RECORDS) - labels.SILENT), [])

    def test_an_unknown_key_is_never_shown_raw(self):
        self.assertEqual(labels.describe('/units/1/no_such_key', {'units': {'1': {'number': 'K-01'}}}),
                         'Unit K-01 · (unnamed figure)')
