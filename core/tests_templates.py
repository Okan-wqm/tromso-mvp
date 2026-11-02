"""Template rules every page relies on."""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

# Django's {# #} comment is one line only: a {# that does not close on its own line is printed on the
# page as text (it once showed in the unit drawer). Longer comments use {% comment %} … {% endcomment %}.
OPEN_COMMENT = re.compile(r'\{#(?!.*#\})')


class TemplateCommentTests(SimpleTestCase):
    def test_no_comment_spans_lines(self):
        found = []
        for directory in [*settings.TEMPLATES[0]['DIRS'], *Path(settings.BASE_DIR).glob('*/templates')]:
            for path in sorted(Path(directory).rglob('*.html')):
                for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                    if OPEN_COMMENT.search(line):
                        found.append(f'{path.relative_to(settings.BASE_DIR)}:{number}')
        self.assertEqual(found, [], 'a {# comment must close on its own line; use {% comment %} for longer ones')
