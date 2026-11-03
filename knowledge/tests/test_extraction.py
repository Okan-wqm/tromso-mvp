"""Reading a PDF's text (knowledge.extraction) on real PDFs built in the test."""
import io

from django.test import SimpleTestCase
from pypdf import PdfReader, PdfWriter

from ..extraction import FAILED, NO_TEXT, TEXT_FOUND, clean, read_pdf
from .helpers import make_pdf


def encrypted(content, user_password, owner_password='owner-secret'):
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(content)))
    writer.encrypt(user_password=user_password, owner_password=owner_password, algorithm='AES-128')
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


class ReadPdfTests(SimpleTestCase):
    def test_the_text_of_each_page_is_read(self):
        stream = io.BytesIO(make_pdf('Carbon dioxide in RAS\nabove 15 mg/L', None, 'Bjørn Olsen, Tromsø'))
        reading = read_pdf(stream)
        self.assertEqual(reading.status, TEXT_FOUND)
        self.assertEqual(reading.page_count, 3)
        self.assertEqual([page.number for page in reading.pages], [1, 2, 3])
        self.assertIn('Carbon dioxide in RAS', reading.pages[0].text)
        self.assertIn('above 15 mg/L', reading.pages[0].text)
        self.assertEqual(reading.pages[1].text, '')
        self.assertIn('Bjørn Olsen, Tromsø', reading.pages[2].text)
        self.assertEqual(reading.error, '')
        self.assertEqual(stream.tell(), 0, 'the stream is left at its start, ready to be stored')

    def test_a_pdf_without_text_is_no_text_not_an_error(self):
        reading = read_pdf(io.BytesIO(make_pdf(None, None)))
        self.assertEqual((reading.status, reading.page_count, reading.error), (NO_TEXT, 2, ''))

    def test_a_damaged_pdf_is_recorded_as_failed_with_its_reason(self):
        reading = read_pdf(io.BytesIO(b'%PDF-1.4\nthis is not a PDF body at all'))
        self.assertEqual(reading.status, FAILED)
        self.assertIsNone(reading.page_count)
        self.assertEqual(reading.pages, [])
        self.assertTrue(reading.error)
        self.assertLessEqual(len(reading.error), 500)

    def test_a_password_protected_pdf_cannot_be_read(self):
        reading = read_pdf(io.BytesIO(encrypted(make_pdf('Secret'), user_password='open-sesame')))
        self.assertEqual((reading.status, reading.error), (FAILED, 'The PDF is protected by a password.'))

    def test_a_pdf_with_an_owner_password_only_is_read(self):
        # Publishers lock printing and copying with an owner password; anyone may open it (AES needs cryptography).
        reading = read_pdf(io.BytesIO(encrypted(make_pdf('Open to read'), user_password='')))
        self.assertEqual(reading.status, TEXT_FOUND)
        self.assertIn('Open to read', reading.pages[0].text)

    def test_page_labels_are_kept_when_the_pdf_has_its_own(self):
        reading = read_pdf(io.BytesIO(make_pdf('First', 'Second', first_label=233)))
        self.assertEqual([page.label for page in reading.pages], ['233', '234'])
        plain = read_pdf(io.BytesIO(make_pdf('First', 'Second')))
        self.assertEqual([page.label for page in plain.pages], ['', ''])

    def test_text_is_normalised_and_cleaned(self):
        self.assertEqual(clean('eﬃciency of CO₂ stripping\x00\x07'), 'efficiency of CO2 stripping')
        self.assertEqual(clean('line one\nline two\ttab\fpage'), 'line one\nline two\ttab\fpage')
        self.assertEqual(clean(None), '')
