"""Migration operations of the core app (`DefinerTrigger`: a trigger run as its owner, hardened; at the end).

`TrackRev` makes a table move `core_rev` (core.rev) whenever one of its rows changes, by three triggers:
- `core_rev_<table>_<scope>_note`, an AFTER ROW trigger, works out the keys the change touches (the old and the new
  row's, both when an update moves a row) and the earliest day it touches, and notes them for the transaction
  (`core_rev_note`: nothing is written, no lock is taken);
- `core_rev_<table>_<scope>_apply`, a deferred constraint trigger, applies what was noted at COMMIT (`core_rev_apply`),
  each key once and in sorted order, so two writers never lock the counter rows in opposite orders (a row stays
  locked from its apply to the end of that COMMIT);
- `core_rev_<table>_<scope>_trunc`, an AFTER TRUNCATE statement trigger: a TRUNCATE fires no row trigger, so it moves
  every key of the scope at once (`core_rev_truncated`), with the whole history as the day.
Because they are triggers, every writer is covered: the services, `bulk_create`, the admin, raw SQL and a restore."""
import re

from django.db.migrations.operations.base import Operation

NAME = re.compile(r'^[a-z_][a-z0-9_]*$')
# A scope is what core_rev_note accepts (migration core/0014): lower-case letters and underscores.
SCOPE = re.compile(r'^[a-z_]+$')
# PostgreSQL cuts a longer name to 63 bytes without an error: the presence check (core.rev.missing) would then look for a
# name that is not there.
LONGEST = 63
SUFFIXES = ('note', 'apply', 'trunc')


class TrackRev(Operation):
    """`keys`: an SQL expression of the row (`{row}.batch_id`) or a SELECT of one column (`SELECT batch_id FROM
    stock_movements WHERE operation_id = {row}.id`) giving the keys of `scope` the row belongs to; None for a table-level
    scope (key '0'). `day`: an SQL expression of the row giving the earliest day the change can affect (a ledger line's
    date), or None for a scope without days (a change then counts for the whole history, core.rev.EVERYTHING). An unknown
    day (the expression is NULL, e.g. a line whose operation is gone) counts as the whole history too. `columns`: only
    updates that change one of these columns count (the insert and delete of a row always do, unless `events` leaves
    them out)."""
    reversible = True
    reduces_to_sql = True

    def __init__(self, table, scope, keys=None, day=None, columns=(), events=('INSERT', 'UPDATE', 'DELETE')):
        if not (NAME.match(table) and SCOPE.match(scope)):
            raise ValueError(f'TrackRev: {table!r} and {scope!r} must be plain lower-case names (a scope has no digits).')
        if columns and any(not NAME.match(column) for column in columns):
            raise ValueError(f'TrackRev: bad column names {columns!r}.')
        if len(f'core_rev_{table}_{scope}_') + max(map(len, SUFFIXES)) > LONGEST:
            raise ValueError(f'TrackRev: the trigger names of {table!r} and {scope!r} would be longer than {LONGEST}.')
        if columns and tuple(events) != ('UPDATE',):
            raise ValueError('TrackRev: a column filter needs events=("UPDATE",) (a WHEN cannot read OLD on an insert).')
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
        return tuple(f'{self.function}_{suffix}' for suffix in SUFFIXES)

    def _keys(self, row):
        if self.keys is None:
            return "SELECT '0'::text"
        text = self.keys.format(row=row)
        if text.lstrip().upper().startswith('SELECT'):
            return f'SELECT DISTINCT q.k::text FROM ({text}) AS q(k)'
        return f'SELECT ({text})::text'

    def _day(self, row):
        if self.day is None:
            return 'NULL::date'
        return f"COALESCE(({self.day.format(row=row)})::date, DATE '0001-01-01')"

    def sql_forwards(self):
        note, apply, trunc = self.names()
        events = []
        for event in self.events:
            if event == 'UPDATE' and self.columns:
                events.append('UPDATE OF ' + ', '.join(self.columns))
            else:
                events.append(event)
        events = ' OR '.join(events)
        when = ''
        if self.columns:
            when = 'WHEN (' + ' OR '.join(f'OLD.{c} IS DISTINCT FROM NEW.{c}' for c in self.columns) + ') '
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
            f"CREATE TRIGGER {trunc} AFTER TRUNCATE ON {self.table} FOR EACH STATEMENT "
            f"EXECUTE FUNCTION core_rev_truncated('{self.scope}')",
        ]

    def sql_backwards(self):
        note, apply, trunc = self.names()
        return [f'DROP TRIGGER IF EXISTS {trunc} ON {self.table}', f'DROP TRIGGER IF EXISTS {apply} ON {self.table}',
                f'DROP TRIGGER IF EXISTS {note} ON {self.table}', f'DROP FUNCTION IF EXISTS {self.function}()']

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


class Statements(Operation):
    """An operation that is its statements: `sql_forwards()` run forwards, `sql_backwards()` back, no model state."""
    reversible = True
    reduces_to_sql = True

    def state_forwards(self, app_label, state):
        pass

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        for statement in self.sql_forwards():
            schema_editor.execute(statement, params=None)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        for statement in self.sql_backwards():
            schema_editor.execute(statement, params=None)


