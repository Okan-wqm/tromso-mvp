"""core.operations.DefinerTrigger: a trigger whose function runs as its owner, made so the app role can neither forge it
nor turn it aside (review of production-plan 2, H1; review of the perf tests 2, H2). What it makes is read here; that
it holds in the database is alarms/tests/test_open_alarms.py (a forged trigger refused, a shadow table never written)
and deploy/scripts/check-roles.sh (the same as the app role, on the go-live stack)."""
from django.test import SimpleTestCase

from .operations import DefinerTrigger

BODY = """
    INSERT INTO public.queue (id) SELECT n.id FROM made n;"""


class DefinerTriggerTests(SimpleTestCase):
    def test_what_it_makes_is_hardened(self):
        function, revoke, trigger = DefinerTrigger('things', 'trg_things_queue', 'things_queued', BODY,
                                                   new_table='made').sql_forwards()
        self.assertIn('CREATE FUNCTION public.things_queued() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER', function)
        self.assertIn('SET search_path = pg_catalog, public, pg_temp', function)           # the temporary schema last
        self.assertIn("IF TG_TABLE_SCHEMA <> 'public' OR TG_TABLE_NAME <> 'things' THEN", function)
        self.assertEqual(revoke, 'REVOKE EXECUTE ON FUNCTION public.things_queued() FROM PUBLIC')
        self.assertEqual(trigger, 'CREATE TRIGGER trg_things_queue AFTER INSERT ON public.things REFERENCING NEW TABLE '
                                  'AS made FOR EACH STATEMENT EXECUTE FUNCTION public.things_queued()')
        self.assertEqual(DefinerTrigger('things', 'trg_things_queue', 'things_queued', BODY,
                                        new_table='made').sql_backwards(),
                         ['DROP TRIGGER IF EXISTS trg_things_queue ON public.things',
                          'DROP FUNCTION IF EXISTS public.things_queued()'])

    def test_a_table_named_without_its_schema_is_refused(self):
        for body in ('DELETE FROM queue q USING made n WHERE q.id = n.id;',
                     'INSERT INTO queue (id) SELECT id FROM made;',
                     'UPDATE queue SET seen = true;',
                     'INSERT INTO public.queue (id) SELECT m.id FROM made m JOIN other o ON o.id = m.id;'):
            with self.subTest(body=body), self.assertRaisesMessage(ValueError, 'name every table with its schema'):
                DefinerTrigger('things', 'trg_things_queue', 'things_queued', body, new_table='made')

    def test_names_and_events_are_checked(self):
        for kwargs in ({'events': ('TRUNCATE',)}, {'level': 'EACH'}):
            with self.subTest(**kwargs), self.assertRaises(ValueError):
                DefinerTrigger('things', 'trg_things_queue', 'things_queued', BODY, new_table='made', **kwargs)
        with self.assertRaises(ValueError):
            DefinerTrigger('things; drop', 'trg_things_queue', 'things_queued', BODY, new_table='made')
