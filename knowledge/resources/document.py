from django.contrib import messages
from django.db.models import Count, IntegerField, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils.text import capfirst
from django.utils.translation import gettext_lazy as _

from core import audit
from core.crud import Resource, filter_by
from farm.models import Species

from ..forms import DocumentForm
from ..models import Document, KnowledgeEntry, TextStatus, Topic
from ..search import matching_pages, search_documents


def entry_counts():
    """How many live knowledge entries cite each document, as a subquery (no GROUP BY over the search's columns)."""
    cited = (KnowledgeEntry.objects.filter(document=OuterRef('pk')).order_by().values('document')
             .annotate(count=Count('pk')).values('count'))
    return Coalesce(Subquery(cited, output_field=IntegerField()), Value(0))


def label(name):
    return capfirst(Document._meta.get_field(name).verbose_name)


class DocumentResource(Resource):
    """Company › Knowledge › Library: the documents, searched by their words (knowledge.search), filtered by topic,
    species and year; a read page with the reference, the file and the entries taken from it."""

    model = Document
    form_class = DocumentForm
    name, plural = _('document'), _('documents')
    url_prefix = 'knowledge/library'
    list_template = 'knowledge/document_list.html'
    detail_template = 'knowledge/document_detail.html'
    icon = 'book-open'
    page_size = 50

    @classmethod
    def queryset(cls):
        return Document.objects.prefetch_related('species').annotate(entry_count=entry_counts())

    @classmethod
    def search(cls, objects, query):
        return search_documents(objects, query)

    @classmethod
    def filter_list(cls, request, objects):
        chosen_topic = request.GET.get('topic', '')
        if chosen_topic in Topic.values:
            objects = objects.filter(topics__contains=[chosen_topic])
        else:
            chosen_topic = ''
        species = Species.objects.all()
        objects, chosen_species = filter_by(request, objects, 'species', species, 'species')
        years = [(year, year) for year in Document.objects.exclude(year=None).order_by('-year')
                 .values_list('year', flat=True).distinct()]
        objects, chosen_year = filter_by(request, objects, 'year', years, 'year')
        return objects, {
            'topics': Topic.choices, 'chosen_topic': chosen_topic,
            'species_choices': species, 'chosen_species': chosen_species,
            'years': [year for year, _label in years], 'chosen_year': chosen_year,
        }

    @classmethod
    def detail_extras(cls, request, document):
        query = request.GET.get('q', '').strip()
        user = request.user
        return {
            'query': query,
            'matches': matching_pages(document, query) if query and document.page_count else [],
            'can_read_entries': user.has_perm('knowledge.view_knowledgeentry'),
            'entries': document.entries.select_related('reviewed_by').prefetch_related('species'),
            'add_entry_url': (f"{reverse('knowledge:knowledgeentry_create')}?document={document.pk}"
                              if user.has_perm('knowledge.add_knowledgeentry') else ''),
        }

    @classmethod
    def snapshot(cls, document):
        """The form's fields, the file by its own name (not the storage's), and what reading its text gave; never
        the text itself."""
        values = super().snapshot(document)
        values[str(label('file'))] = document.file_name or None
        values[str(label('text_status'))] = audit.message(TextStatus(document.text_status).label) if document.file else None
        values[str(label('page_count'))] = None if document.page_count is None else str(document.page_count)
        return values

    @classmethod
    def after_save(cls, request, document, created):
        """Says what reading a new file gave: a scan, or a file that could not be read, is worth knowing at once."""
        if not getattr(document, 'text_read', False):
            return
        say = messages.success if document.text_status == TextStatus.EXTRACTED else messages.warning
        say(request, document.text_summary())
