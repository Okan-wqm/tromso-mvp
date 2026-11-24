"""The library's writes besides its tabs (core.crud): the review of a knowledge entry. Rules live here, never in a view
(the data-layering audit, L-1): who may (asked here, core.access.require), the row locked, the version the reviewer read,
the change logged like an edit."""
from django.db import transaction

from core import access, audit
from core.crud import Crossed

from .models import EntryStatus, KnowledgeEntry


def review(user, pk, status, version):
    """Marks the entry reviewed by `user`, now (status reviewed), or takes it back to draft (status draft). Crossed when
    it changed since the person read it (`version`): a review covers the words the reviewer saw. KnowledgeEntry.
    DoesNotExist for a deleted or unknown one. Returns the entry."""
    from .resources import KnowledgeEntryResource as resource
    access.require(user, resource.perm('change'))
    if status not in EntryStatus.values:
        raise ValueError(f'Not a status of a knowledge entry: {status!r}.')
    with transaction.atomic():
        entry = KnowledgeEntry.objects.select_for_update().get(pk=pk)
        if str(version) != str(entry.version):
            raise Crossed
        before = resource.recorded(entry)
        if status == EntryStatus.REVIEWED:
            entry.review(user)
        else:
            entry.return_to_draft()
        entry.version += 1
        entry.updated_by = user
        entry.save()
        audit.record_update(user, entry, before, resource.recorded(entry), entity_type=resource.entity_type())
    return entry
