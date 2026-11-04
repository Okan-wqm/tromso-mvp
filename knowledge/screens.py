"""What the data map (core.datamap) cannot read from the code, for the knowledge tables the two tabs do not save: the
text read from a document's file, and what the review of an entry sets."""
from core.datamap import Screen, computed, no, system

from . import views
from .resources.document import DocumentResource

SCREENS = {
    'Document': Screen(
        columns={name: computed("read from the uploaded file when it is saved (knowledge/extraction.py)")
                 for name in ('file_name', 'file_size', 'text_status', 'page_count', 'text_error')},
    ),
    'DocumentPage': Screen(
        create=(DocumentResource,),
        edit=no('never edited: saving another file reads the pages again'),
        delete=no('replaced with the file: saving another file reads the pages again'),
        read=(views.document_text,),
        note='Written when a file is saved on the Library tab; what the search finds and what AI agents will read.',
        columns={'*': computed('read from the document\'s PDF, page by page (knowledge/extraction.py)')},
    ),
    'KnowledgeEntry': Screen(
        edit=(views.review_entry,),
        columns={name: system('set by the review: marked reviewed by the person, or taken back to draft')
                 for name in ('status', 'reviewed_by', 'reviewed_at')},
    ),
}
