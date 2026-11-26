"""The helpers that write inside their caller's transaction say so, and check it (the data-layering audit, L-13): there is
no ATOMIC_REQUESTS, so atomicity is explicit everywhere, and a helper that locks a row and writes several must never run
in autocommit, where its lock would end at its first statement and a failure would leave half its writes."""
from django.db import connection
from django.db.transaction import TransactionManagementError


def required(what):
    """Refuses (TransactionManagementError) unless a transaction is open on the default connection: `what` names the
    helper, so the message says whose caller forgot it."""
    if not connection.in_atomic_block:
        raise TransactionManagementError(f'{what} writes inside its caller\'s transaction: open one '
                                         f'(transaction.atomic) around the call.')
