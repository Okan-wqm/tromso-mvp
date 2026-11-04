"""The write path of protocol assignments: the rows for a protocol, a day range and the units or the batch it
feeds (checked as the assignment dialog checks them), writing them, each logged, and ending one. The dialog
(farm/forms/feeding_protocol.py, farm/resources/feeding_protocol.py) and an experiment's start and its amendments
(experiments/services.py) come through here, so a row written or ended for an experiment is the row the dialog
would write or end and the log shows the same entry."""
import uuid
from dataclasses import dataclass
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from core import audit
from farm.models import ProtocolAssignment, Tank
from farm.stock.dates import local_today

# The fields the activity log shows of an assignment (and the assignment's form, on its one tab).
FIELDS = ('protocol', 'unit', 'batch', 'valid_from', 'valid_until', 'notes')


@dataclass(frozen=True)
class RowError:
    """Why the row of `unit` (None: the batch alone) was not made: `message` is on a field of the assignment, or
    on the row as a whole (NON_FIELD_ERRORS: another protocol in force on some of its days)."""
    unit: Tank
    field: str
    message: str


def rows(protocol, units, batch, first, last, notes=''):
    """([ProtocolAssignment], [RowError]): a row per unit (one row for a batch alone), all with one group,
    checked as a row (its fields, and the overlap with the rows in force, by the database's own constraints).
    A row with an error is left out; the caller refuses the whole, or shows what concerns each unit. `last` None:
    until it is ended."""
    group = uuid.uuid4()
    made, errors = [], []
    for unit in units or [None]:
        row = ProtocolAssignment(protocol=protocol, unit=unit, batch=batch, group_id=group, valid_from=first,
                                 valid_until=last, notes=notes)
        try:
            row.full_clean(exclude=['group_id'])
        except ValidationError as error:
            errors.extend(RowError(unit, field, message) for field, messages in error.message_dict.items()
                          for message in messages)
            continue
        made.append(row)
    return made, errors


def recorded(row):
    """The row as the activity log stores it."""
    with audit.source_language():
        return audit.snapshot(row, FIELDS)


def save(user, made):
    """Writes the rows of `rows()` together, each logged as created by `user`. An IntegrityError (a row written
    for the same fish meanwhile: the constraints) leaves nothing written and is the caller's to report."""
    with transaction.atomic():
        for row in made:
            row.created_by = row.updated_by = user
            row.save()
            audit.record_create(user, row, recorded(row))
    return made


def end(user, row, last_day):
    """Ends a row on `last_day` (both included): the row is locked, its last day set, its version counted and the change logged
    as the assignment's edit logs it (before and after). The farm's rule for a row that has started is kept: its past days
    keep their protocol, so the last day is yesterday at the earliest; a day before the row's first day, or after its
    own last day, is refused. Returns the row."""
    with transaction.atomic():
        row = ProtocolAssignment.all_objects.select_for_update().get(pk=row.pk)
        if row.is_deleted:
            raise ValidationError({'valid_until': _('This assignment was deleted meanwhile.')})
        if last_day < row.valid_from:
            raise ValidationError({'valid_until': _('The last day comes on or after the first day.')})
        if row.valid_until is not None and last_day > row.valid_until:
            raise ValidationError({'valid_until': _('The row ends on %(day)s already: it is only ever shortened.') % {
                'day': row.valid_until.isoformat()}})
        if row.valid_from <= local_today(row.unit) and last_day < local_today(row.unit) - timedelta(days=1):
            raise ValidationError({'valid_until': _('The days before yesterday keep their protocol: the last day is '
                                                    'yesterday at the earliest.')})
        before = recorded(row)
        row.valid_until, row.updated_by = last_day, user
        row.version += 1
        row.save()
        audit.record_update(user, row, before, recorded(row))
        return row