class KeepRows(Statements):
    """Makes the database refuse every DELETE of `table`'s rows (a BEFORE DELETE trigger, `trg_<table>_kept`): reference
    rows that a migration seeds and the application only reads and changes, never makes or removes (the platform
    settings, the scheduling settings, the water's freshness rules). With it a reader never meets a lost row it would
    have to make again or stand in for (the data-layering audit, M-1): a read stays a read. `what` names the rows in the
    refusal. A soft delete is refused by each model's own check (`chk_<table>_kept`); a TRUNCATE (a test's flush, a
    restore) is not a row DELETE and is not refused. The alarm severity rules have the same, written by hand before this
    (alarms 0006)."""

    def __init__(self, table, what):
        if not NAME.match(table) or len(f'trg_{table}_kept') > LONGEST:
            raise ValueError(f'KeepRows: {table!r} must be a plain lower-case name of at most {LONGEST - 9} characters.')
        if "'" in what or '%' in what:
            raise ValueError("KeepRows: `what` may hold no ' and no %.")
        self.table, self.what = table, what

    def deconstruct(self):
        return self.__class__.__name__, [self.table, self.what], {}

    def sql_forwards(self):
        return [
            f"CREATE FUNCTION {self.table}_kept() RETURNS trigger AS $f$ BEGIN RAISE EXCEPTION "
            f"'{self.what} are changed, never deleted: the application reads them and never makes them again.' "
            f"USING ERRCODE = 'restrict_violation'; END; $f$ LANGUAGE plpgsql",
            f'CREATE TRIGGER trg_{self.table}_kept BEFORE DELETE ON {self.table} FOR EACH ROW '
            f'EXECUTE FUNCTION {self.table}_kept()',
        ]

    def sql_backwards(self):
        return [f'DROP TRIGGER IF EXISTS trg_{self.table}_kept ON {self.table}',
                f'DROP FUNCTION IF EXISTS {self.table}_kept()']

    def describe(self):
        return f'Refuse every DELETE of {self.table}'

    @property
    def migration_name_fragment(self):
        return f'keep_{self.table}'


class DefinerTrigger(Statements):
    """A trigger whose function runs as its owner (SECURITY DEFINER), so the app role needs no right on what it writes,
    made so the app role can neither forge it nor turn it aside (review of production-plan 2, H1; review of the perf
    tests 2, H2):
    - EXECUTE on the function is taken from PUBLIC: nobody but its owner can make another trigger call it (a trigger on
      a temporary table of the same name would make it write the real table); firing needs no EXECUTE;
    - the function refuses to run for any table but `public.<table>` (TG_TABLE_SCHEMA, TG_TABLE_NAME), the second wall;
    - its search_path is `pg_catalog, public, pg_temp`, the session's temporary schema last, and `body` names every table
      it reads or writes with its schema (`public.alarm_open`), so a temporary table of the same name is never the one
      written; checked here, but for the transition table (`new_table`, `old_table`).
    `body` is plpgsql run before `RETURN NULL`. Going back drops the trigger and the function."""
    NAMED = re.compile(r'\b(?:FROM|INTO|UPDATE|JOIN|USING|TABLE)\s+([A-Za-z_][A-Za-z0-9_.]*)', re.IGNORECASE)

    def __init__(self, table, trigger, function, body, events=('INSERT',), level='STATEMENT', new_table=None,
                 old_table=None):
        names = [table, trigger, function] + [each for each in (new_table, old_table) if each]
        if any(not NAME.match(name) or len(name) > LONGEST for name in names):
            raise ValueError(f'DefinerTrigger: {names!r} must be plain lower-case names of at most {LONGEST} characters.')
        if level not in ('ROW', 'STATEMENT') or not events or any(
                event not in ('INSERT', 'UPDATE', 'DELETE') for event in events):
            raise ValueError(f'DefinerTrigger: events {events!r} and level {level!r}.')
        if '$f$' in body:
            raise ValueError('DefinerTrigger: the body may not hold $f$.')
        own = {new_table, old_table} - {None}
        loose = [name for name in self.NAMED.findall(body) if '.' not in name and name not in own]
        if loose:
            raise ValueError(f'DefinerTrigger: name every table with its schema (public.{loose[0]}): a temporary table '
                             f'of that name would be the one written.')
        self.table, self.trigger, self.function, self.body = table, trigger, function, body
        self.events, self.level, self.new_table, self.old_table = tuple(events), level, new_table, old_table

    def deconstruct(self):
        return self.__class__.__name__, [self.table, self.trigger, self.function, self.body], {
            'events': self.events, 'level': self.level, 'new_table': self.new_table, 'old_table': self.old_table}

    def sql_forwards(self):
        transitions = ' '.join(f'{kind} TABLE AS {name}' for kind, name in (('NEW', self.new_table),
                                                                           ('OLD', self.old_table)) if name)
        return [
            f"""CREATE FUNCTION public.{self.function}() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp AS $f$
BEGIN
    IF TG_TABLE_SCHEMA <> 'public' OR TG_TABLE_NAME <> '{self.table}' THEN
        RAISE EXCEPTION '{self.function} runs for public.{self.table} only, not %.%', TG_TABLE_SCHEMA, TG_TABLE_NAME
            USING ERRCODE = 'insufficient_privilege';
    END IF;
{self.body}
    RETURN NULL;
END
$f$""",
            f'REVOKE EXECUTE ON FUNCTION public.{self.function}() FROM PUBLIC',
            f'CREATE TRIGGER {self.trigger} AFTER {" OR ".join(self.events)} ON public.{self.table} '
            f'{"REFERENCING " + transitions + " " if transitions else ""}FOR EACH {self.level} '
            f'EXECUTE FUNCTION public.{self.function}()',
        ]

    def sql_backwards(self):
        return [f'DROP TRIGGER IF EXISTS {self.trigger} ON public.{self.table}',
                f'DROP FUNCTION IF EXISTS public.{self.function}()']

    def describe(self):
        return f'Trigger {self.trigger} on {self.table}, run as its owner by {self.function}()'

    @property
    def migration_name_fragment(self):
        return f'definer_{self.trigger}'
