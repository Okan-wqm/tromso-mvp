"""The Sensors panel's writes besides its tabs (core.crud) and its named write paths (sensors/bindings.py,
sensors/credentials.py, sensors/alarms.py): resolving a dead letter. Rules live here, never in a view (the data-layering
audit, L-1)."""
from django.db import transaction
from django.utils import timezone

from core import access, audit
from core.models import AuditLog

from .models import DeadLetter

RESOLVE = 'sensors.change_deadletter'


def resolve_dead_letter(user, pk):
    """Marks a dead letter resolved by `user`, now (the cause is dealt with), logged; the message itself stays as it came.
    A letter resolved already is left as it is. The ingest opens it again when the same message comes back
    (sensors-ingest/src/db.rs, dead letters: a recurrence clears `resolved_at`). Returns the letter."""
    access.require(user, RESOLVE)
    with transaction.atomic():
        letter = DeadLetter.objects.select_for_update().get(pk=pk)
        if letter.resolved_at is None:
            letter.resolved_at, letter.resolved_by = timezone.now(), user
            letter.save(update_fields=['resolved_at', 'resolved_by'])
            with audit.source_language():
                audit.record(user, AuditLog.Action.UPDATE, letter, {'Resolved': [None, 'yes']})
    return letter
