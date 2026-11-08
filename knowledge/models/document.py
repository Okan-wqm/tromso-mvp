import os
import uuid
from functools import partial

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator, RegexValidator
from django.core.validators import URLValidator
from django.db import models, transaction
from django.db.models import F, Q
from django.db.models.functions import Lower
from django.template.defaultfilters import filesizeformat
from django.utils import timezone
from django.utils.text import Truncator
from django.utils.translation import gettext, gettext_lazy as _, ngettext

from core.fields import ChoiceArrayField
from core.models import AuditedModel
from farm.models import Species

from .. import citation, extraction
from .common import Language, Topic, search_vector, topic_labels

# A DOI as stored: the prefix 10.<registrant>/ and a suffix without spaces; no https://doi.org/ before it.
DOI = r'^10\.[0-9]{4,9}/\S+$'
DOI_MESSAGE = _('A DOI starts with 10. and has no spaces, e.g. 10.1016/j.aquaculture.2019.01.001.')
DOI_PREFIXES = ('https://doi.org/', 'http://doi.org/', 'https://dx.doi.org/', 'http://dx.doi.org/', 'doi:')
# One author per line, family name first; no empty line, no line with spaces only, none at either end.
AUTHORS = r'^\S([^\n]*\S)?(\n\S([^\n]*\S)?)*$'
YEARS = (1500, 2100)
SHORT_TITLE = 120
TEXT_PAGES = 20      # pages of a document's text shown at a time (knowledge.views.document_text)
FILE_NAME_LENGTH = 255


def normalise_doi(text):
    """' https://doi.org/10.1000/XYZ ' and 'doi:10.1000/XYZ' as '10.1000/XYZ': a DOI, not a link to it."""
    text = (text or '').strip()
    for prefix in DOI_PREFIXES:
        if text.lower().startswith(prefix):
            return text[len(prefix):].strip()
    return text


def normalise_authors(text):
    """The authors one per line, each without spaces at its ends or doubled inside; empty lines dropped."""
    return '\n'.join(' '.join(line.split()) for line in (text or '').splitlines() if line.strip())


def document_path(document, filename):
    """Where a document's file is stored: a name of our own, never the uploaded one (which is kept on the record
    for the person, `file_name`)."""
    return f'knowledge/documents/{uuid.uuid4().hex}.pdf'


def validate_pdf(file):
    """An uploaded file is a PDF of at most KNOWLEDGE_MAX_FILE_BYTES: its first bytes say %PDF- (the browser's
    word for its type, and its name, are not trusted). A file already stored is not read again."""
    if getattr(file, '_committed', True):
        return
    limit = settings.KNOWLEDGE_MAX_FILE_BYTES
    if file.size > limit:
        raise ValidationError(_('The file is %(size)s; the library takes PDFs of up to %(limit)s.'),
                              params={'size': filesizeformat(file.size), 'limit': filesizeformat(limit)})
    stream = file.file
    stream.seek(0)
    head = stream.read(1024)
    stream.seek(0)
    if b'%PDF-' not in head:
        raise ValidationError(_('This file is not a PDF.'))


class TextStatus(models.TextChoices):
    """What reading the file's text gave (knowledge.extraction)."""
    NO_FILE = 'no_file', _('No file')
    EXTRACTED = extraction.TEXT_FOUND, _('Text found')
    NO_TEXT = extraction.NO_TEXT, _('No text found')
    FAILED = extraction.FAILED, _('Could not be read')


