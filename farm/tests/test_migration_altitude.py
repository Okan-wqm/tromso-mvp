"""Migration farm/0027_site_altitude_range on a database that already has sites (F-089): an altitude within -500 .. 5000 m
stays; one outside it (a slip: a minus sign, two zeros too many) is moved into the site's notes with the day and emptied,
so the oxygen is worked out at sea-level pressure and the pages say so, never at an impossible pressure; the database then
holds the range, and the migration goes back."""
from decimal import Decimal

from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [('farm', '0026_production_form_other')]
AFTER = [('farm', '0027_site_altitude_range')]
D = Decimal


class AltitudeMigrationTests(TransactionTestCase):
    serialized_rollback = True

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def setUp(self):
        self.old = self.migrate(BEFORE)
        self.addCleanup(lambda: self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes()))

    def test_an_altitude_off_the_range_goes_to_the_notes_and_the_rest_stay(self):
        Site = self.old.get_model('farm', 'Site')
        kept = Site.objects.create(name='Fjell', code='FJ', altitude=D('812.50'))
        low = Site.objects.create(name='Dead Sea', code='DS', altitude=D('-430'))
        typo = Site.objects.create(name='Typo', code='TY', altitude=D('50000'), notes='Hall B is new.')
        minus = Site.objects.create(name='Minus', code='MI', altitude=D('-5000'))
        new = self.migrate(AFTER)
        Site = new.get_model('farm', 'Site')
        self.assertEqual(Site.objects.get(pk=kept.pk).altitude, D('812.50'))
        self.assertEqual(Site.objects.get(pk=low.pk).altitude, D('-430'))
        for site, typed in ((typo, '50000.00'), (minus, '-5000.00')):
            row = Site.objects.get(pk=site.pk)
            self.assertIsNone(row.altitude)
            self.assertIn(f'Altitude before 2026-11-06, outside -500 .. 5000 m: {typed}', row.notes)
        self.assertTrue(Site.objects.get(pk=typo.pk).notes.startswith('Hall B is new.\n'))
        with self.assertRaisesMessage(IntegrityError, 'chk_sites_altitude_range'), transaction.atomic():
            Site.objects.filter(pk=kept.pk).update(altitude=D('5001'))
        self.migrate(BEFORE)                                                  # and back
