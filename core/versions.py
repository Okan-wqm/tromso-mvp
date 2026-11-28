"""Row versions: what a row was at a moment, read by its identity (the production plan's owner decision 12, as decided
after review 1: a plan from a past start is the plan as it stood then, never rebuilt from the activity log's labels).

`core_rev` (core.rev) counts changes and keeps no values. A kept table (VERSIONED) keeps every version of its rows in
`core_row_versions` (core.models.RowVersion): the database writes them, by the triggers a migration adds with
`core.operations.KeepVersions`, so every writer is covered (the services, `bulk_create`, the admin, raw SQL); the app's
role may read the versions, never write them (deploy/db/sql/grants.sql). A version holds the row's values whole and
the moments it was the row's: from `valid_from`, up to but not including `valid_to` (open: the row's values now).

`as_of(model, moment, **any_of)` gives the rows of a kept model as they were at `moment`: the version of each row valid
then, made into an instance of the model, its values typed as the table types them. A row is found by its primary key,
never by a name: a row renamed since, and another given its old name since, are each themselves. A row made after
`moment` is not read; a row changed or deleted since is read as it was; a row soft-deleted then (`is_deleted`) is left
out unless `deleted=True` (a protocol deleted later is still the table of the rows that named it). `any_of`:
{field: values}, the rows whose field held one of the values at `moment` (several fields: any of them). The rows of a
sealed model (core.sealing) are narrowed for the viewer of the moment by the row as it is now, as its managers narrow
it: a row the viewer may not see now is not read.

The instances are read, never saved (that would write past values over the row). Their links are ids: a link followed
loads the record as it is now. A migration that renames or retypes a kept column rewrites the versions' values too:
the stored values are read by the table's columns at the time of reading, and a column a version lacks reads NULL."""
from django.db import connection

from . import sealing

# Every table a migration keeps the versions of (core.operations.KeepVersions, farm migration 0056): a test compares it
# with the triggers in the database and with the migrations.
VERSIONED = ('feeding_protocols', 'feeding_protocol_bands', 'feeding_protocol_rates', 'protocol_assignments',
             'temperature_profiles', 'temperature_profile_points', 'temperature_profile_assignments',
             'handling_plan_items')


def as_of(model, moment, deleted=False, **any_of):
    """[instances of `model`] as its rows were at `moment` (an aware datetime), in primary-key order; see the module."""
    table = model._meta.db_table
    if table not in VERSIONED:
        raise ValueError(f'{model._meta.label}: its versions are not kept (core.versions.VERSIONED).')
    quote = connection.ops.quote_name
    fields = model._meta.concrete_fields
    where = ['v.table_name = %s', 'v.valid_from <= %s', '(v.valid_to IS NULL OR v.valid_to > %s)']
    params = [table, moment, moment]
    either = []
    for name, values in any_of.items():
        values = [value for value in values if value is not None]
        if values:
            either.append(f'r.{quote(model._meta.get_field(name).column)} = ANY(%s)')
            params.append(values)
    if any_of and not either:
        return []
    if either:
        where.append('(' + ' OR '.join(either) + ')')
    if not deleted and any(field.name == 'is_deleted' for field in fields):
        where.append('NOT r.is_deleted')
    key = quote(model._meta.pk.column)
    seal = sealing.seal_of(model)
    if seal is not None and seal.filters:
        visible, more = model.all_objects.values('pk').query.sql_with_params()
        where.append(f'r.{key} IN ({visible})')
        params.extend(more)
    columns = ', '.join(f'r.{quote(field.column)}' for field in fields)
    return list(model._base_manager.raw(
        f'SELECT {columns} FROM core_row_versions v CROSS JOIN LATERAL jsonb_populate_record(NULL::{quote(table)}, '
        f'v.data) r WHERE {" AND ".join(where)} ORDER BY r.{key}', params))