class Document(AuditedModel):
    """An article, report, book, guideline or regulation in the library: its reference (authors, year, venue,
    DOI or address), its abstract, what it is about, and optionally its PDF with the text read from it.

    The file is stored by Django's storage under MEDIA_ROOT with a name of our own; it is sent only by
    knowledge.views.document_file, to people who may read the library. When a new file is saved its text is read
    at once (knowledge.extraction), page by page into DocumentPage, and the outcome is on the document
    (`text_status`, `page_count`, `text_error`); a file that is replaced or cleared is removed from the storage
    once the change is committed, its pages with it. A deleted document keeps its file and pages, for a restore.

    Searching: `search_vector` is a generated column (title, authors, abstract, venue, by weight) and each page
    has its own (knowledge.search). Delete: a knowledge entry that cites the document holds it (PROTECT): an
    entry is its source, and an entry without one would say nothing anyone could check."""

    title = models.CharField(_('Title'), max_length=500)
    authors = models.CharField(_('Authors'), max_length=5000, blank=True)
    year = models.PositiveSmallIntegerField(
        _('Year'), null=True, blank=True, validators=[MinValueValidator(YEARS[0]), MaxValueValidator(YEARS[1])])
    venue = models.CharField(_('Published in'), max_length=300, blank=True)
    volume = models.CharField(_('Volume'), max_length=20, blank=True)
    issue = models.CharField(_('Issue'), max_length=20, blank=True)
    page_range = models.CharField(_('Pages'), max_length=30, blank=True)
    doi = models.CharField(_('DOI'), max_length=255, blank=True, validators=[RegexValidator(DOI, DOI_MESSAGE)])
    url = models.URLField(_('Web address'), max_length=500, blank=True, validators=[URLValidator(schemes=['http', 'https'])])
    abstract = models.CharField(_('Abstract'), max_length=10000, blank=True)
    language = models.CharField(_('Language'), max_length=10, blank=True, choices=Language.choices)
    topics = ChoiceArrayField(models.TextField(choices=Topic.choices), verbose_name=_('Topics'), default=list,
                              blank=True)
    # A deleted species keeps its link rows: the link comes back with the species (core.softdelete).
    species = models.ManyToManyField(Species, blank=True, related_name='documents', db_table='document_species',
                                     verbose_name=_('Species'))

    file = models.FileField(
        _('PDF file'), upload_to=document_path, blank=True,
        validators=[FileExtensionValidator(['pdf']), validate_pdf],
    )
    file_name = models.CharField(_('File name'), max_length=FILE_NAME_LENGTH, blank=True)
    file_size = models.PositiveIntegerField(_('File size (bytes)'), null=True, blank=True)
    text_status = models.CharField(_('Text'), max_length=20, choices=TextStatus.choices, default=TextStatus.NO_FILE)
    page_count = models.PositiveIntegerField(_('Number of pages'), null=True, blank=True)
    text_error = models.CharField(_('Why the text could not be read'), max_length=extraction.ERROR_LENGTH, blank=True)

    search_vector = models.GeneratedField(
        expression=search_vector(('title', 'A'), ('authors', 'B'), ('abstract', 'C'), ('venue', 'D')),
        output_field=SearchVectorField(), db_persist=True, verbose_name=_('Search vector'),
    )

    class Meta:
        db_table = 'documents'
        ordering = [F('year').desc(nulls_last=True), 'title']
        verbose_name = _('document')
        verbose_name_plural = _('documents')
        constraints = [
            models.UniqueConstraint(
                Lower('doi'), condition=Q(is_deleted=False) & ~Q(doi=''), name='uq_documents_doi_live',
                violation_error_message=_('Another document in the library has this DOI.'),
            ),
            models.CheckConstraint(condition=Q(title__regex=r'\S'), name='chk_documents_title'),
            models.CheckConstraint(condition=Q(authors='') | Q(authors__regex=AUTHORS), name='chk_documents_authors'),
            models.CheckConstraint(
                condition=Q(year__isnull=True) | Q(year__gte=YEARS[0], year__lte=YEARS[1]), name='chk_documents_year',
            ),
            models.CheckConstraint(
                condition=Q(doi='') | Q(doi__regex=DOI), name='chk_documents_doi', violation_error_message=DOI_MESSAGE,
            ),
            models.CheckConstraint(condition=Q(url='') | Q(url__regex=r'^https?://\S+$'), name='chk_documents_url'),
            models.CheckConstraint(condition=Q(language='') | Q(language__in=Language.values),
                                   name='chk_documents_language'),
            models.CheckConstraint(condition=Q(topics__contained_by=Topic.values), name='chk_documents_topics'),
            models.CheckConstraint(condition=Q(text_status__in=TextStatus.values), name='chk_documents_text_status'),
            # The file and what is known about it come together: a name, a size and a reading of its text.
            models.CheckConstraint(
                condition=(Q(file='') & Q(text_status=TextStatus.NO_FILE, file_name='', file_size__isnull=True,
                                          page_count__isnull=True))
                | (~Q(file='') & ~Q(text_status=TextStatus.NO_FILE) & ~Q(file_name='') & Q(file_size__isnull=False)),
                name='chk_documents_file',
            ),
            # A file that could not be read says why, and has no page count; one that was read has its pages.
            models.CheckConstraint(
                condition=(Q(text_status=TextStatus.FAILED) & ~Q(text_error='') & Q(page_count__isnull=True))
                | (~Q(text_status=TextStatus.FAILED) & Q(text_error='')),
                name='chk_documents_text_error',
            ),
            models.CheckConstraint(
                condition=Q(text_status__in=[TextStatus.NO_FILE, TextStatus.FAILED]) | Q(page_count__isnull=False),
                name='chk_documents_page_count',
            ),
        ]
        indexes = [
            GinIndex(fields=['search_vector'], name='ix_documents_search'),
            GinIndex(fields=['topics'], name='ix_documents_topics'),
            models.Index(fields=['year'], name='ix_documents_year'),
        ]

    @classmethod
    def from_db(cls, db, field_names, values, *, fetch_mode=None):
        document = super().from_db(db, field_names, values, fetch_mode=fetch_mode)
        # The file as stored, to tell on save whether it was replaced or cleared.
        document._stored_file = values[field_names.index('file')] if 'file' in field_names else None
        return document

    def __str__(self):
        return self.short_title()

    def short_title(self):
        return Truncator(self.title).chars(SHORT_TITLE)

    # --- citing it ----------------------------------------------------------------------------
    def author_lines(self):
        return citation.author_lines(self.authors)

    def short_citation(self):
        """'Olsen et al. (2019)'."""
        return citation.short(self)

    def reference(self):
        """The full reference, APA-like, as HTML (knowledge.citation)."""
        return citation.reference(self)

    def plain_reference(self):
        return citation.plain(self)

    def link(self):
        return citation.link(self)

    def topic_labels(self):
        return topic_labels(self.topics)

    # --- its file ------------------------------------------------------------------------------
    def clean(self):
        super().clean()
        if self.year and timezone.localdate().year + 1 < self.year <= YEARS[1]:   # beyond YEARS, its validator says it
            raise ValidationError({'year': _('The year cannot be later than next year (in press).')})

    def save(self, *args, **kwargs):
        self.doi = normalise_doi(self.doi)
        self.authors = normalise_authors(self.authors)
        stored = getattr(self, '_stored_file', None) or ''
        upload = self.file if self.file and not self.file._committed else None
        reading = None
        if upload is not None:
            reading = extraction.read_pdf(upload.file)
            self.file_name = _file_name(upload.name)
            self.file_size = upload.size
            self.text_status, self.page_count, self.text_error = reading.status, reading.page_count, reading.error
            self.text_read = True     # for the message after saving (DocumentResource.after_save)
        elif not self.file:
            self.file_name, self.file_size, self.page_count, self.text_error = '', None, None, ''
            self.text_status = TextStatus.NO_FILE
        super().save(*args, **kwargs)
        if upload is not None or (stored and not self.file):
            self.pages.all().delete()
            DocumentPage.objects.bulk_create([
                DocumentPage(document=self, number=page.number, label=page.label, text=page.text)
                for page in (reading.pages if reading else [])
            ])
        if stored and stored != self.file.name:
            # Once the change is committed: a save that is rolled back keeps the file it had.
            transaction.on_commit(partial(self.file.storage.delete, stored))
        self._stored_file = self.file.name

    def text_summary(self):
        """'Text found on 12 of 14 pages', 'No text found (a scan?)': what reading the file gave, in a line."""
        if self.text_status == TextStatus.EXTRACTED:
            found = self.pages.exclude(text='').count()
            return ngettext('Text found on %(found)d of %(count)d page.', 'Text found on %(found)d of %(count)d pages.',
                            self.page_count) % {'found': found, 'count': self.page_count}
        if self.text_status == TextStatus.NO_TEXT:
            return gettext('No text found: the pages are images, as in a scan. Its text needs OCR, which the '
                           'library does not do yet.')
        if self.text_status == TextStatus.FAILED:
            return gettext('The text could not be read: %(reason)s') % {'reason': self.text_error}
        return gettext('No file.')


