"""The next generated code of a record kind (a batch's `B-2026-001`, an experiment's `E-2026-001`): one rule."""
from django.db import connection
from django.db.models import IntegerField, Max
from django.db.models.functions import Cast, Substr


def next_code(model, prefix):
    """`<prefix><n>`, n one more than any number given under that prefix, deleted records included: a number
    is never given twice. An advisory lock (keyed on the model's table, as `hashtext('<table>.code')`) makes
    two creators take turns for it, so call this inside the transaction that saves the record. `model` has
    `all_objects` (core.models.AuditedModel) and a `code`; `prefix` ends where the number starts."""
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', [f'{model._meta.db_table}.code'])
    last = (model.all_objects.filter(code__startswith=prefix)
            .annotate(n=Cast(Substr('code', len(prefix) + 1), IntegerField())).aggregate(last=Max('n'))['last'])
    return f'{prefix}{(last or 0) + 1:03d}'
