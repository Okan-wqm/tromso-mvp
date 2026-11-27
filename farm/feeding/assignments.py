"""The write path of assignments, of feeding protocols and of temperature profiles alike (farm/models/assignment.py):
the rows for a table, a day range and the units or the batch it applies to (checked as the assignment dialog checks them), writing them, each logged, and ending one. The dialog
(farm/forms/feeding_protocol.py, farm/resources/feeding_protocol.py) and an experiment's start and its amendments
(experiments/services.py) come through here, so a row written or ended for an experiment is the row the dialog
would write or end and the log shows the same entry."""
import uuid
from dataclasses import dataclass
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from core import access, audit
from farm.models import Tank
from farm.models.assignment import ProtocolStatus
from farm.stock.dates import local_today

# The fields the activity log shows of an assignment (and the assignment's form, on its one tab).
# Who may assign a protocol (Feeding protocols › Assignments: Create), asked by `save` itself (the data-layering audit,
# L-6). An experiment writes its diet's rows under its own right, through `write` inside its checked call.
ASSIGN = 'farm.add_protocolassignment'
FIELDS = ('protocol', 'unit', 'batch', 'valid_from', 'valid_until', 'notes')


def fields_of(subject):
    """The fields the activity log shows of an assignment of `subject` (its table's field: protocol, profile)."""
    return (subject, *FIELDS[1:])


@dataclass(frozen=True)
class RowError:
    """Why the row of `unit` (None: the batch alone) was not made: `message` is on a field of the assignment, or
    on the row as a whole (NON_FIELD_ERRORS: another protocol in force on some of its days)."""
    unit: Tank
    field: str
    message: str


def rows(subject, units, batch, first, last, notes=''):
    """([assignment], [RowError]) of `subject` (a feeding protocol, a temperature profile: its rows' model): a row per unit (one row for a batch alone), all with one group,
    checked as a row (its fields, and the overlap with the rows in force, by the database's own constraints).
    A row with an error is left out; the caller refuses the whole, or shows what concerns each unit. `last` None:
    until it is ended."""
    group = uuid.uuid4()
    made, errors = [], []
    for unit in units or [None]:
        model = subject.assignments.model
        row = model(**{model.SUBJECT: subject}, unit=unit, batch=batch, group_id=group, valid_from=first,
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
        return audit.snapshot(row, fields_of(row.SUBJECT))


def save(user, made):
    """Writes the rows of `rows()` together for `user`, who may assign their table (its rows' add right), each logged
    as created by them. An IntegrityError (a row written for the same fish meanwhile: the constraints) leaves nothing written and is
    the caller's to report."""
    meta = made[0]._meta if made else None
    access.require(user, f'{meta.app_label}.add_{meta.model_name}' if meta else ASSIGN)
    return write(user, made)


def write(user, made):
    """`save`'s write without its question, for a caller that asked its own (an experiment's start or replacement, under
    the experiment's right): the rows together, each logged as created by `user`. The table each row assigns is locked
    first and asked again whether it is active (owner decision Q3, review 1 L6): a change of its table or points (which
    takes the same lock and asks whether it is assigned) and its assignment never both commit, so an assigned table
    is the table its rows have always read."""
    with transaction.atomic():
        subjects = {(type(row.subject), row.subject_id) for row in made}
        for model, pk in sorted(subjects, key=lambda pair: str(pair[1])):
            locked = model.all_objects.select_for_update().get(pk=pk)
            if locked.is_deleted or locked.status != ProtocolStatus.ACTIVE:
                raise ValidationError({made[0].SUBJECT: _('%(table)s is no longer active: it was changed meanwhile.')
                                       % {'table': locked}})
        for row in made:
            row.created_by = row.updated_by = user
            row.save()
            audit.record_create(user, row, recorded(row))
    return made


def end(user, row, last_day):
    """Ends a row on `last_day` (both included): the row is locked, its last day set, its version counted and the change logged
    as the assignment's edit logs it (before and after). The farm's rule for a row that has started is kept: its past days
    keep their protocol, so the last day is yesterday at the earliest; a day before the row's first day, or after its
    own last day, is refused. Returns the row. A step of an experiment's release, inside its checked call (the
    assignment page has no end of its own: an edit there is crud's)."""
    with transaction.atomic():
        row = type(row).all_objects.select_for_update().get(pk=row.pk)
        if row.is_deleted:
            raise ValidationError({'valid_until': _('This assignment was deleted meanwhile.')})
        if last_day < row.valid_from:
            raise ValidationError({'valid_until': _('The last day comes on or after the first day.')})
        if row.valid_until is not None and last_day > row.valid_until:
            raise ValidationError({'valid_until': _('The row ends on %(day)s already: it is only ever shortened.') % {
                'day': row.valid_until.isoformat()}})
        if row.valid_from <= local_today(row.unit) and last_day < local_today(row.unit) - timedelta(days=1):
            raise ValidationError({'valid_until': str(type(row).KEPT)})
        before = recorded(row)
        row.valid_until, row.updated_by = last_day, user
        row.version += 1
        row.save()
        audit.record_update(user, row, before, recorded(row))
        return row
