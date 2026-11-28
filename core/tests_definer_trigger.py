"""core.operations.DefinerTrigger: a trigger function run as its owner, made so that no other role can call it with a
table of its choosing (review of production-plan 2, H1; review of the perf tests 2, H2, and 3, L2). What it makes is
read here, and run in the database: one function for many tables, with its arguments (TG_ARGV), its variables, a
RETURNING ... INTO, a WHEN and a TRUNCATE trigger, refused for any other table, and a table its body names without a
schema always the public one. alarms/tests/test_open_alarms.py runs the open alarms' triggers the same way, and
deploy/scripts/check-roles.sh proves on the go-live stack that the app role may neither call one nor make a temporary
table."""
from django.db import DatabaseError, connection, transaction
from django.test import SimpleTestCase, TestCase

from .operations import DefinerTrigger, On

BODY = """
    INSERT INTO public.queue (id) SELECT n.id FROM made n;"""


def queued():
    return DefinerTrigger('things_queued', BODY, [On('things', 'trg_things_queue', new_table='made')])


class DefinerTriggerTests(SimpleTestCase):
    def test_what_it_makes_is_hardened(self):
        function, revoke, trigger = queued().sql_forwards()
        self.assertIn('CREATE FUNCTION public.things_queued() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER', function)
        self.assertIn('SET search_path = pg_catalog, public, pg_temp', function)           # the temporary schema last
        self.assertIn("IF TG_TABLE_SCHEMA <> 'public' OR TG_TABLE_NAME <> ALL (ARRAY['things']) THEN", function)
        self.assertNotIn('DECLARE', function)
        self.assertEqual(revoke, 'REVOKE EXECUTE ON FUNCTION public.things_queued() FROM PUBLIC')
        self.assertEqual(trigger, 'CREATE TRIGGER trg_things_queue AFTER INSERT ON public.things REFERENCING NEW TABLE '
                                  'AS made FOR EACH STATEMENT EXECUTE FUNCTION public.things_queued()')
        self.assertEqual(queued().sql_backwards(), ['DROP TRIGGER IF EXISTS trg_things_queue ON public.things',
                                                    'DROP FUNCTION IF EXISTS public.things_queued()'])

    def test_one_function_for_many_tables_with_its_arguments(self):
        operation = DefinerTrigger('versioned', BODY, [
            On('things', 'things_row', events=('INSERT', 'DELETE'), level='ROW', args=('id',)),
            On('things', 'things_upd', events=('UPDATE',), level='ROW', when='OLD.* IS DISTINCT FROM NEW.*',
               args=("it's",)),
            On('others', 'others_trunc', events=('TRUNCATE',))], declare='    at timestamptz;')
        function, _, row, update, truncate = operation.sql_forwards()
        self.assertIn("TG_TABLE_NAME <> ALL (ARRAY['others', 'things'])", function)
        self.assertIn('DECLARE\n    at timestamptz;\nBEGIN', function)
        self.assertEqual(row, 'CREATE TRIGGER things_row AFTER INSERT OR DELETE ON public.things FOR EACH ROW '
                              "EXECUTE FUNCTION public.versioned('id')")
        self.assertEqual(update, 'CREATE TRIGGER things_upd AFTER UPDATE ON public.things FOR EACH ROW '
                                 "WHEN (OLD.* IS DISTINCT FROM NEW.*) EXECUTE FUNCTION public.versioned('it''s')")
        self.assertEqual(truncate, 'CREATE TRIGGER others_trunc AFTER TRUNCATE ON public.others FOR EACH STATEMENT '
                                   'EXECUTE FUNCTION public.versioned()')
        self.assertEqual(operation.sql_backwards()[:3], ['DROP TRIGGER IF EXISTS others_trunc ON public.others',
                                                         'DROP TRIGGER IF EXISTS things_upd ON public.things',
                                                         'DROP TRIGGER IF EXISTS things_row ON public.things'])
        _, args, kwargs = operation.deconstruct()
        self.assertEqual(DefinerTrigger(*args, **kwargs).sql_forwards(), operation.sql_forwards())

    def test_names_events_and_shapes_are_checked(self):
        for kwargs in ({'events': ('TRUNCATE',), 'level': 'ROW'}, {'events': ('TRUNCATE',), 'new_table': 'made'},
                       {'level': 'EACH'}, {'events': ('SELECT',)}, {'events': ()}, {'events': ('INSERT', 'INSERT')},
                       {'events': ('INSERT', 'UPDATE'), 'new_table': 'made'}, {'when': 'NEW.id > 0'},
                       {'level': 'ROW', 'when': '$f$'}, {'args': (1,)}, {'table': 'things; drop'},
                       {'trigger': 'Trg'}):
            with self.subTest(**kwargs), self.assertRaises(ValueError):
                On(**{'table': 'things', 'trigger': 'trg_things_queue', **kwargs})
        one = On('things', 'trg_things_queue')
        for args in (('things; drop', BODY, [one]), ('things_queued', BODY, []),
                     ('things_queued', BODY, ['trg_things_queue']), ('things_queued', BODY, [one, one]),
                     ('things_queued', '$f$', [one])):
            with self.subTest(args=args), self.assertRaises(ValueError):
                DefinerTrigger(*args)


