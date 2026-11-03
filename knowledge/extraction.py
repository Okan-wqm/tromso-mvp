"""Reading the text of an uploaded PDF, page by page (pypdf).

The text is what the library searches and what the AI agents will later read and cite: it is kept per page,
so a hit, a quote or an agent's citation can say "p. 4". The outcome is one of three, never an exception:

- the text of each page (`TEXT_FOUND`), when at least one page has text;
- no text (`NO_TEXT`): a PDF that opens but holds only images, a scan. It is not an error; its text needs
  OCR, which is not done yet;
- could not be read (`FAILED`), with the reason: a damaged or password-protected file. The PDF is kept all the
  same (a browser may still show it); the reason is shown on the document.

A hostile or broken PDF can make any reader fail in its own way (pypdf raises many kinds of errors), so every
error of the reader becomes `FAILED` with its type and message, recorded on the document: nothing is
swallowed.

Each page's text is normalised to NFKC, so the ligatures a PDF stores (ﬁ, ﬂ, ﬃ) read as the letters people
type and a subscript ₂ as 2 ("CO₂" is found by "CO2"), and control characters are removed: PostgreSQL text
cannot hold NUL, and the search's highlight markers (knowledge.search) can then never occur in a text. Line
breaks, tabs and form feeds stay.
"""
import unicodedata
from dataclasses import dataclass, field

from pypdf import PdfReader

TEXT_FOUND, NO_TEXT, FAILED = 'extracted', 'no_text', 'failed'
ERROR_LENGTH = 500          # Document.text_error
LABEL_LENGTH = 30           # DocumentPage.label
KEPT_CONTROLS = {'\n', '\t', '\f'}


@dataclass(frozen=True)
class Page:
    number: int      # 1 for the first page of the file
    label: str       # the page's own number as the PDF labels it ('237', 'iv'); '' when it has none of its own
    text: str


@dataclass(frozen=True)
class Extraction:
    status: str
    pages: list = field(default_factory=list)   # every page of the file, with or without text
    error: str = ''

    @property
    def page_count(self):
        return len(self.pages) if self.status != FAILED else None


def clean(text):
    """A page's text as it is stored and searched: NFKC, without control characters, trimmed."""
    text = unicodedata.normalize('NFKC', text or '')
    return ''.join(ch for ch in text if ch in KEPT_CONTROLS or unicodedata.category(ch) != 'Cc').strip()


def read_pdf(stream):
    """The text of the PDF in `stream` (a binary file object), page by page. The stream is read from its
    start and left at its start, ready to be stored."""
    stream.seek(0)
    try:
        reader = PdfReader(stream)
        if reader.is_encrypted and not reader.decrypt(''):
            return Extraction(FAILED, error='The PDF is protected by a password.')
        labels = _labels(reader)
        pages = [
            Page(number, labels[number - 1] if labels[number - 1] != str(number) else '', clean(page.extract_text()))
            for number, page in enumerate(reader.pages, 1)
        ]
    except Exception as error:   # any failure of the reader on this file, recorded on the document
        return Extraction(FAILED, error=f'{type(error).__name__}: {error}'[:ERROR_LENGTH])
    finally:
        stream.seek(0)
    if not any(page.text for page in pages):
        return Extraction(NO_TEXT, pages)
    return Extraction(TEXT_FOUND, pages)


def _labels(reader):
    """The page labels the PDF declares (a journal's page numbers), one per page; a file without them, or with
    labels the reader cannot make sense of, numbers its pages 1, 2, 3."""
    count = len(reader.pages)
    try:
        labels = [str(label)[:LABEL_LENGTH] for label in reader.page_labels]
    except Exception:   # labels are a nicety: a broken label tree must not cost the text
        labels = []
    return labels if len(labels) == count else [str(number) for number in range(1, count + 1)]
