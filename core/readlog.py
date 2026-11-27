"""The read log's one write path (core.AccessEvent): who read which confidential record, when and how. Its rows are
append-only (a database trigger, core 0016). core.sealing decides who is looking and whether a read is logged at all
(`log_access`, `log_accesses`); this module only writes the rows it is given."""
from .models import AccessEvent


def _row(viewer, kind, entity_type, entity_id, part, route, reason):
    return AccessEvent(user_id=viewer.user_id, user_name=viewer.username, kind=kind, entity_type=entity_type,
                       entity_id=str(entity_id), part=part, route=route[:120], reason=reason[:300])


def write(viewer, kind, entity_type, entity_id, part='', route='', reason=''):
    """One row for `viewer` (a core.sealing.Viewer)."""
    row = _row(viewer, kind, entity_type, entity_id, part, route, reason)
    row.save(force_insert=True)
    return row


def write_many(viewer, kind, entity_type, entity_ids, part='', route='', reason=''):
    """One row per record of `entity_ids` for `viewer`, in one statement."""
    return AccessEvent.objects.bulk_create([_row(viewer, kind, entity_type, each, part, route, reason)
                                            for each in entity_ids])
