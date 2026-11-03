"""The write path of protocol assignments: the rows for a protocol, a day range and the units or the batch it
feeds (checked as the assignment dialog checks them), and writing them, each logged. The dialog
(farm/forms/feeding_protocol.py, farm/resources/feeding_protocol.py) and an experiment's start
(experiments/services.py) both come through here, so a row written for an experiment is the row the dialog
would write and the log shows the same entry."""
import uuid
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction

from core import audit
from farm.models import ProtocolAssignment, Tank

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

