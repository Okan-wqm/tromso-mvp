"""The library's pages besides its tabs: a document's file and its text, and the review of a knowledge entry."""
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

from core import audit
from core.crud import DetailView, done, render_page

from .models import Document, EntryStatus, KnowledgeEntry
from .models.document import TEXT_PAGES
from .resources import DocumentResource, KnowledgeEntryResource


def _allowed(request, resource, action):
    if not request.user.has_perm(resource.perm(action)):
        raise PermissionDenied


@require_GET
def document_file(request, pk):
    """The PDF of a live document, to a signed-in person who may read the library (LoginRequiredMiddleware signs
    people in first). Shown in the browser, or downloaded with ?download; never a public address."""
    _allowed(request, DocumentResource, 'view')
    document = get_object_or_404(Document.objects, pk=pk)
    if not document.file:
        raise Http404
    try:
        stream = document.file.storage.open(document.file.name, 'rb')
    except FileNotFoundError:
        raise Http404 from None
    response = FileResponse(stream, as_attachment='download' in request.GET, filename=document.file_name,
                            content_type='application/pdf')
    response['Cache-Control'] = 'private, no-cache'
    return response


@require_GET
def document_text(request, pk):
    """The text read from a document's PDF, page by page: what the search finds and what the AI agents will read."""
    _allowed(request, DocumentResource, 'view')
    document = get_object_or_404(DocumentResource.queryset(), pk=pk)
    page = Paginator(document.pages.all(), TEXT_PAGES).get_page(request.GET.get('page'))
    view = DetailView.as_page(DocumentResource, request)
    return render_page(request, 'knowledge/document_text.html', view.context(
        object=document, page=page, detail_url=reverse('knowledge:document_detail', args=[document.pk])))


@require_POST
def review_entry(request, pk):
    """Marks a knowledge entry reviewed by the person, now (status=reviewed), or takes it back to draft
    (status=draft). It is refused when the entry changed since the person read it (`version`): a review covers
    the words the reviewer saw. Logged like an edit."""
    _allowed(request, KnowledgeEntryResource, 'change')
    status = request.POST.get('status')
    if status not in EntryStatus.values:
        return HttpResponseBadRequest()
    resource = KnowledgeEntryResource
    url = reverse('knowledge:knowledgeentry_detail', args=[pk])
    with transaction.atomic():
        entry = get_object_or_404(KnowledgeEntry.objects.select_for_update(), pk=pk)
        if request.POST.get('version') != str(entry.version):
            messages.error(request, _('Someone changed this entry while you were reading it. Read it again before '
                                      'you review it.'))
            return done(request, url, stay=True)
        before = resource.recorded(entry)
        if status == EntryStatus.REVIEWED:
            entry.review(request.user)
        else:
            entry.return_to_draft()
        entry.version += 1
        entry.updated_by = request.user
        entry.save()
        audit.record_update(request.user, entry, before, resource.recorded(entry), entity_type=resource.entity_type())
    if status == EntryStatus.REVIEWED:
        messages.success(request, _('Marked as reviewed by you.'))
    else:
        messages.success(request, _('It is a draft again.'))
    return done(request, url, stay=True)
