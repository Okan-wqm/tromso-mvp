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
from django.utils.deconstruct import deconstructible

NAME = re.compile(r'^[a-z_][a-z0-9_]*$')
# A scope is what core_rev_note accepts (migration core/0014): lower-case letters and underscores.
SCOPE = re.compile(r'^[a-z_]+$')
# PostgreSQL cuts a longer name to 63 bytes without an error: the presence check (core.rev.missing) would then look for a
# name that is not there.
LONGEST = 63
SUFFIXES = ('note', 'apply', 'trunc')


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


class TrackRev(Statements):
    """`keys`: an SQL expression of the row (`{row}.batch_id`) or a SELECT of one column (`SELECT batch_id FROM
    stock_movements WHERE operation_id = {row}.id`) giving the keys of `scope` the row belongs to; None for a table-level
    scope (key '0'). `day`: an SQL expression of the row giving the earliest day the change can affect (a ledger line's
    date), or None for a scope without days (a change then counts for the whole history, core.rev.EVERYTHING). An unknown
    day (the expression is NULL, e.g. a line whose operation is gone) counts as the whole history too. `columns`: only
    updates that change one of these columns count (the insert and delete of a row always do, unless `events` leaves
    them out)."""

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

    def describe(self):
        return f'Track changes of {self.table} in core_rev scope {self.scope}'

    @property
    def migration_name_fragment(self):
        return f'track_{self.table}_{self.scope}'


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


@deconstructible(path='core.operations.On')
class On:
    """One trigger of a DefinerTrigger: AFTER `events` on `public.<table>`, named `trigger`, FOR EACH `level` (ROW or
    STATEMENT; a TRUNCATE is a STATEMENT trigger), with its transition tables (`new_table`, `old_table`: one event
    only), a `when` condition (an SQL expression of OLD and NEW, ROW triggers) and `args`, the strings the function
    reads as TG_ARGV."""
    EVENTS = ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE')

    def __init__(self, table, trigger, events=('INSERT',), level='STATEMENT', new_table=None, old_table=None,
                 when=None, args=()):
        names = [table, trigger] + [each for each in (new_table, old_table) if each]
        if any(not NAME.match(name) or len(name) > LONGEST for name in names):
            raise ValueError(f'On: {names!r} must be plain lower-case names of at most {LONGEST} characters.')
        events = tuple(events)
        if (level not in ('ROW', 'STATEMENT') or not events or len(set(events)) != len(events)
                or any(event not in self.EVENTS for event in events)):
            raise ValueError(f'On: events {events!r} and level {level!r}.')
        if 'TRUNCATE' in events and (level != 'STATEMENT' or new_table or old_table or when):
            raise ValueError('On: a TRUNCATE trigger is a STATEMENT trigger, with no transition table and no WHEN.')
        if (new_table or old_table) and len(events) != 1:
            raise ValueError('On: a transition table is for a trigger of one event (PostgreSQL).')
        if when is not None and (level != 'ROW' or '$f$' in when):
            raise ValueError('On: a WHEN condition is for a ROW trigger, and may not hold $f$.')
        if any(not isinstance(arg, str) or '\x00' in arg for arg in args):
            raise ValueError(f'On: args {args!r} must be strings.')
        self.table, self.trigger, self.events, self.level = table, trigger, events, level
        self.new_table, self.old_table, self.when, self.args = new_table, old_table, when, tuple(args)

    def __eq__(self, other):
        return isinstance(other, On) and vars(self) == vars(other)

    def __hash__(self):
        return hash((self.table, self.trigger))

    def create(self, function):
        transitions = ' '.join(f'{kind} TABLE AS {name}' for kind, name in (('NEW', self.new_table),
                                                                           ('OLD', self.old_table)) if name)
        args = ', '.join("'" + arg.replace("'", "''") + "'" for arg in self.args)
        return (f'CREATE TRIGGER {self.trigger} AFTER {" OR ".join(self.events)} ON public.{self.table} '
                f'{"REFERENCING " + transitions + " " if transitions else ""}FOR EACH {self.level} '
                f'{"WHEN (" + self.when + ") " if self.when else ""}EXECUTE FUNCTION public.{function}({args})')

    def drop(self):
        return f'DROP TRIGGER IF EXISTS {self.trigger} ON public.{self.table}'