# The function of production-plan's row versions (wip/production-plan-growth, core 0021), its body as it is there but
# for the probe's table name.
VERSION = """
    IF TG_OP <> 'INSERT' THEN
        UPDATE definer_probe_versions SET valid_to = GREATEST(at, valid_from)
         WHERE table_name = TG_TABLE_NAME AND row_id = to_jsonb(OLD) ->> TG_ARGV[0] AND valid_to IS NULL
        RETURNING valid_to INTO began;
        at := GREATEST(at, began);
    END IF;
    IF TG_OP <> 'DELETE' THEN
        INSERT INTO definer_probe_versions (table_name, row_id, valid_from, data)
        VALUES (TG_TABLE_NAME, to_jsonb(NEW) ->> TG_ARGV[0], at, to_jsonb(NEW));
    END IF;"""
TRUNCATED = """
    UPDATE definer_probe_versions SET valid_to = GREATEST(clock_timestamp(), valid_from)
     WHERE table_name = TG_TABLE_NAME AND valid_to IS NULL;"""


def run(*statements):
    with connection.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)
        return cursor.fetchall() if cursor.description else None


class DefinerTriggerDatabaseTests(TestCase):
    """Made in the test's transaction, as the test's role (a superuser), and rolled back with it."""

    def setUp(self):
        run('CREATE TABLE public.definer_probe_a (id bigint PRIMARY KEY, name text)',
            'CREATE TABLE public.definer_probe_b (code text PRIMARY KEY, name text)',
            'CREATE TABLE public.definer_probe_other (id bigint PRIMARY KEY)',
            'CREATE TABLE public.definer_probe_versions (table_name text, row_id text, valid_from timestamptz, '
            'valid_to timestamptz, data jsonb)')
        tables = (('definer_probe_a', 'id'), ('definer_probe_b', 'code'))
        self.version = DefinerTrigger('definer_probe_version', VERSION, [
            each for table, key in tables for each in (
                On(table, f'{table}_row', events=('INSERT', 'DELETE'), level='ROW', args=(key,)),
                On(table, f'{table}_upd', events=('UPDATE',), level='ROW', when='OLD.* IS DISTINCT FROM NEW.*',
                   args=(key,)))], declare='    at timestamptz := clock_timestamp();\n    began timestamptz;')
        self.truncated = DefinerTrigger('definer_probe_truncated', TRUNCATED, [
            On(table, f'{table}_trunc', events=('TRUNCATE',)) for table, _ in tables])
        run(*self.version.sql_forwards(), *self.truncated.sql_forwards())

    def versions(self):
        return run("SELECT table_name, row_id, data ->> 'name', valid_to IS NULL FROM public.definer_probe_versions "
                   'ORDER BY table_name, row_id, valid_from')

    def test_one_function_keeps_many_tables_with_their_arguments(self):
        run("INSERT INTO definer_probe_a VALUES (1, 'one')", "INSERT INTO definer_probe_b VALUES ('x', 'ex')",
            "UPDATE definer_probe_a SET name = 'uno'", 'UPDATE definer_probe_b SET name = name',   # no change: no row
            'DELETE FROM definer_probe_b')
        self.assertEqual(self.versions(), [('definer_probe_a', '1', 'one', False), ('definer_probe_a', '1', 'uno', True),
                                           ('definer_probe_b', 'x', 'ex', False)])
        run('TRUNCATE definer_probe_a')
        self.assertEqual([row[3] for row in self.versions()], [False, False, False])

    def test_it_runs_for_its_own_tables_only(self):
        with self.assertRaisesMessage(DatabaseError, 'definer_probe_version runs for public.definer_probe_a, '
                                                     'public.definer_probe_b only, not public.definer_probe_other'), \
                transaction.atomic():
            run('CREATE TRIGGER forged AFTER INSERT ON definer_probe_other FOR EACH ROW '
                "EXECUTE FUNCTION public.definer_probe_version('id')", 'INSERT INTO definer_probe_other VALUES (1)')
        self.assertEqual(run("SELECT has_function_privilege('public', 'public.definer_probe_version()', 'EXECUTE')"),
                         [(False,)])

    def test_a_table_named_without_its_schema_is_the_public_one(self):
        """The search path puts the session's temporary schema last: a temporary table of the name the body uses is
        never the one written, so no check of the body's names is needed (none is kept)."""
        run('CREATE TEMP TABLE definer_probe_versions (LIKE public.definer_probe_versions)',
            "INSERT INTO public.definer_probe_a VALUES (1, 'one')")
        self.assertEqual(run('SELECT count(*) FROM public.definer_probe_versions'), [(1,)])
        self.assertEqual(run('SELECT count(*) FROM pg_temp.definer_probe_versions'), [(0,)])

    def test_going_back_drops_the_triggers_and_the_functions(self):
        run(*self.truncated.sql_backwards(), *self.version.sql_backwards())
        self.assertEqual(run("SELECT count(*) FROM pg_trigger WHERE tgname LIKE 'definer\\_probe\\_%'"), [(0,)])
        self.assertEqual(run("SELECT count(*) FROM pg_proc WHERE proname LIKE 'definer\\_probe\\_%'"), [(0,)])
