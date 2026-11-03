from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.text import Truncator
from django.utils.translation import gettext, gettext_lazy as _

from core.fields import ChoiceArrayField
from core.models import AuditedModel
from farm.models import Species

from .common import Topic, search_vector, topic_labels
from .document import Document

TOPICS_MESSAGE = _('Tick at least one topic.')
SHORT_STATEMENT = 100


class SourceKind(models.TextChoices):
    """Where a piece of knowledge comes from; an entry has exactly one kind of source."""
    DOCUMENT = 'document', _('A document in the library')
    EXTERNAL = 'external', _('Another published source')
    EXPERT = 'expert', _('An expert or our own observation')


class EntryStatus(models.TextChoices):
    DRAFT = 'draft', _('Draft')
    REVIEWED = 'reviewed', _('Reviewed')


# The fields of each kind of source, in the order the form shows them. The fields of the other kinds stay empty
# (a database check per kind), so an entry has exactly one source.
SOURCE_FIELDS = {
    SourceKind.DOCUMENT: ('document', 'pages', 'section', 'quote'),
    SourceKind.EXTERNAL: ('citation', 'url', 'quote'),
    SourceKind.EXPERT: ('expert', 'observed_on'),
}
ALL_SOURCE_FIELDS = tuple(dict.fromkeys(name for names in SOURCE_FIELDS.values() for name in names))
EMPTY = {'document': None, 'observed_on': None}   # the empty value of each source field that is not text