class DefinerTrigger(Statements):
    """A trigger function that runs as its owner (SECURITY DEFINER), so the app role needs no right on what it writes,
    and its triggers (`on`: one or more core.operations.On, on one table or many), made so that no other role can call
    it with a table of its choosing (review of production-plan 2, H1; review of the perf tests 2, H2, and 3, L2):
    - EXECUTE on the function is taken from PUBLIC: nobody but its owner may make another trigger call it (firing a
      trigger needs no EXECUTE); the runtime roles may make no temporary table either (deploy/db/sql/roles.sql);
    - the function refuses to run for any table but those of `on`, in the public schema (TG_TABLE_SCHEMA,
      TG_TABLE_NAME);
    - its search_path is `pg_catalog, public, pg_temp`, the session's temporary schema last, so a table named in `body`
      is always the public one, never a temporary table of the same name (core/tests_definer_trigger.py proves it).
    `body` is plpgsql run before `RETURN NULL` (they are AFTER triggers), `declare` its variables. Going back drops the
    triggers and the function. deploy/scripts/check-roles.sh proves on a server that neither runtime role may call a
    SECURITY DEFINER function.

    The tables a function serves are written into it (its check of TG_TABLE_NAME): a later migration that adds a table
    to an existing function (production-plan's row versions, a newly kept table) recreates it, by a migration operation
    that runs this one's `sql_backwards()` and then the `sql_forwards()` of one naming every table, old and new; a
    trigger of the new table on the old function would be refused at its first write. One operation per function, so
    the function and every trigger on it are made, and dropped, together."""

    def __init__(self, function, body, on, declare=''):
        on = tuple(on)
        if not NAME.match(function) or len(function) > LONGEST:
            raise ValueError(f'DefinerTrigger: {function!r} must be a plain lower-case name of at most {LONGEST} '
                             f'characters.')
        if not on or any(not isinstance(each, On) for each in on):
            raise ValueError('DefinerTrigger: `on` is one or more core.operations.On.')
        if len({(each.table, each.trigger) for each in on}) != len(on):
            raise ValueError('DefinerTrigger: two triggers of one name on one table.')
        if '$f$' in body or '$f$' in declare:
            raise ValueError('DefinerTrigger: the body and the declarations may not hold $f$.')
        self.function, self.body, self.on, self.declare = function, body, on, declare

    def deconstruct(self):
        return self.__class__.__name__, [self.function, self.body, list(self.on)], {'declare': self.declare}

    @property
    def tables(self):
        return sorted({each.table for each in self.on})

    def sql_forwards(self):
        tables = ', '.join(f"'{table}'" for table in self.tables)
        named = ', '.join(f'public.{table}' for table in self.tables)
        declare = f'DECLARE\n{self.declare}\n' if self.declare.strip() else ''
        return [
            f"""CREATE FUNCTION public.{self.function}() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp AS $f$
{declare}BEGIN
    IF TG_TABLE_SCHEMA <> 'public' OR TG_TABLE_NAME <> ALL (ARRAY[{tables}]) THEN
        RAISE EXCEPTION '{self.function} runs for {named} only, not %.%', TG_TABLE_SCHEMA, TG_TABLE_NAME
            USING ERRCODE = 'insufficient_privilege';
    END IF;
{self.body}
    RETURN NULL;
END
$f$""",
            f'REVOKE EXECUTE ON FUNCTION public.{self.function}() FROM PUBLIC',
            *(each.create(self.function) for each in self.on),
        ]

    def sql_backwards(self):
        return [*(each.drop() for each in reversed(self.on)), f'DROP FUNCTION IF EXISTS public.{self.function}()']

    def describe(self):
        return f'Triggers {", ".join(each.trigger for each in self.on)}, run as their owner by {self.function}()'

    @property
    def migration_name_fragment(self):
        return f'definer_{self.function}'