def _file_name(name):
    """The uploaded file's own name, as the person knows it, cut to the column with its extension kept."""
    name = os.path.basename(name or '') or 'document.pdf'
    if len(name) <= FILE_NAME_LENGTH:
        return name
    stem, extension = os.path.splitext(name)
    return stem[:FILE_NAME_LENGTH - len(extension)] + extension


class DocumentPage(models.Model):
    """The text of one page of a document's PDF, as read from it (knowledge.extraction): what the library
    searches and what an AI agent will read and cite by page. Written only when a file is saved; never edited."""

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='pages', verbose_name=_('Document'))
    number = models.PositiveIntegerField(_('Page'))
    label = models.CharField(_('Page label'), max_length=extraction.LABEL_LENGTH, blank=True)
    text = models.TextField(_('Text'), blank=True)
    search_vector = models.GeneratedField(
        expression=search_vector(('text', 'D')), output_field=SearchVectorField(), db_persist=True,
        verbose_name=_('Search vector'),
    )

    class Meta:
        db_table = 'document_pages'
        ordering = ['document', 'number']
        verbose_name = _('document page')
        verbose_name_plural = _('document pages')
        constraints = [
            models.UniqueConstraint(fields=['document', 'number'], name='uq_document_pages_number'),
            models.CheckConstraint(condition=Q(number__gte=1), name='chk_document_pages_number'),
        ]
        indexes = [GinIndex(fields=['search_vector'], name='ix_document_pages_search')]

    def __str__(self):
        return f'{self.document} · {self.shown_number()}'

    def shown_number(self):
        """How a citation names the page: its own label when the PDF has one ('p. 237'), else its number."""
        return self.label or str(self.number)

    @property
    def screen(self):
        """The screen of the document's text that shows this page (TEXT_PAGES a screen)."""
        return (self.number - 1) // TEXT_PAGES + 1
