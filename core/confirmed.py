"""Whether a record is still the one the person saw: the version their page carried, compared with the record as read
now. One comparison (`unchanged`) and its sentences (`changed_meanwhile`) for an edit, a row list and a delete, below
the views: crud (core.crud) and the services that lock in their own order (hr.services) both use them. A delete asks
`as_confirmed` last, after the scope, the record's own rule and the reach, so a record the person may not delete is
refused for that (a 404 or a 403), never as unconfirmed or changed."""
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from .models import AuditedModel


class NotConfirmed(Exception):
    """A delete posted without the version its confirmation showed: it confirmed nothing (crud answers 400)."""


class ChangedMeanwhile(ValidationError):
    """The record was changed (or deleted) after the person's confirmation showed it: nothing is deleted, said."""


def unchanged(seen, record):
    """Whether `record` (as read now, locked or not) is still the one the person saw: its version is the one their page
    carried (`seen`, posted as text or cleaned as a number). A record without a version (not an AuditedModel) has
    nothing to compare. The one comparison of an edit, a row list and a delete."""
    return not isinstance(record, AuditedModel) or str(seen) == str(record.version)


def changed_meanwhile(name, deleting=False):
    """The sentence of a record changed since the person read it: for an edit or a row list, the form shows their
    version; for a delete, the confirmation showed another record than the one now there. The one place of both
    sentences."""
    if deleting:
        # Translators: %(name)s is the kind of record in lower case (e.g. site).
        return _('This %(name)s was changed while you were looking at it: check it and delete it again.') % {
            'name': name}
    # Translators: %(name)s is the kind of record in lower case (e.g. site).
    return _('Someone else changed this %(name)s while you were editing it. The form now shows their version; make '
             'your changes again.') % {'name': name}


def as_confirmed(current, seen, name):
    """A delete goes on only for the record its confirmation showed: `seen` is the version the confirmation posted ('' or
    None: none), `current` the record as read now (under the lock of whoever deletes; None when it is gone meanwhile),
    `name` its kind for the sentence. A versioned record (an AuditedModel) posted without a version raises
    NotConfirmed; one gone or changed since raises ChangedMeanwhile. A record without a version has nothing to
    confirm. Asked last, after every other refusal of the delete."""
    if current is not None and not isinstance(current, AuditedModel):
        return
    if seen is None or str(seen) == '':
        raise NotConfirmed(name)
    if current is None or not unchanged(seen, current):
        raise ChangedMeanwhile(changed_meanwhile(name, deleting=True))
