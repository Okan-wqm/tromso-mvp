"""Shared test helpers for the knowledge tabs: real PDFs built in memory, what the dialogs post, roles."""
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from farm.tests.helpers import role

LIBRARIAN = ('view_document', 'add_document', 'change_document', 'delete_document', 'view_knowledgeentry',
             'add_knowledgeentry', 'change_knowledgeentry', 'delete_knowledgeentry', 'view_auditlog')


def _pdf_string(text):
    """A line as a PDF literal string in WinAnsi (Latin-1 covers Norwegian letters), with ( ) \\ escaped."""
    raw = text.encode('cp1252')
    return b'(' + raw.replace(b'\\', b'\\\\').replace(b'(', b'\\(').replace(b')', b'\\)') + b')'


def make_pdf(*pages, first_label=None):
    """A real PDF, one page per argument: a text is written on its page in Helvetica, line by line; None makes a
    page with a filled box and no text, as a scanned page's image would be. `first_label` numbers the pages from
    that number (their page labels, as a journal's PDF has)."""
    count = len(pages)
    objects = {}
    labels = f' /PageLabels << /Nums [0 << /S /D /St {first_label} >>] >>' if first_label else ''
    objects[1] = f'<< /Type /Catalog /Pages 2 0 R{labels} >>'.encode()
    kids = ' '.join(f'{4 + 2 * i} 0 R' for i in range(count))
    objects[2] = f'<< /Type /Pages /Kids [{kids}] /Count {count} >>'.encode()
    objects[3] = b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>'
    for i, text in enumerate(pages):
        page, content = 4 + 2 * i, 5 + 2 * i
        if text is None:
            stream = b'0.5 g 72 500 300 200 re f'
        else:
            lines = b' '.join(_pdf_string(line) + b' Tj T*' for line in text.split('\n'))
            stream = b'BT /F1 12 Tf 16 TL 72 720 Td ' + lines + b' ET'
        objects[page] = (f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> '
                         f'/Contents {content} 0 R >>').encode()
        objects[content] = b'<< /Length %d >>\nstream\n' % len(stream) + stream + b'\nendstream'
    out = bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
    offsets = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += b'%d 0 obj\n' % number + objects[number] + b'\nendobj\n'
    xref = len(out)
    out += b'xref\n0 %d\n0000000000 65535 f \n' % (len(objects) + 1)
    for number in sorted(objects):
        out += b'%010d 00000 n \n' % offsets[number]
    out += b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(objects) + 1, xref)
    return bytes(out)


def upload(content=None, name='article.pdf', content_type='application/pdf'):
    """A file as the browser sends it; by default a one-page PDF with text."""
    return SimpleUploadedFile(name, make_pdf('Carbon dioxide in RAS') if content is None else content,
                              content_type=content_type)


def document_data(**overrides):
    """What the document dialog posts. `topics` and `species` are lists, posted as several values."""
    data = {
        'title': 'Carbon dioxide and the growth of Atlantic salmon', 'authors': '', 'year': '', 'venue': '',
        'volume': '', 'issue': '', 'page_range': '', 'doi': '', 'url': '', 'abstract': '', 'language': '',
        'topics': [], 'species': [],
    }
    data.update(overrides)
    return data


def entry_data(**overrides):
    """What the knowledge entry dialog posts, for a source in a library document unless told otherwise."""
    data = {
        'statement': 'In Atlantic salmon under 50 g, free CO2 above 15 mg/L leads to nephrocalcinosis.',
        'topics': ['water_quality'], 'species': [], 'source_kind': 'document', 'document': '', 'pages': '',
        'section': '', 'quote': '', 'citation': '', 'url': '', 'expert': '', 'observed_on': '',
    }
    data.update(overrides)
    return data


class KnowledgeTestCase(TestCase):
    """A signed-in librarian, and uploads stored in a folder of the test's own (MEDIA_ROOT), removed after it."""

    def setUp(self):
        self.media = tempfile.mkdtemp(prefix='knowledge-media-')
        media_settings = override_settings(MEDIA_ROOT=self.media)
        media_settings.enable()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        self.addCleanup(media_settings.disable)
        self.user = get_user_model().objects.create_user('kari', 'kari@example.com', 'x')
        self.user.groups.add(role('Librarian', *LIBRARIAN))
        self.client.force_login(self.user)

    def errors(self, response):
        self.assertEqual(response.status_code, 200, 'the form was expected to be refused')
        return response.context['form'].errors
