"""Migration operations of the core app.

`TrackRev` makes a table move `core_rev` (core.rev) whenever one of its rows changes, by two triggers:
- `core_rev_<table>_<scope>_note`, an AFTER ROW trigger, works out the keys the change touches (the old and the new
  row's, both when an update moves a row) and the earliest day it touches, and notes them for the transaction
  (`core_rev_note`: nothing is written, no lock is taken);
- `core_rev_<table>_<scope>_apply`, a deferred constraint trigger, applies what was noted at COMMIT (`core_rev_apply`),
  each key once and in sorted order, so the counter rows are locked for microseconds and two writers never lock them
  in opposite orders.
Because they are triggers, every writer is covered: the services, `bulk_create`, the admin, raw SQL and a restore."""
import re

from django.db.migrations.operations.base import Operation

NAME = re.compile(r'^[a-z_][a-z0-9_]*$')


class TrackRev(Operation):
    """`keys`: an SQL expression of the row (`{row}.batch_id`) or a SELECT of one column (`SELECT batch_id FROM
    stock_movements WHERE operation_id = {row}.id`) giving the keys of `scope` the row belongs to; None for a table-level
    scope (key '0'). `day`: an SQL expression of the row giving the earliest day the change can affect (a ledger line's
    date), or None for a scope without days. An unknown day (the expression is NULL, e.g. a line whose operation is
    gone) counts as the whole history. `columns`: only updates that change one of these columns count (the insert and
    delete of a row always do, unless `events` leaves them out)."""
    reversible = True
    reduces_to_sql = True

    def __init__(self, table, scope, keys=None, day=None, columns=(), events=('INSERT', 'UPDATE', 'DELETE')):
        if not (NAME.match(table) and NAME.match(scope)):
            raise ValueError(f'TrackRev: {table!r} and {scope!r} must be plain lower-case names.')
        if columns and any(not NAME.match(column) for column in columns):
            raise ValueError(f'TrackRev: bad column names {columns!r}.')
        self.table, self.scope, self.keys, self.day = table, scope, keys, day
        self.columns, self.events = tuple(columns), tuple(events)

    def deconstruct(self):
        return self.__class__.__name__, [self.table, self.scope], {
            'keys': self.keys, 'day': self.day, 'columns': self.columns, 'events': self.events}

    def state_forwards(self, app_label, state):
        pass

    @property
    def function(self):
        return f'core_rev_{self.table}_{self.scope}'

    def names(self):
        return f'{self.function}_note', f'{self.function}_apply'

    def _keys(self, row):
        if self.keys is None:
            return "SELECT '0'::text"
        text = self.keys.format(row=row)
        return f'SELECT q.k::text FROM ({text}) AS q(k)' if text.lstrip().upper().startswith('SELECT') else f'SELECT ({text})::text'

    def _day(self, row):
        if self.day is None:
            return 'NULL::date'
        return f"COALESCE(({self.day.format(row=row)})::date, DATE '0001-01-01')"

    def sql_forwards(self):
        note, apply = self.names()
        events = []
        for event in self.events:
            if event == 'UPDATE' and self.columns:
                events.append('UPDATE OF ' + ', '.join(self.columns))
            else:
                events.append(event)
        events = ' OR '.join(events)
        when = ''
        if self.columns and self.events == ('UPDATE',):
            when = 'WHEN (' + ' OR '.join(f'OLD.{c} IS DISTINCT FROM NEW.{c}' for c in self.columns) + ') '
        elif self.columns:
            raise ValueError('TrackRev: a column filter needs events=("UPDATE",) (a WHEN cannot read OLD on an insert).')
        function = f"""
CREATE FUNCTION {self.function}() RETURNS trigger LANGUAGE plpgsql AS $f$
DECLARE
    k text;
    d date;
BEGIN
    IF TG_OP = 'INSERT' THEN
        d := {self._day('NEW')};
    ELSIF TG_OP = 'DELETE' THEN
        d := {self._day('OLD')};
    ELSE
        d := LEAST({self._day('OLD')}, {self._day('NEW')});
    END IF;
    IF TG_OP <> 'INSERT' THEN
        FOR k IN {self._keys('OLD')} LOOP
            IF k IS NOT NULL THEN PERFORM core_rev_note('{self.scope}', k, d); END IF;
        END LOOP;
    END IF;
    IF TG_OP <> 'DELETE' THEN
        FOR k IN {self._keys('NEW')} LOOP
            IF k IS NOT NULL THEN PERFORM core_rev_note('{self.scope}', k, d); END IF;
        END LOOP;
    END IF;
    RETURN NULL;
END
$f$"""
        return [
            function,
            f'CREATE TRIGGER {note} AFTER {events} ON {self.table} FOR EACH ROW {when}EXECUTE FUNCTION {self.function}()',
            f'CREATE CONSTRAINT TRIGGER {apply} AFTER {events} ON {self.table} DEFERRABLE INITIALLY DEFERRED '
            f'FOR EACH ROW {when}EXECUTE FUNCTION core_rev_apply()',
        ]

    def sql_backwards(self):
        note, apply = self.names()
        return [f'DROP TRIGGER IF EXISTS {apply} ON {self.table}', f'DROP TRIGGER IF EXISTS {note} ON {self.table}',
                f'DROP FUNCTION IF EXISTS {self.function}()']

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        for statement in self.sql_forwards():
            schema_editor.execute(statement, params=None)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        for statement in self.sql_backwards():
            schema_editor.execute(statement, params=None)

    def describe(self):
        return f'Track changes of {self.table} in core_rev scope {self.scope}'

    @property
    def migration_name_fragment(self):
        return f'track_{self.table}_{self.scope}'