class KnowledgeEntry(AuditedModel):
    """A piece of knowledge in a person's own words, with its source: "In Atlantic salmon under 50 g, free CO₂
    above 15 mg/L leads to nephrocalcinosis", from a document in the library (with the page, the section and the
    words it says it in), from another published source (its citation or address), or from an expert or the
    farm's own observation (with the person). Exactly one kind of source, checked by the database.

    An entry is a draft until someone reviews it (`review`): the reviewer and the time are kept, and an edit of a
    reviewed entry's statement, topics, species or source takes it back to draft (KnowledgeEntryForm), so a review
    always covers the words as they are. AI agents will act on reviewed entries only.

    The structured form an agent can apply (a Rule: conditions over the farm's measured values, a consequence, a
    severity) is designed in the README and not built yet; an entry is what a rule will cite. Delete: a cited
    document cannot be deleted while a live entry cites it (Document, PROTECT)."""

    Kind, Status = SourceKind, EntryStatus

    statement = models.CharField(_('Statement'), max_length=2000)
    topics = ChoiceArrayField(models.TextField(choices=Topic.choices), verbose_name=_('Topics'), default=list)
    # A deleted species keeps its link rows: the link comes back with the species (core.softdelete).
    species = models.ManyToManyField(Species, blank=True, related_name='knowledge_entries',
                                     db_table='knowledge_entry_species', verbose_name=_('Species'))

    source_kind = models.CharField(_('Source'), max_length=20, choices=SourceKind.choices)
    document = models.ForeignKey(Document, null=True, blank=True, on_delete=models.PROTECT, related_name='entries',
                                 verbose_name=_('Document'))
    pages = models.CharField(_('Page(s)'), max_length=30, blank=True)
    section = models.CharField(_('Section'), max_length=200, blank=True)
    quote = models.CharField(_('Quote'), max_length=4000, blank=True)
    citation = models.CharField(_('Citation'), max_length=1000, blank=True)
    url = models.URLField(_('Web address'), max_length=500, blank=True, validators=[URLValidator(schemes=['http', 'https'])])
    expert = models.CharField(_('Person'), max_length=200, blank=True)
    observed_on = models.DateField(_('Observed on'), null=True, blank=True)

    status = models.CharField(_('Status'), max_length=20, choices=EntryStatus.choices, default=EntryStatus.DRAFT)
    # People are deactivated, never deleted (core.resources): a reviewer stays named.
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name='+', verbose_name=_('Reviewed by'))
    reviewed_at = models.DateTimeField(_('Reviewed at'), null=True, blank=True)

    search_vector = models.GeneratedField(
        expression=search_vector(('statement', 'A'), ('quote', 'B'), ('section', 'C'), ('citation', 'C'),
                                 ('expert', 'D')),
        output_field=SearchVectorField(), db_persist=True, verbose_name=_('Search vector'),
    )

    class Meta:
        db_table = 'knowledge_entries'
        ordering = ['-created_at']
        verbose_name = _('knowledge entry')
        verbose_name_plural = _('knowledge entries')
        constraints = [
            models.CheckConstraint(condition=Q(statement__regex=r'\S'), name='chk_knowledge_entries_statement'),
            models.CheckConstraint(condition=Q(topics__contained_by=Topic.values), name='chk_knowledge_entries_topics'),
            models.CheckConstraint(condition=Q(topics__len__gt=0), name='chk_knowledge_entries_topics_not_empty',
                                   violation_error_message=TOPICS_MESSAGE),
            models.CheckConstraint(condition=Q(source_kind__in=SourceKind.values),
                                   name='chk_knowledge_entries_source_kind'),
            # Exactly one kind of source: each kind has what it needs, and the fields of the other kinds are empty.
            models.CheckConstraint(
                condition=Q(source_kind=SourceKind.DOCUMENT, document__isnull=False)
                | (~Q(source_kind=SourceKind.DOCUMENT) & Q(document__isnull=True, pages='', section='')),
                name='chk_knowledge_entries_document_source',
            ),
            models.CheckConstraint(
                condition=(Q(source_kind=SourceKind.EXTERNAL) & (~Q(citation='') | ~Q(url='')))
                | (~Q(source_kind=SourceKind.EXTERNAL) & Q(citation='', url='')),
                name='chk_knowledge_entries_external_source',
            ),
            models.CheckConstraint(
                condition=(Q(source_kind=SourceKind.EXPERT) & Q(expert__regex=r'\S'))
                | (~Q(source_kind=SourceKind.EXPERT) & Q(expert='', observed_on__isnull=True)),
                name='chk_knowledge_entries_expert_source',
            ),
            # A quote is the source's own words: a document's or a published source's, not a person's observation.
            models.CheckConstraint(condition=Q(quote='') | ~Q(source_kind=SourceKind.EXPERT),
                                   name='chk_knowledge_entries_quote'),
            models.CheckConstraint(condition=Q(url='') | Q(url__regex=r'^https?://\S+$'), name='chk_knowledge_entries_url'),
            # A reviewed entry names who reviewed it and when; a draft names nobody (and no other status exists).
            models.CheckConstraint(
                condition=Q(status=EntryStatus.REVIEWED, reviewed_by__isnull=False, reviewed_at__isnull=False)
                | Q(status=EntryStatus.DRAFT, reviewed_by__isnull=True, reviewed_at__isnull=True),
                name='chk_knowledge_entries_review',
            ),
        ]
        indexes = [
            GinIndex(fields=['search_vector'], name='ix_knowledge_entries_search'),
            GinIndex(fields=['topics'], name='ix_knowledge_entries_topics'),
            models.Index(fields=['status'], name='ix_knowledge_entries_status'),
        ]

    def __str__(self):
        return Truncator(' '.join(self.statement.split())).chars(SHORT_STATEMENT)

    def topic_labels(self):
        return topic_labels(self.topics)

    def source_label(self):
        """The source in a line: 'Olsen et al. (2019), p. 4', the citation or address, 'Kari Nordmann, 3 Oct 2026'."""
        if self.source_kind == SourceKind.DOCUMENT and self.document_id:
            where = [self.document.short_citation()]
            if self.pages:
                where.append(gettext('p. %(page)s') % {'page': self.pages})
            if self.section:
                where.append(self.section)
            return ', '.join(where)
        if self.source_kind == SourceKind.EXTERNAL:
            return self.citation or self.url
        if self.source_kind == SourceKind.EXPERT:
            return self.expert
        return ''

    def clean(self):
        """The fields of the other kinds of source are emptied (the form shows only the chosen kind's), and the
        chosen kind must say where the knowledge comes from."""
        super().clean()
        kept = SOURCE_FIELDS.get(self.source_kind, ())
        for name in ALL_SOURCE_FIELDS:
            if name not in kept:
                setattr(self, name, EMPTY.get(name, ''))
        errors = {}
        if self.source_kind == SourceKind.DOCUMENT and self.document_id is None:
            errors['document'] = _('Choose the document in the library it comes from.')
        elif self.source_kind == SourceKind.EXTERNAL and not (self.citation.strip() or self.url):
            errors['citation'] = _('Give the citation of the source, its web address, or both.')
        elif self.source_kind == SourceKind.EXPERT and not self.expert.strip():
            errors['expert'] = _('Name the person whose observation or advice it is.')
        if errors:
            raise ValidationError(errors)

    def review(self, user):
        """Marks it reviewed by `user`, now. The caller saves it."""
        self.status, self.reviewed_by, self.reviewed_at = EntryStatus.REVIEWED, user, timezone.now()

    def return_to_draft(self):
        """Back to draft: no reviewer, no review time. The caller saves it."""
        self.status, self.reviewed_by, self.reviewed_at = EntryStatus.DRAFT, None, None
