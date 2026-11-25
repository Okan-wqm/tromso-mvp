import uuid

from django.contrib import messages
from django.urls import reverse
from django.utils.text import capfirst
from django.utils.translation import gettext, gettext_lazy as _

from core import audit, formpanels
from core.crud import Resource, filter_by
from farm.models import Species

from .. import words
from ..forms import KnowledgeEntryForm
from ..models import Document, KnowledgeEntry, SourceKind, Topic
from ..search import search_entries

REVIEW_FIELDS = ('status', 'reviewed_by', 'reviewed_at')


class KnowledgeEntryResource(Resource):
    """Company › Knowledge › Knowledge entries: what the company knows, each with its source; searched by its words
    and its document's (knowledge.search), filtered by topic, species, status and kind of source; a read page with
    the source and the review."""

    model = KnowledgeEntry
    form_class = KnowledgeEntryForm
    name, plural = _('knowledge entry'), _('knowledge entries')
    url_prefix = 'knowledge/entries'
    list_template = 'knowledge/entry_list.html'
    detail_template = 'knowledge/entry_detail.html'
    form_template = 'knowledge/entry_form.html'
    icon = 'lightbulb'
    page_size = 50

    @classmethod
    def next_panels(cls, view, form, entry, extra):
        """knowledge/entry_form.html in the new look: an existing entry's Review tab (knowledge/_review.html), its status
        and, for a person who may edit entries, the buttons that mark it reviewed or take it back to draft."""
        if entry is None:
            return []
        reviewed = entry.status == 'reviewed'
        state = formpanels.status(
            {'kind': 'ok' if reviewed else 'neutral', 'text': str(entry.get_status_display())},
            words.reviewed_by(entry) if reviewed else words.NOT_REVIEWED_YET_AI_AGENTS_WILL)
        blocks = [state]
        if cls.allows('change') and view.request.user.has_perm(cls.perm('change')):
            action = reverse('knowledge:entry_review', args=[entry.pk])
            if reviewed:
                blocks.append(formpanels.post(action, words.BACK_TO_DRAFT, [('version', entry.version), ('status', 'draft')]))
            blocks += [formpanels.post(action, words.REVIEW_IT_AGAIN if reviewed else words.MARK_AS_REVIEWED,
                                       [('version', entry.version), ('status', 'reviewed')], primary=True),
                       formpanels.help_text(words.REVIEWING_SAYS_THE_STATEMENT_AND_ITS)]
        return [formpanels.panel('review', words.REVIEW, blocks)]

    @classmethod
    def queryset(cls):
        return KnowledgeEntry.objects.select_related('document', 'reviewed_by', 'created_by').prefetch_related('species')

    @classmethod
    def search(cls, objects, query):
        return search_entries(objects, query)

    @classmethod
    def form(cls, request, *args, **kwargs):
        """A new entry opened from a document's page (?document=) starts with that document as its source."""
        chosen = request.GET.get('document', '')
        if not args and 'instance' not in kwargs and 'draft' not in kwargs and chosen:
            document = Document.objects.filter(pk=chosen).first() if _is_uuid(chosen) else None
            if document is not None:
                kwargs['initial'] = {'source_kind': SourceKind.DOCUMENT, 'document': document.pk}
        return cls.form_class(*args, **kwargs)

    @classmethod
    def filter_list(cls, request, objects):
        chosen_topic = request.GET.get('topic', '')
        if chosen_topic in Topic.values:
            objects = objects.filter(topics__contains=[chosen_topic])
        else:
            chosen_topic = ''
        species = Species.objects.all()
        objects, chosen_species = filter_by(request, objects, 'species', species, 'species')
        objects, chosen_status = filter_by(request, objects, 'status', KnowledgeEntry.Status.choices, 'status')
        objects, chosen_source = filter_by(request, objects, 'source', SourceKind.choices, 'source_kind')
        return objects, {
            'topics': Topic.choices, 'chosen_topic': chosen_topic,
            'species_choices': species, 'chosen_species': chosen_species,
            'statuses': KnowledgeEntry.Status.choices, 'chosen_status': chosen_status,
            'sources': SourceKind.choices, 'chosen_source': chosen_source,
        }

    @classmethod
    def detail_extras(cls, request, entry):
        return {
            'can_review': request.user.has_perm('knowledge.change_knowledgeentry'),
            'review_url': reverse('knowledge:entry_review', args=[entry.pk]),
            'can_read_library': request.user.has_perm('knowledge.view_document'),
        }

    @classmethod
    def snapshot(cls, entry):
        """The form's fields, and the review: its status, who reviewed it and when."""
        values = super().snapshot(entry)
        values.update(audit.snapshot(entry, REVIEW_FIELDS))
        label = str(capfirst(KnowledgeEntry._meta.get_field('reviewed_at').verbose_name))
        values[label] = entry.reviewed_at.isoformat(timespec='seconds') if entry.reviewed_at else None
        return values

    @classmethod
    def after_save(cls, request, entry, created):
        if getattr(entry, 'returned_to_draft', False):
            messages.warning(request, gettext('It was reviewed; after this change it is a draft again, until it is '
                                              'reviewed anew.'))


def _is_uuid(text):
    try:
        uuid.UUID(text)
    except ValueError:
        return False
    return True
